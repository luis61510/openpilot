"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import io
import requests

from openpilot.common.file_chunker import get_chunk_name
from openpilot.common.hardware import hw
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.modeld_v2.helpers import dump_oob
import openpilot.sunnypilot.modeld_v2.modeld as modeld_module
from openpilot.sunnypilot.modeld_v2.tests import helpers as tests_helpers
from openpilot.sunnypilot.modeld_v2.tests.helpers import DummyModel, DummyBundle, CAM_W, CAM_H
from openpilot.sunnypilot.models.fetcher import ModelParser, ModelFetcher
from openpilot.sunnypilot.models.helpers import ModelManager, get_driving_model

tmp_path = tests_helpers.tmp_path


class _FakeSubMaster:
  def __init__(self, car_state, car_control, seen=True, alive=True, valid=True):
    self.seen = {'carState': seen, 'carControl': seen}
    self.alive = alive if isinstance(alive, dict) else {'carState': alive, 'carControl': alive}
    self.valid = valid if isinstance(valid, dict) else {'carState': valid, 'carControl': valid}
    self.data = {'carState': car_state, 'carControl': car_control}

  def __getitem__(self, key):
    return self.data[key]


class TestFallback(OpenpilotTestCase):
  def test_driving_model_is_selected_by_type_not_bundle_order(self):
    from types import SimpleNamespace

    vision = SimpleNamespace(type=ModelManager.Model.Type.vision, artifact=SimpleNamespace(fileName="vision.pkl"))
    policy = SimpleNamespace(type=ModelManager.Model.Type.policy, artifact=SimpleNamespace(fileName="policy.pkl"))
    driving = SimpleNamespace(type=ModelManager.Model.Type.supercombo, artifact=SimpleNamespace(fileName="driving.pkl"))
    bundle = SimpleNamespace(models=[vision, policy, driving])

    chunked = SimpleNamespace(type=ModelManager.Model.Type.chunked, artifact=SimpleNamespace(fileName="chunked-driving.pkl"))
    assert get_driving_model(bundle) is driving
    assert get_driving_model(SimpleNamespace(models=[chunked])) is chunked
    assert get_driving_model(SimpleNamespace(models=[vision, policy])) is None
    assert get_driving_model(SimpleNamespace(models=[vision])) is None
    assert get_driving_model(None) is None

  def test_chestnut_recovery_requires_stopped_disengaged_vehicle(self):
    from types import SimpleNamespace

    stopped = SimpleNamespace(standstill=True, vEgo=0.0)
    disengaged = SimpleNamespace(enabled=False, latActive=False, longActive=False)
    assert modeld_module._can_recover_chestnut(_FakeSubMaster(stopped, disengaged))

    moving = SimpleNamespace(standstill=False, vEgo=5.0)
    assert not modeld_module._can_recover_chestnut(_FakeSubMaster(moving, disengaged))

    engaged = SimpleNamespace(enabled=True, latActive=True, longActive=False)
    assert not modeld_module._can_recover_chestnut(_FakeSubMaster(stopped, engaged))

    assert not modeld_module._can_recover_chestnut(_FakeSubMaster(stopped, disengaged, seen=False))

  def test_chestnut_recovery_rejects_stale_or_invalid_vehicle_state(self):
    from types import SimpleNamespace

    stopped = SimpleNamespace(standstill=True, vEgo=0.0)
    disengaged = SimpleNamespace(enabled=False, latActive=False, longActive=False)
    # A message may have been seen previously but is no longer live.
    assert not modeld_module._can_recover_chestnut(
      _FakeSubMaster(stopped, disengaged, alive={'carState': False, 'carControl': True}))
    assert not modeld_module._can_recover_chestnut(
      _FakeSubMaster(stopped, disengaged, valid={'carState': True, 'carControl': False}))

  def test_find_dual_model_in_bundle(self, tmp_path, monkeypatch):
    lebowski_file = 'driving_lebowski.pkl'
    tsfdo_file = 'driving_tsfdo.pkl'
    (tmp_path / lebowski_file).write_bytes(b'fkasdjfkljf')
    (tmp_path / tsfdo_file).write_bytes(b'dskfajklsdjlsfka')

    monkeypatch.setattr(hw.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
    big_bundle = DummyBundle(models=[DummyModel('supercombo', lebowski_file)])
    small_bundle = DummyBundle(models=[DummyModel('supercombo', tsfdo_file)])
    chunked_bundle = DummyBundle(models=[DummyModel('chunked', 'driving_chunked.pkl')])
    (tmp_path / 'driving_chunked.pkl').write_bytes(b'chunked-driving-artifact')
    big_pkl = modeld_module._find_driving_pkl(big_bundle)
    small_pkl = modeld_module._find_driving_pkl(small_bundle)
    chunked_pkl = modeld_module._find_driving_pkl(chunked_bundle)

    assert big_pkl is not None and lebowski_file in big_pkl
    assert small_pkl is not None and tsfdo_file in small_pkl
    assert chunked_pkl is not None and 'driving_chunked.pkl' in chunked_pkl

  def test_download_models_and_init_modelstate_fallback(self, tmp_path, monkeypatch):
    monkeypatch.setattr(hw.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
    big_json = requests.get(ModelFetcher.MODEL_URL_CHESTNUT).json()
    big_bundle = ModelParser.parse_models(big_json)[-1]
    small_json = requests.get(ModelFetcher.MODEL_URL).json()
    small_bundle = ModelParser.parse_models(small_json)[-1]

    buf = io.BytesIO()
    dump_oob(tests_helpers.make_pkl_data(tests_helpers.ARCHETYPES['supercombo_non20hz']), buf)
    oob_bytes = buf.getvalue()

    for bundle in (big_bundle, small_bundle):
      artifact = bundle.models[0].artifact
      for i in range(len(artifact.chunks)):
        (tmp_path / get_chunk_name(artifact.fileName, i, len(artifact.chunks))).write_bytes(oob_bytes if i == 0 else b"")

    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None, *, chestnut=None: small_bundle)
    assert modeld_module.ModelState(CAM_W, CAM_H, chestnut=False).chestnut is False

    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None, *, chestnut=None: big_bundle)
    try:
      assert modeld_module.ModelState(CAM_W, CAM_H, chestnut=True).chestnut is True
    except Exception as e:
      assert "AMD" in str(e) or "device" in str(e).lower()
