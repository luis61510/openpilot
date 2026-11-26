"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.common.filter_simple import FirstOrderFilter


class BlindSpotIndicators:
  def __init__(self):
    self._blind_spot_left_alpha_filter = FirstOrderFilter(0, 0.15, 1 / gui_app.target_fps)
    self._blind_spot_right_alpha_filter = FirstOrderFilter(0, 0.15, 1 / gui_app.target_fps)

  def update(self) -> None:
    sm = ui_state.sm
    CS = sm['carState']

    self._blind_spot_left_alpha_filter.update(1.0 if CS.leftBlindspot else 0.0)
    self._blind_spot_right_alpha_filter.update(1.0 if CS.rightBlindspot else 0.0)

  @property
  def detected(self) -> bool:
    return ui_state.blindspot and (self._blind_spot_left_alpha_filter.x > 0.01 or self._blind_spot_right_alpha_filter.x > 0.01)

  def _draw_vehicle_icon(self, x: int, y: int, alpha: int) -> None:
    """Draw a compact top-down vehicle icon for an occupied blind spot."""
    body = rl.Color(255, 65, 65, alpha)
    glass = rl.Color(35, 45, 55, alpha)
    tires = rl.Color(20, 20, 20, alpha)

    # Wheels
    rl.draw_rectangle(x + 2, y + 13, 8, 17, tires)
    rl.draw_rectangle(x + 34, y + 13, 8, 17, tires)
    rl.draw_rectangle(x + 2, y + 52, 8, 17, tires)
    rl.draw_rectangle(x + 34, y + 52, 8, 17, tires)

    # Vehicle body and windows
    rl.draw_rectangle(x + 7, y + 4, 32, 74, body)
    rl.draw_rectangle(x + 11, y + 17, 24, 18, glass)
    rl.draw_rectangle(x + 11, y + 43, 24, 17, glass)
    rl.draw_rectangle(x + 12, y + 7, 22, 6, rl.Color(255, 190, 190, alpha))

  def render(self, rect: rl.Rectangle) -> None:
    if not ui_state.blindspot:
      return

    BLIND_SPOT_MARGIN_X = 24
    BLIND_SPOT_Y_OFFSET = 108
    ICON_WIDTH = 46

    if self._blind_spot_left_alpha_filter.x > 0.01:
      alpha = int(255 * self._blind_spot_left_alpha_filter.x)
      self._draw_vehicle_icon(int(rect.x + BLIND_SPOT_MARGIN_X), int(rect.y + BLIND_SPOT_Y_OFFSET), alpha)

    if self._blind_spot_right_alpha_filter.x > 0.01:
      alpha = int(255 * self._blind_spot_right_alpha_filter.x)
      pos_x = int(rect.x + rect.width - BLIND_SPOT_MARGIN_X - ICON_WIDTH)
      self._draw_vehicle_icon(pos_x, int(rect.y + BLIND_SPOT_Y_OFFSET), alpha)
