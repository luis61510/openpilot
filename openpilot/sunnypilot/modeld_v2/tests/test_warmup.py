from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.modeld_v2.warmup import _finish_warmup_worker


class _FakeWorker:
  def __init__(self, *, alive=False, exitcode=0, terminate_stops=True):
    self.alive = alive
    self.exitcode = exitcode
    self.terminate_stops = terminate_stops
    self.terminated = False
    self.killed = False

  def join(self, timeout=None):
    pass

  def is_alive(self):
    return self.alive

  def terminate(self):
    self.terminated = True
    if self.terminate_stops:
      self.alive = False
      self.exitcode = -15

  def kill(self):
    self.killed = True
    self.alive = False
    self.exitcode = -9


class TestWarmupWorker(OpenpilotTestCase):
  def test_completed_worker_reports_success(self):
    completed, exitcode = _finish_warmup_worker(_FakeWorker())
    assert completed
    assert exitcode == 0

  def test_timed_out_worker_is_terminated(self):
    worker = _FakeWorker(alive=True)
    completed, exitcode = _finish_warmup_worker(worker, timeout=0.01)
    assert not completed
    assert worker.terminated
    assert not worker.killed
    assert exitcode == -15

  def test_worker_that_ignores_terminate_is_killed(self):
    worker = _FakeWorker(alive=True, terminate_stops=False)
    completed, exitcode = _finish_warmup_worker(worker, timeout=0.01)
    assert not completed
    assert worker.terminated
    assert worker.killed
    assert exitcode == -9
