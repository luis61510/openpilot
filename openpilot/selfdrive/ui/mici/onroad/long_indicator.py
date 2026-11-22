import pyray as rl
from openpilot.cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget

HIGHLIGHT_TIME = 2.5  # seconds


class LongIndicator(Widget):
  def __init__(self):
    super().__init__()
    self._txt_lead_car = (self._texture('car', 35, 27), self._texture('car_green', 50, 42))
    self._alpha_filter = FirstOrderFilter(0.0, 0.05, 1 / gui_app.target_fps)
    self._lead_car_filters = (FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps), FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps))
    self._should_draw = False

  @staticmethod
  def _texture(name: str, width: int, height: int) -> rl.Texture:
    return gui_app.texture(f'icons_mici/longitudinal/{name}.png', width, height, keep_aspect_ratio=False)

  def set_should_draw(self, should_draw: bool):
    self._should_draw = should_draw

  def _render(self, rect: rl.Rectangle) -> None:
    sm = ui_state.sm
    if sm.recv_frame['selfdriveState'] < ui_state.started_frame or not sm['selfdriveState'].enabled or not ui_state.has_longitudinal_control:
      self._alpha_filter.x = 0.0
      return

    alpha = self._alpha_filter.update(True)
    self._draw_lead_car(rect, alpha)
    self._draw_distance_bars(rect, alpha)

  def _draw_lead_car(self, rect: rl.Rectangle, alpha: float) -> None:
    sm = ui_state.sm
    plan = sm['longitudinalPlan']
    has_lead = sm.alive['longitudinalPlan'] and plan.hasLead
    e2e = has_lead and plan.longitudinalPlanSource == log.LongitudinalPlan.LongitudinalPlanSource.e2e

    white_f, green_f = self._lead_car_filters
    white_alpha = white_f.update(0.0 if e2e else 0.9 if has_lead else 0.35)
    green_alpha = green_f.update(float(e2e))

    white, green = self._txt_lead_car
    self._draw_centered(white, rect, 100, white_alpha * alpha)
    self._draw_centered(green, rect, 100, green_alpha * alpha)

  def _draw_distance_bars(self, rect: rl.Rectangle, alpha: float) -> None:
    # Compact six-step distance graphic. The Tesla follow-distance CAN source
    # still needs vehicle-log verification before any bar is allowed to claim
    # an actual selected setting.
    center_x = rect.x + 24
    top_y = rect.y + 122
    row_gap = 7.5
    bar_widths = (9.0, 12.5, 16.0, 19.5, 23.0, 26.5)

    rail_top = top_y - 4.0
    rail_bottom = top_y + row_gap * 5 + 4.0
    rail_half_top = 7.0
    rail_half_bottom = 15.0
    rail_color = rl.Color(35, 220, 105, round(220 * alpha))
    bar_color = rl.Color(105, 112, 112, round(150 * alpha))

    # Two continuous tapered side rails. Keep a visible gap between rails
    # and every rung; rungs are slightly thicker than the rails.
    for side in (-1.0, 1.0):
      start_x = center_x + side * rail_half_top
      end_x = center_x + side * rail_half_bottom
      rl.draw_line_ex(rl.Vector2(start_x, rail_top), rl.Vector2(end_x, rail_bottom), 1.8, rail_color)

    for i, width in enumerate(bar_widths):
      y = top_y + i * row_gap
      half_width = width / 2.0
      rl.draw_line_ex(rl.Vector2(center_x - half_width, y), rl.Vector2(center_x + half_width, y), 3.2, bar_color)

  @staticmethod
  def _draw_centered(texture: rl.Texture, rect: rl.Rectangle, y: float, alpha: float) -> None:
    pos = rl.Vector2(rect.x + 24 - texture.width / 2, rect.y + y - texture.height / 2)
    rl.draw_texture_ex(texture, pos, 0.0, 1.0, rl.Color(255, 255, 255, round(255 * alpha)))
