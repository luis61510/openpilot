"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

tinygrad guards the AMD-over-USB device with a non-blocking flock on
/tmp/am_usb:<bus>-<port>.lock. A previous modeld instance may still hold it,
so retry only this transient lock-contention failure.
"""
import time

from openpilot.common.swaglog import cloudlog

EGPU_LOAD_ATTEMPTS = 5
EGPU_LOCK_RETRY_WAIT = 3.0  # seconds between attempts
EGPU_RETRY_BUDGET = (EGPU_LOAD_ATTEMPTS - 1) * EGPU_LOCK_RETRY_WAIT


def is_lock_contention(e: BaseException) -> bool:
  # The underlying error can be nested in an ExceptionGroup.
  return "Failed to acquire lock file" in repr(e)


def load_with_retry(make_model, attempts: int = EGPU_LOAD_ATTEMPTS, wait: float = EGPU_LOCK_RETRY_WAIT):
  """Return (model, error), retrying only transient am_usb lock contention."""
  last: Exception | None = None
  for attempt in range(1, attempts + 1):
    try:
      return make_model(), None
    except Exception as e:
      last = e
      if not is_lock_contention(e) or attempt == attempts:
        break
      cloudlog.warning(f"eGPU lock held (attempt {attempt}/{attempts}), retrying in {wait}s")
      time.sleep(wait)
  return None, last
