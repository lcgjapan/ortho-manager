import math
import os
import time

from osgeo import gdal

try:
    import numpy as np
except Exception:
    np = None

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton,
    QSizePolicy, QFileDialog, QLineEdit, QComboBox, QCheckBox,
    QProgressBar, QMessageBox, QGridLayout
)
from qgis.core import QgsApplication, QgsMessageLog, QgsProject, QgsRasterLayer, QgsTask, Qgis

from ..i18n import tr


def _format_seconds(seconds):
    return f"{seconds:.1f}"


class RrimTask(QgsTask):
    PRESETS = {
        "weak": {"slope": 0.42, "shade": 0.44, "relief": 0.10},
        "standard": {"slope": 0.60, "shade": 0.55, "relief": 0.16},
        "strong": {"slope": 0.78, "shade": 0.66, "relief": 0.24},
    }

    def __init__(self, input_path, output_path, preset="standard"):
        super().__init__("OrthoManager: RRIM作成", QgsTask.Flag.CanCancel)
        self.input_path = os.path.normpath(os.path.abspath(input_path))
        self.output_path = os.path.normpath(os.path.abspath(output_path))
        self.preset = preset if preset in self.PRESETS else "standard"
        self.error_msg = ""
        self.elapsed_sec = 0.0
        self.finished_callback = None
        self.summary = {}

    def _make_mask(self, array, nodata):
        mask = ~np.isfinite(array)
        if nodata is not None:
            try:
                if math.isfinite(float(nodata)):
                    mask |= np.isclose(array, float(nodata))
            except Exception:
                pass
        return mask

    def _local_mean_3x3(self, array):
        pad = np.pad(array, 1, mode="edge")
        return (
            pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:] +
            pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:] +
            pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]
        ) / 9.0

    def _safe_percentile(self, values, percentile, fallback=1.0):
        if values.size <= 0:
            return fallback
        value = float(np.nanpercentile(values, percentile))
        if not math.isfinite(value) or value <= 0:
            return fallback
        return value

    def _build_rgb(self, elevation, valid_mask, dx, dy):
        filled = elevation.copy()
        mean_value = float(np.nanmean(elevation[valid_mask]))
        filled[~valid_mask] = mean_value

        self.setProgress(35)
        gy, gx = np.gradient(filled, dy, dx)
        slope = np.hypot(gx, gy)
        slope_scale = self._safe_percentile(slope[valid_mask], 98, fallback=1.0)
        slope_norm = np.clip(slope / slope_scale, 0.0, 1.0)

        self.setProgress(55)
        azimuth = math.radians(315.0)
        altitude = math.radians(45.0)
        lx = math.cos(altitude) * math.sin(azimuth)
        ly = math.cos(altitude) * math.cos(azimuth)
        lz = math.sin(altitude)
        nx = -gx
        ny = -gy
        nz = np.ones_like(filled, dtype=np.float32)
        normal_length = np.sqrt(nx * nx + ny * ny + nz * nz)
        hillshade = (nx * lx + ny * ly + nz * lz) / np.maximum(normal_length, 1e-6)
        hillshade = np.clip(hillshade, 0.0, 1.0)

        self.setProgress(70)
        local = filled - self._local_mean_3x3(filled)
        relief_scale = self._safe_percentile(np.abs(local[valid_mask]), 98, fallback=1.0)
        relief = np.clip(local / relief_scale, -1.0, 1.0)
        relief_pos = (relief + 1.0) * 0.5

        weights = self.PRESETS[self.preset]
        brightness = np.clip(
            0.36 + weights["shade"] * hillshade + weights["slope"] * 0.25 * slope_norm,
            0.0,
            1.0,
        )
        red_base = 178.0 + 62.0 * slope_norm + 34.0 * weights["relief"] * relief_pos
        green_base = 42.0 + 38.0 * (1.0 - slope_norm) + 24.0 * weights["relief"] * (1.0 - relief_pos)
        blue_base = 28.0 + 24.0 * (1.0 - relief_pos)

        red = np.clip(red_base * brightness, 1, 255).astype(np.uint8)
        green = np.clip(green_base * brightness, 1, 155).astype(np.uint8)
        blue = np.clip(blue_base * brightness, 1, 115).astype(np.uint8)
        red[~valid_mask] = 0
        green[~valid_mask] = 0
        blue[~valid_mask] = 0
        return red, green, blue

    def _write_rgb(self, red, green, blue, width, height, geotransform, projection):
        out_dir = os.path.dirname(self.output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        if os.path.exists(self.output_path):
            os.remove(self.output_path)

        driver = gdal.GetDriverByName("GTiff")
        if driver is None:
            raise RuntimeError("GTiffドライバを利用できません。")
        dataset = driver.Create(
            self.output_path,
            width,
            height,
            3,
            gdal.GDT_Byte,
            options=["BIGTIFF=IF_SAFER"],
        )
        if dataset is None:
            raise RuntimeError("RRIM GeoTIFFを作成できませんでした。")
        try:
            dataset.SetGeoTransform(geotransform)
            if projection:
                dataset.SetProjection(projection)
            bands = [
                (dataset.GetRasterBand(1), red, getattr(gdal, "GCI_RedBand", None)),
                (dataset.GetRasterBand(2), green, getattr(gdal, "GCI_GreenBand", None)),
                (dataset.GetRasterBand(3), blue, getattr(gdal, "GCI_BlueBand", None)),
            ]
            for band, array, color_interp in bands:
                if color_interp is not None:
                    band.SetColorInterpretation(color_interp)
                band.SetNoDataValue(0)
                band.WriteArray(array)
                band.FlushCache()
            dataset.FlushCache()
        finally:
            dataset = None

    def run(self):
        started = time.perf_counter()
        old_pam = gdal.GetConfigOption("GDAL_PAM_ENABLED")
        try:
            if np is None:
                raise RuntimeError("NumPyを利用できないため、RRIMを作成できません。")
            if not os.path.exists(self.input_path):
                raise RuntimeError("入力ラスタが見つかりません。")

            gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
            dataset = gdal.Open(self.input_path, gdal.GA_ReadOnly)
            if dataset is None or dataset.RasterCount < 1:
                raise RuntimeError("入力ラスタを開けません。")
            try:
                width = dataset.RasterXSize
                height = dataset.RasterYSize
                band = dataset.GetRasterBand(1)
                nodata = band.GetNoDataValue()
                geotransform = dataset.GetGeoTransform(can_return_null=True)
                if not geotransform:
                    geotransform = (0, 1, 0, 0, 0, -1)
                projection = dataset.GetProjection()
                QgsMessageLog.logMessage(
                    (
                        "RRIM_CREATE_START "
                        f"preset={self.preset} width={width} height={height} "
                        f"in={self.input_path}"
                    ),
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                self.setProgress(10)
                elevation = band.ReadAsArray()
            finally:
                dataset = None

            if self.isCanceled():
                self.error_msg = "RRIM作成を中止しました。"
                return False
            if elevation is None:
                raise RuntimeError("入力ラスタの標高値を読み込めません。")
            elevation = elevation.astype(np.float32, copy=False)
            mask = self._make_mask(elevation, nodata)
            valid_mask = ~mask
            valid_count = int(np.count_nonzero(valid_mask))
            if valid_count <= 0:
                raise RuntimeError("有効な標高セルがありません。")

            dx = abs(float(geotransform[1])) if geotransform else 1.0
            dy = abs(float(geotransform[5])) if geotransform else dx
            if dx <= 0:
                dx = 1.0
            if dy <= 0:
                dy = dx

            red, green, blue = self._build_rgb(elevation, valid_mask, dx, dy)
            if self.isCanceled():
                self.error_msg = "RRIM作成を中止しました。"
                return False

            self.setProgress(88)
            self._write_rgb(red, green, blue, elevation.shape[1], elevation.shape[0], geotransform, projection)
            self.elapsed_sec = time.perf_counter() - started
            self.summary = {
                "width": int(elevation.shape[1]),
                "height": int(elevation.shape[0]),
                "valid": valid_count,
                "nodata": int(elevation.size - valid_count),
            }
            self.setProgress(100)
            QgsMessageLog.logMessage(
                (
                    "RRIM_CREATE_DONE "
                    f"seconds={self.elapsed_sec:.1f} valid={valid_count} "
                    f"nodata={self.summary['nodata']} out={self.output_path}"
                ),
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return True
        except Exception as e:
            self.error_msg = str(e)
            QgsMessageLog.logMessage(f"RRIM_CREATE_FAILED error={e}", "OrthoManager", Qgis.MessageLevel.Critical)
            return False
        finally:
            gdal.SetConfigOption("GDAL_PAM_ENABLED", old_pam)

    def finished(self, result):
        if self.finished_callback:
            self.finished_callback(self, result)


class RrimToolWidget(QWidget):
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self.dock = dock
        self._task = None
        self._last_input_dir = ""
        self._last_output_dir = ""
        self._build_ui()
        self.refresh_texts()
        self._update_run_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight:bold; font-size:14px; color:#111827;")
        layout.addWidget(self.title_label)

        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color:#4b5563; font-size:11px;")
        layout.addWidget(self.note_label)

        self.input_group = QGroupBox()
        input_layout = QGridLayout(self.input_group)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setHorizontalSpacing(6)
        input_layout.setVerticalSpacing(6)

        self.input_path_edit = QLineEdit()
        self.input_path_edit.setReadOnly(True)
        self.input_path_edit.textChanged.connect(self._update_run_state)
        self.input_browse_button = QPushButton()
        self.input_browse_button.clicked.connect(self._browse_input)
        self.current_layer_button = QPushButton()
        self.current_layer_button.clicked.connect(self._use_current_layer)
        input_layout.addWidget(self.input_path_edit, 0, 0, 1, 2)
        input_layout.addWidget(self.input_browse_button, 1, 0)
        input_layout.addWidget(self.current_layer_button, 1, 1)
        layout.addWidget(self.input_group)

        self.output_group = QGroupBox()
        output_layout = QGridLayout(self.output_group)
        output_layout.setContentsMargins(8, 8, 8, 8)
        output_layout.setHorizontalSpacing(6)
        output_layout.setVerticalSpacing(6)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.textChanged.connect(self._update_run_state)
        self.output_browse_button = QPushButton()
        self.output_browse_button.clicked.connect(self._browse_output)
        self.preset_label = QLabel()
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("", "standard")
        self.preset_combo.addItem("", "strong")
        self.preset_combo.addItem("", "weak")
        self.load_checkbox = QCheckBox()
        self.load_checkbox.setChecked(True)

        output_layout.addWidget(self.output_path_edit, 0, 0)
        output_layout.addWidget(self.output_browse_button, 0, 1)
        output_layout.addWidget(self.preset_label, 1, 0, 1, 2)
        output_layout.addWidget(self.preset_combo, 2, 0, 1, 2)
        output_layout.addWidget(self.load_checkbox, 3, 0, 1, 2)
        layout.addWidget(self.output_group)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color:#4b5563;")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.status_label)
        layout.addLayout(progress_row)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.run_button = QPushButton()
        self.run_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.run_button.clicked.connect(self._run)
        self.cancel_button = QPushButton()
        self.cancel_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.cancel_button)
        layout.addLayout(action_row)

        layout.addStretch(1)

    def _project_dir(self):
        try:
            project_path = QgsProject.instance().fileName()
            if project_path:
                folder = os.path.dirname(project_path)
                if os.path.isdir(folder):
                    return folder
        except Exception:
            pass
        return ""

    def _home_dir(self):
        return os.path.expanduser("~")

    def _initial_input_dir(self):
        for folder in (self._last_input_dir, self._project_dir(), self._home_dir()):
            if folder and os.path.isdir(folder):
                return folder
        return ""

    def _initial_output_dir(self):
        for folder in (
            self._last_output_dir,
            os.path.dirname(self.input_path_edit.text().strip()),
            self._project_dir(),
            self._home_dir(),
        ):
            if folder and os.path.isdir(folder):
                return folder
        return ""

    def _normalize_source_path(self, source):
        path = (source or "").strip()
        if "|" in path:
            path = path.split("|", 1)[0]
        return os.path.normpath(path) if path else ""

    def _default_output_path(self, input_path):
        if not input_path:
            return ""
        folder = os.path.dirname(input_path)
        name = os.path.splitext(os.path.basename(input_path))[0]
        return os.path.join(folder, f"{name}_RRIM.tif")

    def _browse_input(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            tr("tools.rrim.input_dialog_title"),
            self._initial_input_dir(),
            tr("tools.rrim.input_filter"),
        )
        if not path:
            return
        self._last_input_dir = os.path.dirname(path)
        self.input_path_edit.setText(os.path.normpath(path))
        if not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_path(path))

    def _use_current_layer(self):
        layer = None
        try:
            layer = self.dock.iface.activeLayer()
        except Exception:
            layer = None
        if not isinstance(layer, QgsRasterLayer):
            QMessageBox.warning(self, tr("tools.rrim.warning_title"), tr("tools.rrim.error_no_current_raster"))
            return
        path = self._normalize_source_path(layer.source())
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, tr("tools.rrim.warning_title"), tr("tools.rrim.error_current_raster_path"))
            return
        self._last_input_dir = os.path.dirname(path)
        self.input_path_edit.setText(path)
        if not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_path(path))

    def _browse_output(self):
        initial_dir = self._initial_output_dir()
        initial_path = self.output_path_edit.text().strip()
        if not initial_path:
            input_path = self.input_path_edit.text().strip()
            initial_path = self._default_output_path(input_path) or os.path.join(initial_dir, "RRIM.tif")
        path, _filter = QFileDialog.getSaveFileName(
            self,
            tr("tools.rrim.output_dialog_title"),
            initial_path,
            tr("tools.rrim.output_filter"),
        )
        if not path:
            return
        if not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        self._last_output_dir = os.path.dirname(path)
        self.output_path_edit.setText(os.path.normpath(path))

    def _validate(self):
        input_path = self.input_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()
        if not input_path:
            return False, tr("tools.rrim.error_input_required")
        if not os.path.exists(input_path):
            return False, tr("tools.rrim.error_input_missing")
        if not output_path:
            return False, tr("tools.rrim.error_output_required")
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.isdir(output_dir):
            return False, tr("tools.rrim.error_output_dir_missing")
        if os.path.normcase(os.path.abspath(input_path)) == os.path.normcase(os.path.abspath(output_path)):
            return False, tr("tools.rrim.error_same_path")
        return True, ""

    def _update_run_state(self):
        ready, _message = self._validate()
        self.run_button.setEnabled(ready and self._task is None)

    def _set_running(self, running):
        self.input_browse_button.setEnabled(not running)
        self.current_layer_button.setEnabled(not running)
        self.output_browse_button.setEnabled(not running)
        self.preset_combo.setEnabled(not running)
        self.load_checkbox.setEnabled(not running)
        self.run_button.setEnabled((not running) and self._validate()[0])
        self.cancel_button.setEnabled(running)

    def _run(self):
        ready, message = self._validate()
        if not ready:
            QMessageBox.warning(self, tr("tools.rrim.warning_title"), message)
            return
        input_path = self.input_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()
        if os.path.exists(output_path):
            reply = QMessageBox.question(
                self,
                tr("tools.rrim.overwrite_title"),
                tr("tools.rrim.overwrite_message").format(path=output_path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.progress_bar.setValue(0)
        self.status_label.setText(tr("tools.rrim.status_running"))
        self._set_running(True)
        preset = self.preset_combo.currentData() or "standard"
        task = RrimTask(input_path, output_path, preset=preset)
        self._task = task
        task.finished_callback = self._task_finished
        task.progressChanged.connect(lambda value: self.progress_bar.setValue(int(value)))
        QgsApplication.taskManager().addTask(task)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.status_label.setText(tr("tools.rrim.status_canceling"))

    def _load_result_layer(self, output_path):
        layer_name = os.path.splitext(os.path.basename(output_path))[0]
        layer = QgsRasterLayer(output_path, layer_name, "gdal")
        if not layer.isValid():
            QMessageBox.warning(self, tr("tools.rrim.warning_title"), tr("tools.rrim.error_load_failed"))
            return
        QgsProject.instance().addMapLayer(layer)

    def _task_finished(self, task, result):
        self._task = None
        self._set_running(False)
        if result:
            seconds = task.elapsed_sec
            self.progress_bar.setValue(100)
            self.status_label.setText(tr("tools.rrim.status_done").format(seconds=seconds))
            if self.load_checkbox.isChecked():
                self._load_result_layer(task.output_path)
            return
        self.status_label.setText(tr("tools.rrim.status_failed"))
        if task.error_msg:
            QMessageBox.warning(self, tr("tools.rrim.warning_title"), task.error_msg)

    def refresh_texts(self):
        self.title_label.setText(tr("tools.rrim.title"))
        self.note_label.setText(tr("tools.rrim.note"))
        self.input_group.setTitle(tr("tools.rrim.input_group"))
        self.input_browse_button.setText(tr("tools.rrim.input_browse"))
        self.current_layer_button.setText(tr("tools.rrim.current_layer"))
        self.output_group.setTitle(tr("tools.rrim.output_group"))
        self.output_browse_button.setText(tr("tools.rrim.output_browse"))
        self.preset_label.setText(tr("tools.rrim.preset_label"))
        self.preset_combo.setItemText(0, tr("tools.rrim.preset_standard"))
        self.preset_combo.setItemText(1, tr("tools.rrim.preset_strong"))
        self.preset_combo.setItemText(2, tr("tools.rrim.preset_weak"))
        self.load_checkbox.setText(tr("tools.rrim.load_to_qgis"))
        self.run_button.setText(tr("tools.rrim.run"))
        self.cancel_button.setText(tr("tools.rrim.cancel"))
        if not self.status_label.text():
            self.status_label.setText(tr("tools.rrim.status_ready"))
