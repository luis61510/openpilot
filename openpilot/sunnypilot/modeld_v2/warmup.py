#!/usr/bin/env python3
"""
Offroad Tinygrad model cache warmup.
"""

import multiprocessing
import os
import time

os.environ["GMMU"] = "0"

from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.modeld_v2.helpers import cache_is_fresh, load_model, read_parts
from openpilot.sunnypilot.models.helpers import get_selected_bundle


def main():
  params, failed, native = Params(), set(), set()
  spawn = multiprocessing.get_context("spawn")

  while True:
    bundle = get_selected_bundle(params, "qcom")
    path = os.path.join(Paths.model_root(), bundle.models[0].artifact.fileName) if bundle and bundle.models else ""

    if path and os.path.isfile(path) and not cache_is_fresh(path):
      attempt = (path, os.stat(path).st_mtime_ns)
      if attempt not in failed | native:
        try:
          _, extras = read_parts(path)
        except (OSError, ValueError, KeyError) as e:
          # Legacy OOB pickles are loaded by load_compatible_model, not this Plain Artifact cache worker.
          cloudlog.warning(f"skipping cache warmup for legacy/unsupported model {path}: {e}")
          failed.add(attempt)
        else:
          if "input_specs" in extras:
            native.add(attempt)
          else:
            worker = spawn.Process(target=load_model, args=(path,), daemon=True)
            worker.start()
            worker.join()
            if not cache_is_fresh(path):
              cloudlog.error(f"model cache warmup failed for {path} with exit code {worker.exitcode}")
              failed.add(attempt)

    time.sleep(10)


if __name__ == "__main__":
  main()
