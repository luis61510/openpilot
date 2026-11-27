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

# A cold big artifact is ~1.8 GB of weights over USB (500+ kernels): building its
# graph and writing the cache takes minutes, so the eGPU warmup needs its own
# budget. Killing it early can never produce a cache and leaves every following
# onroad start cold again.
WARMUP_TIMEOUTS = {
  "qcom": 120,
  "chestnut": 1800,
}
WARMUP_TERMINATE_TIMEOUT = 5
# A failed warmup must be retried later, not blacklisted until the file changes:
# the retry is what eventually produces the cache the runner needs.
WARMUP_RETRY_BASE = 60.0
WARMUP_RETRY_MAX = 600.0


def _warmup_model(path: str, source: str) -> None:
  # Match modeld's AMD wait behavior before the first Chestnut device operation.
  if source == "chestnut":
    from tinygrad.runtime.ops_amd import AMDDevice
    AMDDevice.wait_timeout_ms = 3000
  load_model(path)


def _finish_warmup_worker(worker, timeout: float = WARMUP_TIMEOUTS["qcom"]) -> tuple[bool, int | None]:
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


def _retry_delay(failures: int) -> float:
  return min(WARMUP_RETRY_MAX, WARMUP_RETRY_BASE * (2 ** max(0, failures - 1)))


def main():
  """
  Runs offroad and prepares stale plain-artifact caches for the selected QCOM
  and Chestnut models. Chestnut is only touched when its USB device is present.
  Native artifacts are already fused/compiled and legacy OOB artifacts do not
  use this plain-artifact cache format.
  """
  params = Params()
  spawn = multiprocessing.get_context("spawn")
  # attempt -> (failures, next attempt time); keyed on the artifact mtime so a
  # re-download starts with a clean slate and a failed attempt is retried later.
  schedule: dict[tuple, tuple[int, float]] = {}
  native: set[tuple] = set()

  while True:
    for source in ("qcom", "chestnut"):
      if source == "chestnut" and not chestnut_present():
        continue

      bundle = get_selected_bundle(params, source)
      driving_model = get_driving_model(bundle)
      path = os.path.join(Paths.model_root(), driving_model.artifact.fileName) if driving_model else ""

      if not path or not os.path.isfile(path) or cache_is_fresh(path):
        continue

      attempt = (source, path, os.stat(path).st_mtime_ns)
      failures, next_time = schedule.get(attempt, (0, 0.0))
      if attempt in native or time.monotonic() < next_time:
        continue

      try:
        _, extras = read_parts(path)
      except (OSError, ValueError, KeyError, EOFError) as e:
        # Legacy OOB models are loaded by load_compatible_model and have no
        # plain-artifact cache to warm.
        cloudlog.warning(f"skipping {source} cache warmup for legacy/unsupported model {path}: {e}")
        native.add(attempt)
        continue

      if "input_specs" in extras:
        # The runner fuses this artifact with the stock warp at load time, so a
        # plain warmup of the unfused graph would write a cache the runner never
        # reads. Leave it to the runner instead of building a cache twice.
        cloudlog.info(f"skipping {source} cache warmup for fused/native model {path}")
        native.add(attempt)
        continue

      timeout = WARMUP_TIMEOUTS.get(source, WARMUP_TIMEOUTS["qcom"])
      worker = spawn.Process(target=_warmup_model, args=(path, source), daemon=True)
      started = time.monotonic()
      try:
        worker.start()
        completed, exitcode = _finish_warmup_worker(worker, timeout)
      except Exception:
        cloudlog.exception("failed to start or wait for %s model cache warmup: %s", source, path)
        completed, exitcode = False, None
      finally:
        if worker.pid is not None and not worker.is_alive():
          worker.close()

      elapsed = time.monotonic() - started
      if completed and cache_is_fresh(path):
        cloudlog.info(f"{source} model cache warmed in {elapsed:.0f}s: {path}")
        schedule.pop(attempt, None)
      else:
        failures += 1
        delay = _retry_delay(failures)
        schedule[attempt] = (failures, time.monotonic() + delay)
        cloudlog.error(f"{source} model cache warmup failed after {elapsed:.0f}s for {path} "
                       f"with exit code {exitcode}; retrying in {delay:.0f}s")

    time.sleep(10)


if __name__ == "__main__":
  main()
