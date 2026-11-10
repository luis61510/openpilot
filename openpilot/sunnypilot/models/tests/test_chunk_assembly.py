import asyncio
import hashlib
import os
from types import SimpleNamespace

import pytest

from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.sunnypilot.models.manager import DownloadCancelled, ModelManagerSP


class _TestManager(ModelManagerSP):
  def __init__(self, interrupted):
    self._interrupted = interrupted

  def _download_interrupted(self):
    return self._interrupted()


def _manager(interrupted=lambda: False):
  return _TestManager(interrupted)


def _artifact(data: bytes, chunks: int):
  return SimpleNamespace(
    chunks=[object() for _ in range(chunks)],
    downloadUri=SimpleNamespace(sha256=hashlib.sha256(data).hexdigest()),
  )


def test_chunk_assembly_produces_verified_plain_file_and_removes_parts(tmp_path):
  base = str(tmp_path / "driving_model.pkl")
  parts = [b"plain artifact header", b"model weights", b"tail"]
  data = b"".join(parts)
  artifact = _artifact(data, len(parts))

  for i, part in enumerate(parts):
    with open(get_chunk_name(base, i, len(parts)), "wb") as f:
      f.write(part)
  with open(get_manifest_path(base), "w") as f:
    f.write(str(len(parts)))

  asyncio.run(_manager()._assemble_chunked_artifact(base, artifact))

  with open(base, "rb") as f:
    assert f.read() == data
  assert not os.path.exists(get_manifest_path(base))
  assert all(not __import__("os").path.exists(get_chunk_name(base, i, len(parts))) for i in range(len(parts)))
  assert not __import__("os").path.exists(base + ".assembling")


def test_chunk_assembly_rejects_wrong_full_hash_and_keeps_chunks(tmp_path):
  base = str(tmp_path / "bad_model.pkl")
  parts = [b"part one", b"part two"]
  artifact = SimpleNamespace(chunks=[object(), object()], downloadUri=SimpleNamespace(sha256="0" * 64))

  for i, part in enumerate(parts):
    with open(get_chunk_name(base, i, len(parts)), "wb") as f:
      f.write(part)

  with pytest.raises(ValueError, match="Full artifact hash validation failed"):
    asyncio.run(_manager()._assemble_chunked_artifact(base, artifact))

  assert not __import__("os").path.exists(base)
  assert not __import__("os").path.exists(base + ".assembling")
  assert all(__import__("os").path.exists(get_chunk_name(base, i, len(parts))) for i in range(len(parts)))


def test_chunk_assembly_honors_cancel_before_replacing_file(tmp_path):
  base = str(tmp_path / "cancelled_model.pkl")
  parts = [b"part one", b"part two"]
  artifact = _artifact(b"".join(parts), len(parts))

  for i, part in enumerate(parts):
    with open(get_chunk_name(base, i, len(parts)), "wb") as f:
      f.write(part)

  with pytest.raises(DownloadCancelled):
    asyncio.run(_manager(lambda: True)._assemble_chunked_artifact(base, artifact))

  assert not __import__("os").path.exists(base)
  assert not __import__("os").path.exists(base + ".assembling")
  assert all(__import__("os").path.exists(get_chunk_name(base, i, len(parts))) for i in range(len(parts)))
