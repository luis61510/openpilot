import os
import time

from openpilot.cereal import custom
from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.models.fetcher import get_cached_bundles
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS, get_active_source, get_selected_bundle
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.list_view import button_item, text_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.tree_option_dialog import TreeFolder, TreeNode, TreeOptionDialog


class ModelsLayout(Widget):
  """Small/Chestnut model manager using stable bundle refs for all selections."""

  ARTIFACT_ROWS = 6

  def __init__(self):
    super().__init__()
    self.params = Params()
    self._dialog = None
    self._dialog_source = None
    self._refresh_started: float | None = None
    self._last_cache_refresh = 0.0

    self._small_item = button_item(lambda: tr("Small Model"), lambda: tr("SELECT"),
                                   lambda: self._slot_description("qcom"),
                                   callback=lambda: self._open_selector("qcom"))
    self._big_item = button_item(lambda: tr("Big Model"), lambda: tr("SELECT"),
                                 lambda: self._slot_description("chestnut"),
                                 callback=lambda: self._open_selector("chestnut"))
    self._active_item = text_item(lambda: tr("Current Active Model"), self._active_model_name)
    self._download_item = text_item(lambda: tr("Download Status"), self._download_status)
    self._artifact_items = [
      text_item(lambda i=i: f"{tr('Model Component')} {i + 1}", lambda i=i: self._artifact_status(i))
      for i in range(self.ARTIFACT_ROWS)
    ]
    self._cancel_item = button_item(lambda: tr("Cancel Model Download"), lambda: tr("CANCEL"),
                                    callback=self._cancel_download)
    self._refresh_item = button_item(lambda: tr("Refresh Model Lists"),
                                     lambda: tr("FETCHING...") if self._refreshing() else tr("REFRESH"),
                                     callback=self._refresh)
    self._cache_item = text_item(lambda: tr("Model Cache"), self._cache_size_text)
    self._clear_cache_item = button_item(lambda: tr("Clear Model Cache"), lambda: tr("CLEAR"),
                                         tr("The active small and big model files are preserved."),
                                         callback=self._clear_cache)
    self._scroller = Scroller([
      self._small_item, self._big_item, self._active_item, self._download_item,
      *self._artifact_items, self._cancel_item, self._refresh_item,
      self._cache_item, self._clear_cache_item,
    ], line_separator=True, spacing=0)

  def _slot_description(self, source: str) -> str:
    bundle = get_selected_bundle(self.params, source)
    if bundle is not None:
      return bundle.displayName or bundle.internalName
    return tr("Default small model") if source == "qcom" else tr("Default big model")

  def _active_source(self) -> str:
    return get_active_source(chestnut=ui_state.chestnut_present,
                             chestnut_active=ui_state.chestnut_active,
                             chestnut_loading=ui_state.chestnut_loading,
                             offroad=ui_state.is_offroad())

  def _active_model_name(self) -> str:
    source = self._active_source()
    return self._slot_description(source)

  def _cache_size_mb(self) -> float:
    total = 0
    model_root = Paths.model_root()
    try:
      with os.scandir(model_root) as entries:
        for entry in entries:
          if entry.is_file(follow_symlinks=False):
            try:
              total += entry.stat(follow_symlinks=False).st_size
            except OSError:
              pass
    except OSError:
      pass
    return total / (1024 * 1024)

  def _cache_size_text(self) -> str:
    return f"{self._cache_size_mb():.1f} MB"

  def _manager_state(self):
    return ui_state.sm["modelManagerSP"]

  def _selected_bundle(self):
    state = self._manager_state()
    return state.selectedBundle if state and state.selectedBundle.ref else None

  def _download_status(self) -> str:
    bundle = self._selected_bundle()
    if bundle is None:
      return tr("No model download in progress")
    status = getattr(bundle.status, "raw", bundle.status)
    statuses = custom.ModelManagerSP.DownloadStatus
    if status == statuses.downloading:
      return f"{bundle.displayName}: {tr('Downloading')}"
    if status == statuses.verifying:
      return f"{bundle.displayName}: {tr('Verifying')}"
    if status == statuses.failed:
      return f"{bundle.displayName}: {tr('Download failed')}"
    if status in (statuses.downloaded, statuses.cached):
      return f"{bundle.displayName}: {tr('Ready')}"
    return f"{bundle.displayName}: {tr('Queued')}"

  def _artifact_status(self, index: int) -> str:
    bundle = self._selected_bundle()
    artifacts = [model.artifact for model in bundle.models if model.artifact.fileName] if bundle else []
    if index >= len(artifacts):
      return ""
    artifact = artifacts[index]
    progress = artifact.downloadProgress
    status = getattr(progress.status, "raw", progress.status)
    statuses = custom.ModelManagerSP.DownloadStatus
    if status == statuses.downloading:
      state = tr("Downloading")
    elif status == statuses.verifying:
      state = tr("Verifying")
    elif status == statuses.downloaded:
      state = tr("Downloaded")
    elif status == statuses.cached:
      state = tr("Cached")
    elif status == statuses.failed:
      state = tr("Failed")
    else:
      state = tr("Waiting")
    return f"{artifact.fileName} — {state} {progress.progress:.0f}%"

  def _bundles(self, source: str):
    if source == self._active_source():
      state = self._manager_state()
      return list(state.availableBundles) if state else []
    return get_cached_bundles(self.params, source)

  def _source_folders(self, favorites: set[str], source: str):
    bundles = self._bundles(source)
    folders: dict[str, list] = {}
    for bundle in bundles:
      folder = next((override.value for override in bundle.overrides if override.key == "folder"), "")
      folders.setdefault(folder, []).append(bundle)

    result = []
    favorite_nodes = [TreeNode(bundle.ref, {"display_name": bundle.displayName,
                                             "short_name": bundle.internalName})
                      for bundle in bundles if bundle.ref in favorites]
    if favorite_nodes:
      result.append(TreeFolder("Favorites", favorite_nodes))
    result.append(TreeFolder("", [TreeNode("", {"display_name": tr("Default model")})]))

    ordered = sorted(folders.items(), key=lambda item: max((b.index for b in item[1]), default=-1), reverse=True)
    for folder, folder_bundles in ordered:
      if folder == "":
        folder_name = tr("Other Models")
      else:
        folder_name = folder
      folder_bundles.sort(key=lambda bundle: bundle.index, reverse=True)
      nodes = [TreeNode(bundle.ref, {"display_name": bundle.displayName,
                                     "short_name": bundle.internalName})
               for bundle in folder_bundles]
      result.append(TreeFolder(folder_name, nodes))
    return result

  def _open_selector(self, source: str):
    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Model selection is available while offroad.")))
      return
    self._dialog_source = source
    favorites_raw = self.params.get("ModelManager_Favs")
    favorites = set(favorites_raw.split(";")) if favorites_raw else set()
    folders = self._source_folders(favorites, source)
    current = get_selected_bundle(self.params, source)
    current_ref = current.ref if current else ""
    self._dialog = TreeOptionDialog(
      tr("Select a Model"), folders, current_ref, "ModelManager_Favs",
      get_folders_fn=lambda updated_favorites: self._source_folders(updated_favorites, source),
      on_exit=self._on_model_selected,
    )
    gui_app.push_widget(self._dialog)

  def _on_model_selected(self, result: DialogResult):
    dialog = self._dialog
    source = self._dialog_source
    self._dialog = None
    self._dialog_source = None
    if result != DialogResult.CONFIRM or dialog is None or source is None:
      return

    selected_ref = dialog.selection_ref
    if not selected_ref:
      self.params.remove(ACTIVE_BUNDLE_KEYS[source])
      return

    bundle = next((candidate for candidate in self._bundles(source) if candidate.ref == selected_ref), None)
    if bundle is not None:
      # The manager resolves by ref and promotes only after every artifact verifies.
      self.params.put("ModelManager_DownloadRef", bundle.ref)

  def _cancel_download(self):
    self.params.remove("ModelManager_DownloadRef")

  def _refresh(self):
    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Refresh model lists while offroad.")))
      return
    self.params.put("ModelManager_LastSyncTime", 0)
    self.params.put("ModelManager_LastSyncTime_Chestnut", 0)
    self._refresh_started = time.monotonic()

  def _refreshing(self) -> bool:
    if self._refresh_started is None:
      return False
    if time.monotonic() - self._refresh_started > 20:
      self._refresh_started = None
      return False
    return not (self.params.get("ModelManager_LastSyncTime") and
                self.params.get("ModelManager_LastSyncTime_Chestnut"))

  def _clear_cache(self):
    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Cache can only be cleared while offroad.")))
      return

    def confirm(result):
      if result == DialogResult.CONFIRM:
        self.params.put_bool("ModelManager_ClearCache", True)
        self._last_cache_refresh = 0.0

    gui_app.push_widget(ConfirmDialog(
      tr("Delete downloaded model cache files except the active small and big models?"),
      tr("Clear Cache"), callback=confirm,
    ))

  def _update_state(self):
    offroad = ui_state.is_offroad()
    self._small_item.action_item.set_value(self._slot_description("qcom"))
    self._big_item.action_item.set_value(self._slot_description("chestnut"))
    self._active_item.action_item.set_text(self._active_model_name())
    bundle = self._selected_bundle()
    artifacts = [model.artifact for model in bundle.models if model.artifact.fileName] if bundle else []
    for i, item in enumerate(self._artifact_items):
      item.set_visible(i < len(artifacts))

    download_ref = self.params.get("ModelManager_DownloadRef")
    self._cancel_item.set_visible(download_ref is not None)
    self._small_item.set_enabled(offroad)
    self._big_item.set_enabled(offroad)
    self._refresh_item.set_enabled(offroad and not self._refreshing())
    self._clear_cache_item.set_enabled(offroad and not self.params.get_bool("ModelManager_ClearCache"))

    if time.monotonic() - self._last_cache_refresh > 1.0:
      self._last_cache_refresh = time.monotonic()
      self._cache_item.action_item.set_text(self._cache_size_text())

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
