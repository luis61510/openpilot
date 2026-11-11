import hashlib
import io
import os
import pickle
import struct
import tempfile
import time
import urllib.request
from pathlib import Path

from openpilot.common.basedir import BASEDIR

from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'
WARP_ASSET_TAG = "egpu-warps-v1"
WARP_ASSET_REPO = "luis61510/openpilot"
WARP_SHA256 = {
  "big_driving_warp_1344x760_tinygrad.pkl": "f1689356ff8e516f87e3d75f6b53e66953a11ee5a97e859b4808c9a16bfe671b",
  "big_driving_warp_1928x1208_tinygrad.pkl": "56cc9690e0e9fb719323d2c6646c1305e8bc6bbdfdc807724a605a0d0a37554b",
  "driving_warp_1344x760_tinygrad.pkl": "4b22fd6bcb3a3e8a642e6866449dd9c30c12e694ff0741cad9e34e4b00d8c5fa",
  "driving_warp_1928x1208_tinygrad.pkl": "9a17fd6acece4fab23784ef0f3f8bba28a049e9599e5e9e5ee7b36e4b1d24a6f",
}


def ensure_chestnut_warps(timeout: float = 12.) -> bool:
  """Fetch official warp assets atomically; never accept Git LFS pointer files."""
  warp_dir = Path(BASEDIR) / 'openpilot/sunnypilot/modeld_v2/models'
  warp_dir.mkdir(parents=True, exist_ok=True)
  complete = True
  for name, expected in WARP_SHA256.items():
    target = warp_dir / name
    if target.is_file():
      try:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest == expected:
          continue
      except OSError:
        pass
    complete = False
    url = f"https://github.com/{WARP_ASSET_REPO}/releases/download/{WARP_ASSET_TAG}/{name}"
    tmp_name = None
    try:
      with urllib.request.urlopen(url, timeout=timeout) as response, tempfile.NamedTemporaryFile(
        dir=warp_dir, prefix=f".{name}.", delete=False) as tmp:
        tmp_name = tmp.name
        digest = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
          digest.update(chunk)
          tmp.write(chunk)
        tmp.flush()
        os.fsync(tmp.fileno())
      if digest.hexdigest() != expected:
        raise ValueError(f"SHA256 mismatch for {name}")
      os.replace(tmp_name, target)
      tmp_name = None
    except Exception:
      if tmp_name:
        try:
          os.unlink(tmp_name)
        except OSError:
          pass
      return False
  return all(_compiled_file(warp_dir / name) for name in WARP_SHA256)


def modeld_pkl_path(chestnut: bool):
  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def load_oob(f):
  opcodes = f.read(struct.unpack('<q', f.read(8))[0])
  def buffers():
    while (h := f.read(8)):
      pb = pickle.PickleBuffer(bytearray(struct.unpack('<q', h)[0]))
      if f.readinto(pb) != pb.raw().nbytes:
        raise EOFError("incomplete model buffer")
      yield pb
  return pickle.load(io.BytesIO(opcodes), buffers=buffers())

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
  # The USB cable can be detected before the Chestnut bridge finishes enumerating.
  started = time.monotonic()
  while not chestnut_present():
    if time.monotonic() - started > timeout:
      raise TimeoutError("chestnut did not enumerate")
    time.sleep(0.1)


def _compiled_file(path: Path) -> bool:
  try:
    with path.open('rb') as f:
      header = f.read(64)
      return bool(header) and not header.startswith(b'version https://git-lfs.github.com/spec/v1')
  except OSError:
    return False


def compiled_model_file(path: Path, expected_chunks: int | None = None) -> bool:
  """Cheap loader-file completeness check; download/activation verifies hashes."""
  if path.is_file():
    return _compiled_file(path)
  try:
    count = int(Path(get_manifest_path(path)).read_text().strip())
    # ponytail: cap probes at 1024 chunks (~45 GiB); raise only for larger supported models.
    return 0 < count <= 1024 and (expected_chunks is None or count == expected_chunks) and all(
      _compiled_file(Path(get_chunk_name(path, i, count))) for i in range(count))
  except (OSError, ValueError):
    return False


def chestnut_warps_compiled() -> bool:
  warp_dir = Path(BASEDIR) / 'openpilot/sunnypilot/modeld_v2/models'
  return all(_compiled_file(warp_dir / f'big_driving_warp_{size}_tinygrad.pkl') for size in ('1344x760', '1928x1208'))


def chestnut_compiled() -> bool:
  return compiled_model_file(modeld_pkl_path(chestnut=True)) and chestnut_warps_compiled()
