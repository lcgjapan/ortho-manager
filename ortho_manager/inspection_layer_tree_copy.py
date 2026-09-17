from .i18n import tr_text
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtGui import QKeySequence, QShortcut
from qgis.PyQt.QtWidgets import QAction, QApplication, QInputDialog, QMessageBox
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    Qgis,
)

from .inspection_constants import (
    FREE_GROUP_PATH_SEPARATOR,
    GEOM_TYPE_LABELS,
    INSPECTION_GROUP,
    INSPECTION_PROP_PREFIX,
    INSPECTION_TYPE_FREE,
    TRASH_GROUP_NAME,
)

try:
    from osgeo import ogr
    ogr.UseExceptions()
    OGR_OK = True
except Exception:
    OGR_OK = False


class InspectionLayerTreeCopyManager:
    def __init__(self, iface, inspection_tab):
        self.iface = iface
        self.inspection_tab = inspection_tab
        self.view = None
        self.connected = False

    def install(self):
        try:
            self.view = self.iface.layerTreeView()
        except Exception:
            self.view = None
        if self.view is None:
            return
        self._restore_replaced_menu_provider()
        try:
            self.view.contextMenuAboutToShow.connect(self.add_copy_actions_to_menu)
            self.connected = True
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"INSPECTION_COPY_MENU_SIGNAL_CONNECT_FAILED error={exc}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def cleanup(self):
        if self.view is None:
            return
        if self.connected:
            try:
                self.view.contextMenuAboutToShow.disconnect(self.add_copy_actions_to_menu)
            except Exception:
                pass
        self.connected = False
        self.view = None

    def _restore_replaced_menu_provider(self):
        try:
            provider = self.view.menuProvider()
            if provider is not None and provider.__class__.__name__ == "InspectionLayerTreeCopyMenuProvider":
                original_provider = getattr(provider, "original_provider", None)
                self.view.setMenuProvider(original_provider)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"INSPECTION_COPY_MENU_PROVIDER_RESTORE_FAILED error={exc}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def add_copy_actions_to_menu(self, menu):
        if menu is None:
            return
        node = self._current_node()
        layer = self._node_layer(node)
        added = False
        if self._can_copy_layer(layer):
            self._add_separator_if_needed(menu)
            action = QAction(tr_text("検査レイヤをコピー（独立データ）"), menu)
            action.triggered.connect(lambda _=False, l=layer, n=node: self.inspection_tab.copy_inspection_layer_from_tree(l, n))
            menu.addAction(action)
            added = True
            if self._can_select_all_layer(layer, node):
                action = QAction(tr_text("このレイヤの地物を全選択"), menu)
                action.triggered.connect(lambda _=False, l=layer, n=node: self.inspection_tab.select_all_features_from_tree_layer(l, n))
                menu.addAction(action)
        elif self._can_copy_group(node):
            self._add_separator_if_needed(menu)
            action = QAction(tr_text("検査グループをコピー（独立データ）"), menu)
            action.triggered.connect(lambda _=False, g=node: self.inspection_tab.copy_inspection_group_from_tree(g))
            menu.addAction(action)
            added = True
            if self._can_select_all_group(node):
                action = QAction(tr_text("このグループ内の地物を全選択"), menu)
                action.triggered.connect(lambda _=False, g=node: self.inspection_tab.select_all_features_from_tree_group(g))
                menu.addAction(action)
        elif self._can_select_all_layer(layer, node):
            self._add_separator_if_needed(menu)
            action = QAction(tr_text("このレイヤの地物を全選択"), menu)
            action.triggered.connect(lambda _=False, l=layer, n=node: self.inspection_tab.select_all_features_from_tree_layer(l, n))
            menu.addAction(action)
            added = True
        elif self._can_select_all_group(node):
            self._add_separator_if_needed(menu)
            action = QAction(tr_text("このグループ内の地物を全選択"), menu)
            action.triggered.connect(lambda _=False, g=node: self.inspection_tab.select_all_features_from_tree_group(g))
            menu.addAction(action)
            added = True
        if added:
            return

    def _add_separator_if_needed(self, menu):
        actions = menu.actions()
        if actions and not actions[-1].isSeparator():
            menu.addSeparator()

    def _current_node(self):
        try:
            nodes = self.view.selectedNodes(True)
            if len(nodes) == 1:
                return nodes[0]
        except Exception:
            pass
        try:
            return self.view.currentNode()
        except Exception:
            return None

    def _node_layer(self, node):
        if isinstance(node, QgsLayerTreeLayer):
            try:
                return node.layer()
            except Exception:
                return None
        return None

    def _can_copy_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        try:
            return bool(layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")) and not self.inspection_tab.is_trash_layer(layer)
        except Exception:
            return False

    def _can_copy_group(self, node):
        if not isinstance(node, QgsLayerTreeGroup):
            return False
        try:
            if node.name() in (INSPECTION_GROUP, TRASH_GROUP_NAME):
                return False
            if not self.inspection_tab.is_node_under_inspection_root(node):
                return False
            return self.inspection_tab.group_contains_copyable_inspection_layer(node)
        except Exception:
            return False

    def _can_select_all_layer(self, layer, node):
        if not self._can_copy_layer(layer):
            return False
        try:
            return not self.inspection_tab.is_layer_or_node_selection_locked_for_tree_selection(layer, node)
        except Exception:
            return False

    def _can_select_all_group(self, node):
        if not isinstance(node, QgsLayerTreeGroup):
            return False
        try:
            if node.name() == TRASH_GROUP_NAME:
                return False
            if not self.inspection_tab.is_node_under_inspection_root(node):
                return False
            if self.inspection_tab.is_group_selection_locked_for_tree_selection(node):
                return False
            return self.inspection_tab.group_contains_selectable_inspection_layer(node)
        except Exception:
            return False


class InspectionLayerTreeCopyMixin:
    def install_layer_tree_copy_menu(self):
        if getattr(self, "_layer_tree_copy_manager", None) is not None:
            return
        self._layer_tree_copy_manager = InspectionLayerTreeCopyManager(self.iface, self)
        self._layer_tree_copy_manager.install()
        self.install_feature_clipboard_shortcuts()
        self.log_feature_clipboard("INSTALL_LAYER_TREE_COPY_MENU version=4.37")

    def cleanup_layer_tree_copy_menu(self):
        self.cleanup_feature_clipboard_shortcuts()
        manager = getattr(self, "_layer_tree_copy_manager", None)
        if manager is None:
            return
        manager.cleanup()
        self._layer_tree_copy_manager = None

    def install_feature_clipboard_shortcuts(self):
        self.cleanup_feature_clipboard_shortcuts()
        self.inspection_feature_clipboard_shortcuts = []
        try:
            parent = self.iface.mapCanvas() or self
        except Exception:
            parent = self
        for sequence, action in (("Ctrl+C", "copy"), ("Ctrl+V", "paste")):
            try:
                shortcut = QShortcut(QKeySequence(sequence), parent)
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda a=action: self.run_feature_clipboard_shortcut(a))
                shortcut.activatedAmbiguously.connect(lambda a=action: self.run_feature_clipboard_shortcut(a))
                self.inspection_feature_clipboard_shortcuts.append(shortcut)
            except Exception as exc:
                self.log_feature_clipboard(
                    f"SHORTCUT_INSTALL_FAILED sequence={sequence} error={exc}",
                    Qgis.MessageLevel.Warning,
                )
        self.install_feature_clipboard_app_event_filter()
        self.log_feature_clipboard(f"SHORTCUTS_INSTALLED count={len(self.inspection_feature_clipboard_shortcuts)}")

    def cleanup_feature_clipboard_shortcuts(self):
        self.cleanup_feature_clipboard_app_event_filter()
        for shortcut in getattr(self, "inspection_feature_clipboard_shortcuts", []):
            try:
                shortcut.setEnabled(False)
                shortcut.deleteLater()
            except Exception:
                pass
        self.inspection_feature_clipboard_shortcuts = []

    def install_feature_clipboard_app_event_filter(self):
        if getattr(self, "inspection_feature_clipboard_app_filter_installed", False):
            return
        app = QApplication.instance()
        if app is None:
            self.log_feature_clipboard("APP_FILTER_INSTALL_SKIPPED_NO_APP", Qgis.MessageLevel.Warning)
            return
        try:
            app.installEventFilter(self)
            self.inspection_feature_clipboard_app_filter_installed = True
            self.log_feature_clipboard("APP_FILTER_INSTALLED")
        except Exception as exc:
            self.log_feature_clipboard(f"APP_FILTER_INSTALL_FAILED error={exc}", Qgis.MessageLevel.Warning)

    def cleanup_feature_clipboard_app_event_filter(self):
        if not getattr(self, "inspection_feature_clipboard_app_filter_installed", False):
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        self.inspection_feature_clipboard_app_filter_installed = False

    def run_feature_clipboard_shortcut(self, action):
        self.log_feature_clipboard(f"QSHORTCUT_TRIGGER action={action} {self.feature_clipboard_context_text()}")
        if not getattr(self, "inspection_enabled", False):
            self.log_feature_clipboard(f"QSHORTCUT_BLOCKED_INSPECTION_OFF action={action}")
            return False
        if not self.shortcut_focus_allows_run():
            self.log_feature_clipboard(f"QSHORTCUT_BLOCKED_FOCUS action={action} {self.feature_clipboard_context_text()}")
            return False
        if action == "copy":
            return self.copy_selected_inspection_features_to_internal_clipboard()
        if action == "paste":
            return self.paste_internal_inspection_feature_clipboard()
        return False

    def handle_feature_clipboard_event_filter_key(self, event, source="EVENT_FILTER"):
        try:
            event_type = event.type()
            if event_type not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
                return False
            key = event.key()
            modifiers = event.modifiers()
        except Exception:
            return False
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            return False
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        if key not in (Qt.Key.Key_C, Qt.Key.Key_V):
            return False
        action = "copy" if key == Qt.Key.Key_C else "paste"
        if not getattr(self, "inspection_enabled", False):
            self.log_feature_clipboard(f"{source}_BLOCKED_INSPECTION_OFF action={action}")
            return False
        if not self.shortcut_focus_allows_run():
            return False
        try:
            event_type_name = event_type.name
        except Exception:
            event_type_name = str(event_type)
        self.log_feature_clipboard(
            f"{source}_KEY_RECEIVED type={event_type_name} action={action} {self.feature_clipboard_context_text()}"
        )
        if event_type == QEvent.Type.ShortcutOverride:
            try:
                event.accept()
            except Exception:
                pass
            self.log_feature_clipboard(f"{source}_SHORTCUT_OVERRIDE_ACCEPTED action={action}")
            return True
        if action == "copy":
            self.copy_selected_inspection_features_to_internal_clipboard()
        else:
            self.paste_internal_inspection_feature_clipboard()
        try:
            event.accept()
        except Exception:
            pass
        return True

    def log_feature_clipboard(self, message, level=Qgis.MessageLevel.Info):
        text = str(message)
        if level == Qgis.MessageLevel.Info:
            quiet_prefixes = (
                "APP_FILTER_INSTALLED",
                "SHORTCUTS_INSTALLED",
                "INSTALL_LAYER_TREE_COPY_MENU",
            )
            if text.startswith(quiet_prefixes) or "BLOCKED_INSPECTION_OFF" in text:
                return
        QgsMessageLog.logMessage(
            "INSPECTION_FEATURE_CLIPBOARD " + text,
            "OrthoManager",
            level,
        )

    def feature_clipboard_context_text(self):
        focus_name = "None"
        try:
            focus = QApplication.focusWidget()
            focus_name = focus.__class__.__name__ if focus is not None else "None"
        except Exception:
            pass
        active_name = "None"
        try:
            active = self.iface.activeLayer()
            active_name = self.display_layer_name(active) if active is not None else "None"
        except Exception:
            pass
        return (
            f"enabled={getattr(self, 'inspection_enabled', None)} "
            f"mode={getattr(self, 'operation_mode', '')} "
            f"focus={focus_name} active={active_name} "
            f"targets={self.feature_clipboard_targets_summary()}"
        )

    def feature_clipboard_targets_summary(self, targets=None):
        if targets is None:
            try:
                targets = self.selected_vector_targets()
            except Exception as exc:
                return f"error:{exc}"
        parts = []
        total = 0
        for layer, ids in targets:
            count = len(ids or [])
            total += count
            try:
                name = self.display_layer_name(layer)
            except Exception:
                name = getattr(layer, "name", lambda: "unknown")()
            parts.append(f"{name}:{count}")
        return f"layers={len(parts)} total={total} detail=[{'; '.join(parts[:8])}]"

    def handle_qgis_feature_clipboard_key(self, event):
        try:
            modifiers = event.modifiers()
            key = event.key()
        except Exception:
            return False
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            return False
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        if key not in (Qt.Key.Key_C, Qt.Key.Key_V):
            return False
        action = "copy" if key == Qt.Key.Key_C else "paste"
        self.log_feature_clipboard(f"MAPTOOL_KEY_RECEIVED action={action} {self.feature_clipboard_context_text()}")
        if not getattr(self, "inspection_enabled", False):
            self.log_feature_clipboard(f"MAPTOOL_KEY_BLOCKED_INSPECTION_OFF action={action}")
            return False
        if not self.shortcut_focus_allows_run():
            self.log_feature_clipboard(f"MAPTOOL_KEY_BLOCKED_FOCUS action={action} {self.feature_clipboard_context_text()}")
            return False
        if key == Qt.Key.Key_C:
            self.copy_selected_inspection_features_to_internal_clipboard()
        else:
            self.paste_internal_inspection_feature_clipboard()
        return True

    def inspection_editing_layers(self, layers=None):
        if layers is None:
            try:
                layers = self.selectable_inspection_layers()
            except Exception:
                layers = []
        editing = []
        for layer in layers:
            try:
                if isinstance(layer, QgsVectorLayer) and layer.isEditable():
                    editing.append(layer)
            except Exception:
                pass
        return editing

    def block_feature_clipboard_if_editing(self, title):
        editing = self.inspection_editing_layers()
        if not editing:
            self.log_feature_clipboard(f"EDITING_CHECK_OK title={title}")
            return False
        names = "\n".join(self.display_layer_name(layer) for layer in editing[:8])
        if len(editing) > 8:
            names += f"\n...ほか {len(editing) - 8} レイヤ"
        self.log_feature_clipboard(
            f"EDITING_CHECK_BLOCKED title={title} layers={len(editing)} names={names.replace(chr(10), '|')}",
            Qgis.MessageLevel.Warning,
        )
        QMessageBox.information(self, title, tr_text("編集中の検査レイヤがあります。\n編集を完了してからコピー/貼り付けしてください。\n\n" + names))
        self.set_status(tr_text("編集中の検査レイヤがあるため、コピー/貼り付けできません"))
        return True

    def copy_selected_inspection_features_to_internal_clipboard(self):
        self.log_feature_clipboard(f"COPY_START {self.feature_clipboard_context_text()}")
        if self.block_feature_clipboard_if_editing("ベクタコピー"):
            return False
        targets = [(layer, ids) for layer, ids in self.selected_vector_targets() if layer and ids]
        self.log_feature_clipboard(f"COPY_TARGETS {self.feature_clipboard_targets_summary(targets)}")
        if not targets:
            self.log_feature_clipboard("COPY_ABORT_NO_TARGETS", Qgis.MessageLevel.Warning)
            self.set_status(tr_text("コピーする選択地物がありません"))
            return False
        clipboard = []
        total = 0
        for layer, ids in targets:
            features = []
            field_names = [field.name() for field in layer.fields()]
            request = QgsFeatureRequest().setFilterFids(list(ids))
            self.log_feature_clipboard(
                f"COPY_LAYER_START layer={self.display_layer_name(layer)} ids={len(ids)} fields={len(field_names)}"
            )
            for feature in layer.getFeatures(request):
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    self.log_feature_clipboard(
                        f"COPY_SKIP_EMPTY_GEOMETRY layer={self.display_layer_name(layer)} fid={feature.id()}",
                        Qgis.MessageLevel.Warning,
                    )
                    continue
                attrs = {}
                for name in field_names:
                    attrs[name] = self.feature_attribute_by_name(feature, name)
                features.append({
                    "geometry": QgsGeometry(geom),
                    "attributes": attrs,
                })
            if not features:
                self.log_feature_clipboard(
                    f"COPY_LAYER_NO_FEATURES layer={self.display_layer_name(layer)}",
                    Qgis.MessageLevel.Warning,
                )
                continue
            clipboard.append({
                "layer_id": layer.id(),
                "source_name": str(layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") or ""),
                "layer_name": layer.name(),
                "geometry_type": int(layer.geometryType()),
                "features": features,
            })
            total += len(features)
            self.log_feature_clipboard(f"COPY_LAYER_DONE layer={self.display_layer_name(layer)} copied={len(features)}")
        if not clipboard:
            self.log_feature_clipboard("COPY_ABORT_EMPTY_CLIPBOARD", Qgis.MessageLevel.Warning)
            self.set_status(tr_text("コピーできる選択地物がありません"))
            return False
        self.inspection_feature_clipboard = clipboard
        self.log_feature_clipboard(f"COPY_DONE total={total} layers={len(clipboard)}")
        self.set_status(tr_text(f"✅ 選択地物をコピーしました: {total} 件 / {len(clipboard)} レイヤ"))
        return True

    def feature_attribute_by_name(self, feature, name):
        try:
            return feature.attribute(name)
        except Exception:
            pass
        try:
            return feature[name]
        except Exception:
            return None

    def paste_internal_inspection_feature_clipboard(self):
        self.log_feature_clipboard(f"PASTE_START {self.feature_clipboard_context_text()}")
        if self.block_feature_clipboard_if_editing("ベクタ貼り付け"):
            return False
        clipboard = getattr(self, "inspection_feature_clipboard", None) or []
        self.log_feature_clipboard(f"PASTE_CLIPBOARD entries={len(clipboard)}")
        if not clipboard:
            self.log_feature_clipboard("PASTE_ABORT_EMPTY_CLIPBOARD", Qgis.MessageLevel.Warning)
            self.set_status(tr_text("貼り付けるコピー地物がありません"))
            return False
        target_layers = []
        for entry in clipboard:
            layer = self.clipboard_target_layer(entry)
            if layer is not None:
                target_layers.append(layer)
            self.log_feature_clipboard(
                f"PASTE_TARGET_RESOLVE layer_id={entry.get('layer_id', '')} "
                f"source={entry.get('source_name', '')} "
                f"target={self.display_layer_name(layer) if layer is not None else 'None'}"
            )
        if not target_layers:
            self.log_feature_clipboard("PASTE_ABORT_NO_TARGET_LAYERS", Qgis.MessageLevel.Warning)
            self.set_status(tr_text("貼り付け先の検査レイヤが見つかりません"))
            return False
        if self.block_locked_layers(target_layers, "貼り付けできません", "地物を貼り付け"):
            self.log_feature_clipboard("PASTE_ABORT_LOCKED_LAYER", Qgis.MessageLevel.Warning)
            return False
        added_by_layer = []
        total_added = 0
        failed = []
        for entry in clipboard:
            layer = self.clipboard_target_layer(entry)
            if layer is None:
                self.log_feature_clipboard(
                    f"PASTE_SKIP_NO_LAYER source={entry.get('source_name', '')} name={entry.get('layer_name', '')}",
                    Qgis.MessageLevel.Warning,
                )
                failed.append(str(entry.get("layer_name", "不明レイヤ")))
                continue
            if int(layer.geometryType()) != int(entry.get("geometry_type", -1)):
                self.log_feature_clipboard(
                    f"PASTE_SKIP_GEOMETRY_TYPE layer={self.display_layer_name(layer)} "
                    f"target_type={int(layer.geometryType())} source_type={entry.get('geometry_type', -1)}",
                    Qgis.MessageLevel.Warning,
                )
                failed.append(self.display_layer_name(layer))
                continue
            new_features = []
            fields = layer.fields()
            for item in entry.get("features", []):
                feature = QgsFeature(fields)
                geom = item.get("geometry")
                if geom is None or geom.isEmpty():
                    continue
                feature.setGeometry(QgsGeometry(geom))
                attrs_by_name = item.get("attributes", {})
                for index, field in enumerate(fields):
                    name = field.name()
                    if self.is_feature_clipboard_primary_key_field(name):
                        continue
                    if name in attrs_by_name:
                        feature.setAttribute(index, attrs_by_name.get(name))
                new_features.append(feature)
            if not new_features:
                self.log_feature_clipboard(
                    f"PASTE_SKIP_NO_NEW_FEATURES layer={self.display_layer_name(layer)}",
                    Qgis.MessageLevel.Warning,
                )
                continue
            self.log_feature_clipboard(
                f"PASTE_LAYER_ADD_START layer={self.display_layer_name(layer)} features={len(new_features)} "
                f"editable={layer.isEditable()} provider={layer.providerType()}"
            )
            ok, ids, error = self.add_pasted_features_with_edit_commit(layer, new_features)
            self.log_feature_clipboard(
                f"PASTE_LAYER_ADD_RESULT layer={self.display_layer_name(layer)} ok={ok} "
                f"added={len(ids)} provider={layer.providerType()} error={error}"
            )
            if not ok:
                failed.append(self.display_layer_name(layer))
                continue
            added_by_layer.append((layer, ids))
            total_added += len(ids) if ids else len(new_features)
        if added_by_layer:
            self.clear_inspection_selection()
            first_layer = None
            for layer, ids in added_by_layer:
                if first_layer is None:
                    first_layer = layer
                if ids:
                    layer.selectByIds(ids)
            if first_layer is not None:
                self.active_layer_id = first_layer.id()
                try:
                    self.iface.setActiveLayer(first_layer)
                except Exception:
                    pass
            self.refresh_selection_highlight()
            self.flash_pasted_features(added_by_layer)
            self.refresh_counts()
        if failed:
            QgsMessageLog.logMessage(
                "INSPECTION_FEATURE_PASTE_PARTIAL_FAILED layers=" + ",".join(failed[:16]),
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        if total_added:
            self.log_feature_clipboard(f"PASTE_DONE total={total_added} layers={len(added_by_layer)} failed={len(failed)}")
            self.set_status(tr_text(f"✅ 地物を貼り付けました: {total_added} 件 / {len(added_by_layer)} レイヤ（貼り付け地物を選択中）"))
            return True
        self.log_feature_clipboard(f"PASTE_ABORT_NOTHING_ADDED failed={len(failed)}", Qgis.MessageLevel.Warning)
        self.set_status(tr_text("地物を貼り付けできませんでした"))
        return False

    def add_pasted_features_with_edit_commit(self, layer, new_features):
        if layer.isEditable():
            return False, [], "layer_already_editable"
        if not layer.startEditing():
            return False, [], "startEditing_failed"
        command_active = False
        added = []
        try:
            layer.beginEditCommand("地物貼り付け")
            command_active = True
            ok = layer.addFeatures(new_features)
            if not ok:
                if command_active:
                    layer.destroyEditCommand()
                    command_active = False
                errors = "; ".join(layer.commitErrors()) if hasattr(layer, "commitErrors") else ""
                layer.rollBack()
                return False, [], errors or "addFeatures_failed"
            layer.endEditCommand()
            command_active = False
            ids = [feature.id() for feature in new_features if feature.id() is not None and feature.id() >= 0]
            if not layer.commitChanges():
                errors = "; ".join(layer.commitErrors())
                try:
                    layer.rollBack()
                except Exception:
                    pass
                return False, [], errors or "commitChanges_failed"
            self.refresh_vector_layer_after_data_change(layer, reload_data=True)
            if len(ids) < len(new_features):
                ids = self.latest_feature_ids(layer, len(new_features))
            return True, ids, ""
        except Exception as exc:
            try:
                if command_active:
                    layer.destroyEditCommand()
            except Exception:
                pass
            try:
                if layer.isEditable():
                    layer.rollBack()
            except Exception:
                pass
            return False, [], str(exc)

    def is_feature_clipboard_primary_key_field(self, name):
        return str(name or "").lower() in {"fid", "ogc_fid"}

    def latest_feature_ids(self, layer, count):
        if count <= 0:
            return []
        ids = []
        try:
            request = QgsFeatureRequest().setNoAttributes()
            for feature in layer.getFeatures(request):
                ids.append(feature.id())
        except Exception:
            return []
        return sorted(ids)[-count:]

    def clipboard_target_layer(self, entry):
        layer_id = entry.get("layer_id", "")
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if isinstance(layer, QgsVectorLayer):
            return layer
        source_name = str(entry.get("source_name", "") or "")
        if not source_name:
            return None
        for candidate in self.selectable_inspection_layers():
            try:
                if str(candidate.customProperty(INSPECTION_PROP_PREFIX + "source_name", "") or "") == source_name:
                    return candidate
            except Exception:
                pass
        return None

    def is_node_under_inspection_root(self, node):
        current = node
        while current is not None:
            try:
                parent = current.parent()
            except Exception:
                parent = None
            if parent is None:
                return False
            try:
                if current.name() == INSPECTION_GROUP and parent == QgsProject.instance().layerTreeRoot():
                    return True
            except Exception:
                pass
            current = parent
        return False

    def group_contains_copyable_inspection_layer(self, group):
        for layer, _node in self.copyable_layers_in_group(group):
            if layer:
                return True
        return False

    def copyable_layers_in_group(self, group):
        layers = []

        def walk(node):
            try:
                children = list(node.children())
            except Exception:
                children = []
            for child in children:
                if isinstance(child, QgsLayerTreeLayer):
                    layer = child.layer()
                    if self.is_copyable_inspection_layer(layer):
                        layers.append((layer, child))
                elif isinstance(child, QgsLayerTreeGroup):
                    walk(child)

        walk(group)
        return layers

    def is_copyable_inspection_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        if self.is_trash_layer(layer):
            return False
        try:
            if not layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", ""):
                return False
        except Exception:
            return False
        return True

    def group_contains_selectable_inspection_layer(self, group):
        for layer, _node in self.selectable_layers_in_tree_group(group):
            if layer:
                return True
        return False

    def selectable_layers_in_tree_group(self, group):
        layers = []

        def walk(node):
            if self.is_group_selection_locked_for_tree_selection(node):
                return
            try:
                children = list(node.children())
            except Exception:
                children = []
            for child in children:
                if isinstance(child, QgsLayerTreeLayer):
                    layer = child.layer()
                    if self.is_selectable_inspection_layer_for_tree_selection(layer, child):
                        layers.append((layer, child))
                elif isinstance(child, QgsLayerTreeGroup):
                    walk(child)

        if isinstance(group, QgsLayerTreeGroup):
            walk(group)
        return layers

    def is_selectable_inspection_layer_for_tree_selection(self, layer, node=None):
        if not self.is_copyable_inspection_layer(layer):
            return False
        return not self.is_layer_or_node_selection_locked_for_tree_selection(layer, node)

    def is_layer_or_node_selection_locked_for_tree_selection(self, layer, node=None):
        try:
            manager = self.layer_lock_manager
        except Exception:
            manager = None
        if manager is None:
            return False
        try:
            if manager.is_layer_selection_locked(layer):
                return True
        except Exception:
            pass
        try:
            if node is not None and manager.is_node_effectively_selection_locked(node):
                return True
        except Exception:
            pass
        return False

    def is_group_selection_locked_for_tree_selection(self, group):
        try:
            manager = self.layer_lock_manager
        except Exception:
            manager = None
        if manager is None:
            return False
        try:
            return bool(manager.is_node_effectively_selection_locked(group))
        except Exception:
            return False

    def select_all_features_from_tree_layer(self, layer, node=None):
        if not self.is_selectable_inspection_layer_for_tree_selection(layer, node):
            QMessageBox.information(self, tr_text("全選択"), tr_text("選択できる検査レイヤではありません。"))
            return
        self.select_all_features_from_tree_layers([(layer, node)])

    def select_all_features_from_tree_group(self, group):
        if not isinstance(group, QgsLayerTreeGroup) or not self.is_node_under_inspection_root(group):
            QMessageBox.information(self, tr_text("全選択"), tr_text("選択できる検査グループではありません。"))
            return
        if group.name() == TRASH_GROUP_NAME or self.is_group_selection_locked_for_tree_selection(group):
            QMessageBox.information(self, tr_text("全選択"), tr_text("ロック中またはゴミ箱の検査グループは選択できません。"))
            return
        self.select_all_features_from_tree_layers(self.selectable_layers_in_tree_group(group))

    def select_all_features_from_tree_layers(self, layer_entries):
        self.clear_inspection_selection()
        selected_total = 0
        selected_layers = 0
        seen_layer_ids = set()
        for layer, node in layer_entries:
            if not self.is_selectable_inspection_layer_for_tree_selection(layer, node):
                continue
            if layer.id() in seen_layer_ids:
                continue
            seen_layer_ids.add(layer.id())
            try:
                ids = [feature.id() for feature in layer.getFeatures()]
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"INSPECTION_SELECT_ALL_LAYER_FAILED layer={layer.name()} error={exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                continue
            if not ids:
                continue
            try:
                layer.selectByIds(ids)
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"INSPECTION_SELECT_ALL_SELECT_FAILED layer={layer.name()} error={exc}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                continue
            try:
                actual_ids = list(layer.selectedFeatureIds())
            except Exception:
                actual_ids = []
            actual_count = len(actual_ids)
            if actual_count != len(ids):
                QgsMessageLog.logMessage(
                    f"INSPECTION_SELECT_ALL_ACTUAL_COUNT layer={layer.name()} requested={len(ids)} selected={actual_count}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            if actual_count:
                selected_total += actual_count
                selected_layers += 1
        self.refresh_selection_highlight()
        if selected_total:
            self.set_status(tr_text(f"✅ 全選択: {selected_total} 件 / {selected_layers} レイヤ"))
        else:
            self.set_status(tr_text("全選択: 選択できる地物がありません"))

    def copy_inspection_layer_from_tree(self, layer, source_node=None, target_parent=None, target_index=None, name_suffix="コピー"):
        if not self.is_copyable_inspection_layer(layer):
            QMessageBox.information(self, tr_text("検査レイヤコピー"), tr_text("コピーできる検査レイヤではありません。"))
            return None
        if self.is_layer_or_node_locked_for_copy(layer, source_node):
            QMessageBox.information(self, tr_text("検査レイヤコピー"), tr_text("ロック中の検査レイヤはコピーできません。"))
            return None
        ok, error = self.close_edit_buffer_before_provider_change(layer)
        if not ok:
            QMessageBox.warning(self, tr_text("検査レイヤコピー"), tr_text(f"編集中の内容を保存できませんでした。\n{error}"))
            return None
        try:
            new_layer = self.copy_inspection_layer_data(layer, name_suffix=name_suffix)
        except Exception as exc:
            QMessageBox.critical(self, tr_text("検査レイヤコピー"), tr_text(f"検査レイヤをコピーできませんでした。\n{exc}"))
            QgsMessageLog.logMessage(f"INSPECTION_LAYER_COPY_FAILED layer={layer.name()} error={exc}", "OrthoManager", Qgis.MessageLevel.Warning)
            return None
        if new_layer is None:
            QMessageBox.warning(self, tr_text("検査レイヤコピー"), tr_text("検査レイヤをコピーできませんでした。"))
            return None
        try:
            if target_parent is not None:
                self.place_layer_at_group_index(new_layer, target_parent, target_index)
                self.update_copied_layer_group_metadata(new_layer, target_parent)
            elif source_node is not None and source_node.parent() is not None:
                parent = source_node.parent()
                children = list(parent.children())
                self.place_layer_at_group_index(new_layer, parent, children.index(source_node) + 1)
                self.update_copied_layer_group_metadata(new_layer, parent)
            else:
                self.move_layer_node_to_inspection_group(new_layer)
        except Exception as exc:
            QgsMessageLog.logMessage(f"INSPECTION_LAYER_COPY_PLACE_FAILED layer={new_layer.name()} error={exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        self.active_layer_id = new_layer.id()
        self.refresh_ui()
        self.set_status(tr_text(f"✅ 検査レイヤをコピーしました: {self.layer_base_name(new_layer)}"))
        return new_layer

    def copy_inspection_group_from_tree(self, group):
        if not isinstance(group, QgsLayerTreeGroup) or not self.is_node_under_inspection_root(group):
            QMessageBox.information(self, tr_text("検査グループコピー"), tr_text("コピーできる検査グループではありません。"))
            return
        if group.name() in (INSPECTION_GROUP, TRASH_GROUP_NAME):
            QMessageBox.information(self, tr_text("検査グループコピー"), tr_text("このグループはコピーできません。"))
            return
        if self.is_group_locked_for_copy(group):
            QMessageBox.information(self, tr_text("検査グループコピー"), tr_text("ロック中の検査グループはコピーできません。"))
            return
        if not self.group_contains_copyable_inspection_layer(group):
            QMessageBox.information(self, tr_text("検査グループコピー"), tr_text("コピーできる検査レイヤがありません。"))
            return
        default_name = self.unique_copy_group_name(group.name(), group.parent())
        new_name, ok = QInputDialog.getText(self, tr_text("検査グループコピー"), tr_text("コピー後のグループ名:"), text=default_name)
        new_name = str(new_name or "").strip() if ok else ""
        if not new_name:
            return
        try:
            parent = group.parent() or self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
            children = list(parent.children())
            insert_index = children.index(group) + 1 if group in children else len(children)
            copied_group = QgsLayerTreeGroup(new_name)
            copied_group.setItemVisibilityChecked(group.itemVisibilityChecked())
            parent.insertChildNode(insert_index, copied_group)
            result = {"layers": 0, "skipped": 0}
            self.copy_group_children_to_group(group, copied_group, result)
            if result["layers"] == 0:
                parent.removeChildNode(copied_group)
                QMessageBox.information(self, tr_text("検査グループコピー"), tr_text("コピーできる検査レイヤがありませんでした。"))
                return
            self.refresh_ui()
            self.set_status(tr_text(f"✅ 検査グループをコピーしました: {new_name} / {result['layers']} レイヤ"))
            if result["skipped"]:
                QMessageBox.information(self, tr_text("検査グループコピー"), tr_text(f"コピー完了: {result['layers']} レイヤ\nスキップ: {result['skipped']} 件"))
        except Exception as exc:
            QMessageBox.critical(self, tr_text("検査グループコピー"), tr_text(f"検査グループをコピーできませんでした。\n{exc}"))
            QgsMessageLog.logMessage(f"INSPECTION_GROUP_COPY_FAILED group={group.name()} error={exc}", "OrthoManager", Qgis.MessageLevel.Warning)

    def copy_group_children_to_group(self, source_group, target_group, result):
        for child in list(source_group.children()):
            if isinstance(child, QgsLayerTreeLayer):
                layer = child.layer()
                if not self.is_copyable_inspection_layer(layer) or self.is_layer_or_node_locked_for_copy(layer, child):
                    result["skipped"] += 1
                    continue
                index = len(list(target_group.children()))
                copied = self.copy_inspection_layer_from_tree(
                    layer,
                    source_node=child,
                    target_parent=target_group,
                    target_index=index,
                    name_suffix="コピー",
                )
                if copied:
                    result["layers"] += 1
                else:
                    result["skipped"] += 1
            elif isinstance(child, QgsLayerTreeGroup):
                copied_child_group = QgsLayerTreeGroup(child.name())
                copied_child_group.setItemVisibilityChecked(child.itemVisibilityChecked())
                target_group.addChildNode(copied_child_group)
                before = result["layers"]
                self.copy_group_children_to_group(child, copied_child_group, result)
                if result["layers"] == before:
                    try:
                        target_group.removeChildNode(copied_child_group)
                    except Exception:
                        pass

    def copy_inspection_layer_data(self, layer, name_suffix="コピー"):
        if not OGR_OK:
            raise RuntimeError("GDAL/OGRを読み込めないためコピーできません。")
        inspection_type = self.layer_inspection_type(layer)
        gpkg_path = self.ensure_gpkg_path(inspection_type)
        driver = ogr.GetDriverByName("GPKG")
        target_ds = self.open_or_create_inspection_gpkg(gpkg_path, driver)
        if target_ds is None:
            raise RuntimeError(f"検査GPKGを開けません: {gpkg_path}")
        try:
            descriptor = self.layer_descriptor(layer)
            base_name = self.copied_layer_display_name(self.layer_base_name(layer), name_suffix)
            geom_type = descriptor.get("geom_type") or self.layer_geom_type_key(layer)
            source_base = f"inspection_{geom_type}_{base_name}"
            source_name = self.unique_source_layer_name(source_base, target_ds)
            field_map = self._qgis_source_field_map(layer)
            self.create_inspection_layer(
                0,
                "",
                base_name,
                descriptor.get("color", "ff0000"),
                geom_type,
                custom=True,
                inspection_type=INSPECTION_TYPE_FREE,
                extra_fields=field_map,
                source_name_override=source_name,
                multi_geometry=True,
                dataset=target_ds,
            )
            target_layer = target_ds.GetLayerByName(source_name)
            if target_layer is None:
                raise RuntimeError(f"コピー先レイヤを作成できません: {base_name}")
            new_descriptor = dict(descriptor)
            new_descriptor.update({
                "round_no": 0,
                "code": "",
                "name": base_name,
                "source_name": source_name,
                "inspection_type": INSPECTION_TYPE_FREE,
                "group_name": self.group_path_for_new_copied_layer(layer),
                "custom": True,
                "imported": True,
                "preserve_style": True,
                "gpkg_path": gpkg_path,
            })
            target_info = {
                "layer": target_layer,
                "defn": target_layer.GetLayerDefn(),
                "descriptor": new_descriptor,
                "field_map": field_map,
            }
            written = self.write_copied_layer_features(layer, target_info, geom_type)
        finally:
            target_ds = None
        new_layer = self.load_layer(source_name, new_descriptor)
        if new_layer is not None:
            self.copy_visual_settings(layer, new_layer)
        QgsMessageLog.logMessage(
            f"INSPECTION_LAYER_COPY_DONE src={layer.name()} dst={source_name} features={written}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return new_layer

    def update_copied_layer_group_metadata(self, layer, parent_group):
        if not isinstance(layer, QgsVectorLayer) or parent_group is None:
            return
        group_name = self.free_group_path_from_node(parent_group)
        try:
            layer.setCustomProperty(INSPECTION_PROP_PREFIX + "inspection_type", INSPECTION_TYPE_FREE)
            layer.setCustomProperty(INSPECTION_PROP_PREFIX + "group_name", group_name)
        except Exception:
            pass
        source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
        if source in self.layers:
            self.layers[source]["inspection_type"] = INSPECTION_TYPE_FREE
            self.layers[source]["group_name"] = group_name

    def write_copied_layer_features(self, src_layer, target_info, geom_type):
        target_layer = target_info["layer"]
        transaction_started = self._begin_ogr_layer_transaction(target_layer)
        written = 0
        try:
            for feature in src_layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                geom = QgsGeometry(geom)
                if self._write_qgis_import_feature(target_info, feature, geom, geom_type):
                    written += 1
            if transaction_started:
                self._commit_ogr_layer_transaction(target_layer)
        except Exception:
            if transaction_started:
                self._rollback_ogr_layer_transaction(target_layer)
            raise
        return written

    def copy_visual_settings(self, src_layer, dst_layer):
        try:
            renderer = src_layer.renderer()
            if renderer is not None:
                dst_layer.setRenderer(renderer.clone())
        except Exception:
            pass
        try:
            labeling = src_layer.labeling()
            if labeling is not None:
                dst_layer.setLabeling(labeling.clone())
                dst_layer.setLabelsEnabled(src_layer.labelsEnabled())
        except Exception:
            pass
        try:
            dst_layer.setOpacity(src_layer.opacity())
        except Exception:
            pass
        try:
            dst_layer.triggerRepaint()
        except Exception:
            pass

    def copied_layer_display_name(self, base_name, suffix):
        base_name = str(base_name or "検査レイヤ").strip()
        suffix = str(suffix or "コピー").strip()
        candidate = f"{base_name}_{suffix}"
        used = {self.layer_base_name(layer) for layer in self.current_inspection_layers()}
        if candidate not in used:
            return candidate
        number = 2
        while True:
            candidate = f"{base_name}_{suffix}{number}"
            if candidate not in used:
                return candidate
            number += 1

    def unique_copy_group_name(self, name, parent):
        base = str(name or "検査グループ").strip()
        candidate = f"{base}_コピー"
        used = set()
        try:
            for child in parent.children():
                if isinstance(child, QgsLayerTreeGroup):
                    used.add(child.name())
        except Exception:
            pass
        if candidate not in used:
            return candidate
        number = 2
        while True:
            candidate = f"{base}_コピー{number}"
            if candidate not in used:
                return candidate
            number += 1

    def group_path_for_new_copied_layer(self, layer):
        nodes = self.layer_tree_nodes_for_layer(layer.id())
        if not nodes:
            return str(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "") or "")
        parent = nodes[0][0]
        return self.free_group_path_from_node(parent)

    def is_layer_or_node_locked_for_copy(self, layer, node=None):
        try:
            manager = getattr(self.main_ui, "layer_lock_manager", None)
            if manager is not None and manager.is_layer_locked(layer):
                return True
            if node is not None and manager is not None and manager.is_node_effectively_locked(node):
                return True
        except Exception:
            pass
        return False

    def is_group_locked_for_copy(self, group):
        try:
            manager = getattr(self.main_ui, "layer_lock_manager", None)
            if manager is not None and manager.is_node_effectively_locked(group):
                return True
        except Exception:
            pass
        return False

    def free_group_path_from_node(self, node):
        names = []
        current = node
        while current is not None:
            if isinstance(current, QgsLayerTreeGroup):
                try:
                    name = current.name()
                except Exception:
                    name = ""
                if name == INSPECTION_GROUP:
                    break
                if name:
                    names.append(name)
            try:
                current = current.parent()
            except Exception:
                current = None
        names.reverse()
        return FREE_GROUP_PATH_SEPARATOR.join(names)
