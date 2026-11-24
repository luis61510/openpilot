#!/usr/bin/env python3
"""Authenticated local web interface for setting the navigation destination.

The page is served by the Comma device itself. Only the destination parameter is
writable; no generic Params endpoint is exposed.
"""
import ipaddress
import json
import math
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

HOST = "0.0.0.0"
PORT = 8765
MAX_BODY = 16_384
AMAP_HOSTS = {"uri.amap.com", "surl.amap.com", "amap.com", "www.amap.com", "m.amap.com", "ditu.amap.com", "gaode.com", "www.gaode.com"}
PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comma 导航目的地</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}body{font:16px system-ui,sans-serif;margin:0;background:#f4f6f8;color:#17202a}
main{max-width:760px;margin:auto;padding:18px}.panel{background:white;border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 2px 10px #0001}
h2{margin:4px 0 12px;font-size:21px}input,button{font:inherit;padding:12px;border-radius:9px;border:1px solid #c7cdd4;width:100%;margin:5px 0}
button{background:#1769d2;color:white;border:0;font-weight:600}button.secondary{background:#5c6672}button.danger{background:#a83232}
#map{height:360px;border-radius:10px;margin-top:10px}.muted{color:#65717d;font-size:14px}.status{white-space:pre-wrap}.row{display:flex;gap:8px}.row>*{flex:1}
</style></head><body><main>
<div class="panel"><h2>Comma 导航目的地</h2><div class="muted">手机和 Comma 设备需连接同一 Wi-Fi。请先在 Comma「设置 → 导航」中查看配对码。</div></div>
<div class="panel"><h2>1. 配对</h2><input id="token" autocomplete="off" placeholder="输入 Comma 屏幕上的配对码"><button id="pair">连接设备</button><div id="status" class="status muted"></div></div>
<div class="panel"><h2>2. 搜索地点或地图选点</h2><input id="query" placeholder="输入地点名称，例如 武昌实验中学"><button id="search" class="secondary">搜索地点</button><div id="results"></div><div id="map"></div><div class="muted">地图数据来自 OpenStreetMap。点击地图可选择目的地。</div></div>
<div class="panel"><h2>3. 高德地图分享链接</h2><input id="amap" placeholder="粘贴高德地图分享链接"><button id="parse" class="secondary">解析分享链接</button><div class="muted">支持包含坐标的高德 marker/navigation 分享链接。短链接会尝试安全解析；无法识别时可在地图上重新选点。</div></div>
<div class="panel"><h2>当前目的地</h2><div id="current" class="status muted">请先配对</div><div class="row"><button id="send">发送到 Comma</button><button id="clear" class="danger">清除目的地</button></div></div>
</main><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
let token="", selected=null, map=null, marker=null;
const $=id=>document.getElementById(id);
function say(s){$("status").textContent=s}
function setPoint(lon,lat,name){selected={longitude:lon,latitude:lat,name:name||"地图选点"};$("current").textContent=selected.name+"\n经度 "+lon.toFixed(6)+"，纬度 "+lat.toFixed(6);if(map){if(marker)marker.remove();marker=L.marker([lat,lon]).addTo(map);map.setView([lat,lon],15)}}
async function api(path,body){const r=await fetch(path,{method:body===undefined?"GET":"POST",headers:{"Authorization":"Bearer "+token,"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(d.error||"请求失败");return d}
$("pair").onclick=async()=>{token=$("token").value.trim();try{const d=await api("/api/status");say("已连接 Comma 设备");$("current").textContent=d.destination?JSON.stringify(d.destination,null,2):"尚未设置目的地"}catch(e){token="";say("配对失败："+e.message)}};
$("search").onclick=async()=>{const q=$("query").value.trim();if(!q)return;try{const r=await fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&q="+encodeURIComponent(q));const rows=await r.json();$("results").innerHTML="";rows.forEach(x=>{const b=document.createElement("button");b.className="secondary";b.textContent=x.display_name;b.onclick=()=>setPoint(Number(x.lon),Number(x.lat),x.display_name);$("results").appendChild(b)})}catch(e){say("地点搜索失败："+e.message)}};
$("parse").onclick=async()=>{try{const d=await api("/api/parse-amap",{url:$("amap").value.trim()});setPoint(d.longitude,d.latitude,d.name||"高德分享地点");say("已解析高德分享链接，请确认地图位置后发送")}catch(e){say("解析失败："+e.message)}};
$("send").onclick=async()=>{if(!selected){say("请先搜索地点或在地图上选点");return}try{await api("/api/destination",selected);say("目的地已发送到 Comma")}catch(e){say("发送失败："+e.message)}};
$("clear").onclick=async()=>{try{await api("/api/destination",{clear:true});selected=null;$("current").textContent="目的地已清除";if(marker){marker.remove();marker=null}say("已清除 Comma 导航目的地")}catch(e){say("清除失败："+e.message)}};
if(window.L){map=L.map("map").setView([30.5928,114.3055],11);L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"© OpenStreetMap"}).addTo(map);map.on("click",e=>setPoint(e.latlng.lng,e.latlng.lat,"地图选点"))}
</script></body></html>"""


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
  """Convert mainland-China GCJ-02 coordinates to WGS84 for the route backend."""
  if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
    return lon, lat

  a, ee = 6378245.0, 0.00669342162296594323

  def transform_lat(x, y):
    value = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    value += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    value += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    value += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return value

  def transform_lon(x, y):
    value = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    value += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    value += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    value += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return value

  dlat, dlon = transform_lat(lon - 105.0, lat - 35.0), transform_lon(lon - 105.0, lat - 35.0)
  radlat = lat / 180.0 * math.pi
  magic = 1 - ee * math.sin(radlat) ** 2
  sqrtmagic = math.sqrt(magic)
  dlat = dlat * 180.0 / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
  dlon = dlon * 180.0 / (a / sqrtmagic * math.cos(radlat) * math.pi)
  return lon * 2 - (lon + dlon), lat * 2 - (lat + dlat)


def _parse_coordinates(value: str) -> tuple[float, float] | None:
  parts = value.split(",")
  if len(parts) < 2:
    return None
  try:
    lon, lat = float(parts[0]), float(parts[1])
  except ValueError:
    return None
  if not (-180 <= lon <= 180 and -90 <= lat <= 90):
    return None
  return gcj02_to_wgs84(lon, lat)


def parse_amap_url(raw_url: str) -> dict:
  parsed = urlparse(raw_url.strip())
  if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in AMAP_HOSTS:
    raise ValueError("只接受高德地图域名的分享链接")
  current = raw_url.strip()
  for _ in range(4):
    parsed = urlparse(current)
    host = (parsed.hostname or "").lower()
    if host not in AMAP_HOSTS:
      raise ValueError("分享链接跳转到了非高德域名，已阻止")
    query = parse_qs(parsed.query)
    for key in ("position", "to", "location", "destination", "coordinate", "center"):
      values = query.get(key, [])
      if values:
        coords = _parse_coordinates(values[0])
        if coords:
          return {"longitude": coords[0], "latitude": coords[1], "name": (query.get("name") or query.get("poiname") or ["高德分享地点"])[0][:120]}
    if host != "surl.amap.com":
      break
    response = requests.get(current, allow_redirects=False, timeout=4, headers={"User-Agent": "CommaNavigation/1.0"})
    if response.is_redirect and response.headers.get("Location"):
      from urllib.parse import urljoin
      current = urljoin(current, response.headers["Location"])
      continue
    break
  raise ValueError("未在分享链接中找到经纬度；请用网页搜索或地图选点")


def _private_peer(address: str) -> bool:
  try:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return ip.is_private or ip.is_loopback or ip.is_link_local
  except ValueError:
    return False


class NavigationRequestHandler(BaseHTTPRequestHandler):
  server_version = "CommaNavigation/1.0"

  def log_message(self, fmt, *args):
    cloudlog.debug("navigation_webd: " + fmt % args)

  def _send(self, status: int, payload: bytes, content_type: str):
    self.send_response(status)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(payload)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("Content-Security-Policy", "default-src 'self' https:; script-src 'self' https://unpkg.com 'unsafe-inline'; style-src 'self' https://unpkg.com 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self' https:")
    self.end_headers()
    self.wfile.write(payload)

  def _json(self, status: int, data: dict):
    self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

  def _authorized(self) -> bool:
    auth = self.headers.get("Authorization", "")
    expected = "Bearer " + (Params().get("NavigationWebToken") or "")
    return len(expected) > 10 and secrets.compare_digest(auth, expected)

  def _body(self) -> dict:
    length = int(self.headers.get("Content-Length", "0"))
    if length <= 0 or length > MAX_BODY:
      raise ValueError("请求内容大小无效")
    value = json.loads(self.rfile.read(length))
    if not isinstance(value, dict):
      raise ValueError("请求格式无效")
    return value

  def do_GET(self):
    host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
    if host not in ("localhost", "127.0.0.1") and not _private_peer(host):
      return self._json(403, {"error": "只允许通过局域网 IP 访问"})
    if self.path == "/":
      return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
    if self.path == "/api/status":
      if not self._authorized():
        return self._json(401, {"error": "配对码错误或未配对"})
      params = Params()
      destination = params.get("NavDestination")
      return self._json(200, {"destination": destination, "navigation_enabled": params.get_bool("NavigationEnabled")})
    return self._json(404, {"error": "not found"})

  def do_POST(self):
    if not _private_peer(self.client_address[0]):
      return self._json(403, {"error": "只允许局域网设备访问"})
    if not self._authorized():
      return self._json(401, {"error": "配对码错误或未配对"})
    try:
      body = self._body()
      params = Params()
      if self.path == "/api/status":
        destination = params.get("NavDestination")
        return self._json(200, {"destination": destination, "navigation_enabled": params.get_bool("NavigationEnabled")})
      if self.path == "/api/parse-amap":
        result = parse_amap_url(str(body.get("url", ""))[:2048])
        return self._json(200, result)
      if self.path == "/api/destination":
        if body.get("clear") is True:
          params.remove("NavDestination")
          params.put_bool("NavigationEnabled", False, block=True)
          if params.get("NavDestination") is not None or params.get_bool("NavigationEnabled"):
            raise RuntimeError("清除目的地后状态校验失败")
          return self._json(200, {"ok": True, "cleared": True, "navigation_enabled": False})
        lon, lat = float(body.get("longitude")), float(body.get("latitude"))
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
          raise ValueError("经纬度超出有效范围")
        name = str(body.get("name", "手机设置的目的地"))[:120]
        params.put("NavDestination", {"longitude": lon, "latitude": lat, "name": name}, block=True)
        params.put_bool("NavigationEnabled", True, block=True)
        stored_destination = params.get("NavDestination")
        if not isinstance(stored_destination, dict) or not params.get_bool("NavigationEnabled"):
          raise RuntimeError("目的地写入后状态校验失败")
        if stored_destination.get("longitude") != lon or stored_destination.get("latitude") != lat:
          raise RuntimeError("目的地坐标写入校验失败")
        cloudlog.info("navigation_webd: destination updated from paired local client")
        return self._json(200, {"ok": True, "destination": stored_destination, "navigation_enabled": True})
      return self._json(404, {"error": "not found"})
    except (ValueError, TypeError, json.JSONDecodeError, requests.RequestException) as e:
      return self._json(400, {"error": str(e)})
    except Exception:
      cloudlog.exception("navigation_webd request failed")
      return self._json(500, {"error": "设备处理请求失败"})

  def do_OPTIONS(self):
    self._json(405, {"error": "method not allowed"})


def main():
  params = Params()
  if not params.get("NavigationWebToken"):
    params.put("NavigationWebToken", secrets.token_hex(16), block=True)
  server = ThreadingHTTPServer((HOST, PORT), NavigationRequestHandler)
  server.daemon_threads = True
  cloudlog.info(f"navigation_webd listening on port {PORT}")
  try:
    server.serve_forever(poll_interval=0.5)
  finally:
    server.server_close()


if __name__ == "__main__":
  main()
