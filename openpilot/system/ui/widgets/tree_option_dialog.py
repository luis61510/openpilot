from dataclasses import dataclass, field

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller


@dataclass
class TreeNode:
  ref: str
  data: dict = field(default_factory=dict)


@dataclass
class TreeFolder:
  folder: str
  nodes: list[TreeNode]


def _matches(query: str, values: list[str]) -> bool:
  terms = [term.casefold() for term in query.split() if term.strip()]
  return all(any(term in value.casefold() for value in values) for term in terms)


class TreeItemWidget(Button):
  def __init__(self, text, ref, is_folder=False, indent_level=0, click_callback=None,
               favorite_callback=None, is_favorite=False):
    super().__init__(text, click_callback, button_style=ButtonStyle.NORMAL,
                     text_padding=30 + indent_level * 45, elide_right=True)
    self.ref = ref
    self.is_folder = is_folder
    self.indent_level = indent_level
    self.favorite_callback = favorite_callback
    self.is_favorite = is_favorite
    self.selected = False
    self._font = gui_app.font(FontWeight.MEDIUM)

  def _render(self, rect):
    super()._render(rect)
    if self.favorite_callback and not self.is_folder:
      star = "★" if self.is_favorite else "☆"
      color = rl.Color(255, 205, 65, 255) if self.is_favorite else rl.GRAY
      rl.draw_text_ex(self._font, star, rl.Vector2(rect.x + rect.width - 82, rect.y + 25), 65, 0, color)

  def _handle_mouse_release(self, mouse_pos):
    if self.favorite_callback and not self.is_folder:
      star_rect = rl.Rectangle(self._rect.x + self._rect.width - 100, self._rect.y, 100, self._rect.height)
      if rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), star_rect):
        self.favorite_callback()
        return True
    return super()._handle_mouse_release(mouse_pos)


class TreeOptionDialog(MultiOptionDialog):
  """Folder-based model picker. The selected value is always a bundle ref, never a row index."""

  def __init__(self, title, folders, current_ref="", fav_param="", get_folders_fn=None, on_exit=None):
    super().__init__(title, [], "", callback=on_exit)
    self.folders = folders
    self.selection_ref = current_ref
    self.fav_param = fav_param
    self.params = Params()
    raw_favorites = self.params.get(fav_param) if fav_param else None
    self.favorites = set(raw_favorites.split(";")) if raw_favorites else set()
    self.get_folders_fn = get_folders_fn
    self.expanded = {folder.folder for folder in folders if not folder.folder}
    self.query = ""
    self._search_rect = None
    self._search_button = Button(lambda: tr("Search"), self._open_search, button_style=ButtonStyle.NORMAL)
    self._visible_items = []
    self._build_visible_items()

  def _display(self, node):
    return node.data.get("display_name", node.ref) or tr("Default model")

  def _find_current(self):
    for folder in self.folders:
      for node in folder.nodes:
        if node.ref == self.selection_ref:
          return node
    return None

  def _select_node(self, node):
    self.selection_ref = node.ref
    self.selection = self._display(node)

  def _toggle_favorite(self, node):
    if node.ref in self.favorites:
      self.favorites.remove(node.ref)
    else:
      self.favorites.add(node.ref)
    if self.fav_param:
      if self.favorites:
        self.params.put(self.fav_param, ";".join(sorted(self.favorites)))
      else:
        self.params.remove(self.fav_param)
    if self.get_folders_fn:
      self.folders = self.get_folders_fn(self.favorites)
    self._build_visible_items(reset_scroll=False)

  def _toggle_folder(self, folder):
    if folder in self.expanded:
      self.expanded.remove(folder)
    else:
      self.expanded.add(folder)
    self._build_visible_items(reset_scroll=False)

  def _build_visible_items(self, reset_scroll=True):
    self._visible_items = []
    current = self._find_current()
    self.current = self._display(current) if current else ""
    self.selection = self.current

    for folder in self.folders:
      folder_matches = bool(self.query and _matches(self.query, [folder.folder]))
      nodes = [node for node in folder.nodes if not self.query or folder_matches or
               _matches(self.query, [self._display(node), node.data.get("short_name", "")])]
      if self.query and not nodes:
        continue
      expanded = not folder.folder or folder.folder in self.expanded or bool(self.query)
      if folder.folder:
        prefix = "−" if expanded else "+"
        row = TreeItemWidget(f"{prefix} {folder.folder}", "", True, 0,
                             click_callback=lambda name=folder.folder: self._toggle_folder(name))
        self._visible_items.append(row)
      if expanded:
        for node in nodes:
          favorite_cb = (lambda selected=node: self._toggle_favorite(selected)) if node.ref else None
          row = TreeItemWidget(self._display(node), node.ref, False, 1 if folder.folder else 0,
                               click_callback=lambda selected=node: self._select_node(selected),
                               favorite_callback=favorite_cb, is_favorite=node.ref in self.favorites)
          row.selected = node.ref == self.selection_ref
          self._visible_items.append(row)

    self.options = [item.text for item in self._visible_items]
    self.option_buttons = self._visible_items
    self.scroller = Scroller(self._visible_items, spacing=12)
    if reset_scroll:
      self.scroller.scroll_panel.set_offset(0)

  def _open_search(self):
    keyboard = Keyboard(max_text_size=96, callback=lambda result: self._search_result(result, keyboard.text))
    keyboard.set_title(tr("Search Models"), tr("Search model names and folders"))
    keyboard.set_text(self.query)
    gui_app.push_widget(keyboard)

  def _search_result(self, result, text):
    if result == DialogResult.CONFIRM:
      self.query = text.strip()
      self._build_visible_items()

  def _render(self, rect):
    dialog = rl.Rectangle(rect.x + 50, rect.y + 50, rect.width - 100, rect.height - 100)
    rl.draw_rectangle_rounded(dialog, 0.02, 20, rl.Color(0, 0, 0, 255))

    title_rect = rl.Rectangle(dialog.x + 50, dialog.y + 35, dialog.width * 0.48, 100)
    gui_label(title_rect, self.title, 70, font_weight=FontWeight.BOLD)

    search_rect = rl.Rectangle(dialog.x + dialog.width - 50 - dialog.width * 0.42, dialog.y + 30,
                               dialog.width * 0.42, 110)
    self._search_rect = search_rect
    self._search_button.set_text(f"{tr('Search')}: {self.query}" if self.query else tr("Search"))
    self._search_button.render(search_rect)

    options_top = search_rect.y + search_rect.height + 25
    options_rect = rl.Rectangle(dialog.x + 50, options_top, dialog.width - 100,
                                dialog.height - (options_top - dialog.y) - 205)
    for item in self._visible_items:
      item.set_rect(rl.Rectangle(0, 0, options_rect.width, 125))
    self.scroller.render(options_rect)

    button_y = dialog.y + dialog.height - 165
    button_width = (dialog.width - 150) / 2
    self.cancel_button.render(rl.Rectangle(dialog.x + 50, button_y, button_width, 150))
    self.select_button.set_enabled(bool(self.selection_ref != self._current_ref()))
    self.select_button.render(rl.Rectangle(dialog.x + 100 + button_width, button_y, button_width, 150))

  def _current_ref(self):
    return getattr(self, "_initial_ref", self.selection_ref)

  def _set_result(self, result):
    gui_app.pop_widget()
    if self._callback:
      self._callback(result)

  def show_event(self):
    super().show_event()
    self.scroller.show_event()
