from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.modeld_v2.helpers import MAGIC, is_plain_artifact


class TestPlainArtifactDetection(OpenpilotTestCase):
  def test_detects_plain_tinygrad_artifact(self, tmp_path):
    artifact = tmp_path / "plain.pkl"
    artifact.write_bytes(MAGIC + b"\x00" * 16)
    assert is_plain_artifact(str(artifact))

  def test_keeps_legacy_oob_pickle_on_legacy_path(self, tmp_path):
    artifact = tmp_path / "legacy.pkl"
    artifact.write_bytes(b"\x80\x05legacy")
    assert not is_plain_artifact(str(artifact))

  def test_missing_artifact_is_not_plain(self, tmp_path):
    assert not is_plain_artifact(str(tmp_path / "missing.pkl"))
