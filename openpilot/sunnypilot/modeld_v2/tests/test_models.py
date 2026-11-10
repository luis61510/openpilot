"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch
from openpilot.common.basedir import BASEDIR
from openpilot.common.file_chunker import open_file_chunked
from openpilot.sunnypilot.modeld_v2.helpers import PlainJit, is_plain_artifact, load_model, load_oob, read_parts
from tinygrad.device import Device


class TestLegacyModels(unittest.TestCase):
  def test_chestnut_warp_artifacts_load(self):
    warp_dir = Path(BASEDIR) / "openpilot/sunnypilot/modeld_v2/models"
    for resolution in ("1344x760", "1928x1208"):
      path = warp_dir / f"big_driving_warp_{resolution}_tinygrad.pkl"
      if not is_plain_artifact(str(path)):
        self.skipTest(f"Official Chestnut warp artifact is not installed: {path.name}")
      bundle = load_model(str(path), {"AMD": "CPU", "QCOM": "CPU"}, verify=False, cache=False)
      assert "metadata" in bundle and "input_specs" in bundle and "run" in bundle
      assert any(isinstance(value, PlainJit) for value in bundle.values())

  def test_legacy_model_load(self):
    base_name = os.environ.get("MODEL_BASE_NAME")
    if not base_name:
      raise unittest.SkipTest("MODEL_BASE_NAME env var not set, skipping integration test.")
    chunk_dir = os.environ.get("MODEL_CHUNK_DIR", "/tmp/model_chunks")
    base_path = os.path.join(chunk_dir, base_name)

    if is_plain_artifact(base_path):
      parts, _ = read_parts(base_path)
      expected_device = os.environ.get("MODEL_EXPECTED_DEVICE")
      if expected_device:
        targets = [call["target"] for header, _ in parts.values() for call in header["calls"] if call["kind"] == "program"]
        device_targets = [target for target in targets if target.get("device") == expected_device]
        assert device_targets, f"No {expected_device} kernels found in {base_name}"
        if expected_device == "AMD":
          assert all(target.get("arch") == "gfx1200" and target.get("interface") == "USB" for target in device_targets), f"Chestnut model is not compiled for gfx1200 USB: {base_name}"
        elif expected_device == "QCOM":
          assert all(target.get("arch", "").startswith("a630") for target in device_targets), f"QCOM model is not compiled for a630: {base_name}"
      bundle = load_model(base_path, {"QCOM": "CPU", "AMD": "CPU"}, verify=False, cache=False)
      jits = [value for value in bundle.values() if isinstance(value, PlainJit)]
      assert "metadata" in bundle and jits and all(len(jit.captured.linear.src) > 0 for jit in jits)
      if expected_device == "AMD":
        assert bundle["metadata"].get("warp_dev") == "AMD", f"Chestnut model must run warp on AMD: {base_name}"
      return
    if os.environ.get("MODEL_EXPECTED_DEVICE") == "AMD":
      self.fail(f"Chestnut model is not in the expected plain Tinygrad format: {base_name}")

    try:
      f = open_file_chunked(base_path)
    except Exception as error:
      self.fail(f"Failed to open legacy chunked file {base_path}: {error}")
    self.addCleanup(f.close)

    real_getitem = Device.__class__.__getitem__

    def safe_getitem(device_self, ix):
      if ix == "QCOM" and not os.path.exists("/dev/kgsl-3d0"):
        return real_getitem(device_self, "CPU")
      if ix == "AMD" and not os.path.exists("/dev/kfd"):
        return real_getitem(device_self, "CPU")
      return real_getitem(device_self, ix)

    with patch.object(Device.__class__, "__getitem__", safe_getitem):
      obj = load_oob(f)

      assert isinstance(obj, dict), "Parsed object is not a dictionary"
      assert "metadata" in obj, "Metadata key is missing"

      def traverse_jits(d):
        if hasattr(d, "captured") and d.captured is not None:
          linear_attr = getattr(d.captured, "_linear", None)
          if linear_attr is None:
            try:
              linear_attr = getattr(d.captured, "linear", None)
            except AssertionError as e:
              if "alloc size must be positive" in str(e):
                return
              raise

          if linear_attr is not None:
            stack = [linear_attr]
            visited = set()
            while stack:
              node = stack.pop()
              if id(node) in visited:
                continue
              visited.add(id(node))
              if hasattr(node, "src") and node.src is not None:
                for child in node.src:
                  stack.append(child)
        elif isinstance(d, dict):
          for v in d.values():
            traverse_jits(v)
        elif isinstance(d, (list, tuple)):
          for v in d:
            traverse_jits(v)

      if "run_model" in obj:
        traverse_jits(obj["run_model"])
      if "run_policy" in obj:
        traverse_jits(obj["run_policy"])
