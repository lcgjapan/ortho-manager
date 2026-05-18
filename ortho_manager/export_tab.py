import os
import shutil
import time
import concurrent.futures
import multiprocessing
import threading
import xml.etree.ElementTree as ET
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QLineEdit, QComboBox, 
    QCheckBox, QProgressBar, QScrollArea, QFrame, QRadioButton, QButtonGroup,
    QApplication, QSizePolicy, QProgressDialog
)
from qgis.PyQt.QtCore import Qt, QSize, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QColor, QKeySequence, QShortcut, QImage, QPainter
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsMessageLog, Qgis,
    QgsWkbTypes, QgsMapSettings, QgsMapRendererCustomPainterJob, QgsRectangle
)

try:
    from osgeo import gdal
    gdal.UseExceptions()
    GDAL_OK = True
except ImportError:
    GDAL_OK = False

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False


class ExportTabWidget(QWidget):
    progress_updated = pyqtSignal(int)

    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui
        self._export_busy_label = None
        self._export_busy_animation = None
        self._export_progress_dialog = None
        self._export_progress_started_at = 0.0
        self._export_progress_total = 0
        self._export_progress_success = 0
        self._export_progress_skip = 0
        self._export_progress_processed = 0
        self._export_cancel_requested = False
        self._export_cancel_event = None
        
        self.progress_updated.connect(self._update_progress)
        
        self._build_ui()
        
        # ESCキーでの選択解除ショートカット
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_esc.activated.connect(self._clear_selection)
        
        QgsProject.instance().layersAdded.connect(self._refresh_layer_combo)
        QgsProject.instance().layersRemoved.connect(self._refresh_layer_combo)

    def _btn_style(self, color):
        return f"QPushButton{{background:{color};color:white;border:none;border-radius:4px;padding:5px;font-size:11px;}}QPushButton:hover{{background:{color}CC;}}"

    def _btn_style_big(self, color):
        return f"QPushButton{{background:{color};color:white;border:none;border-radius:5px;padding:7px;font-size:12px;font-weight:bold;}}QPushButton:hover{{background:{color}CC;}}"

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # スクロールエリアの作成
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_widget = QWidget()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        layout = QVBoxLayout(content_widget)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        # --- 1. 入力データ設定 ---
        grp_in = QGroupBox("1. 入力データ設定")
        gl_in = QVBoxLayout(grp_in)
        gl_in.setSpacing(4)
        gl_in.setContentsMargins(6, 12, 6, 6)

        lbl_info = QLabel("ℹ 出力対象はレイヤパネル表示順（ON）の全ラスタ")
        lbl_info.setStyleSheet("color: #2980b9; font-weight: bold; font-size:11px;")
        lbl_info.setWordWrap(True)
        gl_in.addWidget(lbl_info)

        self.chk_include_vector = QCheckBox("表示中のベクタデータも画像に焼き付ける")
        self.chk_include_vector.setChecked(False)
        gl_in.addWidget(self.chk_include_vector)
        layout.addWidget(grp_in)

        # --- 2. 出力範囲（図郭）設定 ---
        grp_bound = QGroupBox("2. 出力範囲（図郭）設定")
        gl_bound = QVBoxLayout(grp_bound)
        gl_bound.setSpacing(4)
        gl_bound.setContentsMargins(6, 12, 6, 6)

        row_zuk = QHBoxLayout()
        lbl_zukaku = QLabel("図郭レイヤ：")
        gl_bound.addWidget(lbl_zukaku)
        self.zukaku_combo = QComboBox()
        self.zukaku_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        gl_bound.addWidget(self.zukaku_combo)

        btn_select_map = QPushButton("🖱 マップから選択 (ESCで解除)")
        btn_select_map.setStyleSheet(self._btn_style("#f39c12"))
        btn_select_map.clicked.connect(self._activate_select_tool)
        gl_bound.addWidget(btn_select_map)

        row_id = QHBoxLayout()
        lbl_id = QLabel("図郭ID：")
        lbl_id.setFixedWidth(50)
        row_id.addWidget(lbl_id)
        self.id_field_combo = QComboBox()
        self.id_field_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_id.addWidget(self.id_field_combo)
        gl_bound.addLayout(row_id)
        
        self.zukaku_combo.currentIndexChanged.connect(self._refresh_field_combo)
        self._refresh_layer_combo()
        layout.addWidget(grp_bound)

        # --- 3. 出力設定 ---
        grp_out = QGroupBox("3. 出力設定")
        gl_out = QVBoxLayout(grp_out)
        gl_out.setSpacing(4)
        gl_out.setContentsMargins(6, 12, 6, 6)

        row_mode = QHBoxLayout()
        self.rb_mode_split = QRadioButton("図郭ごとに出力")
        self.rb_mode_single = QRadioButton("1ファイルで出力")
        self.rb_mode_single.setToolTip("選択図郭がある場合は選択図郭、ない場合は全図郭の外接矩形を1ファイルで出力します")
        self.rb_mode_split.setChecked(True)
        row_mode.addWidget(self.rb_mode_split)
        row_mode.addWidget(self.rb_mode_single)
        gl_out.addLayout(row_mode)

        row_single_name = QHBoxLayout()
        lbl_sname = QLabel("名前：")
        lbl_sname.setFixedWidth(35)
        row_single_name.addWidget(lbl_sname)
        self.single_name_edit = QLineEdit()
        self.single_name_edit.setText("merged_ortho")
        self.single_name_edit.setEnabled(False)
        self.rb_mode_single.toggled.connect(self.single_name_edit.setEnabled)
        row_single_name.addWidget(self.single_name_edit)
        gl_out.addLayout(row_single_name)

        lbl_outdir = QLabel("出力フォルダ：")
        gl_out.addWidget(lbl_outdir)
        row_outdir = QHBoxLayout()
        self.export_out_edit = QLineEdit()
        btn_out = QPushButton("...")
        btn_out.setFixedWidth(30)
        btn_out.clicked.connect(self._browse_export_output)
        row_outdir.addWidget(self.export_out_edit)
        row_outdir.addWidget(btn_out)
        gl_out.addLayout(row_outdir)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel("形式：")
        lbl_fmt.setFixedWidth(35)
        row_fmt.addWidget(lbl_fmt)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["TIF＋TFW", "GeoTIFF", "TFWのみ", "JPG＋JGW", "ECW", "PDF"])
        row_fmt.addWidget(self.format_combo)
        gl_out.addLayout(row_fmt)

        row_res = QHBoxLayout()
        lbl_res = QLabel("解像度(m)：")
        row_res.addWidget(lbl_res)
        
        row_res.addStretch()
        
        lbl_res_x = QLabel("X")
        row_res.addWidget(lbl_res_x)
        self.res_x_edit = QLineEdit()
        self.res_x_edit.setPlaceholderText("元画像通り")
        self.res_x_edit.setMaximumWidth(70) 
        row_res.addWidget(self.res_x_edit)
        
        lbl_res_y = QLabel("Y")
        row_res.addWidget(lbl_res_y)
        self.res_y_edit = QLineEdit()
        self.res_y_edit.setPlaceholderText("元画像通り")
        self.res_y_edit.setMaximumWidth(70)
        row_res.addWidget(self.res_y_edit)
        gl_out.addLayout(row_res)

        row_depth = QHBoxLayout()
        lbl_depth = QLabel("ビット：")
        lbl_depth.setFixedWidth(40)
        row_depth.addWidget(lbl_depth)
        self.depth_combo = QComboBox()
        self.depth_combo.addItems([
            "24bit フルカラー (RGB: 透過なし)",
            "32bit フルカラー (RGBA: 透過あり)",
            "8bit (Byte)",
            "16bit 無符号 (UInt16)",
            "16bit 有符号 (Int16)",
            "32bit 浮動小数点 (Float32)"
        ])
        row_depth.addWidget(self.depth_combo)
        gl_out.addLayout(row_depth)

        row_alg = QHBoxLayout()
        lbl_alg = QLabel("補間：")
        lbl_alg.setFixedWidth(35)
        row_alg.addWidget(lbl_alg)
        self.resample_combo = QComboBox()
        self.resample_combo.addItems(["最近傍法 (Nearest)", "キュービック (Cubic)", "バイリニア (Bilinear)"])
        row_alg.addWidget(self.resample_combo)
        gl_out.addLayout(row_alg)
        layout.addWidget(grp_out)

        # --- 4. 高度なオプション ---
        grp_opt = QGroupBox("4. 高度なオプション")
        gl_opt = QVBoxLayout(grp_opt)
        gl_opt.setSpacing(4)
        gl_opt.setContentsMargins(6, 12, 6, 6)

        self.chk_skip_empty_vrt = QCheckBox("ラスタ実データがない図郭はスキップ")
        self.chk_skip_empty_vrt.setToolTip("出力対象ラスタに実データがない図郭を出力せずにスキップします")
        self.chk_skip_empty_vrt.setChecked(True)
        gl_opt.addWidget(self.chk_skip_empty_vrt)

        row_skip = QHBoxLayout()
        self.chk_skip_solid = QCheckBox("図郭内に同色の場合はスキップ：")
        self.chk_skip_solid.setChecked(True)
        self.skip_color_combo = QComboBox()
        self.skip_color_combo.addItems(["白", "黒", "透明"])
        row_skip.addWidget(self.chk_skip_solid)
        row_skip.addWidget(self.skip_color_combo)
        gl_opt.addLayout(row_skip)

        row_bg = QHBoxLayout()
        self.chk_background_process = QCheckBox("背景色処理")
        self.chk_background_process.setChecked(True)
        self.chk_background_process.setToolTip("ON: 選択した背景色を反映します / OFF: 背景処理を行いません")
        row_bg.addWidget(self.chk_background_process)
        lbl_bg = QLabel("背景色：")
        lbl_bg.setFixedWidth(50)
        row_bg.addWidget(lbl_bg)
        self.bg_color_combo = QComboBox()
        self.bg_color_combo.addItems(["白", "黒", "透明", "プロジェクト色"])
        row_bg.addWidget(self.bg_color_combo)
        gl_opt.addLayout(row_bg)

        row_mode = QHBoxLayout()
        lbl_mode = QLabel("モード：")
        lbl_mode.setFixedWidth(50)
        row_mode.addWidget(lbl_mode)
        self.export_mode_combo = QComboBox()
        self.export_mode_combo.addItems([
            "標準高速",
            "標準 2.18",
            "診断: Warp直接出力",
            "診断: Warp直接＋後処理",
            "診断: 図郭形状そのまま",
            "診断: 矩形最速",
            "診断: 選択VRT直接",
        ])
        row_mode.addWidget(self.export_mode_combo)
        gl_opt.addLayout(row_mode)

        row_workers = QHBoxLayout()
        lbl_workers = QLabel("並列数：")
        lbl_workers.setFixedWidth(50)
        row_workers.addWidget(lbl_workers)
        self.worker_count_combo = QComboBox()
        self.worker_count_combo.addItems(["1", "2", "4", "6", "8", "12", "16"])
        self.worker_count_combo.setCurrentText("16")
        row_workers.addWidget(self.worker_count_combo)
        gl_opt.addLayout(row_workers)
        layout.addWidget(grp_opt)

        # --- 実行ボタン ---
        row_run = QHBoxLayout()
        btn_log_mark = QPushButton("ログ開始")
        btn_log_mark.setToolTip("次のテストログの開始位置をQGISログに記録します")
        btn_log_mark.clicked.connect(self._mark_log_start)
        btn_log_mark.setStyleSheet(self._btn_style("#607d8b"))
        row_run.addWidget(btn_log_mark)

        btn_export = QPushButton("🚀 書き出し実行")
        btn_export.clicked.connect(self._run_export)
        btn_export.setStyleSheet(self._btn_style_big("#c0392b"))
        row_run.addWidget(btn_export, 1)
        layout.addLayout(row_run)

        self.export_progress_bar = QProgressBar()
        self.export_progress_bar.setValue(0)
        self.export_progress_bar.setVisible(False)
        self.export_progress_bar.setFixedHeight(12)
        layout.addWidget(self.export_progress_bar)
        
        layout.addStretch()

    # --- UI操作メソッド ---
    def _browse_export_output(self):
        folder = QFileDialog.getExistingDirectory(self, "出力フォルダを選択")
        if folder:
            self.export_out_edit.setText(folder)

    def _refresh_layer_combo(self, *args):
        current_layer_id = self.zukaku_combo.currentData()
        self.zukaku_combo.blockSignals(True)
        self.zukaku_combo.clear()
        
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry:
                if "_overlay" not in lyr.name():
                    self.zukaku_combo.addItem(lyr.name(), lyr.id())
                    self.zukaku_combo.setItemData(self.zukaku_combo.count() - 1, lyr.name(), Qt.ItemDataRole.ToolTipRole)
                    
        if current_layer_id:
            index = self.zukaku_combo.findData(current_layer_id)
            if index >= 0:
                self.zukaku_combo.setCurrentIndex(index)
                
        self.zukaku_combo.blockSignals(False)
        self._refresh_field_combo()

    def _refresh_field_combo(self):
        self.id_field_combo.clear()
        layer_id = self.zukaku_combo.currentData()
        if not layer_id: return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            for field in layer.fields():
                self.id_field_combo.addItem(field.name())

    def _activate_select_tool(self):
        layer_id = self.zukaku_combo.currentData()
        if not layer_id:
            QMessageBox.warning(self, "警告", "図郭レイヤがありません")
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            self.main_ui.iface.setActiveLayer(layer)
            try:
                self.main_ui.iface.actionSelect().trigger()
                self.main_ui._set_status("🖱 マップ上で出力対象の図郭をクリックしてください（ESCで解除）")
            except: pass

    def _clear_selection(self):
        layer_id = self.zukaku_combo.currentData()
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                layer.removeSelection()
                self.main_ui._set_status("ℹ 図郭の選択を解除しました")

    def _mark_log_start(self):
        mark_time = time.strftime("%Y-%m-%d %H:%M:%S")
        run_id = time.strftime("%Y%m%d_%H%M%S")
        QgsMessageLog.logMessage(
            f"===== OrthoManager LOG START {mark_time} run={run_id} =====",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        self.main_ui._set_status("ログ開始位置を記録しました")

    def _show_export_busy_message(self):
        self._hide_export_busy_message()
        try:
            canvas = self.main_ui.iface.mapCanvas()
            parent = canvas.viewport() if hasattr(canvas, "viewport") else canvas
        except Exception:
            parent = self.window()

        label = QLabel("書き出し中です...\nQGISが一時的に反応しにくくなる場合があります", parent)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            "QLabel {"
            "background: rgba(255, 235, 59, 230);"
            "color: #3a2a00;"
            "border: 2px solid rgba(190, 150, 0, 220);"
            "border-radius: 8px;"
            "padding: 14px 22px;"
            "font-size: 15px;"
            "font-weight: bold;"
            "}"
        )
        label.adjustSize()
        label.resize(max(label.width(), 300), max(label.height(), 78))
        label.move((parent.width() - label.width()) // 2, (parent.height() - label.height()) // 2)

        self._export_busy_label = label
        self._export_busy_animation = None
        label.show()
        label.raise_()
        label.repaint()
        parent.repaint()
        for _ in range(3):
            QApplication.processEvents()

    def _hide_export_busy_message(self):
        if self._export_busy_animation:
            try:
                self._export_busy_animation.stop()
            except Exception:
                pass
            self._export_busy_animation = None
        if self._export_busy_label:
            try:
                self._export_busy_label.hide()
                self._export_busy_label.deleteLater()
            except Exception:
                pass
            self._export_busy_label = None
        QApplication.processEvents()

    def _format_export_time(self, seconds):
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}時間 {m}分"
        if m:
            return f"{m}分 {s}秒"
        return f"{s}秒"

    def _show_export_progress_dialog(self, total):
        self._hide_export_progress_dialog()
        self._export_progress_total = max(1, int(total or 1))
        self._export_progress_success = 0
        self._export_progress_skip = 0
        self._export_progress_processed = 0
        self._export_progress_started_at = time.time()
        self._export_cancel_requested = False
        dlg = QProgressDialog("書き出し準備中...", "キャンセル", 0, self._export_progress_total, self)
        dlg.setWindowTitle("書き出し中")
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(self._confirm_export_cancel)
        self._export_progress_dialog = dlg
        self._update_export_progress_dialog(0)
        dlg.show()
        dlg.raise_()
        for _ in range(3):
            QApplication.processEvents()

    def _hide_export_progress_dialog(self):
        if self._export_progress_dialog:
            try:
                self._export_progress_dialog.canceled.disconnect(self._confirm_export_cancel)
            except Exception:
                pass
            try:
                self._export_progress_dialog.hide()
                self._export_progress_dialog.deleteLater()
            except Exception:
                pass
            self._export_progress_dialog = None
        QApplication.processEvents()

    def _confirm_export_cancel(self):
        if self._export_cancel_requested:
            self._show_export_cancel_processing()
            return
        reply = QMessageBox.question(
            self,
            "キャンセル確認",
            "本当に書き出しをキャンセルしてもよろしいでしょうか？\n\n"
            "はいを押すと実行中の処理を停止し、未完成ファイルを削除します。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._request_export_cancel()
        else:
            if self._export_progress_dialog:
                self._export_progress_dialog.show()
                self._export_progress_dialog.raise_()
                self._update_export_progress_dialog(self._export_progress_processed)

    def _request_export_cancel(self):
        self._export_cancel_requested = True
        if self._export_cancel_event:
            self._export_cancel_event.set()
        self._show_export_cancel_processing()
        self.main_ui._set_status("キャンセル要求を受け付けました。実行中の処理を停止しています...")
        QApplication.processEvents()
        QTimer.singleShot(0, self._show_export_cancel_processing)
        QTimer.singleShot(200, self._show_export_cancel_processing)

    def _show_export_cancel_processing(self):
        if not self._export_progress_dialog:
            return
        try:
            self._export_progress_dialog.setWindowTitle("キャンセル処理中")
            self._export_progress_dialog.setCancelButton(None)
            self._export_progress_dialog.setRange(0, 0)
            self._export_progress_dialog.setLabelText(
                "キャンセル処理中...\n実行中の処理を停止し、未完成ファイルを削除しています。"
            )
            self._export_progress_dialog.show()
            self._export_progress_dialog.raise_()
        except Exception:
            pass

    def _set_export_progress_total(self, total):
        self._export_progress_total = max(1, int(total or 1))
        if self._export_progress_dialog:
            self._update_export_progress_dialog(self._export_progress_processed)

    def _update_export_progress_dialog(self, processed):
        if not self._export_progress_dialog:
            return
        total_tasks = max(1, self._export_progress_total)
        processed = min(max(0, int(processed)), total_tasks)
        self._export_progress_processed = processed
        output_total = max(0, total_tasks - self._export_progress_skip)
        progress_max = max(1, output_total)
        progress_value = min(self._export_progress_success, progress_max)
        elapsed = time.time() - self._export_progress_started_at if self._export_progress_started_at else 0.0
        if self._export_cancel_requested:
            text = (
                "キャンセル処理中...\n"
                f"出力済み: {self._export_progress_success}/{output_total} 件\n"
                f"スキップ等: {self._export_progress_skip} 件\n"
                "実行中の処理を停止し、未完成ファイルを削除しています。"
            )
        elif output_total == 0 and processed >= total_tasks:
            text = (
                "書き出し完了処理中...\n"
                "出力対象: 0 件（スキップのみ）\n"
                f"スキップ等: {self._export_progress_skip} 件\n"
                f"経過: {self._format_export_time(elapsed)}"
            )
            progress_value = 1
        elif self._export_progress_success > 0 and self._export_progress_success < output_total:
            remaining = elapsed / self._export_progress_success * (output_total - self._export_progress_success)
            text = (
                "書き出し中...\n"
                f"出力済み: {self._export_progress_success}/{output_total} 件\n"
                f"スキップ等: {self._export_progress_skip} 件\n"
                f"経過: {self._format_export_time(elapsed)}\n"
                f"残り: 約 {self._format_export_time(remaining)}"
            )
        elif output_total > 0 and self._export_progress_success >= output_total:
            text = (
                "書き出し完了処理中...\n"
                f"出力済み: {self._export_progress_success}/{output_total} 件\n"
                f"スキップ等: {self._export_progress_skip} 件\n"
                f"経過: {self._format_export_time(elapsed)}"
            )
        else:
            text = (
                "書き出し中...\n"
                f"出力済み: {self._export_progress_success}/{output_total} 件\n"
                f"スキップ等: {self._export_progress_skip} 件\n"
                "残り: 計算中"
            )
        self._export_progress_dialog.setMaximum(progress_max)
        self._export_progress_dialog.setLabelText(text)
        self._export_progress_dialog.setValue(progress_value)
        QApplication.processEvents()

    # --- エクスポート処理コア ---
    def _get_input_layers(self):
        input_layers = []
        root = QgsProject.instance().layerTreeRoot()
        
        for node in root.findLayers():
            try:
                visible = node.itemVisibilityCheckedRecursive()
            except Exception:
                visible = node.isVisible()
            if visible:
                lyr = node.layer()
                if isinstance(lyr, QgsRasterLayer):
                    src = lyr.source()
                    if src and os.path.exists(src):
                        input_layers.append(lyr)
                        
        input_layers.reverse()
        return input_layers

    def _get_bg_color_value(self):
        val = self.bg_color_combo.currentText()
        if val == "透明": return (0, 0, 0, 0)
        if val == "白": return (255, 255, 255, 255)
        if val == "黒": return (0, 0, 0, 255)
        if "プロジェクト" in val:
            try:
                canvas = self.main_ui.iface.mapCanvas() if self.main_ui and self.main_ui.iface else None
                color = canvas.canvasColor() if canvas and hasattr(canvas, "canvasColor") else QgsProject.instance().backgroundColor()
                return (color.red(), color.green(), color.blue(), 255)
            except Exception:
                return (255, 255, 255, 255)
        return (255, 255, 255, 255)

    def _render_vector_overlay(self, img_path, extent):
        """ QGISのレンダリングエンジンを利用して、出力画像にベクタを焼き込む """
        import numpy as np
        from osgeo import gdal
        
        vector_layers = []
        root = QgsProject.instance().layerTreeRoot()
        for node in root.findLayers():
            if node.isVisible():
                lyr = node.layer()
                if isinstance(lyr, QgsVectorLayer) and "_overlay" not in lyr.name():
                    vector_layers.append(lyr)
                    
        if not vector_layers: return

        ds = gdal.Open(img_path, gdal.GA_Update)
        if not ds: return
        
        x_size = ds.RasterXSize
        y_size = ds.RasterYSize
        b_count = ds.RasterCount
        gt = ds.GetGeoTransform()
        if gt is None:
            ds = None
            return
            
        settings = self.main_ui.iface.mapCanvas().mapSettings()
        settings.setLayers(vector_layers)
        settings.setBackgroundColor(QColor(Qt.GlobalColor.transparent))
        
        chunk_size = 2048

        for y in range(0, y_size, chunk_size):
            ys = min(chunk_size, y_size - y)
            for x in range(0, x_size, chunk_size):
                xs = min(chunk_size, x_size - x)
                
                minx = gt[0] + x * gt[1] + y * gt[2]
                maxy = gt[3] + x * gt[4] + y * gt[5]
                maxx = gt[0] + (x + xs) * gt[1] + (y + ys) * gt[2]
                miny = gt[3] + (x + xs) * gt[4] + (y + ys) * gt[5]
                
                chunk_extent = QgsRectangle(min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))
                
                overlay_img = QImage(QSize(xs, ys), QImage.Format.Format_RGBA8888)
                overlay_img.fill(Qt.GlobalColor.transparent)
                
                settings.setExtent(chunk_extent)
                settings.setOutputSize(overlay_img.size())
                
                painter = QPainter(overlay_img)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                job = QgsMapRendererCustomPainterJob(settings, painter)
                job.renderSynchronously()
                painter.end()
                
                ptr = overlay_img.constBits()
                try:
                    ptr.setsize(overlay_img.sizeInBytes())
                except:
                    pass
                arr_rgba = np.array(ptr).reshape((ys, xs, 4))
                
                if np.max(arr_rgba[:, :, 3]) == 0:
                    continue
                    
                alpha_norm = arr_rgba[:, :, 3] / 255.0
                
                for b in range(1, b_count + 1):
                    band = ds.GetRasterBand(b)
                    base_arr = band.ReadAsArray(x, y, xs, ys)
                    if base_arr is None: continue
                    
                    if b == 1:
                        color_arr = arr_rgba[:, :, 0]
                    elif b == 2:
                        color_arr = arr_rgba[:, :, 1]
                    elif b == 3:
                        color_arr = arr_rgba[:, :, 2]
                    elif b == 4:
                        color_arr = arr_rgba[:, :, 3]
                        new_arr = np.clip(base_arr + color_arr, 0, 255).astype(np.uint8)
                        band.WriteArray(new_arr, x, y)
                        continue
                    else:
                        continue
                        
                    dt = band.DataType
                    if dt == gdal.GDT_Byte:
                        new_arr = base_arr * (1.0 - alpha_norm) + color_arr * alpha_norm
                        band.WriteArray(np.clip(new_arr, 0, 255).astype(np.uint8), x, y)
                    elif dt == gdal.GDT_UInt16:
                        color_arr_16 = color_arr.astype(np.float32) * 257.0
                        new_arr = base_arr * (1.0 - alpha_norm) + color_arr_16 * alpha_norm
                        band.WriteArray(np.clip(new_arr, 0, 65535).astype(np.uint16), x, y)
                    elif dt == gdal.GDT_Int16:
                        color_arr_16 = color_arr.astype(np.float32) * 257.0
                        new_arr = base_arr * (1.0 - alpha_norm) + color_arr_16 * alpha_norm
                        band.WriteArray(np.clip(new_arr, -32768, 32767).astype(np.int16), x, y)
                    elif dt == gdal.GDT_Float32:
                        color_arr_f = color_arr.astype(np.float32) / 255.0
                        new_arr = base_arr * (1.0 - alpha_norm) + color_arr_f * alpha_norm
                        band.WriteArray(new_arr.astype(np.float32), x, y)
        
        ds.FlushCache()
        ds = None

    @staticmethod
    def _static_format_worldfile_coord(val):
        v_float = float(val)
        if round(v_float, 6) == round(v_float, 10):
            return f"{v_float:.6f}"
        return f"{v_float:.13f}"

    @staticmethod
    def _static_write_world_file(raster_path, ext, gt):
        center_x = gt[0] + (gt[1] / 2.0)
        center_y = gt[3] + (gt[5] / 2.0)
        lines = [
            ExportTabWidget._static_format_worldfile_coord(gt[1]),
            ExportTabWidget._static_format_worldfile_coord(gt[4]),
            ExportTabWidget._static_format_worldfile_coord(gt[2]),
            ExportTabWidget._static_format_worldfile_coord(gt[5]),
            ExportTabWidget._static_format_worldfile_coord(center_x),
            ExportTabWidget._static_format_worldfile_coord(center_y)
        ]
        wf_path = os.path.splitext(raster_path)[0] + ext
        with open(wf_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    @staticmethod
    def _static_check_skip_solid_image(img_path, color_str):
        if not NUMPY_OK: return False
        from osgeo import gdal
        import numpy as np
        
        ds = gdal.Open(img_path)
        if not ds: return False
        
        skip = False
        x_size = ds.RasterXSize
        y_size = ds.RasterYSize
        b_count = ds.RasterCount
        chunk_size = 2048
        
        if color_str == "透明":
            is_transparent = True
            alpha_band = None
            if b_count >= 4:
                alpha_band = ds.GetRasterBand(4)
            elif b_count > 1 and ds.GetRasterBand(b_count).GetColorInterpretation() == gdal.GCI_AlphaBand:
                alpha_band = ds.GetRasterBand(b_count)
            
            for y in range(0, y_size, chunk_size):
                if not is_transparent: break
                ys = min(chunk_size, y_size - y)
                for x in range(0, x_size, chunk_size):
                    xs = min(chunk_size, x_size - x)
                    
                    if alpha_band:
                        alpha = alpha_band.ReadAsArray(x, y, xs, ys)
                        if alpha is not None and np.any(alpha > 0):
                            is_transparent = False
                            break
                    else:
                        band1 = ds.GetRasterBand(1)
                        nodata = band1.GetNoDataValue()
                        if nodata is not None:
                            arr = band1.ReadAsArray(x, y, xs, ys)
                            if arr is not None and np.any(arr != nodata):
                                is_transparent = False
                                break
                        else:
                            is_transparent = False
                            break
            if is_transparent:
                skip = True
                
        else:
            is_solid = True
            bands_to_check = min(b_count, 3) 
            if bands_to_check == 0:
                is_solid = False
                
            target_vals = []
            for i in range(1, bands_to_check + 1):
                band = ds.GetRasterBand(i)
                tv = 0
                if color_str == "白":
                    dt = band.DataType
                    if dt == gdal.GDT_Byte: tv = 255
                    elif dt == gdal.GDT_UInt16: tv = 65535
                    elif dt == gdal.GDT_Int16: tv = 32767
                    else: tv = 255
                target_vals.append(tv)
                
            for y in range(0, y_size, chunk_size):
                if not is_solid: break
                ys = min(chunk_size, y_size - y)
                for x in range(0, x_size, chunk_size):
                    xs = min(chunk_size, x_size - x)
                    
                    for idx, i in enumerate(range(1, bands_to_check + 1)):
                        band = ds.GetRasterBand(i)
                        arr = band.ReadAsArray(x, y, xs, ys)
                        if arr is None:
                            is_solid = False
                            break
                            
                        if not np.all(arr == target_vals[idx]):
                            is_solid = False
                            break
                        arr = None 
                    if not is_solid: break
            
            if is_solid:
                skip = True

        band = None
        alpha_band = None
        band1 = None
        ds = None
        return skip

    @staticmethod
    def _static_cancel_requested(cancel_event):
        try:
            return bool(cancel_event and cancel_event.is_set())
        except Exception:
            return False

    @staticmethod
    def _static_gdal_cancel_callback(cancel_event):
        def _callback(complete, message, data):
            return 0 if ExportTabWidget._static_cancel_requested(cancel_event) else 1
        return _callback

    @staticmethod
    def _static_init_dest_value(bg_val, include_alpha=False):
        vals = [int(bg_val[0]), int(bg_val[1]), int(bg_val[2])]
        if include_alpha:
            vals.append(int(bg_val[3]))
        return ",".join(str(v) for v in vals)

    @staticmethod
    def _static_cleanup_export_outputs(out_path, gdal_fmt, format_val):
        candidates = {
            out_path,
            out_path + ".aux.xml",
            out_path + ".tmp.tif",
            out_path + ".tmp.tif.aux.xml",
            out_path + ".master.vrt",
            out_path + ".check.vrt",
            out_path + ".rgb_tmp.tif",
        }
        base, _ = os.path.splitext(out_path)
        if gdal_fmt == "GTiff" or format_val == "TIF＋TFW":
            candidates.add(base + ".tfw")
        if gdal_fmt == "JPEG" or format_val == "JPG＋JGW":
            candidates.add(base + ".jgw")
        failed = []
        for path in sorted(candidates):
            if not path or not os.path.exists(path):
                continue
            removed = False
            for _ in range(6):
                try:
                    os.remove(path)
                    removed = True
                    break
                except Exception:
                    time.sleep(0.15)
            if not removed and os.path.exists(path):
                failed.append(path)
        if failed:
            QgsMessageLog.logMessage(
                "キャンセル後に削除できなかった出力ファイルがあります: " + ", ".join(failed[:5]),
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        return failed

    @staticmethod
    def _static_fill_alpha_background(img_path, bg_val, cancel_event=None):
        if not NUMPY_OK or bg_val[3] == 0:
            return True
        from osgeo import gdal
        import numpy as np

        ds_update = gdal.Open(img_path, gdal.GA_Update)
        if not ds_update:
            return True
        try:
            x_size = ds_update.RasterXSize
            y_size = ds_update.RasterYSize
            b_count = ds_update.RasterCount
            alpha_idx = -1
            if b_count >= 4:
                alpha_idx = 4
            elif b_count > 1 and ds_update.GetRasterBand(b_count).GetColorInterpretation() == gdal.GCI_AlphaBand:
                alpha_idx = b_count
            if alpha_idx < 1:
                return True

            chunk_size = 2048
            for y in range(0, y_size, chunk_size):
                if ExportTabWidget._static_cancel_requested(cancel_event):
                    return False
                ys = min(chunk_size, y_size - y)
                for x in range(0, x_size, chunk_size):
                    if ExportTabWidget._static_cancel_requested(cancel_event):
                        return False
                    xs = min(chunk_size, x_size - x)
                    alpha_band = ds_update.GetRasterBand(alpha_idx)
                    alpha_arr = alpha_band.ReadAsArray(x, y, xs, ys)
                    if alpha_arr is None:
                        continue
                    mask = alpha_arr == 0
                    if not np.any(mask):
                        alpha_arr = None
                        alpha_band = None
                        continue
                    for b in range(1, alpha_idx):
                        band = ds_update.GetRasterBand(b)
                        arr = band.ReadAsArray(x, y, xs, ys)
                        if arr is not None:
                            color = bg_val[b - 1] if b - 1 < len(bg_val) else bg_val[0]
                            dt = band.DataType
                            if dt == gdal.GDT_UInt16:
                                color = int(color * 257)
                            elif dt == gdal.GDT_Int16:
                                color = int(color * 257) - 32768
                            elif dt == gdal.GDT_Float32:
                                color = float(color) / 255.0
                            arr[mask] = color
                            band.WriteArray(arr, x, y)
                        arr = None
                        band = None
                    alpha_arr[mask] = 255
                    alpha_band.WriteArray(alpha_arr, x, y)
                    alpha_arr = None
                    alpha_band = None
            ds_update.FlushCache()
            return True
        finally:
            ds_update = None

    @staticmethod
    def _static_force_rgb_output(img_path, cancel_event=None):
        from osgeo import gdal

        if ExportTabWidget._static_cancel_requested(cancel_event):
            return False
        ds = gdal.Open(img_path)
        if not ds:
            return True
        try:
            if ds.RasterCount < 4:
                return True
        finally:
            ds = None

        tmp_rgb_path = img_path + ".rgb_tmp.tif"
        try:
            translate_opts = gdal.TranslateOptions(
                format="GTiff",
                bandList=[1, 2, 3],
                creationOptions=["BIGTIFF=IF_SAFER", "PROFILE=BASELINE"],
                callback=ExportTabWidget._static_gdal_cancel_callback(cancel_event),
            )
            ds_out = gdal.Translate(tmp_rgb_path, img_path, options=translate_opts)
            if ExportTabWidget._static_cancel_requested(cancel_event):
                return False
            if ds_out:
                ds_out.FlushCache()
                ds_out = None
                os.replace(tmp_rgb_path, img_path)
            return True
        finally:
            if os.path.exists(tmp_rgb_path):
                try:
                    os.remove(tmp_rgb_path)
                except Exception:
                    pass

    @staticmethod
    def _gdal_process_worker(args):
        """ 戻り値は (成功可否: bool, 理由: str) """
        (master_vrt_path, check_master_vrt_path, out_path, bbox_coords, cutline_wkt, gdal_fmt, format_val, 
         res_x, res_y, resample_alg, bg_val, src_datatype, output_type, force_24bit, 
         need_empty_check, need_solid_check, color_str, crs_wkt, postprocess_background,
         warp_direct_output, background_control_enabled, cancel_event) = args

        if format_val == "TFWのみ":
            if ExportTabWidget._static_cancel_requested(cancel_event):
                return False, "キャンセル"
            gt = [bbox_coords[0], res_x, 0, bbox_coords[3], 0, -res_y]
            ExportTabWidget._static_write_world_file(out_path, ".tfw", gt)
            return True, "TFWのみの出力"

        from osgeo import gdal
        import numpy as np

        old_pam_enabled = gdal.GetConfigOption('GDAL_PAM_ENABLED')
        gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
        
        worker_master_vrt = out_path + ".master.vrt"
        worker_check_vrt = out_path + ".check.vrt"
        try:
            if ExportTabWidget._static_cancel_requested(cancel_event):
                return False, "キャンセル"
            shutil.copy2(master_vrt_path, worker_master_vrt)
            if check_master_vrt_path and check_master_vrt_path != master_vrt_path:
                shutil.copy2(check_master_vrt_path, worker_check_vrt)
            else:
                worker_check_vrt = worker_master_vrt
        except Exception as e:
            if old_pam_enabled is None:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', None)
            else:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', old_pam_enabled)
            return False, f"VRTコピーエラー: {e}"

        target_path = out_path if warp_direct_output else out_path + ".tmp.tif"
        
        try:
            if (need_empty_check or need_solid_check) and NUMPY_OK:
                translate_check_opts = gdal.TranslateOptions(
                    format="VRT", 
                    projWin=[bbox_coords[0], bbox_coords[3], bbox_coords[2], bbox_coords[1]]
                )
                ds_check = gdal.Translate("", worker_check_vrt, options=translate_check_opts)
                
                if ds_check:
                    x_size = ds_check.RasterXSize
                    y_size = ds_check.RasterYSize
                    b_count = ds_check.RasterCount
                    
                    has_alpha = False
                    alpha_band_idx = 0
                    if b_count >= 4:
                        has_alpha = True
                        alpha_band_idx = 4
                    elif b_count > 1 and ds_check.GetRasterBand(b_count).GetColorInterpretation() == gdal.GCI_AlphaBand:
                        has_alpha = True
                        alpha_band_idx = b_count

                    chunk_size = 2048
                    
                    if need_empty_check:
                        has_data = False
                        for y in range(0, y_size, chunk_size):
                            if ExportTabWidget._static_cancel_requested(cancel_event):
                                ds_check = None
                                return False, "キャンセル"
                            if has_data: break
                            ys = min(chunk_size, y_size - y)
                            for x in range(0, x_size, chunk_size):
                                if ExportTabWidget._static_cancel_requested(cancel_event):
                                    ds_check = None
                                    return False, "キャンセル"
                                xs = min(chunk_size, x_size - x)
                                
                                if has_alpha:
                                    alpha_arr = ds_check.GetRasterBand(alpha_band_idx).ReadAsArray(x, y, xs, ys)
                                    if alpha_arr is not None and np.any(alpha_arr > 0):
                                        has_data = True
                                        break
                                else:
                                    band1 = ds_check.GetRasterBand(1)
                                    arr1 = band1.ReadAsArray(x, y, xs, ys)
                                    nodata = band1.GetNoDataValue()
                                    if nodata is not None and arr1 is not None:
                                        if np.any(arr1 != nodata):
                                            has_data = True
                                            break
                                    else:
                                        has_data = True
                                        break
                                        
                        if not has_data:
                            ds_check = None
                            return False, "元データが存在しないためスキップ"
                            
                    if need_solid_check:
                        is_solid = True
                        
                        bands_to_check = min(b_count, 3)
                        if color_str == "透明":
                            bands_to_check = 0
                        elif bg_val[3] == 0 and b_count > 1 and has_alpha:
                            bands_to_check = b_count - 1
                            
                        target_vals = []
                        for i in range(1, bands_to_check + 1):
                            dt = ds_check.GetRasterBand(i).DataType
                            tv = 0
                            if color_str == "白":
                                if dt == gdal.GDT_Byte: tv = 255
                                elif dt == gdal.GDT_UInt16: tv = 65535
                                elif dt == gdal.GDT_Int16: tv = 32767
                                else: tv = 255
                            target_vals.append(tv)

                        for y in range(0, y_size, chunk_size):
                            if ExportTabWidget._static_cancel_requested(cancel_event):
                                ds_check = None
                                return False, "キャンセル"
                            if not is_solid: break
                            ys = min(chunk_size, y_size - y)
                            for x in range(0, x_size, chunk_size):
                                if ExportTabWidget._static_cancel_requested(cancel_event):
                                    ds_check = None
                                    return False, "キャンセル"
                                xs = min(chunk_size, x_size - x)
                                
                                alpha_arr = None
                                if has_alpha:
                                    alpha_arr = ds_check.GetRasterBand(alpha_band_idx).ReadAsArray(x, y, xs, ys)
                                    
                                if color_str == "透明":
                                    if bg_val[3] == 0:
                                        if alpha_arr is None or np.any(alpha_arr > 0):
                                            is_solid = False
                                            break
                                    else:
                                        is_solid = False
                                        break
                                else:
                                    for idx, i in enumerate(range(1, bands_to_check + 1)):
                                        band = ds_check.GetRasterBand(i)
                                        arr = band.ReadAsArray(x, y, xs, ys)
                                        if arr is None:
                                            is_solid = False
                                            break
                                            
                                        if has_alpha and alpha_arr is not None:
                                            if bg_val[3] == 0:
                                                if np.any(alpha_arr == 0):
                                                    is_solid = False
                                                    break
                                            else:
                                                arr = np.where(alpha_arr == 0, bg_val[idx], arr)
                                        else:
                                            nodata = band.GetNoDataValue()
                                            if nodata is not None:
                                                if bg_val[3] == 0:
                                                    if np.any(arr == nodata):
                                                        is_solid = False
                                                        break
                                                else:
                                                    arr = np.where(arr == nodata, bg_val[idx], arr)
                                                    
                                        if not np.all(arr == target_vals[idx]):
                                            is_solid = False
                                            break
                                            
                                    if not is_solid: break
                                    
                        if is_solid:
                            ds_check = None
                            return False, f"出力画像が全ピクセル指定色（{color_str}）になるためスキップ"
                            
                ds_check = None

            options = {
                'format': 'GTiff',
                'outputBounds': bbox_coords,
                'xRes': res_x, 'yRes': res_y, 'resampleAlg': resample_alg,
                'cutlineWKT': cutline_wkt, 'cropToCutline': bool(cutline_wkt),
                'srcSRS': crs_wkt, 'dstSRS': crs_wkt, 'multithread': True,
                'creationOptions': ['BIGTIFF=IF_SAFER']
            }
            options['callback'] = ExportTabWidget._static_gdal_cancel_callback(cancel_event)
            if force_24bit:
                options['dstAlpha'] = False
                if bg_val[3] != 0:
                    options['warpOptions'] = [f"INIT_DEST={ExportTabWidget._static_init_dest_value(bg_val, False)}"]
            elif warp_direct_output and background_control_enabled and bg_val[3] != 0:
                options['dstAlpha'] = True
                options['warpOptions'] = [f"INIT_DEST={ExportTabWidget._static_init_dest_value(bg_val, True)}"]
            else:
                options['dstAlpha'] = True
            if warp_direct_output and format_val == "TIF＋TFW":
                options['creationOptions'].append('PROFILE=BASELINE')
            if output_type is not None: options['outputType'] = output_type

            warp_opts = gdal.WarpOptions(**options)
            ds_tmp = gdal.Warp(target_path, [worker_master_vrt], options=warp_opts)
            if ExportTabWidget._static_cancel_requested(cancel_event):
                if ds_tmp:
                    ds_tmp = None
                ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                return False, "キャンセル"
            
            if ds_tmp:
                gt = ds_tmp.GetGeoTransform()
                
                ds_tmp.FlushCache()
                ds_tmp = None

                if warp_direct_output:
                    if postprocess_background and background_control_enabled:
                        if not ExportTabWidget._static_fill_alpha_background(out_path, bg_val, cancel_event):
                            ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                            return False, "キャンセル"
                    if force_24bit:
                        if not ExportTabWidget._static_force_rgb_output(out_path, cancel_event):
                            ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                            return False, "キャンセル"
                    if format_val in ["TIF＋TFW", "JPG＋JGW"]:
                        if ExportTabWidget._static_cancel_requested(cancel_event):
                            ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                            return False, "キャンセル"
                        ext_wf = ".tfw" if gdal_fmt == "GTiff" else ".jgw"
                        ExportTabWidget._static_write_world_file(out_path, ext_wf, gt)
                    return True, "出力成功"

                if postprocess_background and NUMPY_OK:
                    ds_update = gdal.Open(target_path, gdal.GA_Update)
                    if ds_update:
                        tmp_x_size = ds_update.RasterXSize
                        tmp_y_size = ds_update.RasterYSize
                        tmp_b_count = ds_update.RasterCount
                        
                        has_alpha_tmp = False
                        alpha_idx = -1
                        if tmp_b_count >= 4:
                            has_alpha_tmp = True
                            alpha_idx = 4
                        elif tmp_b_count > 1 and ds_update.GetRasterBand(tmp_b_count).GetColorInterpretation() == gdal.GCI_AlphaBand:
                            has_alpha_tmp = True
                            alpha_idx = tmp_b_count

                        if has_alpha_tmp:
                            chunk_size = 2048
                            for y in range(0, tmp_y_size, chunk_size):
                                if ExportTabWidget._static_cancel_requested(cancel_event):
                                    ds_update = None
                                    ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                                    return False, "キャンセル"
                                ys = min(chunk_size, tmp_y_size - y)
                                for x in range(0, tmp_x_size, chunk_size):
                                    if ExportTabWidget._static_cancel_requested(cancel_event):
                                        ds_update = None
                                        ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                                        return False, "キャンセル"
                                    xs = min(chunk_size, tmp_x_size - x)
                                    
                                    alpha_band_ref = ds_update.GetRasterBand(alpha_idx)
                                    alpha_arr = alpha_band_ref.ReadAsArray(x, y, xs, ys)
                                    if alpha_arr is None: continue
                                    
                                    if bg_val[3] != 0:
                                        mask = (alpha_arr == 0)
                                        if np.any(mask):
                                            for b in range(1, alpha_idx):
                                                band = ds_update.GetRasterBand(b)
                                                dt = band.DataType
                                                arr = band.ReadAsArray(x, y, xs, ys)
                                                if arr is not None:
                                                    color = bg_val[b-1] if b-1 < len(bg_val) else bg_val[0]
                                                    
                                                    if dt == gdal.GDT_UInt16: color = int(color * 257)
                                                    elif dt == gdal.GDT_Int16: color = int(color * 257) - 32768
                                                    elif dt == gdal.GDT_Float32: color = float(color) / 255.0
                                                    
                                                    arr[mask] = color
                                                    band.WriteArray(arr, x, y)
                                                arr = None
                                                band = None
                                            
                                            alpha_arr[mask] = 255
                                            alpha_band_ref.WriteArray(alpha_arr, x, y)
                                    
                                    alpha_arr = None
                                    alpha_band_ref = None

                        ds_update.FlushCache()
                        ds_update = None

                ds_tmp = gdal.Open(target_path)
                b_count = ds_tmp.RasterCount

                translate_args = {
                    'format': gdal_fmt,
                    'outputType': output_type if output_type is not None else src_datatype,
                    'callback': ExportTabWidget._static_gdal_cancel_callback(cancel_event)
                }
                
                creation_opts = []
                if gdal_fmt == "GTiff":
                    creation_opts.append('BIGTIFF=IF_SAFER')
                    if format_val == "TIF＋TFW":
                        creation_opts.append('PROFILE=BASELINE')
                
                if creation_opts:
                    translate_args['creationOptions'] = creation_opts
                    
                if force_24bit and b_count >= 3:
                    translate_args['bandList'] = [1, 2, 3]

                translate_opts = gdal.TranslateOptions(**translate_args)
                ds_out = gdal.Translate(out_path, ds_tmp, options=translate_opts)
                if ExportTabWidget._static_cancel_requested(cancel_event):
                    ds_out = None
                    ds_tmp = None
                    ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                    return False, "キャンセル"
                if not ds_out:
                    ds_tmp = None
                    ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                    return False, "GDAL Translate処理の失敗"
                ds_out.FlushCache()
                ds_out = None
                ds_tmp = None
                
                try: os.remove(target_path)
                except: pass

                if format_val in ["TIF＋TFW", "JPG＋JGW"]:
                    if ExportTabWidget._static_cancel_requested(cancel_event):
                        ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                        return False, "キャンセル"
                    ext_wf = ".tfw" if gdal_fmt == "GTiff" else ".jgw"
                    ExportTabWidget._static_write_world_file(out_path, ext_wf, gt)

                ds_update = gdal.Open(out_path, gdal.GA_Update)
                if ds_update:
                    try:
                        if format_val == "GeoTIFF":
                            ds_update.SetProjection(crs_wkt)
                        ds_update.FlushCache()
                    except: pass
                    ds_update = None
                    
                if need_solid_check and format_val != "TFWのみ" and os.path.exists(out_path):
                    if ExportTabWidget._static_check_skip_solid_image(out_path, color_str):
                        for _ in range(3):
                            try:
                                os.remove(out_path)
                                break 
                            except:
                                import time
                                time.sleep(0.1) 
                                
                        ext_wf = ".tfw" if gdal_fmt == "GTiff" else ".jgw"
                        wf = os.path.splitext(out_path)[0] + ext_wf
                        if os.path.exists(wf): 
                            try: os.remove(wf)
                            except: pass
                        return False, f"出力画像が全ピクセル指定色（{color_str}）になるためスキップ"

                return True, "出力成功"
                
            ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
            return False, "GDAL Warp処理の失敗"

        except Exception as e:
            ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
            if ExportTabWidget._static_cancel_requested(cancel_event) or "User terminated" in str(e):
                return False, "キャンセル"
            return False, f"GDAL処理エラー: {e}"

        finally:
            for ext in [".tmp.vrt", ".tmp.vrt.aux.xml", ".aux.xml", ".tmp.tif", ".tmp.tif.aux.xml", ".master.vrt", ".check.vrt"]:
                tmp_file = out_path + ext
                if os.path.exists(tmp_file):
                    try: os.remove(tmp_file)
                    except: pass
            if old_pam_enabled is None:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', None)
            else:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', old_pam_enabled)
            
    def _update_progress(self, val):
        output_total = max(0, self._export_progress_total - self._export_progress_skip)
        progress_max = max(1, output_total)
        progress_value = min(self._export_progress_success, progress_max)
        if output_total == 0 and self._export_progress_processed >= self._export_progress_total:
            progress_value = 1
        self.export_progress_bar.setMaximum(progress_max)
        self.export_progress_bar.setValue(progress_value)
        self._update_export_progress_dialog(val)

    @staticmethod
    def _actual_output_path(out_path, format_val):
        if format_val == "TFWのみ":
            return os.path.splitext(out_path)[0] + ".tfw"
        return out_path

    def _summarize_export_reasons(self, skip_reasons):
        summary = {
            "empty_skip": 0,
            "solid_skip": 0,
            "overwrite_skip": 0,
            "failed": 0,
            "other_skip": 0,
        }
        for reason, count in (skip_reasons or {}).items():
            if "元データが存在しない" in reason:
                summary["empty_skip"] += count
            elif "全ピクセル指定色" in reason:
                summary["solid_skip"] += count
            elif "同名ファイル" in reason:
                summary["overwrite_skip"] += count
            elif "エラー" in reason or "失敗" in reason:
                summary["failed"] += count
            else:
                summary["other_skip"] += count
        return summary

    def _raster_path_has_alpha(self, path):
        try:
            ds = gdal.Open(path)
            if not ds:
                return False
            try:
                count = ds.RasterCount
                if count >= 4:
                    return True
                if count > 1 and ds.GetRasterBand(count).GetColorInterpretation() == gdal.GCI_AlphaBand:
                    return True
            finally:
                ds = None
        except Exception:
            return False
        return False

    def _vrt_source_paths(self, vrt_path):
        paths = []
        try:
            root = ET.parse(vrt_path).getroot()
            base_dir = os.path.dirname(vrt_path)
            for node in root.findall(".//SourceFilename"):
                text = (node.text or "").strip()
                if not text:
                    continue
                if node.attrib.get("relativeToVRT") == "1" and not os.path.isabs(text):
                    text = os.path.normpath(os.path.join(base_dir, text))
                paths.append(text)
        except Exception:
            pass
        return paths

    def _input_layers_have_alpha(self, input_layers):
        for layer in input_layers:
            if not layer:
                continue
            path = layer.source()
            if not path:
                continue
            if os.path.splitext(path)[1].lower() == ".vrt":
                source_paths = self._vrt_source_paths(path)
                if source_paths:
                    if any(self._raster_path_has_alpha(src) for src in source_paths):
                        return True
                    continue
            if self._raster_path_has_alpha(path):
                return True
        return False

    def _run_export(self):
        start_time = time.time()
        
        if not GDAL_OK:
            QMessageBox.critical(self, "エラー", "GDALライブラリが見つかりません。")
            return

        out_dir = self.export_out_edit.text().strip()
        layer_id = self.zukaku_combo.currentData()
        id_field = self.id_field_combo.currentText()
        format_val = self.format_combo.currentText()
        resample_str = self.resample_combo.currentText()
        bg_val = self._get_bg_color_value()
        export_mode = self.export_mode_combo.currentText()
        export_mode_key = export_mode.replace(" ", "_").replace(":", "")
        export_run_id = time.strftime("%Y%m%d_%H%M%S")
        worker_count = int(self.worker_count_combo.currentText())
        standard_fast_mode = export_mode == "標準高速"
        standard_mode = export_mode == "標準 2.18"
        standard_no_bg_mode = export_mode == "診断: 標準・背景処理なし"
        warp_direct_mode = export_mode == "診断: Warp直接出力"
        warp_direct_post_mode = standard_fast_mode or export_mode == "診断: Warp直接＋後処理"
        rect_fast_mode = export_mode == "診断: 矩形最速"
        direct_vrt_mode = export_mode == "診断: 選択VRT直接"
        requested_empty_check = self.chk_skip_empty_vrt.isChecked()
        requested_solid_check = self.chk_skip_solid.isChecked()
        background_control_enabled = self.chk_background_process.isChecked()
        selected_bg_color = self.bg_color_combo.currentText()
        selected_solid_color = self.skip_color_combo.currentText()
        standard_like_mode = standard_fast_mode or standard_mode or standard_no_bg_mode or warp_direct_mode or warp_direct_post_mode
        postprocess_background = background_control_enabled
        effective_warp_direct_mode = (warp_direct_mode or warp_direct_post_mode) and format_val in ["TIF＋TFW", "GeoTIFF"]
        
        if not out_dir:
            QMessageBox.warning(self, "警告", "出力フォルダを指定してください")
            return
        if not layer_id:
            QMessageBox.warning(self, "警告", "図郭レイヤを選択してください")
            return

        if direct_vrt_mode:
            current_name = getattr(self.main_ui, "current_vrt_name", "")
            entry = self.main_ui.vrt_registry.get(current_name, {}) if current_name else {}
            direct_vrt_path = entry.get("path", "") if isinstance(entry, dict) else ""
            if not direct_vrt_path or not os.path.exists(direct_vrt_path):
                QMessageBox.warning(self, "警告", "選択中VRTのファイルが見つかりません")
                return
            direct_layer = self.main_ui._get_vrt_layer(current_name) if hasattr(self.main_ui, "_get_vrt_layer") else None
            input_layers = [direct_layer] if direct_layer else []
            input_paths = [direct_vrt_path]
        else:
            input_layers = self._get_input_layers()
            if not input_layers:
                QMessageBox.warning(self, "警告", "出力対象のラスタがありません。レイヤパネルでラスタを表示(ON)にしてください。")
                return
            input_paths = [lyr.source() for lyr in input_layers]

        missing_crs_files = []
        for lyr in input_layers:
            if not lyr.crs().isValid():
                src = lyr.source()
                ext = os.path.splitext(src)[1].lower()
                lyr_type = "[VRT]" if ext == ".vrt" else "[TIF]"
                missing_crs_files.append(f"{lyr_type} {lyr.name()}")

        if missing_crs_files:
            msg = "以下のレイヤに座標系（CRS）が設定されていません：\n\n"
            for f in missing_crs_files[:5]:
                msg += f"・{f}\n"
            if len(missing_crs_files) > 5:
                msg += f"...他 {len(missing_crs_files)-5} 件\n"
            msg += "\n現在のプロジェクトの座標系を強制的に適用して書き出しを続行しますか？\n（「いいえ」を押して、事前にQGIS上でレイヤの座標系を設定してから再度お試しいただくことをお勧めします）"
            
            reply = QMessageBox.question(
                self, "座標系未設定の警告", msg, 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.main_ui._set_status("ℹ 座標系未設定のため書き出しをキャンセルしました。")
                return

        os.makedirs(out_dir, exist_ok=True)
        zlayer = QgsProject.instance().mapLayer(layer_id)
        
        if zlayer.selectedFeatureCount() > 0:
            features = list(zlayer.selectedFeatures())
        else:
            features = list(zlayer.getFeatures())
            
        if not features:
            QMessageBox.warning(self, "警告", "対象となる図郭フィーチャがありません")
            return

        temp_info_vrt = os.path.join(out_dir, "_temp_info.vrt")
        src_gt = None
        src_datatype = None
        try:
            build_opts = gdal.BuildVRTOptions(resolution="highest")
            ds_info = gdal.BuildVRT(temp_info_vrt, input_paths, options=build_opts)
            if ds_info:
                src_gt = ds_info.GetGeoTransform()
                if ds_info.RasterCount > 0:
                    src_datatype = ds_info.GetRasterBand(1).DataType
                ds_info = None
        except: pass
        finally:
            try: os.remove(temp_info_vrt)
            except: pass

        if src_gt is None:
            src_gt = (0, 1, 0, 0, 0, -1)

        try: res_x = float(self.res_x_edit.text())
        except ValueError: res_x = src_gt[1]
        try: res_y = float(self.res_y_edit.text())
        except ValueError: res_y = abs(src_gt[5])

        depth_str = self.depth_combo.currentText()
        output_type = None
        force_24bit = False
        
        if "24bit" in depth_str:
            output_type = gdal.GDT_Byte
            force_24bit = True
        elif "32bit" in depth_str:
            output_type = gdal.GDT_Byte
        elif "8bit" in depth_str: 
            output_type = gdal.GDT_Byte
        elif "UInt16" in depth_str: output_type = gdal.GDT_UInt16
        elif "Int16" in depth_str: output_type = gdal.GDT_Int16
        elif "Float32" in depth_str: output_type = gdal.GDT_Float32

        if bg_val[3] == 0 and force_24bit:
            reply = QMessageBox.question(
                self,
                "透過設定の確認",
                "現在のビット設定（24bit 透過なし）では、画像を『透明』にして保存することができません。\n\n透明な背景で出力するために、自動的に『32bit (透過あり)』に変更して出力しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                force_24bit = False
                QgsMessageLog.logMessage("ユーザーの選択により透過設定を32bitに変更して出力します。", "OrthoManager", Qgis.MessageLevel.Info)
            else:
                self.main_ui._set_status("ℹ 書き出しをキャンセルしました。")
                return

        if force_24bit and self._input_layers_have_alpha(input_layers):
            reply = QMessageBox.question(
                self,
                "32bit画像が含まれています",
                "入力ラスタに透過情報を持つ画像が含まれています。\n\n"
                "24bitで出力すると透過情報は失われます。\n\n"
                "はい: 32bit (RGBA: 透過あり) に変更して出力します。\n"
                "いいえ: 24bit (RGB: 透過なし) のまま出力します。\n"
                "キャンセル: 書き出しを中止します。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self.main_ui._set_status("ℹ 書き出しをキャンセルしました。")
                return
            if reply == QMessageBox.StandardButton.Yes:
                force_24bit = False
                QgsMessageLog.logMessage("入力に透過情報があるため、ユーザーの選択により32bit出力へ変更します。", "OrthoManager", Qgis.MessageLevel.Info)

        resample_alg = gdal.GRA_NearestNeighbour
        if "Cubic" in resample_str: resample_alg = gdal.GRA_Cubic
        elif "Bilinear" in resample_str: resample_alg = gdal.GRA_Bilinear

        gdal_fmt = "GTiff"
        ext = ".tif"
        if format_val == "JPG＋JGW":
            gdal_fmt = "JPEG"
            ext = ".jpg"
        elif format_val == "ECW":
            gdal_fmt = "ECW"
            ext = ".ecw"
        elif format_val == "PDF":
            gdal_fmt = "PDF"
            ext = ".pdf"

        is_single_mode = self.rb_mode_single.isChecked()

        if not is_single_mode:
            seen_output_names = {}
            duplicate_output_names = []
            for feat in features:
                zid = feat[id_field] if id_field else feat.id()
                out_path = os.path.join(out_dir, f"{zid}{ext}")
                actual_path = self._actual_output_path(out_path, format_val)
                key = os.path.basename(actual_path).lower()
                if key in seen_output_names:
                    duplicate_output_names.append(os.path.basename(actual_path))
                else:
                    seen_output_names[key] = feat.id()

            if duplicate_output_names:
                shown = "\n".join(f"・{name}" for name in duplicate_output_names[:10])
                if len(duplicate_output_names) > 10:
                    shown += f"\n...他 {len(duplicate_output_names) - 10} 件"
                QMessageBox.critical(
                    self,
                    "図郭IDが重複しています",
                    "同じ出力ファイル名になる図郭があります。\n\n"
                    f"{shown}\n\n"
                    "同時書き込みによる破損を防ぐため、書き出しを中止しました。\n"
                    "図郭IDを重複しない値に修正してから再実行してください。"
                )
                self.main_ui._set_status("❌ 図郭ID重複のため書き出しを中止しました")
                return
        
        self.export_progress_bar.setVisible(True)
        self.export_progress_bar.setValue(0)
        
        success_count = 0
        skip_reasons = {}
        cancelled_by_user = False
        export_error = None
        self._export_cancel_event = threading.Event()
        
        self.overwrite_all = False
        self.skip_all = False
        
        try:
            self._show_export_progress_dialog(1 if self.rb_mode_single.isChecked() else len(features))
            crs_wkt = QgsProject.instance().crs().toWkt()
            need_empty_check = standard_like_mode and requested_empty_check
            need_solid_check = standard_like_mode and requested_solid_check
            color_str = selected_solid_color
            master_build_sec = 0.0
            task_prepare_sec = 0.0
            parallel_sec = 0.0
            vector_overlay_sec = 0.0
            finalize_sec = 0.0
            total_before_message_sec = 0.0
            master_vrt_should_remove = False
            check_master_vrt_path = None
            check_master_vrt_should_remove = False
            fail_count = 0

            if direct_vrt_mode:
                master_vrt_path = input_paths[0]
                check_master_vrt_path = master_vrt_path
            else:
                master_vrt_path = os.path.join(out_dir, "_temp_master.vrt")
                check_master_vrt_path = master_vrt_path
                master_vrt_should_remove = True
                master_start = time.perf_counter()
                rgb_master_requested = force_24bit
                rgb_master_active = False
                build_opts = gdal.BuildVRTOptions(
                    resolution="highest",
                    addAlpha=not force_24bit,
                    hideNodata=True,
                    bandList=[1, 2, 3] if force_24bit else None,
                )
                try:
                    ds_master = gdal.BuildVRT(master_vrt_path, input_paths, options=build_opts)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"RGBマスターVRT作成エラー。アルファ付きマスターVRTへ戻します: {e}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    ds_master = None
                if not ds_master and force_24bit:
                    try:
                        fallback_opts = gdal.BuildVRTOptions(resolution="highest", addAlpha=True, hideNodata=True)
                        ds_master = gdal.BuildVRT(master_vrt_path, input_paths, options=fallback_opts)
                        rgb_master_active = False
                    except Exception:
                        ds_master = None
                elif ds_master and force_24bit:
                    rgb_master_active = True
                if ds_master:
                    ds_master.FlushCache()
                    ds_master = None
                else:
                    QMessageBox.critical(self, "エラー", "レイヤの合成処理（マスターVRT構築）に失敗しました。")
                    return

                if force_24bit and (need_empty_check or need_solid_check):
                    check_master_vrt_path = os.path.join(out_dir, "_temp_master_check.vrt")
                    check_master_vrt_should_remove = True
                    check_opts = gdal.BuildVRTOptions(resolution="highest", addAlpha=True, hideNodata=True)
                    try:
                        ds_check_master = gdal.BuildVRT(check_master_vrt_path, input_paths, options=check_opts)
                        if ds_check_master:
                            ds_check_master.FlushCache()
                            ds_check_master = None
                        else:
                            check_master_vrt_path = master_vrt_path
                            check_master_vrt_should_remove = False
                    except Exception as e:
                        QgsMessageLog.logMessage(
                            f"空判定用VRT作成エラー。出力用VRTで判定します: {e}",
                            "OrthoManager",
                            Qgis.MessageLevel.Warning,
                        )
                        check_master_vrt_path = master_vrt_path
                        check_master_vrt_should_remove = False
                master_build_sec = time.perf_counter() - master_start

            QgsMessageLog.logMessage(
                "EXPORT_DIAG_CONFIG "
                f"run={export_run_id} "
                f"mode={export_mode_key} workers={worker_count} features={len(features)} input_rasters={len(input_paths)} "
                f"requested_empty_skip={requested_empty_check} effective_empty_skip={need_empty_check} "
                f"requested_solid_skip={requested_solid_check} effective_solid_skip={need_solid_check} solid_color={color_str} "
                f"background_color={selected_bg_color} background_control={background_control_enabled} "
                f"background_postprocess={postprocess_background} "
                f"rect_fast={rect_fast_mode} direct_vrt={direct_vrt_mode} standard_no_bg={standard_no_bg_mode} "
                f"warp_direct={effective_warp_direct_mode} warp_direct_post={warp_direct_post_mode} "
                f"force_24bit={force_24bit} rgb_master_requested={locals().get('rgb_master_requested', False)} "
                f"rgb_master_active={locals().get('rgb_master_active', False)} "
                f"check_master_separate={check_master_vrt_path != master_vrt_path} "
                f"format={format_val} resample={resample_str}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )

            if is_single_mode:
                self.export_progress_bar.setMaximum(1)
                union_geom = features[0].geometry()
                for f in features[1:]:
                    union_geom = union_geom.combine(f.geometry())
                    
                bbox = union_geom.boundingBox()
                bbox_coords = (bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum())
                
                out_name = self.single_name_edit.text().strip() or "merged_ortho"
                out_path = os.path.join(out_dir, f"{out_name}{ext}")
                actual_out_path = self._actual_output_path(out_path, format_val)
                
                if os.path.exists(actual_out_path):
                    reply = QMessageBox.question(
                        self, "上書き確認",
                        f"ファイル '{os.path.basename(actual_out_path)}' はすでに存在します。\n上書きしますか？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Cancel:
                        self.main_ui._set_status("ℹ 書き出しをキャンセルしました。")
                        return
                    elif reply == QMessageBox.StandardButton.No:
                        skip_reasons["同名ファイルが存在するためスキップ（上書き拒否）"] = 1
                        QgsMessageLog.logMessage(f"出力スキップ: ユーザーによる上書き拒否", "OrthoManager", Qgis.MessageLevel.Info)
                        self.export_progress_bar.setValue(1)
                        self.export_progress_bar.setVisible(False)
                        return

                args = (
                    master_vrt_path, check_master_vrt_path, out_path, bbox_coords, None, gdal_fmt, format_val,
                    res_x, res_y, resample_alg, bg_val, src_datatype, output_type, force_24bit,
                    need_empty_check, need_solid_check, color_str, crs_wkt, postprocess_background,
                    effective_warp_direct_mode, background_control_enabled, self._export_cancel_event
                )
                
                single_start = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._gdal_process_worker, args)
                    while not future.done():
                        QApplication.processEvents()
                        concurrent.futures.wait([future], timeout=0.1)
                    try:
                        success, reason = future.result()
                    except Exception as exc:
                        ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                        if self._export_cancel_requested or "User terminated" in str(exc):
                            success, reason = False, "キャンセル"
                        else:
                            success, reason = False, f"並列処理エラー: {exc}"
                parallel_sec = time.perf_counter() - single_start
                if success:
                    success_count = 1
                    self._export_progress_success = success_count
                    if self.chk_include_vector.isChecked():
                        vector_start = time.perf_counter()
                        self._render_vector_overlay(out_path, bbox)
                        vector_overlay_sec += time.perf_counter() - vector_start
                else:
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    self._export_progress_skip = sum(skip_reasons.values())
                    QgsMessageLog.logMessage(f"出力スキップ: {reason}", "OrthoManager", Qgis.MessageLevel.Info)
                    if reason == "キャンセル":
                        cancelled_by_user = True

                self.export_progress_bar.setValue(1)
                self._update_export_progress_dialog(1)
            else:
                self.export_progress_bar.setMaximum(len(features))
                
                prepare_start = time.perf_counter()
                tasks = []
                for i, feat in enumerate(features):
                    zid = feat[id_field] if id_field else feat.id()
                    out_path = os.path.join(out_dir, f"{zid}{ext}")
                    actual_out_path = self._actual_output_path(out_path, format_val)
                    
                    if os.path.exists(actual_out_path) and not self.overwrite_all:
                        if self.skip_all:
                            skip_reasons["同名ファイルが存在するためスキップ"] = skip_reasons.get("同名ファイルが存在するためスキップ", 0) + 1
                            continue
                            
                        msg_box = QMessageBox(self)
                        msg_box.setWindowTitle("上書き確認")
                        msg_box.setText(f"ファイル '{os.path.basename(actual_out_path)}' はすでに存在します。\n上書きしますか？")
                        
                        btn_yes_all = msg_box.addButton("すべて上書き", QMessageBox.ButtonRole.YesRole)
                        btn_yes = msg_box.addButton("上書き", QMessageBox.ButtonRole.AcceptRole)
                        btn_skip = msg_box.addButton("スキップ", QMessageBox.ButtonRole.RejectRole)
                        btn_skip_all = msg_box.addButton("すべてスキップ", QMessageBox.ButtonRole.NoRole)
                        btn_cancel = msg_box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
                        
                        msg_box.exec()
                        clicked_btn = msg_box.clickedButton()
                        
                        if clicked_btn == btn_cancel:
                            self.main_ui._set_status("ℹ 書き出しをキャンセルしました。")
                            return
                        elif clicked_btn == btn_yes_all:
                            self.overwrite_all = True
                        elif clicked_btn == btn_skip_all:
                            self.skip_all = True
                            skip_reasons["同名ファイルが存在するためスキップ"] = skip_reasons.get("同名ファイルが存在するためスキップ", 0) + 1
                            continue
                        elif clicked_btn == btn_skip:
                            skip_reasons["同名ファイルが存在するためスキップ"] = skip_reasons.get("同名ファイルが存在するためスキップ", 0) + 1
                            continue

                    geom = feat.geometry()
                    bbox = geom.boundingBox()
                    bbox_coords = (bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum())
                    cutline_wkt = None if rect_fast_mode else geom.asWkt()
                    
                    args = (
                        master_vrt_path, check_master_vrt_path, out_path, bbox_coords, cutline_wkt, gdal_fmt, format_val,
                        res_x, res_y, resample_alg, bg_val, src_datatype, output_type, force_24bit,
                        need_empty_check, need_solid_check, color_str, crs_wkt, postprocess_background,
                        effective_warp_direct_mode, background_control_enabled, self._export_cancel_event
                    )
                    tasks.append((args, bbox, zid))
                task_prepare_sec = time.perf_counter() - prepare_start

                if not tasks:
                    self.export_progress_bar.setVisible(False)
                    self.main_ui._set_status("✅ 書き出し完了: すべてスキップされました")
                    return

                max_workers = max(1, worker_count)
                completed = 0
                
                self.export_progress_bar.setMaximum(len(tasks))
                self._set_export_progress_total(len(tasks))
                 
                parallel_start = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    task_iter = iter(tasks)
                    future_to_info = {}

                    def submit_next():
                        if self._export_cancel_requested:
                            return False
                        try:
                            task = next(task_iter)
                        except StopIteration:
                            return False
                        future_to_info[executor.submit(self._gdal_process_worker, task[0])] = task
                        return True

                    for _ in range(min(max_workers, len(tasks))):
                        submit_next()

                    while future_to_info:
                        done, _ = concurrent.futures.wait(
                            future_to_info.keys(),
                            timeout=0.1,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        QApplication.processEvents()
                        if not done:
                            continue

                        for future in done:
                            args, bbox, zid = future_to_info.pop(future)
                            out_path = args[2]
                            
                            try:
                                success, reason = future.result()
                            except Exception as exc:
                                ExportTabWidget._static_cleanup_export_outputs(out_path, gdal_fmt, format_val)
                                if self._export_cancel_requested or "User terminated" in str(exc):
                                    success, reason = False, "キャンセル"
                                else:
                                    success, reason = False, f"並列処理エラー: {exc}"
                            
                            if success:
                                success_count += 1
                                self._export_progress_success = success_count
                                if self.chk_include_vector.isChecked():
                                    vector_start = time.perf_counter()
                                    self._render_vector_overlay(out_path, bbox)
                                    vector_overlay_sec += time.perf_counter() - vector_start
                            else:
                                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                                self._export_progress_skip = sum(skip_reasons.values())
                                if reason == "キャンセル":
                                    cancelled_by_user = True
                                if "エラー" in reason or "失敗" in reason:
                                    fail_count += 1
                                    if skip_reasons[reason] <= 3:
                                        QgsMessageLog.logMessage(
                                            f"EXPORT_DIAG_FAIL run={export_run_id} zid={zid} reason={reason}",
                                            "OrthoManager",
                                            Qgis.MessageLevel.Warning,
                                        )
                                
                            completed += 1
                            self.progress_updated.emit(completed)
                            QApplication.processEvents()

                            if not self._export_cancel_requested:
                                submit_next()

                    cancelled_by_user = cancelled_by_user or self._export_cancel_requested
                    not_started_count = len(tasks) - completed
                    if cancelled_by_user and not_started_count > 0:
                        skip_reasons["キャンセル"] = skip_reasons.get("キャンセル", 0) + not_started_count
                parallel_sec = time.perf_counter() - parallel_start

        except Exception as e:
            export_error = e
            QMessageBox.critical(self, "エラー", f"書き出し中にエラーが発生しました:\n{e}")
            QgsMessageLog.logMessage(f"Export Error: {e}", "OrthoManager", Qgis.MessageLevel.Critical)
        finally:
            finalize_start = time.perf_counter()
            self._hide_export_busy_message()
            self.export_progress_bar.setVisible(False)
            self._export_cancel_event = None
            
            try:
                if 'master_vrt_path' in locals() and 'master_vrt_should_remove' in locals() and master_vrt_should_remove and os.path.exists(master_vrt_path):
                    os.remove(master_vrt_path)
                if 'check_master_vrt_path' in locals() and 'check_master_vrt_should_remove' in locals() and check_master_vrt_should_remove and os.path.exists(check_master_vrt_path):
                    os.remove(check_master_vrt_path)
            except: pass
            finalize_sec = time.perf_counter() - finalize_start
             
            elapsed_time = time.time() - start_time
            total_before_message_sec = elapsed_time
            m, s = divmod(elapsed_time, 60)
            time_str = f"{int(m)}分 {int(s)}秒" if m > 0 else f"{int(s)}秒"
            cancelled_by_user = cancelled_by_user or self._export_cancel_requested
            
            msg = f"{success_count} 件の書き出しが完了しました。\n出力先: {out_dir}"
            msg += f"\n\n【処理時間】\n・{time_str}"
            if skip_reasons:
                msg += "\n\n【スキップされた理由】"
                for r, count in skip_reasons.items():
                    msg += f"\n・{r} : {count} 件"
            reason_summary = self._summarize_export_reasons(skip_reasons)
            skipped_or_failed = sum(skip_reasons.values()) if skip_reasons else 0
            failure_count = reason_summary["failed"]
            analyzed_skip = reason_summary["empty_skip"] + reason_summary["solid_skip"] + reason_summary["overwrite_skip"] + reason_summary["other_skip"]
            avg_sec = (elapsed_time / max(1, success_count)) if success_count else 0.0
            QgsMessageLog.logMessage(
                "EXPORT_DIAG_SUMMARY "
                f"run={locals().get('export_run_id', '')} "
                f"mode={locals().get('export_mode_key', '')} workers={locals().get('worker_count', '')} "
                f"total_sec={elapsed_time:.2f} master_vrt_sec={locals().get('master_build_sec', 0.0):.2f} "
                f"task_prepare_sec={locals().get('task_prepare_sec', 0.0):.2f} parallel_sec={locals().get('parallel_sec', 0.0):.2f} "
                f"vector_overlay_sec={locals().get('vector_overlay_sec', 0.0):.2f} "
                f"finalize_sec={locals().get('finalize_sec', 0.0):.2f} "
                f"post_parallel_sec={max(0.0, total_before_message_sec - locals().get('master_build_sec', 0.0) - locals().get('task_prepare_sec', 0.0) - locals().get('parallel_sec', 0.0)):.2f} "
                f"total_before_message_sec={total_before_message_sec:.2f} "
                f"success={success_count} skipped_or_failed={skipped_or_failed} "
                f"cancelled={cancelled_by_user} "
                f"empty_skip={reason_summary['empty_skip']} solid_skip={reason_summary['solid_skip']} "
                f"overwrite_skip={reason_summary['overwrite_skip']} other_skip={reason_summary['other_skip']} "
                f"failed={failure_count} analyzed_skip={analyzed_skip} "
                f"avg_success_sec={avg_sec:.2f} "
                f"requested_empty_skip={locals().get('requested_empty_check', '')} effective_empty_skip={locals().get('need_empty_check', '')} "
                f"requested_solid_skip={locals().get('requested_solid_check', '')} effective_solid_skip={locals().get('need_solid_check', '')} "
                f"solid_color={locals().get('color_str', '')} background_color={locals().get('selected_bg_color', '')} "
                f"background_control={locals().get('background_control_enabled', '')} "
                f"background_postprocess={locals().get('postprocess_background', '')} "
                f"warp_direct_post={locals().get('warp_direct_post_mode', '')} "
                f"force_24bit={locals().get('force_24bit', '')} "
                f"rgb_master_requested={locals().get('rgb_master_requested', False)} "
                f"rgb_master_active={locals().get('rgb_master_active', False)} "
                f"check_master_separate={locals().get('check_master_vrt_path', '') != locals().get('master_vrt_path', '')}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )

            if export_error is not None:
                self._hide_export_progress_dialog()
                self.main_ui._set_status("❌ 書き出し中にエラーが発生しました")
                return

            if cancelled_by_user:
                self.main_ui._set_status(f"ℹ 書き出しをキャンセルしました: {success_count} 件成功 ({time_str})")
                cancel_msg = (
                    "書き出しをキャンセルしました。\n\n"
                    f"完了済み: {success_count} 件\n"
                    "未完成の出力ファイルは可能な限り自動削除しました。"
                )
                if skip_reasons:
                    cancel_msg += "\n\n【内訳】"
                    for r, count in skip_reasons.items():
                        cancel_msg += f"\n・{r} : {count} 件"
                self._hide_export_progress_dialog()
                QMessageBox.information(self, "キャンセル", cancel_msg)
            else:
                self.main_ui._set_status(f"✅ 書き出し完了: {success_count} 件成功 ({time_str})")
                self._hide_export_progress_dialog()
                QMessageBox.information(self, "完了", msg)

