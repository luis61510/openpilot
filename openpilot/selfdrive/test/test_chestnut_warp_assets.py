import hashlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.modeld import helpers


class TestChestnutWarpAssets(OpenpilotTestCase):
  def test_download_replaces_lfs_pointer_after_checksum(self):
    payload = b"SPTGPLN1 verified test warp"
    digest = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
      target_dir = Path(tmp) / "openpilot/sunnypilot/modeld_v2/models"
      target_dir.mkdir(parents=True)
      target = target_dir / "big_driving_warp_1344x760_tinygrad.pkl"
      target.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 10\n")
      with patch.object(helpers, "BASEDIR", tmp), patch.dict(helpers.WARP_SHA256, {
        "big_driving_warp_1344x760_tinygrad.pkl": digest,
      }, clear=True), patch.object(helpers.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
        assert helpers.ensure_chestnut_warps(timeout=0.1)
      assert target.read_bytes() == payload

  def test_checksum_failure_keeps_existing_pointer_and_fails_closed(self):
    payload = b"untrusted warp"
    with tempfile.TemporaryDirectory() as tmp:
      target_dir = Path(tmp) / "openpilot/sunnypilot/modeld_v2/models"
      target_dir.mkdir(parents=True)
      target = target_dir / "big_driving_warp_1344x760_tinygrad.pkl"
      pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 10\n"
      target.write_bytes(pointer)
      with patch.object(helpers, "BASEDIR", tmp), patch.dict(helpers.WARP_SHA256, {
        "big_driving_warp_1344x760_tinygrad.pkl": "0" * 64,
      }, clear=True), patch.object(helpers.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
        assert not helpers.ensure_chestnut_warps(timeout=0.1)
      assert target.read_bytes() == pointer
