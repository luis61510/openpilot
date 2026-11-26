#!/usr/bin/env python3
"""
Offroad Tinygrad model cache warmup for QCOM and Chestnut AMD models.
"""

import contextlib
import multiprocessing
import os
import shutil
import tempfile
import time

os.environ["GMMU"] = "0"

from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld.helpers import chestnut_present
from openpilot.sunnypilot.modeld_v2.helpers import artifact_size_mtime, cache_is_fresh, load_model, read_parts
from openpilot.sunnypilot.models.helpers import get_selected_bundle, get_driving_model
from openpilot.common.file_chunker import get_manifest_path, open_file_chunked

WARMUP_TIMEOUT = 120
WARMUP_TERMINATE_TIMEOUT = 5


@contextlib.contextmanager
def _materialized_artifact(path: str):
  """Expose a chunked artifact as a temporary file for mmap-based parsing/loading."""
  if os.path.isfile(path):
    yield path
    return

  size, mtime_ns = artifact_size_mtime(path)
  fd, temporary_path = tempfile.mkstemp(prefix=".model-warmup-", dir=os.path.dirname(path) or ".")
  try:
    with os.fdopen(fd, "wb") as destination, open_file_chunked(path) as source:
      shutil.copyfileobj(source, destination)
    if os.path.getsize(temporary_path) != size:
      raise OSError(f"incomplete chunked model materialization: {path}")
    os.utime(temporary_path, ns=(mtime_ns, mtime_ns))
    yield temporary_path
  finally:
    with contextlib.suppress(FileNotFoundError):
      os.unlink(temporary_path)
    with contextlib.suppress(FileNotFoundError):
      os.unlink(f"{temporary_path}.cache")


def _warmup_model(path: str, source: str) -> None:
  # Match modeld's AMD wait behavior before the first Chestnut device operation.
  if source == "chestnut":
    from tinygrad.runtime.ops_amd import AMDDevice
    AMDDevice.wait_timeout_ms = 3000
  with _materialized_artifact(path) as load_path:
    load_model(load_path)
    if load_path != path:
      os.replace(f"{load_path}.cache", f"{path}.cache")


def _finish_warmup_worker(worker, timeout: float = WARMUP_TIMEOUT) -> tuple[bool, int | None]:
  """Wait for cache generation; terminate a hung offroad worker without blocking the loop."""
  worker.join(timeout)
  if worker.is_alive():
    cloudlog.error("model cache warmup exceeded %.0fs; terminating worker", timeout)
    worker.terminate()
    worker.join(WARMUP_TERMINATE_TIMEOUT)
    if worker.is_alive():
      cloudlog.error("model cache warmup worker ignored terminate; killing it")
      worker.kill()
      worker.join(WARMUP_TERMINATE_TIMEOUT)

  if worker.is_alive():
    # Do not close or reuse a process handle while the child is still running.
    return False, None

  exitcode = worker.exitcode
  return exitcode == 0, exitcode


def main():
  """
  Runs offroad and prepares stale plain-artifact caches for the selected QCOM
  and Chestnut models. Chestnut is only touched when its USB device is present.
  Native artifacts are already fused/compiled and legacy OOB artifacts do not
  use this plain-artifact cache format.
  """
  params, failed, native = Params(), set(), set()
  spawn = multiprocessing.get_context("spawn")

  while True:
    for source in ("chestnut", "qcom"):
      if source == "chestnut" and not chestnut_present():
        continue

      bundle = get_selected_bundle(params, source)
      driving_model = get_driving_model(bundle)
      path = os.path.join(Paths.model_root(), driving_model.artifact.fileName) if driving_model else ""

      if not path or not (os.path.isfile(path) or os.path.isfile(get_manifest_path(path))):
        continue

      try:
        artifact_size, artifact_mtime_ns = artifact_size_mtime(path)
        if cache_is_fresh(path):
          continue
      except (OSError, ValueError) as e:
        cloudlog.warning(f"skipping {source} cache warmup for incomplete artifact {path}: {e}")
        continue
      attempt = (source, path, artifact_size, artifact_mtime_ns)
      if attempt in failed | native:
        continue

      try:
        with _materialized_artifact(path) as read_path:
          _, extras = read_parts(read_path)
      except (OSError, ValueError, KeyError, EOFError) as e:
        # Legacy OOB models are loaded by load_compatible_model and have no
        # plain-artifact cache to warm.
        cloudlog.warning(f"skipping {source} cache warmup for legacy/unsupported model {path}: {e}")
        failed.add(attempt)
        continue

      if "input_specs" in extras:
        native.add(attempt)
        continue

      worker = spawn.Process(target=_warmup_model, args=(path, source), daemon=True)
      try:
        worker.start()
        completed, exitcode = _finish_warmup_worker(worker)
      except Exception:
        cloudlog.exception("failed to start or wait for %s model cache warmup: %s", source, path)
        completed, exitcode = False, None
      finally:
        if worker.pid is not None and not worker.is_alive():
          worker.close()

      if not completed or not cache_is_fresh(path):
        cloudlog.error(f"{source} model cache warmup failed for {path} with exit code {exitcode}")
        failed.add(attempt)

    time.sleep(10)


if __name__ == "__main__":
  main()
