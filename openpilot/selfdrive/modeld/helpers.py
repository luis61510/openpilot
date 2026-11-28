import json
import sys
import time
from pathlib import Path

from openpilot.common.hardware.hw import Paths

from openpilot.common.hardware import AGNOS
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'
TG_INPUT_DEVICES_PATH = MODELS_DIR / 'tg_input_devices.json'
USBGPU_VID = 0xADD1
USBGPU_PID = 0x0001


def stock_modeld_pkl_path(usbgpu: bool = False) -> Path:
  """Return the built-in stock model artifact, separate from user-selected bundles."""
  prefix = 'big_' if usbgpu else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'


def get_tg_input_devices(process_name: str, usbgpu: bool) -> dict[str, str]:
  with TG_INPUT_DEVICES_PATH.open() as f:
    devices = json.load(f)
  process_devices = devices.get(process_name)
  if process_devices is None:
    raise KeyError(f"No Tinygrad input-device configuration for {process_name}")
  selected = process_devices.get('usbgpu' if usbgpu else 'default')
  if not isinstance(selected, dict) or not {'WARP_DEV', 'QUEUE_DEV'} <= selected.keys():
    raise ValueError(f"Invalid Tinygrad input-device configuration for {process_name}")
  return selected


def usbgpu_present() -> bool:
  for device in Path("/sys/bus/usb/devices").glob("*"):
    try:
      if int((device / "idVendor").read_text(), 16) == USBGPU_VID and \\
          int((device / "idProduct").read_text(), 16) == USBGPU_PID:
        return True
    except (OSError, ValueError):
      continue
  return False


def modeld_pkl_path(chestnut: bool):
  # Custom bundles are activated only after the model manager has completed
  # download and SHA256 verification. Keep the compiled model as the explicit
  # default when the corresponding slot has no custom selection.
  from openpilot.common.params import Params
  from openpilot.sunnypilot.models.helpers import get_selected_bundle

  source = "chestnut" if chestnut else "qcom"
  bundle = get_selected_bundle(Params(), source)
  if bundle is not None:
    from openpilot.cereal import custom
    runner = getattr(bundle.runner, "raw", bundle.runner)
    tinygrad_runner = getattr(custom.ModelManagerSP.Runner.tinygrad, "raw", custom.ModelManagerSP.Runner.tinygrad)
    if runner != tinygrad_runner:
      raise RuntimeError(f"Selected model bundle {bundle.ref} uses an unsupported runner: {runner}")
    artifacts = [model.artifact.fileName for model in bundle.models
                 if model.artifact.fileName and model.artifact.fileName.endswith(".pkl")]
    if not artifacts:
      raise RuntimeError(f"Selected {source} model bundle {bundle.ref} has no Tinygrad .pkl artifact")
    model_path = Path(Paths.model_root()) / artifacts[0]
    if not model_path.is_file():
      raise FileNotFoundError(f"Selected {source} model artifact is missing: {model_path}")
    return model_path

  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def load_oob(path, chestnut=False):
  from tinygrad import Context
  device = 'USB+AMD:LLVM' if chestnut else 'QCOM' if AGNOS else 'METAL' if sys.platform == 'darwin' else 'CPU:LLVM'
  with Context(DEV=device):
    from tinygrad_repo.examples.openpilot.helpers import load_pickle
    return load_pickle(path, out_of_band=True)

def chestnut_present() -> bool:
  for d in USB_DEVICES_PATH.glob("*"):
    try:
      usb_id = (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16))
      product = (d / "product").read_text().strip()
      if is_chestnut_usb_id(*usb_id) and product == CHESTNUT_USB_PRODUCT:
        return True
    except Exception:
      pass
  return False

def wait_for_chestnut(timeout: float = 10.) -> None:
  # the cable is detected before chestnut enumerates
  st = time.monotonic()
  while not chestnut_present():
    if time.monotonic() - st > timeout:
      raise TimeoutError("chestnut did not enumerate")
    time.sleep(0.1)

def chestnut_compiled() -> bool:
  # The compiled default bundle and downloaded custom bundles share the same
  # warp kernels. A selected custom artifact is usable when those kernels exist.
  warp_files_present = all(
    (MODELS_DIR / f'big_driving_warp_{size}_tinygrad.pkl').is_file() for size in ('1344x760', '1928x1208'))
  if not warp_files_present:
    return False
  try:
    return modeld_pkl_path(chestnut=True).is_file()
  except (FileNotFoundError, RuntimeError):
    return False
