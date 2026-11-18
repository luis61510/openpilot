import unittest
from types import SimpleNamespace

from openpilot.cereal.services import QueueSize, SERVICE_LIST
PNG_BYTES = bytes.fromhex("89504e47")

from openpilot.selfdrive.carrot.carrot_navi_cereal import (
  CarrotNaviCerealPublisher,
  build_carrot_navi_media_payload,
  build_carrot_navi_payload,
)


class FakePubMaster:
  def __init__(self, services):
    self.services = services
    self.sent = []

  def send(self, service, message):
    self.sent.append((service, message))


class FakeMessaging:
  PubMaster = FakePubMaster

  @staticmethod
  def new_message(service, valid=True):
    return SimpleNamespace(service=service, valid=valid)


class FakeReceiver:
  def __init__(self, snapshot):
    self.snapshot = snapshot
    self.publish_errors = []

  def cereal_snapshot(self):
    return self.snapshot

  def record_cereal_publish(self, error=None):
    self.publish_errors.append(error)


def sample_snapshot():
  return {
    "generation": 9,
    "session_id": "a1b2c3d4",
    "connected": True,
    "items": {
      "vehicle": {
        "present": True,
        "sequence": 2,
        "source_timestamp_ms": 1000,
        "received_mono_ns": 2000,
        "value": {
          "lat": 30.5, "lon": 114.3, "heading_deg": 180,
          "speed_kph": 42, "road_name": "Test Road", "virtual_gps": False,
        },
      },
      "guidance_current": {
        "present": True,
        "sequence": 3,
        "source_timestamp_ms": 1001,
        "received_mono_ns": 2001,
        "value": {
          "distance_m": 250, "time_sec": 20, "turn_type": 2,
          "road_name": "Next Street", "main_text": "Turn left",
          "near_direction": "left", "point": {"lat": 30.51, "lon": 114.31},
        },
      },
      "lane_current": {
        "present": True,
        "sequence": 4,
        "source_timestamp_ms": 1002,
        "received_mono_ns": 2002,
        "value": {
          "count": 3, "distance_m": 120, "visible": True,
          "current_lane": 1, "turn_code": 2, "turn_info": [1, 2, 3],
          "etc_info": [4], "available": [1, 1, 0],
          "road_category": 2, "voice_code": 5,
        },
      },
      "lane_ahead": {
        "present": True,
        "sequence": 5,
        "source_timestamp_ms": 1003,
        "received_mono_ns": 2003,
        "value": [{"count": i} for i in range(10)],
      },
      "speed": {
        "present": True,
        "sequence": 6,
        "source_timestamp_ms": 1004,
        "received_mono_ns": 2004,
        "value": {
          "current_kph": 42, "road_limit_kph": 70,
          "sdi": {"type": 1, "distance_m": 300, "speed_limit_kph": 70},
          "sdi_secondary": {"type": 2, "distance_m": 600, "speed_limit_kph": 60},
          "section": {"active": True, "speed_limit_kph": 80, "progress": 0.5},
        },
      },
      "traffic_signal": {
        "present": True,
        "sequence": 7,
        "source_timestamp_ms": 1005,
        "received_mono_ns": 2005,
        "value": {
          "visible": True, "distance_m": 45, "source": "camera",
          "lights": {"red": {"on": True, "remain_sec": 12}},
          "ui_counter": {"remain_sec": 10},
        },
      },
      "crossroad": {
        "present": True,
        "sequence": 8,
        "source_timestamp_ms": 1006,
        "received_mono_ns": 2006,
        "value": {"visible": True, "distance_m": 30, "image_code": 4},
      },
      "route": {
        "present": True,
        "sequence": 9,
        "source_timestamp_ms": 1007,
        "received_mono_ns": 2007,
        "value": {
          "remain_distance_m": 1200, "remain_time_sec": 90,
          "polyline": [{"lat": 30.5, "lon": 114.3}],
        },
      },
      "navigation_status": {
        "present": True,
        "sequence": 10,
        "source_timestamp_ms": 1008,
        "received_mono_ns": 2008,
        "value": {"mode": "active", "guidance_active": True, "route_present": True},
      },
    },
  }


class CarrotNaviCerealPayloadTest(unittest.TestCase):
  def test_navigation_payload_maps_and_bounds_source_data(self):
    payload = build_carrot_navi_payload(sample_snapshot(), publish_mono_ns=3000)

    self.assertEqual(payload["schemaVersion"], 1)
    self.assertEqual(payload["generation"], 9)
    self.assertTrue(payload["connected"])
    self.assertEqual(payload["vehicle"]["latitude"], 30.5)
    self.assertEqual(payload["guidanceCurrent"]["mainText"], "Turn left")
    self.assertTrue(payload["guidanceCurrent"]["pointValid"])
    self.assertEqual(len(payload["laneAhead"]), 8)
    self.assertEqual(payload["speed"]["roadLimitKph"], 70)
    self.assertTrue(payload["speed"]["roadLimitValid"])
    self.assertTrue(payload["trafficSignal"]["redOn"])
    self.assertEqual(payload["route"]["polyline"][0]["longitude"], 114.3)

  def test_invalid_speed_limit_is_not_marked_valid(self):
    snapshot = sample_snapshot()
    snapshot["items"]["speed"]["value"]["road_limit_kph"] = 65
    payload = build_carrot_navi_payload(snapshot)
    self.assertFalse(payload["speed"]["roadLimitValid"])
    self.assertEqual(payload["speed"]["roadLimitKph"], 0)

  def test_media_payload_preserves_binary_bytes_and_metadata(self):
    record = SimpleNamespace(
      kind="image", name="tbt_current_compact", sequence=11,
      source_timestamp_ms=1200, received_mono_ns=3400, present=True,
      message_type=1, format_or_reason=1, flags=0, width=1, height=1,
      reason=None, payload=PNG_BYTES,
    )
    payload = build_carrot_navi_media_payload(record, "session-1")
    self.assertEqual(payload["sessionId"], "session-1")
    self.assertEqual(payload["payload"], PNG_BYTES)
    self.assertEqual(payload["width"], 1)
    self.assertTrue(payload["present"])

  def test_publisher_sends_navigation_and_media_services(self):
    receiver = FakeReceiver(sample_snapshot())
    publisher = CarrotNaviCerealPublisher(receiver, messaging_module=FakeMessaging)

    generation = publisher.publish_once()
    self.assertEqual(generation, 9)
    publisher.publish_media(SimpleNamespace(
      kind="image", name="tbt_current_compact", sequence=1,
      source_timestamp_ms=100, received_mono_ns=200, present=True,
      message_type=1, format_or_reason=1, flags=0, width=1, height=1,
      reason=None, payload=b"png",
    ), "session-1")

    self.assertEqual([name for name, _ in publisher.pm.sent],
                     ["carrotNavi", "carrotNaviMedia"])
    nav_message = publisher.pm.sent[0][1]
    media_message = publisher.pm.sent[1][1]
    self.assertEqual(nav_message.carrotNavi["generation"], 9)
    self.assertEqual(media_message.carrotNaviMedia["payload"], b"png")
    self.assertEqual(receiver.publish_errors, [None, None])

  def test_service_registry_has_non_conflicting_navigation_queues(self):
    self.assertEqual(SERVICE_LIST["carrotNavi"].frequency, 2.)
    self.assertTrue(SERVICE_LIST["carrotNavi"].should_log)
    self.assertEqual(SERVICE_LIST["carrotNaviMedia"].frequency, 20.)
    self.assertFalse(SERVICE_LIST["carrotNaviMedia"].should_log)
    self.assertEqual(SERVICE_LIST["carrotNaviMedia"].queue_size, QueueSize.BIG)


class CarrotNaviCerealSchemaTest(unittest.TestCase):
  def test_capnp_schema_compiles_and_round_trips_both_events(self):
    from openpilot.cereal import log

    nav_event = log.Event.new_message()
    nav = nav_event.init("carrotNavi")
    nav.schemaVersion = 1
    nav.generation = 7
    nav.connected = True
    nav.vehicle.latitude = 30.5
    nav.vehicle.longitude = 114.3
    nav.guidanceCurrent.mainText = "Turn left"
    restored_nav = log.Event.from_bytes(nav_event.to_bytes())
    self.assertEqual(restored_nav.which(), "carrotNavi")
    self.assertEqual(restored_nav.carrotNavi.vehicle.latitude, 30.5)
    self.assertEqual(restored_nav.carrotNavi.guidanceCurrent.mainText, "Turn left")

    media_event = log.Event.new_message()
    media = media_event.init("carrotNaviMedia")
    media.schemaVersion = 1
    media.kind = "image"
    media.name = "tbt_current_compact"
    media.payload = PNG_BYTES
    restored_media = log.Event.from_bytes(media_event.to_bytes())
    self.assertEqual(restored_media.which(), "carrotNaviMedia")
    self.assertEqual(restored_media.carrotNaviMedia.payload, PNG_BYTES)


if __name__ == "__main__":
  unittest.main()
