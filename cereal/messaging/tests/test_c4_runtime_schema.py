"""Runtime Cereal contract checks for the Comma 4 release-mici environment.

These checks exercise the Python Cap'n Proto runtime used by the installed device.
They intentionally do not pretend to compile the checked-in C++ generated files:
the release-mici install branch does not include the top-level SCons build graph.
"""

from cereal import custom, log
from cereal.services import SERVICE_LIST


NAVASSIST_SERVICES = (
  "navAssistStateSP",
  "laneTopologyStateSP",
  "navLaneIntentSP",
)

EXPECTED_CUSTOM_FIELDS = {
  custom.NavAssistStateSP: {
    "publishMonoTime", "receiveMonoTime", "sequence", "routeRevision",
    "sessionId", "valid", "stale", "maneuver", "lanes",
  },
  custom.LaneTopologyStateSP: {
    "publishMonoTime", "modelMonoTime", "imageMonoTime", "valid", "stale",
    "calibrationValid", "topologyState", "validForControl",
    "leftMarking", "rightMarking", "leftEvidenceValid", "rightEvidenceValid",
  },
  custom.NavLaneIntentSP: {
    "publishMonoTime", "valid", "signalRequested", "laneChangeAuthorized",
    "direction", "requestId", "targetLaneIndex", "forkNow",
    "allowUnknownCrossing", "ignoreSolidBoundary",
  },
}


def test_navassist_cereal_event_and_service_registry():
  event_fields = log.Event.schema.fields
  for service in NAVASSIST_SERVICES:
    assert service in event_fields, f"missing Event union field: {service}"
    assert service in SERVICE_LIST, f"missing cereal service registration: {service}"


def test_navassist_custom_struct_fields_are_loaded_by_pycapnp():
  for schema, expected_fields in EXPECTED_CUSTOM_FIELDS.items():
    actual_fields = set(schema.schema.fields)
    assert expected_fields <= actual_fields, (
      f"{schema.__name__} missing fields: {sorted(expected_fields - actual_fields)}"
    )


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
