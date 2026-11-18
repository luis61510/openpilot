import asyncio
import unittest

from aiohttp.test_utils import TestClient, TestServer

from openpilot.selfdrive.carrot.carrot_navi import (
  CATALOG,
  CarrotNaviReceiver,
  PROTOCOL_VERSION,
  create_app,
  parse_binary_packet,
)


class CarrotNaviTransportTest(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.receiver = CarrotNaviReceiver()
    self.client = TestClient(TestServer(create_app(self.receiver)))
    await self.client.start_server()

  async def asyncTearDown(self):
    await self.client.close()

  async def test_health_and_discovery_document(self):
    health = await self.client.get("/health")
    self.assertEqual(health.status, 200)
    health_data = await health.json()
    self.assertIn("connected", health_data)

    index = await self.client.get("/")
    self.assertEqual(index.status, 200)
    index_data = await index.json()
    self.assertEqual(index_data["protocol_version"], PROTOCOL_VERSION)
    self.assertEqual(index_data["port"], 7714)
    self.assertIn("/api/navi/ws/v2/control/{version}", index_data["ws_control"])

  async def test_control_negotiation_and_json_stream(self):
    ws = await self.client.ws_connect("/api/navi/ws/v2/control/11.2.3.3740")
    requirements = {
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
    await ws.send_json(requirements)
    response = await ws.receive_json(timeout=3)
    self.assertEqual(response["type"], "subscription_manifest")
    self.assertEqual(response["protocol_version"], PROTOCOL_VERSION)
    self.assertEqual(len(response["streams"]), 28)

    stream = next(item for item in response["streams"]
                  if item["kind"] == "json" and item["name"] == "guidance_current")
    self.assertTrue(stream["enabled"])
    session_id = response["session_id"]
    item_ws = await self.client.ws_connect(
      f"/api/navi/ws/v2/json/{session_id}/guidance_current"
    )
    await item_ws.send_json({
      "type": "item_update",
      "protocol_version": PROTOCOL_VERSION,
      "session_id": session_id,
      "manifest_revision": response["revision"],
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
    self.assertIsNone(self.receiver.health().get("last_error"))

    await item_ws.close()
    await ws.close()

  async def test_binary_header_rejects_invalid_magic(self):
    with self.assertRaises(ValueError):
      parse_binary_packet(b"not-a-valid-CNV2-frame")


if __name__ == "__main__":
  unittest.main()
