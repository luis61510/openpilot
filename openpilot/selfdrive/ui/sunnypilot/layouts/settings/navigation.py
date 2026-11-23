"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import socket

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import text_item
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import LineSeparator, Scroller


class NavigationLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    items = [
      text_item(lambda: tr("Phone setup address"), self._get_address),
      LineSeparator(),
      text_item(lambda: tr("Pairing code"), self._get_pairing_code),
      LineSeparator(),
      text_item(lambda: tr("How to use"), lambda: tr("Connect your phone to the same Wi-Fi, open the address above, enter the pairing code, then search or select a destination.")),
    ]
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  @staticmethod
  def _get_device_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
      sock.connect(("8.8.8.8", 53))
      return sock.getsockname()[0]
    except OSError:
      return None
    finally:
      sock.close()

  def _get_address(self):
    ip = self._get_device_ip()
    return f"http://{ip}:8765" if ip else tr("Connect Comma to Wi-Fi to show its address")

  def _get_pairing_code(self):
    return self._params.get("NavigationWebToken") or tr("Starting navigation web service...")

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
