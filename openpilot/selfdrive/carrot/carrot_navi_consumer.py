"""Validated, read-only consumer for the Carrot Navi Cereal service."""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any


MAX_NAV_AGE_SECONDS = 2.0


def _get(value: Any, name: str, default: Any = None) -> Any:
  if isinstance(value, dict):
    return value.get(name, default)
  return getattr(value, name, default)


def _finite(value: Any, default: float = 0.0) -> float:
  try:
    result = float(value)
  except (TypeError, ValueError):
    return default
  return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
  try:
    return int(value)
  except (TypeError, ValueError):
    return default


@dataclass(frozen=True)
class CarrotNaviState:
  connected: bool = False
  generation: int = 0
  session_id: str = ""
  publish_mono_time_nanos: int = 0
  road_name: str = ""
  guidance_text: str = ""
  next_road_name: str = ""
  distance_m: int = 0
  guidance_time_sec: int = 0
  turn_type: int = -1
  road_limit_kph: int = 0
  road_limit_valid: bool = False
  speed_kph: float = 0.0
  lane_count: int = 0
  current_lane: int = -1
  lane_distance_m: int = 0
  traffic_visible: bool = False
  traffic_distance_m: int = 0
  red_on: bool = False
  green_on: bool = False
  left_on: bool = False
  right_on: bool = False
  traffic_remaining_sec: int = 0
  route_remaining_distance_m: int = 0
  route_remaining_time_sec: int = 0
  guidance_active: bool = False
  off_route: bool = False
  route_present: bool = False


def state_from_cereal(value: Any) -> CarrotNaviState:
  vehicle = _get(value, "vehicle")
  guidance = _get(value, "guidanceCurrent")
  next_guidance = _get(value, "guidanceNext")
  speed = _get(value, "speed")
  lane = _get(value, "laneCurrent")
  traffic = _get(value, "trafficSignal")
  route = _get(value, "route")
  status = _get(value, "navigationStatus")
  return CarrotNaviState(
    connected=bool(_get(value, "connected", False)),
    generation=_integer(_get(value, "generation", 0)),
    session_id=str(_get(value, "sessionId", "")),
    publish_mono_time_nanos=max(0, _integer(_get(value, "publishMonoTimeNanos", 0))),
    road_name=str(_get(vehicle, "roadName", "")),
    guidance_text=str(_get(guidance, "mainText", "")),
    next_road_name=str(_get(next_guidance, "roadName", "")),
    distance_m=max(0, _integer(_get(guidance, "distanceM", 0))),
    guidance_time_sec=max(0, _integer(_get(guidance, "timeSec", 0))),
    turn_type=_integer(_get(guidance, "turnType", -1), -1),
    road_limit_kph=max(0, _integer(_get(speed, "roadLimitKph", 0))),
    road_limit_valid=bool(_get(speed, "roadLimitValid", False)),
    speed_kph=max(0.0, _finite(_get(speed, "currentKph", 0))),
    lane_count=max(0, _integer(_get(lane, "count", 0))),
    current_lane=_integer(_get(lane, "currentLane", -1), -1),
    lane_distance_m=max(0, _integer(_get(lane, "distanceM", 0))),
    traffic_visible=bool(_get(traffic, "visible", False)),
    traffic_distance_m=max(0, _integer(_get(traffic, "distanceM", 0))),
    red_on=bool(_get(traffic, "redOn", False)),
    green_on=bool(_get(traffic, "greenOn", False)),
    left_on=bool(_get(traffic, "leftOn", False)),
    right_on=bool(_get(traffic, "rightOn", False)),
    traffic_remaining_sec=max(0, _integer(_get(traffic, "uiCounterRemainSec", 0))),
    route_remaining_distance_m=max(0, _integer(_get(route, "remainingDistanceM", 0))),
    route_remaining_time_sec=max(0, _integer(_get(route, "remainingTimeSec", 0))),
    guidance_active=bool(_get(status, "guidanceActive", False)),
    off_route=bool(_get(status, "offRoute", False)),
    route_present=bool(_get(status, "routePresent", False)),
  )


class CarrotNaviConsumer:
  def __init__(self, messaging_module: Any | None = None,
               max_age_seconds: float = MAX_NAV_AGE_SECONDS) -> None:
    if messaging_module is None:
      import openpilot.cereal.messaging as messaging_module
    self.sm = messaging_module.SubMaster(["carrotNavi"])
    self.max_age_seconds = max(0.2, float(max_age_seconds))
    self.state: CarrotNaviState | None = None

  def update(self, timeout_ms: int = 0) -> bool:
    self.sm.update(timeout_ms)
    if not self.sm.updated.get("carrotNavi", False):
      if self.state is not None and not self._is_fresh(self.state):
        self.state = None
      return self.state is not None
    if not self.sm.valid.get("carrotNavi", False):
      self.state = None
      return False
    candidate = state_from_cereal(self.sm["carrotNavi"].carrotNavi)
    if not candidate.connected or not self._is_fresh(candidate):
      self.state = None
      return False
    self.state = candidate
    return True

  def _is_fresh(self, state: CarrotNaviState) -> bool:
    if state.publish_mono_time_nanos <= 0:
      return False
    age = (time.monotonic_ns() - state.publish_mono_time_nanos) / 1e9
    return 0.0 <= age <= self.max_age_seconds

  @property
  def available(self) -> bool:
    return self.state is not None and self._is_fresh(self.state)
