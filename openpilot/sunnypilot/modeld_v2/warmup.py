#!/usr/bin/env python3
"""
Offroad Tinygrad model cache warmup for QCOM and Chestnut AMD models.
"""

import multiprocessing
import os
import time

os.environ["GMMU"] = "0"

from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld.helpers import chestnut_present
from openpilot.sunnypilot.modeld_v2.helpers import cache_is_fresh, load_model, read_parts
from openpilot.sunnypilot.models.helpers import get_selected_bundle, get_driving_model

WARMUP_TIMEOUT = 120
WARMUP_TERMINATE_TIMEOUT = 5


def _warmup_model(path: str, source: str) -> None:
  # Match modeld's AMD wait behavior before the first Chestnut device operation.
  if source == "chestnut":
    from tinygrad.runtime.ops_amd import AMDDevice
    AMDDevice.wait_timeout_ms = 3000
  load_model(path)


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

      if not path or not os.path.isfile(path) or cache_is_fresh(path):
        continue

      attempt = (source, path, os.stat(path).st_mtime_ns)
      if attempt in failed | native:
        continue

      try:
        _, extras = read_parts(path)
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
