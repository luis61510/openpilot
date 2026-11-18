"""Read-only Carrot Navi Cereal consumer for UI and navigation integrations.

This module intentionally does not alter GPS, cruise speed, lateral control, or
route state. It provides a single validated navigation snapshot for later
consumers while preserving the existing SunnyPilot source-of-truth rules.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any


MAX_NAV_AGE_SECONDS = 2.0


@dataclass(frozen=True)
class CarrotNaviState:
  connected: bool
  generation: int
  session_id: str
  latitude: float
  longitude: float
  speed_kph: float
  road_limit_kph: int
  road_limit_valid: bool
  guidance_distance_m: int
  guidance_time_sec: int
  turn_type: int
  main_text: str
  route_remaining_distance_m: int
  route_remaining_time_sec: int
  guidance_active: bool
  off_route: bool
  publish_mono_time_nanos: int


def _finite(value: Any, default: float = 0.0) -> float:
  try:
    value = float(value)
  except (TypeError, ValueError):
    return default
  return value if math.isfinite(value) else default


def _integer(value: Any, default: int = 0) -> int:
  try:
    return int(value)
  except (TypeError, ValueError):
    return default


def _dict(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def state_from_cereal(value: Any) -> CarrotNaviState:
  vehicle = _dict(getattr(value, "vehicle", None))
  guidance = _dict(getattr(value, "guidanceCurrent", None))
  speed = _dict(getattr(value, "speed", None))
  route = _dict(getattr(value, "route", None))
  status = _dict(getattr(value, "navigationStatus", None))

  return CarrotNaviState(
    connected=bool(getattr(value, "connected", False)),
    generation=_integer(getattr(value, "generation", 0)),
    session_id=str(getattr(value, "sessionId", "")),
    latitude=_finite(vehicle.get("latitude")),
    longitude=_finite(vehicle.get("longitude")),
    speed_kph=max(0.0, _finite(vehicle.get("speedKph"))),
    road_limit_kph=max(0, _integer(speed.get("roadLimitKph"))),
    road_limit_valid=bool(speed.get("roadLimitValid", False)),
    guidance_distance_m=max(0, _integer(guidance.get("distanceM"))),
    guidance_time_sec=max(0, _integer(guidance.get("timeSec"))),
    turn_type=_integer(guidance.get("turnType"), -1),
    main_text=str(guidance.get("mainText", "")),
    route_remaining_distance_m=max(0, _integer(route.get("remainingDistanceM"))),
    route_remaining_time_sec=max(0, _integer(route.get("remainingTimeSec"))),
    guidance_active=bool(status.get("guidanceActive", False)),
    off_route=bool(status.get("offRoute", False)),
    publish_mono_time_nanos=max(0, _integer(getattr(value, "publishMonoTimeNanos", 0))),
  )


class CarrotNaviConsumer:
  def __init__(self, messaging_module: Any | None = None,
               max_age_seconds: float = MAX_NAV_AGE_SECONDS) -> None:
    if messaging_module is None:
      import openpilot.cereal.messaging as messaging_module
    self.messaging = messaging_module
    self.sm = messaging_module.SubMaster(["carrotNavi"])
    self.max_age_seconds = max(0.2, float(max_age_seconds))
    self.state: CarrotNaviState | None = None

  def update(self, timeout_ms: int = 0) -> bool:
    self.sm.update(timeout_ms)
    if not self.sm.updated.get("carrotNavi", False):
      return False

    message = self.sm["carrotNavi"]
    if not self.sm.valid.get("carrotNavi", False):
      self.state = None
      return False

    candidate = state_from_cereal(message.carrotNavi)
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
    return self.state is not None
