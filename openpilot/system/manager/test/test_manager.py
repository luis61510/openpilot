#!/usr/bin/env python3

import os
import unittest
import signal
import time
from types import SimpleNamespace

from opendbc.car.structs import car
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.params import Params
from openpilot.cereal import custom
import openpilot.system.manager.process_config as process_config
import openpilot.sunnypilot.models.helpers as model_helpers
import openpilot.sunnypilot.models.manager as model_manager
from openpilot.system.manager.process import PythonProcess
import openpilot.system.manager.manager as manager
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes, procs
from openpilot.common.hardware import HARDWARE

os.environ['FAKEUPLOAD'] = "1"

MAX_STARTUP_TIME = 3
BLACKLIST_PROCS = ['manage_athenad', 'pandad', 'pigeond']


class TestManager(OpenpilotTestCase):
  def setup_method(self):
    HARDWARE.set_power_save(False)

    # ensure clean CarParams
    params = Params()
    params.clear_all()

  def teardown_method(self):
    manager.manager_cleanup()

  def test_duplicate_procs(self):
    assert len(procs) == len(managed_processes), "Duplicate process names"

  def test_four_default_and_custom_runner_paths(self, monkeypatch):
    params = Params()
    params.remove("ModelRunnerTypeCache")

    # Default small model: stock runner.
    monkeypatch.setattr(model_helpers, "get_active_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(model_helpers, "chestnut_present", lambda: False)
    monkeypatch.setattr(model_helpers, "chestnut_compiled", lambda: False)
    assert model_helpers.get_active_model_runner(params, force_check=True) == custom.ModelManagerSP.Runner.stock

    # Default big model on Chestnut: the built-in artifact still uses Tinygrad.
    monkeypatch.setattr(model_helpers, "chestnut_present", lambda: True)
    monkeypatch.setattr(model_helpers, "chestnut_compiled", lambda: True)
    assert model_helpers.get_active_model_runner(params, force_check=True) == custom.ModelManagerSP.Runner.tinygrad

    # Non-default small and big bundles both dispatch by their declared runner.
    small_runner = type("Runner", (), {"raw": custom.ModelManagerSP.Runner.tinygrad})()
    small_bundle = type("Bundle", (), {"runner": small_runner})()
    monkeypatch.setattr(model_helpers, "get_active_bundle", lambda *_args, **_kwargs: small_bundle)
    assert model_helpers.get_active_model_runner(params, force_check=True) == custom.ModelManagerSP.Runner.tinygrad

    big_runner = type("Runner", (), {"raw": custom.ModelManagerSP.Runner.tinygrad})()
    big_bundle = type("Bundle", (), {"runner": big_runner})()
    monkeypatch.setattr(model_helpers, "get_active_bundle", lambda *_args, **_kwargs: big_bundle)
    assert model_helpers.get_active_model_runner(params, force_check=True) == custom.ModelManagerSP.Runner.tinygrad

    stock_runner = type("Runner", (), {"raw": custom.ModelManagerSP.Runner.stock})()
    stock_bundle = type("Bundle", (), {"runner": stock_runner})()
    monkeypatch.setattr(model_helpers, "get_active_bundle", lambda *_args, **_kwargs: stock_bundle)
    assert model_helpers.get_active_model_runner(params, force_check=True) == custom.ModelManagerSP.Runner.stock

  def test_model_runner_dispatch(self, monkeypatch):
    CP = car.CarParams.new_message()
    params = Params()

    monkeypatch.setattr(process_config, "get_active_model_runner",
                        lambda _params, force_check=False: custom.ModelManagerSP.Runner.stock)
    assert process_config.is_stock_model(True, params, CP)
    assert not process_config.is_tinygrad_model(True, params, CP)

    monkeypatch.setattr(process_config, "get_active_model_runner",
                        lambda _params, force_check=False: custom.ModelManagerSP.Runner.tinygrad)
    assert not process_config.is_stock_model(True, params, CP)
    assert process_config.is_tinygrad_model(True, params, CP)

  def test_exited_process_uses_bounded_restart_backoff(self):
    class DeadProcess:
      exitcode = 1
      pid = 12345

      @staticmethod
      def is_alive():
        return False

    params = Params()
    CP = car.CarParams.new_message()
    process = PythonProcess("modeld_tinygrad", "unused.module", lambda *_: True)
    process.proc = DeadProcess()
    process.started_at = time.monotonic() - 10
    process.start = lambda: setattr(process, "started", True)

    ensure_running([process], True, params, CP)
    assert process.proc is None
    assert process.restart_count == 1
    assert process.restart_at > time.monotonic()
    assert not getattr(process, "started", False)

    process.restart_at = 0
    ensure_running([process], True, params, CP)
    assert getattr(process, "started", False)

  def test_model_download_cancel_signal(self):
    manager_instance = object.__new__(model_manager.ModelManagerSP)
    manager_instance.params = Params()
    manager_instance.params.put("ModelManager_DownloadRef", "cancel-test-ref")
    assert not manager_instance._download_interrupted()
    manager_instance.params.remove("ModelManager_DownloadRef")
    assert manager_instance._download_interrupted()

  def test_cache_cleanup_preserves_active_chunked_bundle(self, monkeypatch, tmp_path):
    model_dir = tmp_path
    chunk = model_dir / "active.pkl.chunk01of01"
    manifest = model_dir / "active.pkl.chunkmanifest"
    sidecar = model_dir / "active.pkl.download"
    inactive = model_dir / "inactive.pkl"
    chunk.write_bytes(b"active model")
    manifest.write_text("1")
    sidecar.write_text("resume metadata")
    inactive.write_bytes(b"inactive model")

    artifact = SimpleNamespace(fileName="active.pkl", chunks=[])
    metadata = SimpleNamespace(fileName="", chunks=[])
    bundle = SimpleNamespace(models=[SimpleNamespace(artifact=artifact, metadata=metadata)])
    monkeypatch.setattr(model_manager.Paths, "model_root", staticmethod(lambda: str(model_dir)))
    monkeypatch.setattr(model_manager, "get_selected_bundle",
                        lambda _params, source: bundle if source == "qcom" else None)

    manager_instance = object.__new__(model_manager.ModelManagerSP)
    manager_instance.params = Params()
    manager_instance.selected_bundle = None
    manager_instance.clear_model_cache()

    assert chunk.is_file()
    assert manifest.is_file()
    assert sidecar.is_file()
    assert not inactive.exists()

  def test_stock_runner_device_map_and_artifact_names(self):
    from openpilot.selfdrive.modeld.helpers import get_tg_input_devices, stock_modeld_pkl_path

    default_devices = get_tg_input_devices("selfdrive.modeld.modeld", False)
    usbgpu_devices = get_tg_input_devices("selfdrive.modeld.modeld", True)
    assert default_devices == {"WARP_DEV": "QCOM", "QUEUE_DEV": "QCOM"}
    assert usbgpu_devices == {"WARP_DEV": "QCOM", "QUEUE_DEV": "AMD"}
    assert stock_modeld_pkl_path(False).name == "driving_tinygrad.pkl"
    assert stock_modeld_pkl_path(True).name == "big_driving_tinygrad.pkl"

  def test_blacklisted_procs(self):
    # TODO: ensure there are blacklisted procs until we have a dedicated test
    assert len(BLACKLIST_PROCS), "No blacklisted procs to test not_run"

  def test_set_params_with_default_value(self):
    params = Params()
    params.clear_all()

    os.environ['PREPAREONLY'] = '1'
    manager.main()
    for k in params.all_keys():
      default_value = params.get_default_value(k)
      if default_value is not None:
        assert params.get(k) == default_value
    assert params.get("OpenpilotEnabledToggle")
    assert params.get("RouteCount") == 0

  @unittest.skip("this test is flaky the way it's currently written, should be moved to test_onroad")
  def test_clean_exit(self, subtests):
    """
      Ensure all processes exit cleanly when stopped.
    """
    HARDWARE.set_power_save(False)
    manager.manager_init()

    CP = car.CarParams.new_message()
    procs = ensure_running(managed_processes.values(), True, Params(), CP, not_run=BLACKLIST_PROCS)

    time.sleep(10)

    for p in procs:
      with subtests.test(proc=p.name):
        state = p.get_process_state_msg()
        assert state.running, f"{p.name} not running"
        exit_code = p.stop(retry=False)

        assert p.name not in BLACKLIST_PROCS, f"{p.name} was started"

        assert exit_code is not None, f"{p.name} failed to exit"

        # TODO: interrupted blocking read exits with 1 in cereal. use a more unique return code
        exit_codes = [0, 1]
        if p.sigkill:
          exit_codes = [-signal.SIGKILL]
        assert exit_code in exit_codes, f"{p.name} died with {exit_code}"


if __name__ == "__main__":
  unittest.main()
