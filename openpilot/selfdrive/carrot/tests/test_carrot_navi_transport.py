import asyncio
import json
import socket
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from openpilot.selfdrive.carrot.carrot_navi import (
  BINARY_HEADER,
  CATALOG,
  DISCOVERY_PORT,
  PROTOCOL_VERSION,
  CarrotNaviDiscoveryBeacon,
  CarrotNaviReceiver,
  create_app,
  parse_binary_packet,
)


PNG_1X1 = bytes.fromhex(
  "89504e470d0a1a0a"
  "0000000d49484452000000010000000108060000001f15c489"
  "0000000b49444154789c636000020000050001a5f64540"
  "0000000049454e44ae426082"
)


def requirements_payload():
  return {
    "type": "requirements_query",
    "protocol_version": PROTOCOL_VERSION,
    "timestamp_ms": 1783920000000,
    "app_version": "11.2.3.3740",
    "catalog_revision": 1,
    "limits": {
      "max_binary_frame_bytes": 8388608,
      "max_total_bitrate_kbps": 12000,
    },
    "streams": [
      {"kind": kind, "name": name, "schema_version": 1}
      for kind, name in CATALOG
    ],
  }


def binary_packet(stream, revision, payload=PNG_1X1, sequence=1):
  header = BINARY_HEADER.pack(
    b"CNV2", PROTOCOL_VERSION, 1, 1, 0,
    stream["stream_handle"], revision, sequence, 1783920000200,
    len(payload), 1, 1,
  )
  return header + payload


class CarrotNaviTransportTest(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.receiver = CarrotNaviReceiver()
    self.client = TestClient(TestServer(create_app(self.receiver)))
    await self.client.start_server()

  async def asyncTearDown(self):
    await self.client.close()

  async def negotiate(self):
    ws = await self.client.ws_connect("/api/navi/ws/v2/control/11.2.3.3740")
    await ws.send_json(requirements_payload())
    manifest = await ws.receive_json(timeout=3)
    self.assertEqual(manifest["type"], "subscription_manifest")
    return ws, manifest

  async def test_health_and_discovery_document(self):
    health = await self.client.get("/health")
    self.assertEqual(health.status, 200)
    health_data = await health.json()
    self.assertTrue(health_data["ok"])
    self.assertIn("control_connected", health_data)

    index = await self.client.get("/")
    self.assertEqual(index.status, 200)
    index_data = await index.json()
    self.assertEqual(index_data["protocol_version"], PROTOCOL_VERSION)
    self.assertEqual(index_data["port"], 7714)
    self.assertIn("/api/navi/ws/v2/control/{version}", index_data["ws_control"])

  async def test_control_negotiation_and_json_stream(self):
    ws, manifest = await self.negotiate()
    self.assertEqual(len(manifest["streams"]), 28)

    stream = next(item for item in manifest["streams"]
                  if item["kind"] == "json" and item["name"] == "guidance_current")
    self.assertTrue(stream["enabled"])
    session_id = manifest["session_id"]
    item_ws = await self.client.ws_connect(
      f"/api/navi/ws/v2/json/{session_id}/guidance_current"
    )
    await item_ws.send_json({
      "type": "item_update",
      "protocol_version": PROTOCOL_VERSION,
      "session_id": session_id,
      "manifest_revision": manifest["revision"],
      "schema_version": stream["schema_version"],
      "kind": "json",
      "name": "guidance_current",
      "stream_handle": stream["stream_handle"],
      "sequence": 1,
      "source_timestamp_ms": 1783920000200,
      "sent_at_ms": 1783920000201,
      "present": True,
      "value": {"distance_m": 120, "turn_type": "left"},
    })

    await asyncio.sleep(0.05)
    latest = await (await self.client.get("/api/navi/latest")).json()
    self.assertGreaterEqual(latest.get("session_received_count", 0), 1)
    self.assertIsNone(self.receiver.health().get("error"))

    await item_ws.close()
    await ws.close()

  async def test_valid_png_binary_frame_reaches_latest_cache(self):
    control_ws, manifest = await self.negotiate()
    stream = next(item for item in manifest["streams"]
                  if item["kind"] == "image" and item["name"] == "tbt_current_compact")
    self.assertTrue(stream["enabled"])
    packet = binary_packet(stream, manifest["revision"])
    metadata, payload = parse_binary_packet(packet)
    self.assertEqual(payload, PNG_1X1)
    self.assertEqual(metadata["width"], 1)

    image_ws = await self.client.ws_connect(
      f"/api/navi/ws/v2/image/{manifest['session_id']}/tbt_current_compact"
    )
    await image_ws.send_bytes(packet)
    await asyncio.sleep(0.05)

    latest = await (await self.client.get("/api/navi/latest")).json()
    item = latest["items"]["image:tbt_current_compact"]
    self.assertTrue(item["present"])
    self.assertEqual(item["bytes"], len(PNG_1X1))
    self.assertEqual(item["message_type"], 1)
    self.assertEqual(item["width"], 1)
    self.assertIsNone(latest["error"])

    await image_ws.close()
    await control_ws.close()

  async def test_binary_stream_rejects_bad_payload(self):
    control_ws, manifest = await self.negotiate()
    stream = next(item for item in manifest["streams"]
                  if item["kind"] == "image" and item["name"] == "tbt_current_compact")
    packet = binary_packet(stream, manifest["revision"], payload=b"not-a-png")
    image_ws = await self.client.ws_connect(
      f"/api/navi/ws/v2/image/{manifest['session_id']}/tbt_current_compact"
    )
    await image_ws.send_bytes(packet)
    response = await image_ws.receive_json(timeout=3)
    self.assertEqual(response["type"], "protocol_error")
    self.assertEqual(response["code"], "binary_stream_error")
    await image_ws.receive()
    self.assertEqual(image_ws.close_code, 1008)
    await control_ws.close()

  async def test_control_disconnect_and_reconnect_creates_fresh_session(self):
    first_ws, first_manifest = await self.negotiate()
    first_session = first_manifest["session_id"]
    await first_ws.close()

    for _ in range(20):
      if not self.receiver.health()["control_connected"]:
        break
      await asyncio.sleep(0.01)
    self.assertFalse(self.receiver.health()["control_connected"])

    second_ws, second_manifest = await self.negotiate()
    self.assertNotEqual(first_session, second_manifest["session_id"])
    self.assertEqual(second_manifest["type"], "subscription_manifest")
    self.assertTrue(self.receiver.health()["control_connected"])
    await second_ws.close()

  async def test_binary_header_rejects_invalid_magic(self):
    with self.assertRaises(ValueError):
      parse_binary_packet(b"not-a-valid-CNV2-frame")


class CarrotNaviDiscoveryTest(unittest.TestCase):
  def test_udp_discovery_broadcast_payload(self):
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.settimeout(2.0)
    try:
      listener.bind(("127.0.0.1", DISCOVERY_PORT))
      beacon = CarrotNaviDiscoveryBeacon(interval_s=0.2)
      with patch(
        "openpilot.selfdrive.carrot.carrot_navi.discovery_targets",
        return_value=(("127.0.0.1", "127.0.0.1"),),
      ):
        beacon.broadcast_once()
      payload, peer = listener.recvfrom(2048)
      message = json.loads(payload.decode("utf-8"))
      self.assertEqual(message, {"ip": "127.0.0.1", "navi_debug": 1})
      self.assertEqual(peer[0], "127.0.0.1")
    finally:
      listener.close()


if __name__ == "__main__":
  unittest.main()
