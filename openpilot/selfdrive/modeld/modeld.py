#!/usr/bin/env python3
"""Stock Tinygrad model runner.

This entrypoint handles the built-in model artifacts only. User-selected Tinygrad
bundles and Chestnut/AMD eGPU models are handled by modeld_tinygrad.py.
"""
import os
import pickle
import time

import numpy as np
from tinygrad.tensor import Tensor

import openpilot.cereal.messaging as messaging
from openpilot.cereal import log
from opendbc.car.structs import car
from openpilot.cereal.messaging import PubMaster, SubMaster
from openpilot.cereal.visionipc import VisionStreamType
from msgq.visionipc import VisionIpcClient, VisionBuf
from opendbc.car.car_helpers import get_demo_car_params
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import config_realtime_process, DT_MDL
from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.common.transformations.model import get_warp_matrix
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.drive_helpers import get_accel_from_plan, should_stop, smooth_value, get_curvature_from_plan
from openpilot.selfdrive.modeld.compile_modeld import make_input_queues, WARP_INPUTS, POLICY_INPUTS
from openpilot.selfdrive.modeld.parse_model_outputs import Parser
from openpilot.selfdrive.modeld.fill_model_msg import fill_model_msg, fill_driving_model_data, fill_pose_msg, PublishState
from openpilot.selfdrive.modeld.constants import ModelConstants, Plan
from openpilot.selfdrive.modeld.helpers import stock_modeld_pkl_path, get_tg_input_devices, usbgpu_present
from openpilot.common.file_chunker import read_file_chunked, get_manifest_path

PROCESS_NAME = "selfdrive.modeld.modeld"
SEND_RAW_PRED = os.getenv('SEND_RAW_PRED')
LAT_SMOOTH_SECONDS = 0.0
LONG_SMOOTH_SECONDS = 0.3
MIN_LAT_CONTROL_SPEED = 0.3


def get_action_from_model(model_output: dict[str, np.ndarray], prev_action: log.ModelDataV2.Action,
                          lat_action_t: float, long_action_t: float, v_ego: float) -> log.ModelDataV2.Action:
  if 'action' not in model_output:
    plan = model_output['plan'][0]
    desired_accel = get_accel_from_plan(plan[:,Plan.VELOCITY][:,0],
                                        plan[:,Plan.ACCELERATION][:,0],
                                        ModelConstants.T_IDXS,
                                        action_t=long_action_t)
    desired_curvature = get_curvature_from_plan(plan[:,Plan.T_FROM_CURRENT_EULER][:,2],
                                                plan[:,Plan.ORIENTATION_RATE][:,2],
                                                ModelConstants.T_IDXS,
                                                v_ego,
                                                lat_action_t)
  else:
    desired_accel = model_output['action'][0,1]
    desired_curvature = model_output['action'][0,0] / (max(1.0, v_ego))**2
  stop = should_stop(v_ego, desired_accel)
  desired_accel = smooth_value(desired_accel, prev_action.desiredAcceleration, LONG_SMOOTH_SECONDS)
  if v_ego > MIN_LAT_CONTROL_SPEED:
    desired_curvature = smooth_value(desired_curvature, prev_action.desiredCurvature, LAT_SMOOTH_SECONDS)
  else:
    desired_curvature = prev_action.desiredCurvature

  return log.ModelDataV2.Action(desiredCurvature=float(desired_curvature),
                                desiredAcceleration=float(desired_accel),
                                shouldStop=bool(stop))


class FrameMeta:
  frame_id: int = 0
  timestamp_sof: int = 0
  timestamp_eof: int = 0

  def __init__(self, vipc=None):
    if vipc is not None:
      self.frame_id, self.timestamp_sof, self.timestamp_eof = vipc.frame_id, vipc.timestamp_sof, vipc.timestamp_eof


class ModelState:
  prev_desire: np.ndarray  # for tracking the rising edge of the pulse

  def __init__(self, cam_w: int, cam_h: int, usbgpu: bool):
    self.LAT_SMOOTH_SECONDS = LAT_SMOOTH_SECONDS
    input_devices = get_tg_input_devices(PROCESS_NAME, usbgpu)
    self.WARP_DEV, self.QUEUE_DEV = input_devices['WARP_DEV'], input_devices['QUEUE_DEV']
    jits = pickle.loads(read_file_chunked(stock_modeld_pkl_path(usbgpu)))
    vision_metadata = jits['metadata']['vision']
    self.vision_input_shapes = vision_metadata['input_shapes']
    self.vision_input_names = list(self.vision_input_shapes.keys())
    self.vision_output_slices = vision_metadata['output_slices']

    policy_metadata = jits['metadata']['on_policy']
    self.policy_input_shapes = policy_metadata['input_shapes']
    self.policy_output_slices = policy_metadata['output_slices']

    self.prev_desire = np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32)

    self.frame_skip = ModelConstants.MODEL_RUN_FREQ // ModelConstants.MODEL_CONTEXT_FREQ
    self.input_queues, self.npy = make_input_queues(self.vision_input_shapes, self.policy_input_shapes, self.frame_skip, device=self.QUEUE_DEV)
    self.full_frames: dict[str, Tensor] = {}
    self._blob_cache: dict[int, Tensor] = {}
    self.parser = Parser()
    self.frame_buf_params = {k: get_nv12_info(cam_w, cam_h) for k in ('img', 'big_img')}
    self.run_policy = jits['run_policy']
    self.warp_enqueue = jits[(cam_w,cam_h)]

  def slice_outputs(self, model_outputs: np.ndarray, output_slices: dict[str, slice]) -> dict[str, np.ndarray]:
    parsed_model_outputs = {k: model_outputs[np.newaxis, v] for k,v in output_slices.items()}
    return parsed_model_outputs

  def run(self, bufs: dict[str, VisionBuf], transforms: dict[str, np.ndarray],
          inputs: dict[str, np.ndarray], prepare_only: bool) -> dict[str, np.ndarray] | None:
    for key in bufs.keys():
      ptr = np.frombuffer(bufs[key].data, dtype=np.uint8).ctypes.data
      yuv_size = self.frame_buf_params[key][3]
      # There is a ringbuffer of imgs, just cache tensors pointing to all of them
      cache_key = (key, ptr)
      if cache_key not in self._blob_cache:
        self._blob_cache[cache_key] = Tensor.from_blob(ptr, (yuv_size,), dtype='uint8', device=self.WARP_DEV)
      self.full_frames[key] = self._blob_cache[cache_key]

    # Model decides when action is completed, so desire input is just a pulse triggered on rising edge
    inputs['desire_pulse'][0] = 0
    self.npy['desire'][:] = np.where(inputs['desire_pulse'] - self.prev_desire > .99, inputs['desire_pulse'], 0)
    self.prev_desire[:] = inputs['desire_pulse']
    self.npy['traffic_convention'][:] = inputs['traffic_convention']
    self.npy['action_t'][:] = inputs['action_t']
    self.npy['tfm'][:,:] = transforms['img'][:,:]
    self.npy['big_tfm'][:,:] = transforms['big_img'][:,:]

    img, big_img = self.warp_enqueue(**{k: self.input_queues[k] for k in WARP_INPUTS}, frame=self.full_frames['img'], big_frame=self.full_frames['big_img'])

    if prepare_only:
      return None

    vision_output, on_policy_output = self.run_policy(
      **{k: self.input_queues[k] for k in POLICY_INPUTS}, img=img, big_img=big_img
    )

    vision_output = vision_output.numpy().flatten()
    on_policy_output = on_policy_output.numpy().flatten()
    vision_outputs_dict = self.parser.parse_vision_outputs(self.slice_outputs(vision_output, self.vision_output_slices))
    policy_outputs_dict = self.parser.parse_policy_outputs(self.slice_outputs(on_policy_output, self.policy_output_slices))
    combined_outputs_dict = {**vision_outputs_dict, **policy_outputs_dict}

    if SEND_RAW_PRED:
      combined_outputs_dict['raw_pred'] = np.concatenate([vision_output.copy(), on_policy_output.copy()])
    return combined_outputs_dict



def main(demo=False):
  cloudlog.warning("stock modeld init")

  gpu_present = usbgpu_present()
  gpu_artifact = stock_modeld_pkl_path(usbgpu=True)
  gpu_compiled = os.path.isfile(gpu_artifact) or os.path.isfile(get_manifest_path(gpu_artifact))
  usbgpu = gpu_present and gpu_compiled
  params = Params()
  params.put_bool("UsbGpuPresent", gpu_present)
  params.put_bool("UsbGpuCompiled", gpu_compiled)

  if not usbgpu:
    config_realtime_process(7, 54)

  while True:
    available_streams = VisionIpcClient.available_streams("camerad", block=False)
    if available_streams:
      use_extra_client = (VisionStreamType.VISION_STREAM_WIDE_ROAD in available_streams and
                          VisionStreamType.VISION_STREAM_NARROW_ROAD in available_streams)
      main_wide_camera = VisionStreamType.VISION_STREAM_NARROW_ROAD not in available_streams
      break
    time.sleep(.1)

  main_stream = VisionStreamType.VISION_STREAM_WIDE_ROAD if main_wide_camera else VisionStreamType.VISION_STREAM_NARROW_ROAD
  vipc_client_main = VisionIpcClient("camerad", main_stream, True)
  vipc_client_extra = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, False)
  cloudlog.warning(f"stock modeld vision streams: main_wide_camera={main_wide_camera}, use_extra_client={use_extra_client}")

  while not vipc_client_main.connect(False):
    time.sleep(0.1)
  while use_extra_client and not vipc_client_extra.connect(False):
    time.sleep(0.1)

  cloudlog.warning(f"connected main cam: {vipc_client_main.width} x {vipc_client_main.height}")
  if use_extra_client:
    cloudlog.warning(f"connected extra cam: {vipc_client_extra.width} x {vipc_client_extra.height}")

  model_path = stock_modeld_pkl_path(usbgpu)
  if not (os.path.isfile(model_path) or os.path.isfile(get_manifest_path(model_path))):
    raise FileNotFoundError(f"Stock model artifact is missing: {model_path}")

  load_started = time.monotonic()
  cloudlog.warning(f"loading stock model artifact: {model_path}")
  model = ModelState(vipc_client_main.width, vipc_client_main.height, usbgpu)
  cloudlog.warning(f"stock model loaded in {time.monotonic() - load_started:.1f}s")

  pm = PubMaster(["modelV2", "drivingModelData", "cameraOdometry"])
  sm = SubMaster(["deviceState", "carState", "narrowRoadCameraState", "extrinsicsCalibration",
                  "driverMonitoringState", "carControl", "controlsState", "lateralDelay"])
  publish_state = PublishState()
  frame_dropped_filter = FirstOrderFilter(0., 10., 1. / ModelConstants.MODEL_RUN_FREQ)
  last_vipc_frame_id = 0
  run_count = 0
  model_transform_main = np.zeros((3, 3), dtype=np.float32)
  model_transform_extra = np.zeros((3, 3), dtype=np.float32)
  extrinsics_calibration_seen = False
  buf_main, buf_extra = None, None
  meta_main, meta_extra = FrameMeta(), FrameMeta()

  if demo:
    CP = get_demo_car_params()
  else:
    CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cloudlog.info("stock modeld got CarParams: %s", CP.brand)
  long_delay = CP.longitudinalActuatorDelay + LONG_SMOOTH_SECONDS
  prev_action = log.ModelDataV2.Action()
  desire_helper = DesireHelper()

  while True:
    while meta_main.timestamp_sof < meta_extra.timestamp_sof + 25000000:
      buf_main = vipc_client_main.recv()
      meta_main = FrameMeta(vipc_client_main)
      if buf_main is None:
        break

    if buf_main is None:
      cloudlog.debug("stock modeld main camera has no frame")
      continue

    if use_extra_client:
      while True:
        buf_extra = vipc_client_extra.recv()
        meta_extra = FrameMeta(vipc_client_extra)
        if buf_extra is None or meta_main.timestamp_sof < meta_extra.timestamp_sof + 25000000:
          break
      if buf_extra is None:
        cloudlog.debug("stock modeld extra camera has no frame")
        continue
      if abs(meta_main.timestamp_sof - meta_extra.timestamp_sof) > 10000000:
        cloudlog.error(f"stock modeld frames out of sync: main={meta_main.frame_id}, extra={meta_extra.frame_id}")
    else:
      buf_extra, meta_extra = buf_main, meta_main

    sm.update(0)
    is_rhd = sm["driverMonitoringState"].isRHD
    frame_id = sm["narrowRoadCameraState"].frameId
    v_ego = max(sm["carState"].vEgo, 0.0)
    lat_delay = sm["lateralDelay"].lateralDelay + LAT_SMOOTH_SECONDS

    if (sm.updated["extrinsicsCalibration"] and sm.seen["narrowRoadCameraState"] and
        sm.seen["deviceState"]):
      device_from_calib_euler = np.array(sm["extrinsicsCalibration"].rpyCalib, dtype=np.float32)
      device_camera = DEVICE_CAMERAS[(str(sm["deviceState"].deviceType), str(sm["narrowRoadCameraState"].sensor))]
      main_intrinsics = device_camera.wide_road.intrinsics if main_wide_camera else device_camera.narrow_road.intrinsics
      model_transform_main = get_warp_matrix(device_from_calib_euler, main_intrinsics, False).astype(np.float32)
      has_wide_camera = use_extra_client or main_wide_camera
      extra_intrinsics = device_camera.wide_road.intrinsics if has_wide_camera else device_camera.narrow_road.intrinsics
      model_transform_extra = get_warp_matrix(device_from_calib_euler, extra_intrinsics, True).astype(np.float32)
      extrinsics_calibration_seen = True

    traffic_convention = np.zeros(2)
    traffic_convention[int(is_rhd)] = 1
    desire_vector = np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32)
    if 0 <= desire_helper.desire < ModelConstants.DESIRE_LEN:
      desire_vector[desire_helper.desire] = 1

    vipc_dropped_frames = max(0, meta_main.frame_id - last_vipc_frame_id - 1)
    frames_dropped = frame_dropped_filter.update(min(vipc_dropped_frames, 10))
    if run_count < 10:
      frame_dropped_filter.x = 0.0
      frames_dropped = 0.0
    run_count += 1
    frame_drop_ratio = frames_dropped / (1 + frames_dropped)
    prepare_only = vipc_dropped_frames > 0
    if prepare_only:
      cloudlog.error(f"stock modeld skipping model eval after dropping {vipc_dropped_frames} frames")

    bufs = {name: buf_extra if "big" in name else buf_main for name in model.vision_input_names}
    transforms = {name: model_transform_extra if "big" in name else model_transform_main for name in model.vision_input_names}
    frame_delay = DT_MDL
    action_delay = DT_MDL / 2
    lat_action_t = lat_delay + frame_delay + action_delay
    long_action_t = long_delay + frame_delay + action_delay
    inputs = {
      "desire_pulse": desire_vector,
      "traffic_convention": traffic_convention,
      "action_t": np.array([lat_action_t, long_action_t], dtype=np.float32),
    }

    model_started = time.perf_counter()
    model_output = model.run(bufs, transforms, inputs, prepare_only)
    model_execution_time = time.perf_counter() - model_started

    if model_output is not None:
      modelv2_send = messaging.new_message("modelV2")
      drivingdata_send = messaging.new_message("drivingModelData")
      posenet_send = messaging.new_message("cameraOdometry")

      if not sm["carControl"].latActive:
        prev_action.desiredCurvature = sm["controlsState"].curvature
      action = get_action_from_model(model_output, prev_action, lat_action_t, long_action_t, v_ego)
      prev_action = action
      fill_model_msg(modelv2_send, model_output, action, publish_state,
                     meta_main.frame_id, meta_extra.frame_id, frame_id,
                     frame_drop_ratio, meta_main.timestamp_eof, model_execution_time, extrinsics_calibration_seen)
      modelv2_send.modelV2.big = False
      desire_state = modelv2_send.modelV2.meta.desireState
      lane_change_prob = desire_state[log.Desire.laneChangeLeft] + desire_state[log.Desire.laneChangeRight]
      desire_helper.update(sm["carState"], sm["carControl"].latActive, lane_change_prob)
      modelv2_send.modelV2.meta.laneChangeState = desire_helper.lane_change_state
      modelv2_send.modelV2.meta.laneChangeDirection = desire_helper.lane_change_direction
      fill_driving_model_data(drivingdata_send, modelv2_send)
      fill_pose_msg(posenet_send, model_output, meta_main.frame_id, vipc_dropped_frames,
                    meta_main.timestamp_eof, extrinsics_calibration_seen)
      pm.send("modelV2", modelv2_send)
      pm.send("drivingModelData", drivingdata_send)
      pm.send("cameraOdometry", posenet_send)

    last_vipc_frame_id = meta_main.frame_id


if __name__ == "__main__":
  try:
    import argparse
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--demo", action="store_true", help="Run modeld in demo mode")
    args = argument_parser.parse_args()
    main(demo=args.demo)
  except KeyboardInterrupt:
    cloudlog.warning("got SIGINT")
