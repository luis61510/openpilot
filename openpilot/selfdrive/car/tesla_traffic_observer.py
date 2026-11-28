from __future__ import annotations

from dataclasses import dataclass

from opendbc.can import CANParser


DBC_NAME = "tesla_modely_hw4_perception"
TRAFFIC_CONTROL_ADDRESS = 0x25D
TRAFFIC_CONTROL_BUSES = (2,)
TRAFFIC_CONTROL_MIN_DLC = 6
TRAFFIC_CONTROL_STALE_NS = 750_000_000
TRAFFIC_CONTROL_MAX_DISTANCE = 200.0


@dataclass(frozen=True)
class TeslaTrafficControlObservation:
  available: bool = False
  valid_for_control: bool = False
  source_bus: int = 0
  dlc: int = 0
  feature_state: int = 0
  state_machine: int = 0
  control_source: int = 0
  control_type: int = 0
  distance: float = 255.0
  light_state: int = 0
  continuation_reason: int = 0
  confirmation_type: int = 0
  warning_suppression_reason: int = 0
  unavailable_reason: int = 0
  vision_light: bool = False
  vision_sign: bool = False
  vision_road_marking: bool = False
  vision_line: bool = False
  frame_mono_time: int = 0
  quality: int = 0
  raw_address: int = 0
  raw_payload: bytes = b""


class TeslaTrafficControlObserver:
  """Read-only Tesla traffic-light observer; never sends CAN or controls motion."""

  def __init__(self) -> None:
    self.parsers = {
      bus: CANParser(DBC_NAME, [("APP_trafficControl", float("nan"))], bus)
      for bus in TRAFFIC_CONTROL_BUSES
    }
    self.latest_by_bus: dict[int, TeslaTrafficControlObservation] = {}

  @staticmethod
  def _build(values: dict[str, float], bus: int, dlc: int, timestamp_ns: int,
             raw_address: int, raw_payload: bytes) -> TeslaTrafficControlObservation:
    control_type = int(values["APP_tcControlType"])
    light_state = int(values["APP_tcControlLightState"])
    distance = float(values["APP_tcControlDistance"])
    decoded = control_type == 3 and light_state in (0, 1, 2, 3) and distance < 255.0
    eligible = bool(decoded and 0.0 <= distance <= TRAFFIC_CONTROL_MAX_DISTANCE)
    return TeslaTrafficControlObservation(
      available=True,
      valid_for_control=eligible,
      source_bus=bus,
      dlc=dlc,
      feature_state=int(values["APP_tcFeatureState"]),
      state_machine=int(values["APP_tcStateMachine"]),
      control_source=int(values["APP_tcControlSource"]),
      control_type=control_type,
      distance=distance,
      light_state=light_state,
      continuation_reason=int(values["APP_tcContinuationReason"]),
      confirmation_type=int(values["APP_tcConfirmationType"]),
      warning_suppression_reason=int(values["APP_tcWarningSuppressionReason"]),
      unavailable_reason=int(values["APP_tcUnavailableReason"]),
      vision_light=bool(values["APP_tcVisionLight"]),
      vision_sign=bool(values["APP_tcVisionSign"]),
      vision_road_marking=bool(values["APP_tcVisionRoadMarking"]),
      vision_line=bool(values["APP_tcVisionLine"]),
      frame_mono_time=timestamp_ns,
      quality=2 if eligible else (1 if decoded else 0),
      raw_address=raw_address,
      raw_payload=raw_payload,
    )

  def update(self, can_packets: list[tuple[int, list[tuple[int, bytes, int]]]], now_ns: int) -> None:
    del now_ns
    for packet_mono_time, frames in can_packets:
      for address, data, source in frames:
        if source not in self.parsers or address != TRAFFIC_CONTROL_ADDRESS or len(data) < TRAFFIC_CONTROL_MIN_DLC:
          continue
        previous = self.latest_by_bus.get(source)
        if previous is not None and packet_mono_time < previous.frame_mono_time:
          continue
        parser = self.parsers[source]
        if address not in parser.update([(packet_mono_time, [(address, data, source)])]):
          continue
        self.latest_by_bus[source] = self._build(
          dict(parser.vl["APP_trafficControl"]), source, len(data), packet_mono_time,
          address, bytes(data),
        )

  def snapshot(self, now_ns: int) -> TeslaTrafficControlObservation:
    for bus in TRAFFIC_CONTROL_BUSES:
      observation = self.latest_by_bus.get(bus)
      if observation is None:
        continue
      age_ns = now_ns - observation.frame_mono_time
      if 0 <= age_ns <= TRAFFIC_CONTROL_STALE_NS:
        return observation
    for bus in TRAFFIC_CONTROL_BUSES:
      observation = self.latest_by_bus.get(bus)
      if observation is not None:
        return TeslaTrafficControlObservation(
          source_bus=observation.source_bus, dlc=observation.dlc,
          feature_state=observation.feature_state, state_machine=observation.state_machine,
          control_source=observation.control_source, control_type=observation.control_type,
          distance=observation.distance, light_state=observation.light_state,
          continuation_reason=observation.continuation_reason,
          confirmation_type=observation.confirmation_type,
          warning_suppression_reason=observation.warning_suppression_reason,
          unavailable_reason=observation.unavailable_reason,
          vision_light=observation.vision_light, vision_sign=observation.vision_sign,
          vision_road_marking=observation.vision_road_marking, vision_line=observation.vision_line,
          frame_mono_time=observation.frame_mono_time, quality=observation.quality,
          raw_address=observation.raw_address, raw_payload=observation.raw_payload,
        )
    return TeslaTrafficControlObservation()


def publish_tesla_traffic_control(builder, observation: TeslaTrafficControlObservation) -> None:
  target = builder.teslaTrafficControl
  target.available = observation.available
  target.validForControl = observation.valid_for_control
  target.sourceBus = observation.source_bus
  target.dlc = observation.dlc
  target.featureState = observation.feature_state
  target.stateMachine = observation.state_machine
  target.controlSource = observation.control_source
  target.controlType = observation.control_type
  target.distance = observation.distance
  target.lightState = observation.light_state
  target.continuationReason = observation.continuation_reason
  target.confirmationType = observation.confirmation_type
  target.warningSuppressionReason = observation.warning_suppression_reason
  target.unavailableReason = observation.unavailable_reason
  target.visionLight = observation.vision_light
  target.visionSign = observation.vision_sign
  target.visionRoadMarking = observation.vision_road_marking
  target.visionLine = observation.vision_line
  target.frameMonoTime = observation.frame_mono_time
  target.quality = observation.quality
  target.rawAddress = observation.raw_address
  target.rawPayload = observation.raw_payload
