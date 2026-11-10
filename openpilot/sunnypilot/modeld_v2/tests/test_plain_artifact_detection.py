import tempfile
from pathlib import Path

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.modeld_v2.helpers import MAGIC, is_plain_artifact


class TestPlainArtifactDetection(OpenpilotTestCase):
  def test_detects_plain_tinygrad_artifact(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      artifact = Path(temp_dir) / "plain.pkl"
      artifact.write_bytes(MAGIC + b"\x00" * 16)
      assert is_plain_artifact(str(artifact))

  def test_keeps_legacy_oob_pickle_on_legacy_path(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      artifact = Path(temp_dir) / "legacy.pkl"
      artifact.write_bytes(b"\x80\x05legacy")
      assert not is_plain_artifact(str(artifact))

  def test_missing_artifact_is_not_plain(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      assert not is_plain_artifact(str(Path(temp_dir) / "missing.pkl"))
