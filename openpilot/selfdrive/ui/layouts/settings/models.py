from openpilot.cereal import custom
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.models.fetcher import get_cached_bundles
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS, get_selected_bundle
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.list_view import button_item, text_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller


class ModelsLayout(Widget):
  """Model selector for the existing openpilot settings UI.

  The manager owns downloads and atomically promotes a bundle only after its
  artifacts have been downloaded and verified. This page only writes the
  selected ref, so it cannot accidentally activate a partial download.
  """

  def __init__(self):
    super().__init__()
    self.params = Params()
    self._dialog = None
    self._dialog_source = None
    self._dialog_bundles = []
    self._small_item = button_item(lambda: tr("Small Model"), lambda: tr("SELECT"),
                                   lambda: self._slot_description("qcom"),
                                   callback=lambda: self._open_selector("qcom"))
    self._big_item = button_item(lambda: tr("Big Model"), lambda: tr("SELECT"),
                                 lambda: self._slot_description("chestnut"),
                                 callback=lambda: self._open_selector("chestnut"))
    self._refresh_item = button_item(lambda: tr("Refresh Model Lists"),
                                     lambda: tr("REFRESH"), callback=self._refresh)
    self._cancel_item = button_item(lambda: tr("Cancel Model Download"),
                                    lambda: tr("CANCEL"), callback=self._cancel_download)
    self._status_item = text_item(lambda: tr("Download Status"), self._download_status)
    self._scroller = Scroller([self._small_item, self._big_item, self._status_item,
                               self._cancel_item, self._refresh_item], line_separator=True, spacing=0)

  def _slot_description(self, source):
    bundle = get_selected_bundle(self.params, source)
    if bundle is None:
      return tr("Default model")
    return bundle.displayName or bundle.internalName

  def _download_status(self):
    state = ui_state.sm["modelManagerSP"]
    selected = state.selectedBundle if state and state.selectedBundle.ref else None
    if selected is None:
      return tr("No model download in progress")
    status = selected.status
    statuses = custom.ModelManagerSP.DownloadStatus
    if status == statuses.downloading:
      progresses = [m.artifact.downloadProgress for m in selected.models if m.artifact.fileName]
      if progresses:
        percent = sum(p.progress for p in progresses) / len(progresses)
        return f"{selected.displayName}: {percent:.0f}%"
      return tr("Downloading")
    if status == statuses.verifying:
      return f"{selected.displayName}: {tr('Verifying')}"
    if status == statuses.failed:
      return f"{selected.displayName}: {tr('Download failed')}"
    if status == statuses.downloaded or status == statuses.cached:
      return f"{selected.displayName}: {tr('Ready')}"
    return tr("Idle")

  def _bundles(self, source):
    # The active source is published live; the other hardware slot is read
    # from the manager's independently cached manifest.
    active_source = "chestnut" if ui_state.chestnut_present and (ui_state.chestnut_active or
                    ui_state.chestnut_loading or ui_state.is_offroad()) else "qcom"
    if source == active_source:
      return list(ui_state.sm["modelManagerSP"].availableBundles)
    return get_cached_bundles(self.params, source)

  def _open_selector(self, source):
    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Model selection is available while offroad.")))
      return
    bundles = self._bundles(source)
    self._dialog_source = source
    self._dialog_bundles = bundles
    options = [tr("Default")] + [f"{b.displayName} ({b.internalName})" for b in bundles]
    current = get_selected_bundle(self.params, source)
    selected = 0
    if current:
      selected = next((i + 1 for i, b in enumerate(bundles) if b.ref == current.ref), 0)
    def on_selection(result):
      if result == DialogResult.CONFIRM and self._dialog is not None:
        index = self._dialog.selection
        if index == 0:
          self.params.remove(ACTIVE_BUNDLE_KEYS[source])
        elif 0 < index <= len(self._dialog_bundles):
          self.params.put("ModelManager_DownloadRef", self._dialog_bundles[index - 1].ref)
      self._dialog = None
      self._dialog_source = None
      self._dialog_bundles = []

    self._dialog = MultiOptionDialog(tr("Select a Model"), options, selected, callback=on_selection)
    gui_app.push_widget(self._dialog)

  def _refresh(self):
    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Refresh model lists while offroad.")))
      return
    self.params.put("ModelManager_LastSyncTime", 0)
    self.params.put("ModelManager_LastSyncTime_Chestnut", 0)

  def _cancel_download(self):
    self.params.remove("ModelManager_DownloadRef")

  def show_event(self):
    super().show_event()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)

  def _update_state(self):
    self._small_item.action_item.set_value(self._slot_description("qcom"))
    self._big_item.action_item.set_value(self._slot_description("chestnut"))
    self._cancel_item.set_visible(self.params.get("ModelManager_DownloadRef") is not None)
    self._refresh_item.set_enabled(ui_state.is_offroad())
    self._small_item.set_enabled(ui_state.is_offroad())
    self._big_item.set_enabled(ui_state.is_offroad())
