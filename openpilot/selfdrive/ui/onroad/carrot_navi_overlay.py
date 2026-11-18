"""On-road Carrot Navi information overlay; display-only, never a control input."""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.carrot.carrot_navi_consumer import CarrotNaviConsumer, CarrotNaviState


PANEL_WIDTH = 560
PANEL_HEIGHT = 220
PANEL_MARGIN = 28


def _distance(meters: int) -> str:
  return f"{meters} m" if meters < 1000 else f"{meters / 1000:.1f} km"


def _duration(seconds: int) -> str:
  minutes, seconds = divmod(max(0, seconds), 60)
  return f"{minutes} min" if minutes else f"{seconds} sec"


class CarrotNaviOverlay:
  def __init__(self) -> None:
    self.consumer = CarrotNaviConsumer()
    self._last_state: CarrotNaviState | None = None

  def render(self, rect: rl.Rectangle) -> None:
    self.consumer.update(0)
    state = self.consumer.state if self.consumer.available else None
    if state is None:
      self._render_disconnected(rect)
      return
    self._last_state = state
    x = int(rect.x + rect.width - PANEL_WIDTH - PANEL_MARGIN)
    y = int(rect.y + PANEL_MARGIN)
    panel = rl.Rectangle(x, y, PANEL_WIDTH, PANEL_HEIGHT)
    rl.draw_rectangle_rounded(panel, 0.08, 8, rl.Color(10, 16, 24, 220))

    title = state.guidance_text or ("Off route" if state.off_route else "Navigation")
    rl.draw_text(title[:26], x + 22, y + 18, 34, rl.WHITE)

    road = state.next_road_name or state.road_name
    if road:
      rl.draw_text(road[:32], x + 22, y + 62, 23, rl.Color(205, 215, 225, 255))

    distance = _distance(state.distance_m) if state.distance_m else "--"
    eta = _duration(state.guidance_time_sec) if state.guidance_time_sec else "--"
    rl.draw_text(f"{distance}  |  {eta}", x + 22, y + 100, 27, rl.Color(255, 220, 130, 255))

    limit = f"{state.road_limit_kph}" if state.road_limit_valid else "--"
    rl.draw_text(f"Limit {limit} km/h", x + 22, y + 145, 25, rl.Color(160, 220, 255, 255))

    route = _distance(state.route_remaining_distance_m) if state.route_present else "--"
    lane = f"{state.current_lane + 1}/{state.lane_count}" if state.lane_count else "--"
    rl.draw_text(f"Lane {lane}   Route {route}", x + 250, y + 145, 23, rl.WHITE)

    if state.traffic_visible:
      if state.red_on:
        signal = "Red light"
      elif state.green_on:
        signal = "Green light"
      elif state.left_on:
        signal = "Left signal"
      elif state.right_on:
        signal = "Right signal"
      else:
        signal = "Signal"
      rl.draw_text(f"{signal}  {_distance(state.traffic_distance_m)}", x + 250, y + 185, 22,
                   rl.Color(255, 190, 120, 255))

  @staticmethod
  def _render_disconnected(rect: rl.Rectangle) -> None:
    # Keep the overlay quiet when no phone is linked; no stale navigation is shown.
    return
