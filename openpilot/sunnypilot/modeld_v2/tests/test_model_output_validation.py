"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import numpy as np
import pytest

from openpilot.sunnypilot.modeld_v2.modeld import _check_finite_model_output


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_model_output_rejects_non_finite_values(invalid):
  with pytest.raises(RuntimeError, match="model output not finite"):
    _check_finite_model_output(np.array([0.0, invalid], dtype=np.float32))


def test_model_output_checks_every_split_output():
  outputs = {
    "vision": np.array([1.0, 2.0], dtype=np.float32),
    "policy": np.array([3.0, np.nan], dtype=np.float32),
  }
  with pytest.raises(RuntimeError, match="model output not finite"):
    _check_finite_model_output(outputs)


def test_model_output_accepts_finite_values():
  _check_finite_model_output({
    "vision": np.array([1.0, 2.0], dtype=np.float32),
    "policy": np.array([3.0, 4.0], dtype=np.float32),
  })
