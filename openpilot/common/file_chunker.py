#!/usr/bin/env python3
import math
import os
import sys
from pathlib import Path

CHUNK_SIZE = 45 * 1024 * 1024
MAX_CHUNKS = 1024


def get_chunk_name(name, idx, num_chunks):
  return f"{name}.chunk{idx + 1:02d}of{num_chunks:02d}"


def get_manifest_path(name):
  return f"{name}.chunkmanifest"


def _chunk_paths(path, num_chunks):
  return [get_manifest_path(path)] + [get_chunk_name(path, i, num_chunks) for i in range(num_chunks)]


def get_chunk_targets(path, file_size):
  return _chunk_paths(path, max(1, math.ceil(file_size / CHUNK_SIZE)))


def _read_manifest(path):
  manifest = Path(get_manifest_path(path))
  count = int(manifest.read_text().strip())
  if not 1 <= count <= MAX_CHUNKS:
    raise ValueError(f"Invalid chunk count {count} in {manifest}")
  return count


def chunk_file(path, targets):
  manifest_path, *chunk_paths = targets
  data_path = Path(path)
  actual_chunks = max(1, math.ceil(data_path.stat().st_size / CHUNK_SIZE))
  if len(chunk_paths) < actual_chunks:
    raise ValueError(f"Allowed {len(chunk_paths)} chunks but needs {actual_chunks}: {path}")
  with data_path.open("rb") as source:
    for index, chunk_path in enumerate(chunk_paths[:actual_chunks]):
      chunk = source.read(CHUNK_SIZE)
      tmp_path = Path(f"{chunk_path}.tmp")
      tmp_path.write_bytes(chunk)
      os.replace(tmp_path, chunk_path)
  manifest_tmp = Path(f"{manifest_path}.tmp")
  manifest_tmp.write_text(str(actual_chunks))
  os.replace(manifest_tmp, manifest_path)
  data_path.unlink()


def get_existing_chunks(path):
  if os.path.isfile(path):
    return [path]
  count = _read_manifest(path)
  chunks = [get_chunk_name(path, i, count) for i in range(count)]
  missing = [chunk for chunk in chunks if not os.path.isfile(chunk)]
  if missing:
    raise FileNotFoundError(f"Incomplete chunked artifact {path}: missing {missing[0]}")
  return chunks


def read_file_chunked(path):
  if os.path.isfile(path):
    return Path(path).read_bytes()
  chunks = get_existing_chunks(path)
  return b"".join(Path(chunk).read_bytes() for chunk in chunks)


if __name__ == "__main__":
  source_path = sys.argv[1]
  chunk_file(source_path, get_chunk_targets(source_path, os.path.getsize(source_path)))
