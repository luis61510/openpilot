"""
Regression tests for parallel ranged model downloads.
"""
import asyncio
import hashlib
import http.server
import os
import tempfile
import threading
import unittest
from unittest import mock

from openpilot.cereal import custom
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.models import manager as manager_module
from openpilot.sunnypilot.models.manager import ModelManagerSP

BODY = bytes((i * 37) % 251 for i in range(12_345))


class RangeServerState:
  requests = []
  fail_once = set()
  support_ranges = True


class RangeHandler(http.server.BaseHTTPRequestHandler):
  def log_message(self, *_args):
    pass

  def do_GET(self):
    state = RangeServerState
    header = self.headers.get("Range")
    start, end = 0, len(BODY) - 1
    if header and state.support_ranges:
      unit = header.removeprefix("bytes=").split("-")
      start, end = int(unit[0]), int(unit[1])
      state.requests.append((start, end))
      if (start, end) in state.fail_once:
        state.fail_once.remove((start, end))
        self.send_response(503)
        self.end_headers()
        return
      payload = BODY[start:end + 1]
      self.send_response(206)
      self.send_header("Content-Range", f"bytes {start}-{end}/{len(BODY)}")
    else:
      state.requests.append(None)
      payload = BODY
      self.send_response(200)
    self.send_header("Content-Length", str(len(payload)))
    self.send_header("Accept-Ranges", "bytes")
    self.end_headers()
    self.wfile.write(payload)


class TestParallelModelDownload(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    RangeServerState.requests = []
    RangeServerState.fail_once = set()
    RangeServerState.support_ranges = True
    self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    self.thread.start()
    self.addCleanup(self._stop_server)
    self.url = f"http://127.0.0.1:{self.server.server_port}/model.pkl"
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.path = os.path.join(self.tmp.name, "model.pkl")

    self.manager = ModelManagerSP.__new__(ModelManagerSP)
    self.manager.params = mock.MagicMock()
    self.manager.params.get.return_value = b"active"
    self.manager.pm = mock.MagicMock()
    self.manager.selected_bundle = None
    self.manager.active_bundle = None
    self.manager.available_models = []
    self.manager.chestnut_present = False
    self.manager._block_size = 256
    self.manager._chunk_size = 1024
    self.manager._download_start_times = {}

    self.artifact = custom.ModelManagerSP.ModelBundle.new_message()
    self.artifact.init("models", 1)
    self.artifact = self.artifact.models[0].artifact
    self.artifact.fileName = "model.pkl"

    self.stack = mock.patch.multiple(manager_module, PIECE_SIZE=1024, PIECE_BACKOFF=0.01, REPORT_INTERVAL=0.02)
    self.stack.start()
    self.addCleanup(self.stack.stop)

  def _stop_server(self):
    self.server.shutdown()
    self.server.server_close()
    self.thread.join(timeout=2)

  def download(self):
    asyncio.run(self.manager._download_file(self.url, self.path, self.artifact))

  def test_range_download_writes_exact_file(self):
    self.download()
    with open(self.path, "rb") as f:
      self.assertEqual(f.read(), BODY)
    self.assertEqual(self.artifact.downloadProgress.speed > 0, True)
    ranges = [r for r in RangeServerState.requests if r is not None and r != (0, 0)]
    self.assertEqual(sorted(ranges), [(s, min(s + 1024, len(BODY)) - 1) for s in range(0, len(BODY), 1024)])
    self.assertNotIn("model.pkl", self.manager._download_start_times)

  def test_falls_back_when_server_ignores_range(self):
    RangeServerState.support_ranges = False
    self.download()
    with open(self.path, "rb") as f:
      self.assertEqual(f.read(), BODY)
    self.assertEqual(RangeServerState.requests, [None, None])

  def test_retries_transient_piece_failure(self):
    RangeServerState.fail_once.add((1024, 2047))
    self.download()
    with open(self.path, "rb") as f:
      self.assertEqual(f.read(), BODY)
    self.assertEqual(RangeServerState.requests.count((1024, 2047)), 2)

  def test_content_range_parser(self):
    response = mock.MagicMock()
    response.status_code = 206
    response.headers = {"Content-Range": f"bytes 0-0/{len(BODY)}"}
    self.assertEqual(manager_module._content_range_total(response), len(BODY))


if __name__ == "__main__":
  unittest.main()
