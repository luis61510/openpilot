from __future__ import annotations

from dataclasses import dataclass

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget


RED = rl.Color(255, 72, 72, 255)
AMBER = rl.Color(255, 190, 50, 255)
GREEN = rl.Color(53, 220, 118, 255)
LAMP_OFF = rl.Color(65, 69, 76, 220)
BORDER = rl.Color(255, 255, 255, 38)


@dataclass(frozen=True)
class TrafficSignalDisplayState:
  visible: bool = False
  light_state: int = 0


class TrafficControlRenderer(Widget):
  """Compact single-lamp display of fresh, read-only Tesla traffic recognition."""

  def __init__(self, *, compact: bool = True) -> None:
    super().__init__()
    self.compact = compact
    self.state = TrafficSignalDisplayState()

  def update(self) -> None:
    sm = ui_state.sm
    valid = bool(sm.seen["carStateSP"] and sm.alive["carStateSP"] and sm.valid["carStateSP"])
    if not valid:
      self.state = TrafficSignalDisplayState()
      return
    target = sm["carStateSP"].teslaTrafficControl
    light = int(target.lightState)
    distance = float(target.distance)
    visible = bool(target.available and int(target.quality) > 0 and
                   0.0 <= distance <= 200.0 and light in (1, 2, 3))
    self.state = TrafficSignalDisplayState(visible=visible, light_state=light)

  def _render(self, rect: rl.Rectangle) -> None:
    if not self.state.visible:
      return
    x, y = rect.x + 8, rect.y + 8
    housing = rl.Rectangle(x, y, 40, 40)
    radius = 16.0
    color = {1: RED, 3: AMBER, 2: GREEN}.get(self.state.light_state)
    rl.draw_rectangle_rounded(housing, 0.6, 24, rl.Color(12, 15, 19, 210))
    rl.draw_rectangle_rounded_lines_ex(housing, 0.6, 24, 1.5, BORDER)
    center = rl.Vector2(housing.x + housing.width / 2, housing.y + housing.height / 2)
    if color is None:
      rl.draw_circle_v(center, radius, LAMP_OFF)
    else:
      rl.draw_circle_v(center, radius + 2.0, rl.Color(color.r, color.g, color.b, 42))
      rl.draw_circle_v(center, radius, color)
