"""Runtime Cereal contract checks for the Comma 4 release-mici environment.

These checks exercise the Python Cap'n Proto runtime used by the installed device.
They intentionally do not pretend to compile the checked-in C++ generated files:
the release-mici install branch does not include the top-level SCons build graph.
"""

import os
from pathlib import Path
from importlib.metadata import version

from cereal import custom, log
from cereal.services import SERVICE_LIST


NAVASSIST_SERVICES = (
  "navAssistStateSP",
  "laneTopologyStateSP",
  "navLaneIntentSP",
)

EXPECTED_CUSTOM_FIELDS = (
  ("NavAssistStateSP", custom.NavAssistStateSP, {
    "publishMonoTime", "receiveMonoTime", "sequence", "routeRevision",
    "sessionId", "valid", "stale", "maneuver", "lanes",
  }),
  ("LaneTopologyStateSP", custom.LaneTopologyStateSP, {
    "publishMonoTime", "modelMonoTime", "imageMonoTime", "valid", "stale",
    "calibrationValid", "topologyState", "validForControl",
    "leftMarking", "rightMarking", "leftEvidenceValid", "rightEvidenceValid",
  }),
  ("NavLaneIntentSP", custom.NavLaneIntentSP, {
    "publishMonoTime", "valid", "signalRequested", "laneChangeAuthorized",
    "direction", "requestId", "targetLaneIndex", "forkNow",
    "allowUnknownCrossing", "ignoreSolidBoundary",
  }),
)


def test_c4_runtime_dependency_and_device_contract():
  assert version("pycapnp") == "2.1.0", "release-mici runtime requires pycapnp 2.1.0"

  if os.path.isfile("/TICI"):
    from openpilot.system.hardware import HARDWARE, TICI, PC
    assert TICI and not PC
    assert HARDWARE.get_device_type().lower() == "mici", "this port targets Comma 4 (mici)"


def test_navassist_cereal_event_and_service_registry():
  event_fields = log.Event.schema.fields
  for service in NAVASSIST_SERVICES:
    assert service in event_fields, f"missing Event union field: {service}"
    assert service in SERVICE_LIST, f"missing Python cereal service registration: {service}"

  # The installed C4 package has a second generated C++ service registry.
  packaged_services = Path(__file__).resolve().parents[3] / "openpilot/cereal/services.h"
  packaged_header = packaged_services.read_text()
  for service in NAVASSIST_SERVICES:
    assert f'"{service}"' in packaged_header, f"missing packaged C++ service registration: {service}"


def test_navassist_custom_struct_fields_are_loaded_by_pycapnp():
  for name, schema, expected_fields in EXPECTED_CUSTOM_FIELDS:
    actual_fields = set(schema.schema.fields)
    assert expected_fields <= actual_fields, (
      f"{name} missing fields: {sorted(expected_fields - actual_fields)}"
    )


def test_c4_navassist_process_modules_import_against_release_mici_cereal():
  # release-mici exposes the Python Cereal API as top-level "cereal".
  # openpilot/cereal only contains generated/native package artifacts.
  from openpilot.sunnypilot.navassist import navassistd, lane_topologyd, nav_lane_intentd
  assert navassistd.log is log
  assert lane_topologyd.log is log
  assert navassistd.messaging is lane_topologyd.messaging


def test_navassist_messages_round_trip_through_cereal_runtime():
  for service in NAVASSIST_SERVICES:
    event = log.Event.new_message()
    payload = event.init(service)
    payload.valid = True
    payload.publishMonoTime = 123456789
    encoded = event.to_bytes()

    with log.Event.from_bytes(encoded) as decoded:
      assert decoded.which() == service
      decoded_payload = getattr(decoded, service)
      assert decoded_payload.valid
      assert decoded_payload.publishMonoTime == 123456789


def test_model_data_v2_sp_navassist_diagnostics_fields_are_loaded():
  expected = {
    "laneTurnDirection",
    "leftLaneChangeEdgeBlock",
    "rightLaneChangeEdgeBlock",
    "turnEntryModelMonoTime",
    "turnEntryInputReason",
    "turnEntryLeftReason",
    "turnEntryRightReason",
    "turnDecisionReason",
  }
  actual = set(custom.ModelDataV2SP.schema.fields)
  assert expected <= actual, f"ModelDataV2SP missing fields: {sorted(expected - actual)}"


if __name__ == "__main__":
  test_c4_runtime_dependency_and_device_contract()
  test_navassist_cereal_event_and_service_registry()
  test_navassist_custom_struct_fields_are_loaded_by_pycapnp()
  test_c4_navassist_process_modules_import_against_release_mici_cereal()
  test_navassist_messages_round_trip_through_cereal_runtime()
  test_model_data_v2_sp_navassist_diagnostics_fields_are_loaded()
  print("C4 Cereal runtime schema checks: PASS")
