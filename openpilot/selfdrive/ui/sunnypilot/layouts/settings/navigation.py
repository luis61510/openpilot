"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import socket

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import FontWeight, TextAlignment, TextAlignmentVertical
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import LineSeparator, Scroller


class CompactParamItem(Widget):
  """Two-line, compact parameter row for small Comma displays."""
  def __init__(self, title, value):
    super().__init__()
    self._title = title
    self._value = value
    self.set_rect(rl.Rectangle(0, 0, 600, 116))

  def _render(self, _rect):
    title_rect = rl.Rectangle(self._rect.x + 20, self._rect.y + 8, self._rect.width - 40, 38)
    value_rect = rl.Rectangle(self._rect.x + 20, self._rect.y + 48, self._rect.width - 40, 60)
    gui_label(title_rect, self._title(), font_size=26, color=rl.Color(170, 170, 170, 255),
              font_weight=FontWeight.NORMAL, alignment=TextAlignment.LEFT,
              alignment_vertical=TextAlignmentVertical.MIDDLE)
    gui_label(value_rect, self._value(), font_size=32, color=rl.WHITE,
              font_weight=FontWeight.NORMAL, alignment=TextAlignment.LEFT,
              alignment_vertical=TextAlignmentVertical.MIDDLE)


class NavigationLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    items = [
      CompactParamItem(lambda: tr("Phone setup address"), self._get_address),
      LineSeparator(),
      CompactParamItem(lambda: tr("Pairing code"), self._get_pairing_code),
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
