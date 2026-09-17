from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import os

from qgis.PyQt.QtCore import QSize, Qt, QTimer
from qgis.PyQt.QtGui import QCursor, QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    QMenu,
)
from qgis.core import QgsMessageLog, QgsSettings, Qgis, QgsProject

from .i18n import tr, tr_text
from .inspection_constants import *
from .inspection_map_tool import (
    InspectionActionMenuButton,
    InspectionGroupMenuButton,
    InspectionLayerMenuButton,
)


class InspectionContextMenuMixin:
    def context_menu_icon_path(self, icon_name):
        return os.path.join(os.path.dirname(__file__), "icons", "inspection", f"{icon_name}.svg")

    def context_menu_icon(self, icon_name):
        return QIcon(self.context_menu_icon_path(icon_name))

    def context_menu_icon_name_for_action(self, action_key):
        return {
            "pan": "pan",
            "select": "select_rect",
            "select_polygon": "select_polygon",
            "layer_change": "layer_change",
            "restore": "restore",
            "delete": "delete",
            "edit": "edit",
            "move": "move",
            "merge": "merge",
        }.get(action_key, "")

    def context_icon_button_style(self, danger=False):
        if danger:
            return (
                "QPushButton{border:none;border-radius:3px;background:#efefef;"
                "padding:1px;}"
                "QPushButton:hover{background:#dcecff;}"
                "QPushButton:checked{background:#14598f;}"
            )
        return (
            "QPushButton{border:none;border-radius:3px;background:#efefef;"
            "padding:1px;}"
            "QPushButton:hover{background:#dcecff;}"
            "QPushButton:checked{background:#14598f;}"
        )

    def configure_context_icon_button(self, btn, icon_name, tooltip, size=34, icon_size=29, danger=False):
        btn.setText("")
        if icon_name:
            btn.setIcon(self.context_menu_icon(icon_name))
        btn.setIconSize(QSize(icon_size, icon_size))
        btn.setFixedSize(size, size)
        btn.setToolTip(tooltip)
        base_style = self.context_icon_button_style(danger=danger)
        btn.setProperty("base_style", base_style)
        btn.setStyleSheet(base_style)

    def context_action_definitions(self):
        return {
            "pan": (tr("inspection.menu.action.pan"), self.switch_to_pan, tr("inspection.menu.tip.pan")),
            "select": (tr("inspection.menu.action.select"), self.start_select, tr("inspection.menu.tip.select")),
            "select_polygon": (tr("inspection.menu.action.select_polygon"), self.start_select_polygon, tr("inspection.menu.tip.select_polygon")),
            "layer_change": (tr("inspection.menu.action.layer_change"), self.start_layer_change, tr("inspection.menu.tip.layer_change")),
            "restore": ("復帰", self.start_restore_mode, "削除した検査図形をゴミ箱から復帰"),
            "delete": (tr("inspection.menu.action.delete"), self.start_delete, tr("inspection.menu.tip.delete")),
            "edit": (tr("inspection.menu.action.edit"), self.start_edit, tr("inspection.menu.tip.edit")),
            "move": (tr("inspection.menu.action.move"), self.start_move, tr("inspection.menu.tip.move")),
            "merge": (tr("inspection.menu.action.merge"), self.start_merge, tr("inspection.menu.tip.merge")),
        }

    def context_action_order(self):
        default_order = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            raw = QgsSettings().value(CONTEXT_ACTION_ORDER_KEY, "")
        except Exception:
            raw = ""
        saved = []
        if raw:
            saved = [part.strip() for part in str(raw).split(",") if part.strip()]
        order = [key for key in saved if key in default_order]
        for key in default_order:
            if key not in order:
                order.append(key)
        return order[:len(default_order)]

    def context_action_rows(self):
        default_order = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            raw = QgsSettings().value(CONTEXT_ACTION_ORDER_KEY, "")
        except Exception:
            raw = ""
        raw = str(raw or "")
        if "|" not in raw:
            order = self.context_action_order()
            return [order[:4], order[4:]]
        rows = []
        seen = set()
        for part in raw.split("|", 1):
            row = []
            for key in [item.strip() for item in part.split(",") if item.strip()]:
                if key in default_order and key not in seen:
                    row.append(key)
                    seen.add(key)
            rows.append(row)
        while len(rows) < 2:
            rows.append([])
        for key in default_order:
            if key not in seen:
                rows[1].append(key)
        if not rows[0] and rows[1]:
            rows[0].append(rows[1].pop(0))
        return [rows[0], rows[1]]

    def save_context_action_order(self, order):
        valid = [key for key in order if key in CONTEXT_ACTION_DEFAULT_ORDER]
        if not valid:
            valid = list(CONTEXT_ACTION_DEFAULT_ORDER)
        try:
            QgsSettings().setValue(CONTEXT_ACTION_ORDER_KEY, ",".join(valid))
        except Exception:
            _om_record_ignored_exception(__name__, 138)

    def save_context_action_rows(self, rows):
        seen = set()
        cleaned = [[], []]
        for row_index in range(2):
            for key in rows[row_index] if row_index < len(rows) else []:
                if key in CONTEXT_ACTION_DEFAULT_ORDER and key not in seen:
                    cleaned[row_index].append(key)
                    seen.add(key)
        for key in CONTEXT_ACTION_DEFAULT_ORDER:
            if key not in seen:
                cleaned[1].append(key)
        if not cleaned[0] and cleaned[1]:
            cleaned[0].append(cleaned[1].pop(0))
        try:
            QgsSettings().setValue(
                CONTEXT_ACTION_ORDER_KEY,
                ",".join(cleaned[0]) + "|" + ",".join(cleaned[1]),
            )
        except Exception:
            _om_record_ignored_exception(__name__, 159)

    def context_action_is_active(self, action_key):
        mode = self.operation_mode
        active_by_mode = {
            "pan": "pan",
            "pan_pending": "pan",
            "select": "select",
            "select_polygon": "select_polygon",
            "layer_change": "layer_change",
            "layer_change_select": "layer_change",
            "layer_change_select_polygon": "layer_change",
            "restore": "restore",
            "delete": "delete",
            "edit": "edit",
            "move": "move",
            "merge": "merge",
        }
        return active_by_mode.get(mode) == action_key

    def add_context_action_drop_zone(self, row, row_index, slot_index, expand=False):
        zone = QPushButton("")
        zone.setFlat(True)
        zone.setFixedHeight(34)
        zone.setMinimumWidth(8 if expand else 2)
        if expand:
            zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            zone.setFixedWidth(2)
        target = f"__action_slot__:{row_index}:{slot_index}"
        zone.setProperty("inspection_action_drop_target", target)
        base_style = (
            "QPushButton{border:none;background:transparent;padding:0;margin:0;}"
            "QPushButton:hover{background:#dcecff;}"
        )
        zone.setProperty("base_style", base_style)
        zone.setStyleSheet(base_style)
        row.addWidget(zone)

    def add_context_action_button(self, row, menu, menu_pos, action_key, row_index, slot_index):
        definitions = self.context_action_definitions()
        if action_key not in definitions:
            return
        text, slot, tooltip = definitions[action_key]
        btn = InspectionActionMenuButton(text, self, action_key, menu, menu_pos)
        icon_name = self.context_menu_icon_name_for_action(action_key)
        btn.setCheckable(True)
        btn.setChecked(self.context_action_is_active(action_key))
        btn.setProperty("inspection_action_row", row_index)
        btn.setProperty("inspection_action_index", slot_index)
        self.configure_context_icon_button(
            btn,
            icon_name,
            tooltip or text,
            size=34,
            icon_size=29,
            danger=(action_key == "delete"),
        )
        btn.clicked.connect(lambda _=False, s=slot, m=menu: (m.close(), s()))
        row.addWidget(btn)

    def add_context_action_row(self, top_rows, menu, menu_pos, row_index, action_keys):
        row_widget = QWidget()
        row_widget.setProperty("inspection_action_row", row_index)
        row_widget.setProperty("inspection_action_row_len", len(action_keys))
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(0)
        for slot_index, action_key in enumerate(action_keys):
            self.add_context_action_drop_zone(row, row_index, slot_index)
            self.add_context_action_button(row, menu, menu_pos, action_key, row_index, slot_index)
        self.add_context_action_drop_zone(row, row_index, len(action_keys), expand=True)
        top_rows.addWidget(row_widget)

    def add_context_icon_gap(self, layout, width=2):
        layout.addSpacing(width)

    def populate_free_context_tree_menu(self, menu, global_pos):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        current_ids = {layer.id() for layer in self.current_inspection_layers()}
        displayed_sources = set()
        tree_sources = set()
        shown_any = False

        def mark_tree_layers(group_node):
            try:
                children = list(group_node.children())
            except Exception:
                return
            for child in children:
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer:
                    source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
                    if source:
                        tree_sources.add(source)
                    continue
                mark_tree_layers(child)

        def add_layer_row(layer, indent):
            nonlocal shown_any
            if layer is None or layer.id() not in current_ids:
                return
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if not source or source in displayed_sources:
                return
            displayed_sources.add(source)
            self.add_layer_menu_button(
                menu,
                self.layer_base_name(layer),
                source,
                lambda s=source: self.activate_layer_by_source(s),
                close_menu=True,
                bold=False,
                indent=indent,
            )
            shown_any = True

        def add_group_row(group_node, group_path, indent):
            nonlocal shown_any
            title = self.free_group_menu_label(group_path)
            expanded = self.free_group_menu_expanded.get(group_path, True)
            self.add_free_group_menu_button(
                menu,
                f"{'➖' if expanded else '➕'} {title}",
                lambda g=group_path, p=global_pos: self.toggle_free_group_menu(g, p),
                group_path,
                global_pos,
                close_menu=True,
                bold=True,
                indent=indent,
                icon_name="group",
            )
            shown_any = True
            if expanded:
                walk(group_node, group_path, indent + 26)

        def add_module_group_row(group_node, name, indent):
            nonlocal shown_any
            expanded = self.free_group_menu_expanded.get(f"__module__/{name}", True)
            self.add_menu_button(
                menu,
                f"{'➖' if expanded else '➕'} {name}",
                lambda n=name, p=global_pos: self.toggle_free_group_menu(f"__module__/{n}", p),
                close_menu=True,
                bold=True,
                indent=indent,
                icon_name="group",
            )
            shown_any = True
            if expanded:
                walk(group_node, "", indent + 26)

        def walk(group_node, parent_path, indent):
            try:
                children = list(group_node.children())
            except Exception:
                return
            for child in children:
                try:
                    layer = child.layer()
                except Exception:
                    layer = None
                if layer:
                    add_layer_row(layer, indent)
                    continue
                try:
                    name = str(child.name() or "").strip()
                except Exception:
                    name = ""
                if not name:
                    continue
                if not parent_path and name in ORTHO_MODULE_GROUP_NAMES:
                    add_module_group_row(child, name, indent)
                    continue
                group_path = self.child_free_group_path(parent_path, name)
                add_group_row(child, group_path, indent)

        mark_tree_layers(root_group)
        walk(root_group, "", 0)

        for layer in self.current_inspection_layers():
            source = layer.customProperty(INSPECTION_PROP_PREFIX + "source_name", "")
            if source and source not in displayed_sources and source not in tree_sources:
                add_layer_row(layer, 0)

        return shown_any

    def populate_context_menu(self, menu, global_pos):
        if self.operation_mode == "restore":
            self.populate_restore_context_menu(menu, global_pos)
            return
        top_action = QWidgetAction(menu)
        top_widget = QWidget(menu)
        top_rows = QVBoxLayout(top_widget)
        top_rows.setContentsMargins(0, 2, 0, 2)
        top_rows.setSpacing(2)
        layer_change_mode = self.operation_mode in ("layer_change", "layer_change_select", "layer_change_select_polygon")
        if layer_change_mode:
            row = QHBoxLayout()
            row.setSpacing(2)
            btn_pan = QPushButton(tr("inspection.menu.main"))
            btn_pan.setFixedWidth(CONTEXT_ACTION_BUTTON_WIDTH)
            btn_pan.clicked.connect(lambda _=False, m=menu, p=global_pos: (m.close(), self.show_main_menu(p)))
            row.addWidget(btn_pan)
            menu.setStyleSheet("QMenu{background:#fff6c8;} QMenu::item:selected{background:#ffe58a;color:#202020;}")
            top_widget.setStyleSheet("background:#fff6c8;")
            for text, slot, width in [
                (tr("inspection.menu.reselect"), self.restart_layer_change_selection, 56),
                (tr("inspection.menu.cancel"), self.cancel_layer_change, 50),
            ]:
                btn = QPushButton(text)
                btn.setFixedWidth(width)
                btn.clicked.connect(lambda _=False, s=slot, m=menu: (m.close(), s()))
                row.addWidget(btn)
            top_rows.addLayout(row)
        else:
            menu.setStyleSheet(
                "QMenu{background:#efefef;}"
                "QMenu::item:selected{background:#dcecff;color:#202020;}"
                "QMenu::separator{height:1px;background:#c8c8c8;margin:3px 4px;}"
            )
            top_widget.setStyleSheet("background:#efefef;")
            rows = self.context_action_rows()
            self.add_context_action_row(top_rows, menu, global_pos, 0, rows[0])
            self.add_context_action_row(top_rows, menu, global_pos, 1, rows[1])
        top_action.setDefaultWidget(top_widget)
        menu.addAction(top_action)
        if not layer_change_mode:
            self.add_capture_options_row(menu)
        menu.addSeparator()
        if self.is_free_inspection():
            has_items = self.populate_free_context_tree_menu(menu, global_pos)
            if not has_items:
                self.add_menu_button(
                    menu, tr("inspection.menu.add_layer"),
                    lambda p=global_pos: self.run_context_menu_action_and_reopen(lambda: self.add_manual_layer(free_group_name=""), p),
                    close_menu=True, bold=True, indent=0, icon_name="add_layer"
                )
                self.add_menu_button(
                    menu, tr("inspection.menu.add_group"),
                    lambda p=global_pos: self.run_context_menu_action_and_reopen(lambda: self.add_free_group(), p),
                    close_menu=True, bold=True, indent=0, icon_name="add_group"
                )
            else:
                menu.addSeparator()
                self.add_menu_button(
                    menu, tr("inspection.menu.add_layer"),
                    lambda p=global_pos: self.run_context_menu_action_and_reopen(lambda: self.add_manual_layer(free_group_name=""), p),
                    close_menu=True, bold=True, indent=0, icon_name="add_layer"
                )
                self.add_menu_button(
                    menu, tr("inspection.menu.add_group"),
                    lambda p=global_pos: self.run_context_menu_action_and_reopen(lambda: self.add_free_group(), p),
                    close_menu=True, bold=True, indent=0, icon_name="add_group"
                )
        else:
            grouped = {}
            group_order = []
            for layer in self.ordered_inspection_layers():
                desc = self.layer_descriptor(layer)
                if desc.get("geom_type") != "polygon":
                    continue
                round_no = int(desc.get("round_no", 0) or 0)
                if round_no not in grouped:
                    grouped[round_no] = []
                    group_order.append(round_no)
                grouped[round_no].append(layer)
            for round_no in group_order:
                title = tr("inspection.menu.manual_layers") if round_no == 0 else tr("inspection.menu.round_title").format(round=round_no)
                expanded = self.round_menu_expanded.get(round_no, True)
                self.add_menu_button(
                    menu,
                    f"{'➖' if expanded else '➕'} {title}",
                    lambda r=round_no, p=global_pos: self.toggle_round_menu(r, p),
                    close_menu=True,
                    bold=True,
                    indent=0,
                )
                if not expanded:
                    continue
                for layer in grouped[round_no]:
                    desc = self.layer_descriptor(layer)
                    source = desc.get("source_name")
                    self.add_layer_menu_button(
                        menu,
                        self.layer_base_name(layer),
                        source,
                        lambda s=source: self.activate_layer_by_source(s),
                        close_menu=True,
                        bold=False,
                        indent=26,
                    )
                self.add_round_bottom_drop_button(menu, round_no, indent=26)

    def refresh_context_menu(self, menu, global_pos):
        if menu:
            self.close_current_context_menu(keep_menu=menu)
            self.current_context_menu = menu
            menu.clear()
            self.populate_context_menu(menu, global_pos)
            menu.update()
            return
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def run_context_menu_action_and_reopen(self, callback, global_pos):
        callback()
        QTimer.singleShot(0, lambda p=global_pos: self.show_context_menu(p))

    def add_capture_options_row(self, menu):
        menu.addSeparator()
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        widget.setStyleSheet("background:#efefef;")
        continuous_btn = QPushButton()
        continuous_btn.setCheckable(True)
        continuous_btn.setChecked(self.continuous_capture_enabled)
        continuous_btn.setToolTip(tr("inspection.menu.continuous_tooltip"))
        self.configure_context_icon_button(
            continuous_btn,
            "continuous_on" if self.continuous_capture_enabled else "continuous_off",
            tr("inspection.menu.continuous_tooltip"),
            size=34,
            icon_size=29,
        )

        def toggle_continuous(checked, btn=continuous_btn):
            self.set_continuous_capture(checked)
            btn.setIcon(self.context_menu_icon("continuous_on" if checked else "continuous_off"))

        continuous_btn.toggled.connect(toggle_continuous)
        self.add_context_icon_gap(layout)
        layout.addWidget(continuous_btn)
        group = QButtonGroup(widget)
        group.setExclusive(True)
        for key, text, icon_name, tooltip in [
            ("polygon", tr("inspection.menu.shape_polygon"), "shape_polygon", tr("inspection.menu.shape_polygon_tooltip")),
            (
                "fixed_angle_90",
                tr("inspection.menu.shape_fixed_angle_90"),
                "shape_fixed_angle_90",
                tr("inspection.menu.shape_fixed_angle_90_tooltip"),
            ),
            ("rectangle", tr("inspection.menu.shape_rectangle"), "shape_rectangle", tr("inspection.menu.shape_rectangle_tooltip")),
            ("ellipse", tr("inspection.menu.shape_ellipse"), "shape_ellipse", tr("inspection.menu.shape_ellipse_tooltip")),
            ("circle", tr("inspection.menu.shape_circle"), "shape_circle", tr("inspection.menu.shape_circle_tooltip")),
        ]:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(self.active_capture_shape == key)
            self.configure_context_icon_button(btn, icon_name, tooltip, size=34, icon_size=29)
            btn.clicked.connect(lambda _=False, k=key: self.set_capture_shape(k))
            group.addButton(btn)
            self.add_context_icon_gap(layout)
            layout.addWidget(btn)
        layout.addStretch()
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def populate_restore_context_menu(self, menu, global_pos):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(2)
        menu.setStyleSheet("QMenu{background:#eeeeee;} QMenu::item:selected{background:#d0d0d0;color:#202020;}")
        widget.setStyleSheet("background:#eeeeee;")
        for text, slot, width in [
            ("メイン", lambda: self.show_main_menu(global_pos), 54),
            ("元に戻す", self.restore_selected_trash_features, 70),
            ("完全削除", self.permanently_delete_selected_trash_features, 74),
            ("やめる", self.cancel_restore_mode, 54),
        ]:
            btn = QPushButton(text)
            btn.setFixedWidth(width)
            if text == "完全削除":
                btn.setStyleSheet(
                    "QPushButton{background:#d93025;color:white;font-weight:bold;border:1px solid #b3261e;padding:3px 6px;}"
                    "QPushButton:hover{background:#b3261e;}"
                )
            btn.clicked.connect(lambda _=False, s=slot, m=menu: (m.close(), s()))
            row.addWidget(btn)
        action.setDefaultWidget(widget)
        menu.addAction(action)
        menu.addSeparator()
        self.add_menu_button(menu, "ゴミ箱の図形を選択してから操作してください", lambda: None, close_menu=False, bold=False, indent=0)

    def add_menu_button(self, menu, text, callback, close_menu=True, bold=False, indent=0, icon_name=None):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        display_text = str(text or "")
        if icon_name in ("add_layer", "add_group"):
            display_text = display_text.strip()
            while display_text.startswith(("+", "＋")):
                display_text = display_text[1:].strip()
        button = QPushButton(display_text)
        button.setFlat(True)
        button.setMinimumWidth(170)
        if icon_name:
            button.setIcon(self.context_menu_icon(icon_name))
            button.setIconSize(QSize(22, 22))
        text_color = "#202020"
        base_style = (
            f"QPushButton{{border:none;text-align:left;padding:2px 6px;color:{text_color};}}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_group_menu_button(self, menu, text, callback, group_name, menu_pos, close_menu=True, bold=False, indent=0, icon_name=None):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_group_bottom__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        widget.setProperty("inspection_group_name", group_name or "")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = InspectionGroupMenuButton(text, self, group_name, menu, menu_pos, widget)
        button.setFlat(True)
        button.setMinimumWidth(170)
        if icon_name:
            button.setIcon(self.context_menu_icon(icon_name))
            button.setIconSize(QSize(22, 22))
        button.setProperty("inspection_drop_target", target)
        button.setProperty("inspection_group_name", group_name or "")
        if self.is_free_group_locked(group_name):
            text_color = "#d93025"
        elif self.is_free_group_selection_locked(group_name):
            text_color = "#f9ab00"
        else:
            text_color = "#202020"
        base_style = (
            f"QPushButton{{border:none;text-align:left;padding:2px 6px;color:{text_color};}}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_layer_menu_button(self, menu, text, source_name, callback, close_menu=True, bold=False, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        widget.setProperty("inspection_source", source_name)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 1, 4, 1)
        button = InspectionLayerMenuButton(text, self, source_name, menu, QCursor.pos(), widget)
        button.setFlat(True)
        button.setMinimumWidth(170)
        layer = self.layer_by_source(source_name)
        if self.is_layer_locked(layer):
            text_color = "#d93025"
        elif self.is_layer_selection_locked(layer):
            text_color = "#f9ab00"
        else:
            text_color = "#0645ad" if layer and self.is_manual_layer(layer) else "#202020"
        base_style = (
            f"QPushButton{{border:none;text-align:left;padding:3px 6px;color:{text_color};}}"
            "QPushButton:hover{background:#dcecff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        if bold:
            font = QFont(button.font())
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            button.setFont(font)
        if close_menu:
            button.clicked.connect(lambda _=False, m=menu, cb=callback: (m.close(), cb()))
        else:
            button.clicked.connect(lambda _=False, cb=callback: cb())
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_round_bottom_drop_button(self, menu, round_no, indent=0):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__round_bottom__:{round_no}"
        widget.setProperty("inspection_drop_target", target)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(8)
        button.setProperty("inspection_drop_target", target)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_group_bottom_drop_button(self, menu, group_name, indent=0, height=3):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_group_bottom__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        widget.setProperty("inspection_group_name", group_name or "")
        widget.setProperty("inspection_group_drop_zone", "bottom")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(height)
        button.setProperty("inspection_drop_target", target)
        button.setProperty("inspection_group_name", group_name or "")
        button.setProperty("inspection_group_drop_zone", "bottom")
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_root_gap_drop_button(self, menu, index, indent=0, height=3):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_root_gap__:{int(index)}"
        widget.setProperty("inspection_drop_target", target)
        widget.setProperty("inspection_group_drop_zone", "root_gap")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(height)
        button.setProperty("inspection_drop_target", target)
        button.setProperty("inspection_group_drop_zone", "root_gap")
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_root_after_group_drop_button(self, menu, group_name, indent=0, height=3):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_root_after_group__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(height)
        button.setProperty("inspection_drop_target", target)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_root_before_group_drop_button(self, menu, group_name, indent=0, height=3):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        target = f"__free_root_before_group__:{group_name or ''}"
        widget.setProperty("inspection_drop_target", target)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(height)
        button.setProperty("inspection_drop_target", target)
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def add_free_group_root_top_drop_button(self, menu, indent=0, height=3):
        action = QWidgetAction(menu)
        widget = QWidget(menu)
        widget.setProperty("inspection_group_name", "")
        widget.setProperty("inspection_group_drop_zone", "root_top")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(indent, 0, 4, 0)
        button = QPushButton("")
        button.setFlat(True)
        button.setMinimumWidth(170)
        button.setFixedHeight(height)
        button.setProperty("inspection_group_name", "")
        button.setProperty("inspection_group_drop_zone", "root_top")
        base_style = (
            "QPushButton{border:none;text-align:left;padding:0;background:transparent;color:transparent;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        button.setProperty("base_style", base_style)
        button.setStyleSheet(base_style)
        layout.addWidget(button)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def layer_source_at_global_pos(self, global_pos):
        source, _button = self.layer_button_at_global_pos(global_pos)
        return source

    def layer_button_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            drop_target = widget.property("inspection_drop_target")
            if drop_target:
                if self.is_free_root_gap_drop_target(drop_target):
                    button = widget if isinstance(widget, QPushButton) else None
                    if button is None:
                        button = widget.findChild(QPushButton)
                    return str(drop_target), button
                group_name = widget.property("inspection_group_name")
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_drop_target") == drop_target:
                        button = child
                if button and group_name is not None:
                    group_name = self.normalize_free_group_path(group_name)
                    local_pos = button.mapFromGlobal(global_pos)
                    if group_name and not self.free_group_parent_path(group_name):
                        return drop_target, button
                    if local_pos.y() < button.height() / 2 and group_name:
                        return f"__free_root_before_group__:{group_name}", button
                return drop_target, button
            source = widget.property("inspection_source")
            if source:
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_source") == source:
                        button = child
                if button:
                    local_pos = button.mapFromGlobal(global_pos)
                    layer = self.layer_by_source(source)
                    if (
                        layer
                        and self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE
                        and not self.normalize_free_group_path(layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
                    ):
                        return "", None
                    if local_pos.y() > button.height() / 2:
                        return "", None
                return source, button
            widget = widget.parentWidget()
        return "", None

    def free_group_drop_target_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            drop_target = widget.property("inspection_drop_target")
            if drop_target and self.is_free_root_gap_drop_target(drop_target):
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    button = widget.findChild(QPushButton)
                return str(drop_target), "root_gap", button
            group_name = widget.property("inspection_group_name")
            if group_name is not None:
                group_name = str(group_name or "").strip()
                drop_zone = widget.property("inspection_group_drop_zone")
                is_bottom_zone = drop_zone == "bottom"
                is_root_top_zone = drop_zone == "root_top"
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_group_name") is not None:
                        button = child
                        child_zone = child.property("inspection_group_drop_zone")
                        is_bottom_zone = is_bottom_zone or child_zone == "bottom"
                        is_root_top_zone = is_root_top_zone or child_zone == "root_top"
                if button:
                    if is_root_top_zone:
                        position = "root_top"
                    elif is_bottom_zone:
                        position = "inside"
                    else:
                        local_pos = button.mapFromGlobal(global_pos)
                        if not group_name and local_pos.y() < button.height() / 2:
                            return None, "", None
                        if group_name and not self.free_group_parent_path(group_name) and local_pos.y() < button.height() / 2:
                            return None, "", None
                        if local_pos.y() < button.height() / 2:
                            position = "before"
                        else:
                            position = "inside"
                    return group_name, position, button
            source = widget.property("inspection_source")
            if source:
                source = str(source or "").strip()
                layer = self.layer_by_source(source)
                if layer and self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE:
                    button = widget if isinstance(widget, QPushButton) else None
                    if button is None:
                        child = widget.findChild(QPushButton)
                        if child:
                            button = child
                    if button:
                        local_pos = button.mapFromGlobal(global_pos)
                        if local_pos.y() > button.height() / 2:
                            return None, "", None
                        position = "before_layer"
                        return f"__free_layer__:{source}", position, button
            widget = widget.parentWidget()
        return None, "", None

    def clear_free_group_drag_highlight(self):
        if self.group_drag_highlight_button:
            base_style = self.group_drag_highlight_button.property("base_style")
            if base_style:
                self.group_drag_highlight_button.setStyleSheet(base_style)
        self.group_drag_highlight_button = None
        self.group_drag_highlight_target = ""

    def clear_free_group_drag_visual(self):
        self.clear_free_group_drag_highlight()
        if self.group_drag_source_button:
            base_style = self.group_drag_source_button.property("base_style")
            if base_style:
                self.group_drag_source_button.setStyleSheet(base_style)
        self.group_drag_source_button = None
        if self.group_drag_preview_label:
            self.group_drag_preview_label.hide()

    def update_free_group_drag_target(self, group_name, global_pos, source_button=None):
        group_name = str(group_name or "").strip()
        if not group_name:
            return
        if source_button and source_button is not self.group_drag_source_button:
            if self.group_drag_source_button:
                base_style = self.group_drag_source_button.property("base_style")
                if base_style:
                    self.group_drag_source_button.setStyleSheet(base_style)
            self.group_drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;text-align:left;padding:2px 6px;"
                "background:#f3f4f6;color:#8a8f98;font-weight:bold;}"
            )
        self.update_free_group_drag_preview(group_name, global_pos)
        target_group, position, button = self.free_group_drop_target_at_global_pos(global_pos)
        has_drop_target = target_group is not None
        target_group = self.normalize_free_group_path(target_group)
        invalid_target = not has_drop_target or target_group == group_name
        if target_group and target_group.startswith(group_name + FREE_GROUP_PATH_SEPARATOR):
            invalid_target = True
        if invalid_target:
            target_key = ""
            button = None
        else:
            target_key = f"{position}:{target_group}"
        if button is self.group_drag_highlight_button and target_key == self.group_drag_highlight_target:
            return
        self.clear_free_group_drag_highlight()
        if not target_key or not button:
            return
        base_style = button.property("base_style") or "QPushButton{border:none;text-align:left;padding:2px 6px;color:#202020;}"
        if position == "inside":
            button.setStyleSheet(
                str(base_style).replace("border:none;", "border:2px solid #2f7d32;")
            )
        else:
            line_side = "border-bottom" if position in ("after", "after_layer") else "border-top"
            button.setStyleSheet(
                str(base_style).replace("border:none;", f"border:none;{line_side}:3px solid #1456d9;")
            )
        self.group_drag_highlight_button = button
        self.group_drag_highlight_target = target_key
        if position == "inside":
            destination = self.free_group_title(target_group)
            suffix = " の中" if target_group else ""
            self.set_status(tr_text(f"グループ移動先: {destination}{suffix}"))
        elif position == "root_top":
            self.set_status(tr_text("グループ移動先: 検査直下の一番上"))
        elif position in ("before_layer", "after_layer"):
            target_source = self.source_from_free_layer_group_drop_target(target_group)
            layer = self.layer_by_source(target_source)
            side_label = "下" if position == "after_layer" else "上"
            if layer:
                self.set_status(tr_text(f"グループ移動先: {self.display_layer_name(layer)} の{side_label}"))
        elif position == "root_gap":
            self.set_status(tr_text("グループ移動先: 検査直下の隙間"))
        else:
            side_label = "下" if position == "after" else "上"
            self.set_status(tr_text(f"グループ移動先: {self.free_group_title(target_group)} の{side_label}"))

    def update_free_group_drag_preview(self, group_name, global_pos):
        label_text = self.free_group_title(group_name)
        if not self.group_drag_preview_label:
            self.group_drag_preview_label = QLabel()
            try:
                self.group_drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.group_drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.group_drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.group_drag_preview_label.setText(label_text)
        self.group_drag_preview_label.adjustSize()
        self.group_drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.group_drag_preview_label.show()

    def clear_layer_drag_highlight(self):
        if self.drag_highlight_button:
            base_style = self.drag_highlight_button.property("base_style")
            if base_style:
                self.drag_highlight_button.setStyleSheet(base_style)
        self.drag_highlight_button = None
        self.drag_highlight_target = ""

    def clear_layer_drag_visual(self):
        self.clear_layer_drag_highlight()
        if self.drag_source_button:
            base_style = self.drag_source_button.property("base_style")
            if base_style:
                self.drag_source_button.setStyleSheet(base_style)
        self.drag_source_button = None
        if self.drag_preview_label:
            self.drag_preview_label.hide()

    def update_layer_drag_target(self, source_name, global_pos, source_button=None):
        if source_button and source_button is not self.drag_source_button:
            if self.drag_source_button:
                base_style = self.drag_source_button.property("base_style")
                if base_style:
                    self.drag_source_button.setStyleSheet(base_style)
            self.drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;text-align:left;padding:3px 6px;"
                "background:#f3f4f6;color:#8a8f98;}"
            )
        self.update_layer_drag_preview(source_name, global_pos)
        target_source, button = self.layer_button_at_global_pos(global_pos)
        if target_source == source_name or target_source == f"__after__:{source_name}":
            target_source = ""
            button = None
        if button is self.drag_highlight_button and target_source == self.drag_highlight_target:
            return
        self.clear_layer_drag_highlight()
        if not target_source or not button:
            return
        base_style = button.property("base_style") or "QPushButton{border:none;text-align:left;padding:3px 6px;color:#202020;}"
        line_side = "border-bottom" if (
            self.is_after_drop_target(target_source)
            or self.is_round_bottom_drop_target(target_source)
            or self.is_free_group_bottom_drop_target(target_source)
            or self.is_free_root_after_group_drop_target(target_source)
        ) else "border-top"
        button.setStyleSheet(
            str(base_style).replace("border:none;", f"border:none;{line_side}:3px solid #1456d9;")
        )
        self.drag_highlight_button = button
        self.drag_highlight_target = target_source
        if target_source.startswith("__round_bottom__:"):
            round_no = self.round_no_from_drop_target(target_source)
            self.set_status(tr_text(f"移動先: {self.round_title(round_no)} の一番下"))
        elif self.is_free_root_gap_drop_target(target_source):
            self.set_status(tr_text("移動先: 検査直下の隙間"))
        elif target_source.startswith("__free_group_bottom__:"):
            group_name = self.group_name_from_drop_target(target_source)
            self.set_status(tr_text(f"移動先: {self.free_group_title(group_name)} の一番下"))
        elif target_source.startswith("__free_root_after_group__:"):
            group_name = self.group_name_from_root_after_drop_target(target_source)
            self.set_status(tr_text(f"移動先: {self.free_group_title(group_name)} の下（検査直下）"))
        elif target_source.startswith("__free_root_before_group__:"):
            group_name = self.group_name_from_root_before_drop_target(target_source)
            self.set_status(tr_text(f"移動先: {self.free_group_title(group_name)} の上（検査直下）"))
        elif self.is_after_drop_target(target_source):
            layer = self.layer_by_source(self.source_from_after_drop_target(target_source))
            if layer:
                self.set_status(tr_text(f"移動先: {self.display_layer_name(layer)} の下"))
        else:
            layer = self.layer_by_source(target_source)
            if layer:
                self.set_status(tr_text(f"移動先: {self.display_layer_name(layer)} の上"))

    def round_title(self, round_no):
        return "手動レイヤ" if round_no == 0 else ORTHO_ROUND_GROUP_NAMES.get(round_no, f"オルソ{round_no}回目検査")

    def round_no_from_drop_target(self, target_source):
        try:
            return int(str(target_source).split(":", 1)[1])
        except Exception:
            return None

    def is_round_bottom_drop_target(self, target_source):
        return str(target_source).startswith("__round_bottom__:")

    def is_free_group_bottom_drop_target(self, target_source):
        return str(target_source).startswith("__free_group_bottom__:")

    def group_name_from_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_free_group_bottom_drop_target(target_source) else ""

    def is_free_root_after_group_drop_target(self, target_source):
        return str(target_source).startswith("__free_root_after_group__:")

    def group_name_from_root_after_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_free_root_after_group_drop_target(target_source) else ""

    def is_free_root_before_group_drop_target(self, target_source):
        return str(target_source).startswith("__free_root_before_group__:")

    def group_name_from_root_before_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_free_root_before_group_drop_target(target_source) else ""

    def is_free_root_gap_drop_target(self, target_source):
        return str(target_source).startswith("__free_root_gap__:")

    def index_from_free_root_gap_drop_target(self, target_source):
        if not self.is_free_root_gap_drop_target(target_source):
            return 0
        try:
            return int(str(target_source).split(":", 1)[1])
        except Exception:
            return 0

    def is_free_layer_group_drop_target(self, target_source):
        return str(target_source).startswith("__free_layer__:")

    def source_from_free_layer_group_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_free_layer_group_drop_target(target_source) else ""

    def free_group_title(self, group_name):
        parts = self.free_group_path_parts(group_name)
        return " / ".join(parts) if parts else "検査直下"

    def free_group_menu_label(self, group_name):
        return self.free_group_leaf_name(group_name) or self.free_group_title(group_name)

    def free_group_depth(self, group_name):
        parts = self.free_group_path_parts(group_name)
        return max(0, len(parts) - 1)

    def free_group_ancestors_expanded(self, group_name):
        parts = self.free_group_path_parts(group_name)
        for idx in range(1, len(parts)):
            ancestor = FREE_GROUP_PATH_SEPARATOR.join(parts[:idx])
            if not self.free_group_menu_expanded.get(ancestor, True):
                return False
        return True

    def layer_lock_manager(self):
        return getattr(self.main_ui, "layer_lock_manager", None)

    def schedule_layer_lock_indicator_rebuild(self, delay_ms=0):
        manager = self.layer_lock_manager()
        if manager is None or not hasattr(manager, "rebuild_indicators"):
            return
        if self._layer_lock_rebuild_pending:
            return
        self._layer_lock_rebuild_pending = True

        def rebuild():
            self._layer_lock_rebuild_pending = False
            try:
                manager.rebuild_indicators()
                QTimer.singleShot(160, manager.rebuild_indicators)
            except Exception as exc:
                QgsMessageLog.logMessage(f"ロックマーク再構築エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)

        QTimer.singleShot(max(0, int(delay_ms)), rebuild)

    def is_layer_locked(self, layer):
        manager = self.layer_lock_manager()
        if manager is None or layer is None:
            return False
        try:
            return manager.is_layer_locked(layer)
        except Exception:
            return False

    def is_layer_selection_locked(self, layer):
        manager = self.layer_lock_manager()
        if manager is None or layer is None:
            return False
        try:
            return manager.is_layer_selection_locked(layer)
        except Exception:
            return False

    def is_free_group_locked(self, group_name):
        manager = self.layer_lock_manager()
        group = self.find_free_group_node(group_name)
        if manager is None or group is None:
            return False
        try:
            return manager.is_node_effectively_locked(group)
        except Exception:
            return False

    def is_free_group_selection_locked(self, group_name):
        manager = self.layer_lock_manager()
        group = self.find_free_group_node(group_name)
        if manager is None or group is None:
            return False
        try:
            return manager.is_node_effectively_selection_locked(group)
        except Exception:
            return False

    def find_free_group_node(self, group_name):
        root = QgsProject.instance().layerTreeRoot()
        if not group_name:
            return root.findGroup(FREE_INSPECTION_GROUP)
        parts = self.free_group_path_parts(group_name)
        for free_root in self.direct_child_groups(root, FREE_INSPECTION_GROUP):
            current = free_root
            for part in parts:
                groups = self.direct_child_groups(current, part)
                if not groups:
                    current = None
                    break
                current = groups[0]
            if current is not None:
                return current
        return None

    def free_group_path_from_node(self, node):
        if node is None:
            return ""
        try:
            if node.layer():
                return ""
        except Exception:
            _om_record_ignored_exception(__name__, 1229)
        names = []
        current = node
        while current is not None:
            try:
                name = str(current.name() or "").strip()
            except Exception:
                break
            if name == FREE_INSPECTION_GROUP:
                path = self.normalize_free_group_path(FREE_GROUP_PATH_SEPARATOR.join(reversed(names)))
                first = self.free_group_path_parts(path)[0] if self.free_group_path_parts(path) else ""
                return "" if first in ORTHO_MODULE_GROUP_NAMES else path
            names.append(name)
            try:
                current = current.parent()
            except Exception:
                break
        return ""

    def selected_free_group_path(self):
        try:
            node = self.iface.layerTreeView().currentNode()
        except Exception:
            node = None
        return self.free_group_path_from_node(node)

    def locked_layer_names(self, layers):
        names = []
        for layer in layers:
            if layer is not None and self.is_layer_locked(layer):
                names.append(self.display_layer_name(layer))
        return names

    def block_locked_layers(self, layers, title, action_label):
        names = self.locked_layer_names(layers)
        if not names:
            return False
        QMessageBox.warning(
            self,
            title,
            tr_text(f"ロック中のレイヤには{action_label}できません。\n\n" + "\n".join(names[:8])),
        )
        self.set_status(tr_text("ロック中のレイヤです"))
        return True

    def is_after_drop_target(self, target_source):
        return str(target_source).startswith("__after__:")

    def source_from_after_drop_target(self, target_source):
        return str(target_source).split(":", 1)[1] if self.is_after_drop_target(target_source) else target_source

    def is_action_slot_target(self, target_key):
        return str(target_key).startswith("__action_slot__:")

    def action_slot_from_target(self, target_key):
        if not self.is_action_slot_target(target_key):
            return None, None
        parts = str(target_key).split(":")
        try:
            return int(parts[1]), int(parts[2])
        except Exception:
            return None, None

    def action_drop_target_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            drop_target = widget.property("inspection_action_drop_target")
            if drop_target:
                button = widget if isinstance(widget, QPushButton) else None
                return str(drop_target), button
            action_key = widget.property("inspection_action_key")
            if action_key:
                button = widget if isinstance(widget, QPushButton) else None
                if button is None:
                    child = widget.findChild(QPushButton)
                    if child and child.property("inspection_action_key") == action_key:
                        button = child
                if button:
                    local_pos = button.mapFromGlobal(global_pos)
                    row_index = button.property("inspection_action_row")
                    slot_index = button.property("inspection_action_index")
                    try:
                        row_index = int(row_index)
                        slot_index = int(slot_index)
                    except Exception:
                        row_index = 0
                        slot_index = 0
                    if local_pos.x() > button.width() / 2:
                        slot_index += 1
                    return f"__action_slot__:{row_index}:{slot_index}", button
            row_index = widget.property("inspection_action_row")
            row_len = widget.property("inspection_action_row_len")
            if row_index is not None and row_len is not None:
                try:
                    return f"__action_slot__:{int(row_index)}:{int(row_len)}", widget
                except Exception:
                    _om_record_ignored_exception(__name__, 1325)
            widget = widget.parentWidget()
        return "", None

    def clear_action_drag_highlight(self):
        if self.action_drag_highlight_button:
            base_style = self.action_drag_highlight_button.property("base_style")
            if base_style:
                self.action_drag_highlight_button.setStyleSheet(base_style)
        self.action_drag_highlight_button = None
        self.action_drag_highlight_target = ""

    def clear_action_drag_visual(self):
        self.clear_action_drag_highlight()
        if self.action_drag_source_button:
            base_style = self.action_drag_source_button.property("base_style")
            if base_style:
                self.action_drag_source_button.setStyleSheet(base_style)
        self.action_drag_source_button = None
        if self.action_drag_preview_label:
            self.action_drag_preview_label.hide()

    def update_action_drag_target(self, action_key, global_pos, source_button=None):
        if source_button and source_button is not self.action_drag_source_button:
            if self.action_drag_source_button:
                base_style = self.action_drag_source_button.property("base_style")
                if base_style:
                    self.action_drag_source_button.setStyleSheet(base_style)
            self.action_drag_source_button = source_button
            source_button.setStyleSheet(
                "QPushButton{border:1px dashed #9aa0a6;border-radius:3px;"
                "background:#f3f4f6;color:#8a8f98;padding:3px 0;}"
            )
        self.update_action_drag_preview(action_key, global_pos)
        target_key, target_widget = self.action_drop_target_at_global_pos(global_pos)
        row_index, slot_index = self.action_slot_from_target(target_key)
        rows = self.context_action_rows()
        source_row = None
        source_index = None
        for idx, row in enumerate(rows):
            if action_key in row:
                source_row = idx
                source_index = row.index(action_key)
                break
        if row_index is None or slot_index is None:
            target_key = ""
        elif source_row == row_index and (slot_index == source_index or slot_index == source_index + 1):
            target_key = ""
        if target_key == self.action_drag_highlight_target:
            return
        self.clear_action_drag_highlight()
        if not target_key:
            return
        if isinstance(target_widget, QPushButton):
            base_style = target_widget.property("base_style") or ""
            target_widget.setStyleSheet(
                "QPushButton{border-left:3px solid #1456d9;background:#e7f0ff;padding:0;}"
            )
            self.action_drag_highlight_button = target_widget
        else:
            self.action_drag_highlight_button = None
        self.action_drag_highlight_target = target_key
        self.set_status(tr_text(f"ボタン移動先: {row_index + 1}行目 {slot_index + 1}番目"))

    def update_action_drag_preview(self, action_key, global_pos):
        label_text = self.context_action_definitions().get(action_key, (action_key, None, ""))[0]
        if not self.action_drag_preview_label:
            self.action_drag_preview_label = QLabel()
            try:
                self.action_drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.action_drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.action_drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.action_drag_preview_label.setText(label_text)
        self.action_drag_preview_label.adjustSize()
        self.action_drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.action_drag_preview_label.show()

    def handle_action_button_drop(self, action_key, target_key, menu_pos, menu=None):
        row_index, slot_index = self.action_slot_from_target(target_key)
        if row_index is None or slot_index is None:
            self.refresh_context_menu(menu, menu_pos)
            return
        if action_key not in CONTEXT_ACTION_DEFAULT_ORDER or row_index not in (0, 1):
            self.refresh_context_menu(menu, menu_pos)
            return
        rows = self.context_action_rows()
        source_row = None
        source_index = None
        for idx, row in enumerate(rows):
            if action_key in row:
                source_row = idx
                source_index = row.index(action_key)
                break
        if source_row is not None:
            rows[source_row].remove(action_key)
        if source_row == row_index and source_index is not None and source_index < slot_index:
            slot_index -= 1
        slot_index = max(0, min(slot_index, len(rows[row_index])))
        rows[row_index].insert(slot_index, action_key)
        self.save_context_action_rows(rows)
        self.set_status(tr_text("✅ 右クリックボタン配置を保存しました"))
        self.refresh_context_menu(menu, menu_pos)

    def update_layer_drag_preview(self, source_name, global_pos):
        layer = self.layer_by_source(source_name)
        label_text = self.layer_base_name(layer) if layer else source_name
        if not self.drag_preview_label:
            self.drag_preview_label = QLabel()
            try:
                self.drag_preview_label.setWindowFlags(Qt.WindowType.ToolTip)
            except Exception:
                self.drag_preview_label.setWindowFlags(Qt.ToolTip)
            self.drag_preview_label.setStyleSheet(
                "QLabel{background:#202124;color:white;border:1px solid #4d5156;"
                "border-radius:3px;padding:4px 8px;font-weight:bold;}"
            )
        self.drag_preview_label.setText(label_text)
        self.drag_preview_label.adjustSize()
        self.drag_preview_label.move(global_pos.x() + 14, global_pos.y() + 14)
        self.drag_preview_label.show()

    def show_layer_management_menu(self, source_name, global_pos, return_pos=None):
        layer = self.layer_by_source(source_name)
        if not layer:
            return
        menu = QMenu()
        title_action = menu.addAction(self.layer_base_name(layer))
        title_action.setEnabled(False)
        menu.addSeparator()
        add_action = menu.addAction(tr("inspection.btn.layer_add"))
        add_action.triggered.connect(lambda _=False, s=source_name: self.add_manual_layer(insert_above_source=s))
        import_action = menu.addAction(tr("inspection.btn.vector_import"))
        import_action.triggered.connect(lambda _=False, s=source_name: self.import_vector_layers(insert_above_source=s))
        rename_action = menu.addAction(tr("inspection.menu.layer_rename"))
        rename_action.triggered.connect(lambda _=False, l=layer: self.rename_inspection_item(l))
        color_action = menu.addAction(tr("inspection.menu.color"))
        color_action.triggered.connect(lambda _=False, l=layer: self.change_inspection_color(l))
        size_action = menu.addAction(tr("inspection.menu.size"))
        size_action.triggered.connect(lambda _=False, l=layer: self.change_layer_size(l))
        delete_action = menu.addAction(tr("inspection.btn.manual_delete"))
        delete_action.setEnabled(self.is_manual_layer(layer))
        delete_action.triggered.connect(lambda _=False, l=layer: self.delete_manual_layer(l))
        menu.exec(global_pos)
        if return_pos:
            QTimer.singleShot(0, lambda: self.show_context_menu(return_pos))

    def show_free_group_management_menu(self, group_name, global_pos, return_pos=None):
        if not self.is_free_inspection():
            return
        menu = QMenu()
        title_action = menu.addAction(self.free_group_title(group_name))
        title_action.setEnabled(False)
        menu.addSeparator()
        add_action = menu.addAction(tr("inspection.btn.layer_add"))
        add_action.triggered.connect(lambda _=False, g=group_name: self.add_manual_layer(free_group_name=g))
        child_group_action = menu.addAction(tr_text("子グループ追加"))
        child_group_action.triggered.connect(lambda _=False, g=group_name: self.add_free_group(parent_group_name=g))
        rename_action = menu.addAction(tr("inspection.menu.group_rename"))
        rename_action.triggered.connect(lambda _=False, g=group_name: self.rename_free_group(g))
        delete_action = menu.addAction(tr("inspection.menu.group_delete"))
        delete_action.triggered.connect(lambda _=False, g=group_name: self.delete_free_group(g))
        menu.exec(global_pos)
        if return_pos:
            QTimer.singleShot(0, lambda: self.show_context_menu(return_pos))

    def handle_free_group_button_drop(self, source_group, target_group, position, menu_pos, menu=None):
        source_group = self.normalize_free_group_path(source_group)
        has_drop_target = target_group is not None
        raw_target = str(target_group or "")
        target_layer_source = self.source_from_free_layer_group_drop_target(raw_target)
        target_layer = self.layer_by_source(target_layer_source) if target_layer_source else None
        is_root_gap_target = position == "root_gap" and self.is_free_root_gap_drop_target(raw_target)
        root_gap_index = self.index_from_free_root_gap_drop_target(raw_target) if is_root_gap_target else 0
        is_layer_target = position in ("before_layer", "after_layer") and target_layer is not None
        target_group = (
            self.normalize_free_group_path(target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", ""))
            if is_layer_target
            else "" if is_root_gap_target
            else self.normalize_free_group_path(target_group)
        )
        position = position if position in ("before", "after", "inside", "root_top", "root_gap", "before_layer", "after_layer") else "inside"
        if not source_group or not has_drop_target:
            self.refresh_context_menu(menu, menu_pos)
            return
        groups = self.free_group_names()
        if source_group not in groups or (not is_layer_target and not is_root_gap_target and target_group and target_group not in groups):
            self.refresh_context_menu(menu, menu_pos)
            return
        if is_layer_target and self.layer_inspection_type(target_layer) != INSPECTION_TYPE_FREE:
            self.refresh_context_menu(menu, menu_pos)
            return
        if target_group == source_group or (
            target_group and target_group.startswith(source_group + FREE_GROUP_PATH_SEPARATOR)
        ):
            self.refresh_context_menu(menu, menu_pos)
            return

        old_title = self.free_group_title(source_group)
        leaf_name = self.free_group_leaf_name(source_group)
        if is_root_gap_target:
            target_parent = ""
        elif is_layer_target:
            target_parent = target_group
        elif position == "root_top":
            target_parent = ""
        elif position == "inside" or not target_group:
            target_parent = target_group
        else:
            target_parent = self.free_group_parent_path(target_group)
        new_path = self.child_free_group_path(target_parent, leaf_name)
        if new_path != source_group and new_path in groups:
            QMessageBox.information(self, tr_text("グループ移動"), tr_text("移動先に同じ名前のグループが既にあります。"))
            self.refresh_context_menu(menu, menu_pos)
            return

        old_subtree = self.free_group_subtree_paths(source_group, groups)
        moved_paths = [
            new_path + name[len(source_group):]
            if name == source_group or name.startswith(source_group + FREE_GROUP_PATH_SEPARATOR)
            else name
            for name in old_subtree
        ]
        if new_path != source_group:
            self.move_free_group_tree_node(source_group, target_parent)
            self.apply_free_group_path_change(source_group, new_path)
        if is_layer_target:
            self.reorder_free_group_paths_for_layer_drop(moved_paths, target_layer, position)
        elif is_root_gap_target:
            pass
        else:
            self.reorder_free_group_paths_for_drop(moved_paths, target_group, position)
        if is_layer_target:
            self.place_free_group_at_layer_position(new_path, target_layer, after=(position == "after_layer"))
            self.sync_free_groups_from_layer_tree()
        elif is_root_gap_target:
            self.place_free_group_at_root_index(new_path, root_gap_index)
            self.sync_free_groups_from_layer_tree()
        elif position in ("before", "after"):
            self.place_free_group_at_group_position(new_path, target_group, after=(position == "after"))
            self.sync_free_groups_from_layer_tree()
        elif position == "root_top":
            self.place_free_root_group_at_top(new_path)
            self.sync_free_groups_from_layer_tree()
        self.refresh_counts()
        self.schedule_layer_lock_indicator_rebuild()
        if is_layer_target:
            side_label = "下" if position == "after_layer" else "上"
            self.set_status(tr_text(f"✅ グループ移動: {self.free_group_title(new_path)} → {self.display_layer_name(target_layer)} の{side_label}"))
        elif is_root_gap_target:
            self.set_status(tr_text(f"✅ グループ移動: {self.free_group_title(new_path)} → 検査直下の隙間"))
        elif position == "root_top":
            self.set_status(tr_text(f"✅ グループ移動: {self.free_group_title(new_path)} → 検査直下の一番上"))
        elif position == "inside":
            self.set_status(tr_text(f"✅ グループ移動: {old_title} → {self.free_group_title(target_parent)}"))
        else:
            side_label = "下" if position == "after" else "上"
            self.set_status(tr_text(f"✅ グループ並び替え: {self.free_group_title(new_path)} → {self.free_group_title(target_group)} の{side_label}"))
        self.refresh_context_menu(menu, menu_pos)

    def reorder_free_group_layer_tree(self):
        root_group = self.ensure_inspection_root_group(INSPECTION_TYPE_FREE)
        desired = [name for name in self.free_group_names() if name]
        if not desired:
            return
        for name in desired:
            self.ensure_free_group(name)
        self.reorder_free_group_children(root_group, "", desired)
        try:
            root_children = list(root_group.children())
        except Exception:
            root_children = []
        for child in root_children:
            try:
                child.layer()
                is_layer = True
            except Exception:
                is_layer = False
            if not is_layer:
                self.reorder_free_group_direct_layers(child)
        QApplication.processEvents()

    def reorder_free_group_children(self, parent_node, parent_path, desired):
        child_desired = []
        for name in desired:
            parts = self.free_group_path_parts(name)
            if not parts:
                continue
            if self.free_group_parent_path(name) == parent_path:
                leaf = parts[-1]
                if leaf not in child_desired:
                    child_desired.append(leaf)
        if not child_desired:
            return
        try:
            children = list(parent_node.children())
        except Exception:
            return
        group_indices = []
        for index, child in enumerate(children):
            try:
                child.children()
                is_group = True
            except Exception:
                is_group = False
            try:
                if is_group and child.name() in child_desired:
                    group_indices.append(index)
            except Exception:
                _om_record_ignored_exception(__name__, 1637)
        if parent_path == "":
            current_names = []
            for child in children:
                try:
                    child.children()
                    is_group = True
                except Exception:
                    is_group = False
                if not is_group:
                    continue
                try:
                    name = child.name()
                except Exception:
                    name = ""
                if name in child_desired:
                    current_names.append(name)
            if current_names == child_desired:
                for name in child_desired:
                    group = self.ensure_direct_group(parent_node, name)
                    child_path = self.child_free_group_path(parent_path, name)
                    self.reorder_free_group_children(group, child_path, desired)
                return
        insert_index = min(group_indices) if group_indices else len(children)
        for name in child_desired:
            group = self.ensure_direct_group(parent_node, name)
            try:
                children = list(parent_node.children())
                current_index = children.index(group)
            except Exception:
                _om_record_ignored_exception(__name__, 1667); continue
            if current_index != insert_index:
                try:
                    clone = group.clone()
                    parent_node.insertChildNode(insert_index, clone)
                    parent_node.removeChildNode(group)
                    group = clone
                except Exception as exc:
                    QgsMessageLog.logMessage(f"自由式グループ並び替えエラー: {name}: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
                    continue
            insert_index += 1
            child_path = self.child_free_group_path(parent_path, name)
            self.reorder_free_group_children(group, child_path, desired)

    def reorder_free_group_direct_layers(self, group):
        try:
            children = list(group.children())
        except Exception:
            return 0
        moved = 0
        for child in list(children):
            try:
                child_layer = child.layer()
            except Exception:
                child_layer = None
            if child_layer:
                continue
            moved += self.reorder_free_group_direct_layers(child)
        try:
            children = list(group.children())
        except Exception:
            return moved
        layer_nodes = []
        first_group_index = None
        for index, child in enumerate(children):
            try:
                child_layer = child.layer()
            except Exception:
                child_layer = None
            if child_layer:
                try:
                    if self.layer_inspection_type(child_layer) == INSPECTION_TYPE_FREE:
                        layer_nodes.append(child)
                except Exception:
                    _om_record_ignored_exception(__name__, 1711)
                continue
            if first_group_index is None:
                first_group_index = index
        if first_group_index is None:
            return moved
        insert_index = first_group_index
        for node in layer_nodes:
            try:
                children = list(group.children())
                current_index = children.index(node)
            except Exception:
                _om_record_ignored_exception(__name__, 1723); continue
            if current_index < insert_index:
                insert_index += 1
                continue
            try:
                clone = node.clone()
                group.insertChildNode(insert_index, clone)
                group.removeChildNode(node)
                moved += 1
                insert_index += 1
            except Exception as exc:
                QgsMessageLog.logMessage(f"自由グループ内レイヤ順番復元エラー: {exc}", "OrthoManager", Qgis.MessageLevel.Warning)
        return moved

    def handle_layer_button_drop(self, source_name, target_source, menu_pos, menu=None):
        if not target_source or source_name == target_source:
            self.refresh_context_menu(menu, menu_pos)
            return
        layer = self.layer_by_source(source_name)
        if not layer:
            self.refresh_context_menu(menu, menu_pos)
            return
        if self.layer_inspection_type(layer) == INSPECTION_TYPE_FREE:
            if self.is_free_root_gap_drop_target(target_source):
                index = self.index_from_free_root_gap_drop_target(target_source)
                self.set_layer_group_name(layer, "")
                self.active_free_group_name = ""
                if self.place_layer_at_free_root_index(layer, index):
                    self.refresh_counts()
                    self.set_status(tr_text("✅ レイヤ移動: 検査直下の隙間"))
                self.refresh_context_menu(menu, menu_pos)
                return
            if self.is_free_root_before_group_drop_target(target_source):
                group_name = self.group_name_from_root_before_drop_target(target_source)
                self.set_layer_group_name(layer, "")
                self.active_free_group_name = ""
                if self.place_layer_before_free_root_group(layer, group_name):
                    self.refresh_counts()
                    self.set_status(tr_text(f"✅ レイヤ移動: {self.free_group_title(group_name)} の上（検査直下）"))
                self.refresh_context_menu(menu, menu_pos)
                return
            if self.is_free_root_after_group_drop_target(target_source):
                group_name = self.group_name_from_root_after_drop_target(target_source)
                self.set_layer_group_name(layer, "")
                self.active_free_group_name = ""
                if self.place_layer_after_free_root_group(layer, group_name):
                    self.refresh_counts()
                    self.set_status(tr_text(f"✅ レイヤ移動: {self.free_group_title(group_name)} の下（検査直下）"))
                self.refresh_context_menu(menu, menu_pos)
                return
            if self.is_free_group_bottom_drop_target(target_source):
                group_name = self.group_name_from_drop_target(target_source)
                self.set_layer_group_name(layer, group_name)
                self.active_free_group_name = group_name
                if self.place_layer_at_group_bottom(layer, self.ensure_free_group(group_name)):
                    self.refresh_counts()
                    self.set_status(tr_text(f"✅ レイヤ移動: {self.free_group_title(group_name)} の一番下"))
                self.refresh_context_menu(menu, menu_pos)
                return
            after_target = self.is_after_drop_target(target_source)
            if after_target:
                target_source = self.source_from_after_drop_target(target_source)
                if source_name == target_source:
                    self.refresh_context_menu(menu, menu_pos)
                    return
            target_layer = self.layer_by_source(target_source)
            if not target_layer:
                self.refresh_context_menu(menu, menu_pos)
                return
            if self.layer_inspection_type(target_layer) != INSPECTION_TYPE_FREE:
                QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("自由式検査レイヤは自由式検査グループ内だけで移動できます。"))
                self.refresh_context_menu(menu, menu_pos)
                return
            group_name = target_layer.customProperty(INSPECTION_PROP_PREFIX + "group_name", "")
            self.set_layer_group_name(layer, group_name)
            placed = self.place_layer_after(layer, target_layer) if after_target else self.place_layer_before(layer, target_layer)
            if placed:
                self.refresh_counts()
                self.set_status(tr_text(f"✅ レイヤ並び替え: {self.display_layer_name(layer)}"))
            self.refresh_context_menu(menu, menu_pos)
            return
        source_round = int(layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        if self.is_round_bottom_drop_target(target_source):
            target_round = self.round_no_from_drop_target(target_source)
            if target_round is None:
                self.refresh_context_menu(menu, menu_pos)
                return
            if source_round != target_round:
                if not self.is_manual_layer(layer):
                    QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("標準検査レイヤは検査回をまたいで移動できません。"))
                    self.refresh_context_menu(menu, menu_pos)
                    return
                self.set_layer_round(layer, target_round)
            if self.place_layer_at_round_bottom(layer, target_round):
                self.refresh_counts()
                self.set_status(tr_text(f"✅ レイヤ移動: {self.round_title(target_round)} の一番下"))
            self.refresh_context_menu(menu, menu_pos)
            return
        after_target = self.is_after_drop_target(target_source)
        if after_target:
            target_source = self.source_from_after_drop_target(target_source)
            if source_name == target_source:
                self.refresh_context_menu(menu, menu_pos)
                return
        target_layer = self.layer_by_source(target_source)
        if not layer or not target_layer:
            self.refresh_context_menu(menu, menu_pos)
            return
        if self.layer_inspection_type(target_layer) != INSPECTION_TYPE_ORTHO:
            QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("オルソ検査レイヤはオルソ検査グループ内だけで移動できます。"))
            self.refresh_context_menu(menu, menu_pos)
            return
        target_round = int(target_layer.customProperty(INSPECTION_PROP_PREFIX + "round_no", 0) or 0)
        if source_round != target_round:
            if not self.is_manual_layer(layer):
                QMessageBox.information(self, tr_text("レイヤ移動"), tr_text("標準検査レイヤは検査回をまたいで移動できません。"))
                self.refresh_context_menu(menu, menu_pos)
                return
            self.set_layer_round(layer, target_round)
        placed = self.place_layer_after(layer, target_layer) if after_target else self.place_layer_before(layer, target_layer)
        if placed:
            self.refresh_counts()
            self.set_status(tr_text(f"✅ レイヤ並び替え: {self.display_layer_name(layer)}"))
        self.refresh_context_menu(menu, menu_pos)

    def set_continuous_capture(self, enabled):
        self.continuous_capture_enabled = enabled

    def set_capture_shape(self, shape):
        self.finish_edit_for_mode_switch()
        self.active_capture_shape = shape
        labels = {
            "polygon": "多角形",
            "fixed_angle_90": "直角多角",
            "rectangle": "長方形",
            "ellipse": "楕円",
            "circle": "正円",
        }
        self.set_status(tr_text(f"作成形状: {labels.get(shape, shape)}"))

    def toggle_round_menu(self, round_no, global_pos):
        self.round_menu_expanded[round_no] = not self.round_menu_expanded.get(round_no, True)
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def toggle_free_group_menu(self, group_name, global_pos):
        self.free_group_menu_expanded[group_name] = not self.free_group_menu_expanded.get(group_name, True)
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))

    def show_main_menu(self, global_pos):
        self.finish_edit_for_mode_switch()
        if self.operation_mode == "restore":
            self.clear_trash_selection()
            self.set_trash_layers_visible(False)
        self.operation_mode = "pan"
        QTimer.singleShot(0, lambda: self.show_context_menu(global_pos))
