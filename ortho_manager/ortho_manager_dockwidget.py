from .process_args import validated_process_args
from .diagnostics import record_ignored_exception as _om_record_ignored_exception
import os
import json
from .safe_xml import parse_vrt_xml
import time
import shutil
import hashlib
import subprocess  # nosec B404 # local GIS helpers use validated argument lists and shell=False.
import re
import struct
import glob
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QLabel, QTabWidget, QApplication,
    QMessageBox, QSizePolicy, QGraphicsOpacityEffect, QScrollArea, QFrame, QDialog
)
from qgis.PyQt.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap, QPainter
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMessageLog, Qgis,
    QgsLayerTreeLayer, QgsFillSymbol, QgsSingleSymbolRenderer,
    QgsLinePatternFillSymbolLayer, QgsSimpleLineSymbolLayer, QgsPointPatternFillSymbolLayer,
    QgsMarkerSymbol, QgsSettings,
    QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob, QgsFeatureRequest,
    QgsCoordinateReferenceSystem, QgsApplication, QgsProviderRegistry,
    QgsProviderSublayerDetails
)

from qgis.gui import QgsMapCanvas, QgsProjectionSelectionDialog

from .utils import PROJECT_KEY, PROJECT_ENTRY, DEFAULT_MIN_SCALE, get_plugin_version, is_supported_raster_path
from .vrt_tab import VrtTabWidget
from .export_tab import ExportTabWidget
from .inspection_tab import InspectionTabWidget
from .tools_tab import ToolsTabWidget
from .settings_tab import SettingsTabWidget
from .i18n import current_language, tr, tr_text
from .layer_lock import LayerLockManager
from .tasks import find_external_vrt_engine_path, run_external_vrt_engine_sync

VPC_POINT_CLOUD_SCALE_CAP = 2500

class OrthoManagerDockWidget(QDockWidget):
    VRT_NAME_EMOJI = "🖼️"
    VPC_NAME_EMOJI = "☁️"
    POINT_CLOUD_NAME_EMOJI = "🔹"
    GROUP_CRS_PROPERTY = "OrthoManager/group_crs_authid"

    def __init__(self, iface, parent=None):
        title = f"OrthoManager v{get_plugin_version('unknown')}"
        super().__init__(title, parent)
        self.iface = iface
        self.setWindowTitle(title)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # --- 状態管理データ ---
        self.vrt_registry = {}      # { name: {"path": path, "tif_list": []} }
        self.current_vrt_name = ""  # 現在アクティブなVRT名
        self.vpc_registry = {}      # { name: {"path": path, "source_list": []} }
        self.current_vpc_name = ""  # 現在アクティブなVPC名
        self.scale_target_mode = "vrt"
        self._scale_timer = {}      # 縮尺シグナル用の辞書
        self._vpc_scale_canvas_connected = False
        self._last_status_message = "準備完了"
        self._last_reset_completed_log_sec = 0.0
        self._reset_completed_log_interval_sec = 2.0
        self._crs_alert_label = None
        self._crs_alert_animation = None
        self._crs_alert_timer = None
        self.view_cache_enabled = False
        self._view_cache_previous_canvas_settings = {}
        self.custom_cache_enabled = False
        self._custom_cache_restore_view_cache_enabled = None
        self._custom_cache_last_key = None
        self._custom_cache_job = None
        self._custom_cache_pending = False
        self._custom_cache_canvas = None
        self._custom_cache_job_canvas = None
        self._custom_cache_job_layer = None
        self._custom_cache_job_extent = None
        self._custom_cache_job_map_to_pixel = None
        self._custom_cache_registered_canvases = []
        self._custom_cache_canvas_slots = {}
        self._custom_cache_timer = QTimer(self)
        self._custom_cache_timer.setSingleShot(True)
        self._custom_cache_timer.setInterval(300)
        self._custom_cache_timer.timeout.connect(self._run_custom_cache_prefetch)
        self.screen_shield_enabled = False
        self.mouse_shield_enabled = False
        self.mouse_shield_scale = 5
        self._screen_shield_labels = {}
        self._screen_shield_hide_timer = QTimer(self)
        self._screen_shield_hide_timer.setSingleShot(True)
        self._screen_shield_hide_timer.timeout.connect(self._hide_screen_shield_overlay)
        self._screen_shield_event_filter_installed = False
        self._screen_shield_registered_canvases = []
        self._screen_shield_canvas_timer = QTimer(self)
        self._screen_shield_canvas_timer.setInterval(1000)
        self._screen_shield_canvas_timer.timeout.connect(self._refresh_screen_shield_canvas_filters)
        self._screen_shield_mouse_drag_active = False
        self._screen_shield_mouse_shown_for_drag = False
        self._mouse_pan_light_active = False
        self._mouse_pan_light_canvas = None
        self._mouse_pan_light_canvas_settings = {}
        self._mouse_pan_snapshot_pixmap = None
        self._mouse_pan_snapshot_start_pos = None
        self._mouse_pan_snapshot_target = None
        self._mouse_pan_snapshot_margin = (0, 0)
        self._mouse_pan_current_pos = None
        self._mouse_pan_preview_pixmap = None
        self._mouse_pan_preview_margin = (0, 0)
        self._mouse_pan_preview_target_size = (0, 0)
        self._mouse_pan_preview_canvas = None
        self._mouse_pan_preview_target = None
        self._mouse_pan_preview_extent_key = None
        self._mouse_pan_preview_extent = None
        self._mouse_pan_preview_scale = 5
        self._mouse_pan_preview_job = None
        self._mouse_pan_preview_job_canvas = None
        self._mouse_pan_preview_job_target = None
        self._mouse_pan_preview_job_margin = (0, 0)
        self._mouse_pan_preview_job_size = (0, 0)
        self._mouse_pan_preview_job_key = None
        self._mouse_pan_preview_job_extent = None
        self._mouse_pan_preview_job_scale = 5
        self._mouse_pan_preview_pending = False
        self._mouse_pan_fallback_active = False
        self._mouse_pan_preview_timer = QTimer(self)
        self._mouse_pan_preview_timer.setSingleShot(True)
        self._mouse_pan_preview_timer.setInterval(250)
        self._mouse_pan_preview_timer.timeout.connect(self._start_mouse_pan_wide_preview)
        self._mouse_diag_canvas_slots = {}
        self._mouse_diag_render_start_sec = {}
        self._mouse_diag_pan_id = 0
        self._mouse_diag_last_move_log_sec = 0.0
        self._mouse_diag_last_extent_log_sec = 0.0
        self.layer_lock_manager = None

        # --- UI構築 ---
        self._build_ui()
        self.layer_lock_manager = LayerLockManager(self.iface, self)
        self.setMinimumSize(280, 200)
        self.setMaximumWidth(16777215)
        self.resize(320, self.height())
        self.load_view_cache_setting()
        self.load_custom_cache_setting()
        self.load_screen_shield_setting()
        self.load_mouse_shield_setting()

    def closeEvent(self, event):
        message = (
            "OrthoManagerのウィンドウだけを閉じます。\n"
            "プラグイン自体は停止しません。\n\n"
            "再表示する場合は、ツールバーのOrthoManagerアイコン、"
            "またはラスタメニューのOrthoManagerを押してください。\n\n"
            "完全に停止する場合は、QGISのプラグイン管理で"
            "OrthoManagerのチェックを外してください。"
        )
        reply = QMessageBox.question(
            self,
            tr_text("OrthoManagerを閉じますか？"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()

    # ==========================================
    # プロパティ (各タブから参照されるデータ)
    # ==========================================
    @property
    def tif_list(self):
        return self.vrt_registry.get(self.current_vrt_name, {}).get("tif_list", [])

    @property
    def vrt_path(self):
        return self.vrt_registry.get(self.current_vrt_name, {}).get("path", "")

    @property
    def vpc_source_list(self):
        return self.vpc_registry.get(self.current_vpc_name, {}).get("source_list", [])

    @property
    def vpc_path(self):
        return self.vpc_registry.get(self.current_vpc_name, {}).get("path", "")

    def _tif_basename_key(self, path):
        return os.path.basename(os.path.normpath(path)).lower()

    def _disable_gdal_pam(self, reason=""):
        try:
            from osgeo import gdal
            old_pam_enabled = gdal.GetConfigOption('GDAL_PAM_ENABLED')
            gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
            if reason:
                QgsMessageLog.logMessage(
                    f"{reason}: GDAL_PAM_ENABLED=NOでaux.xml生成を抑制します",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            return gdal, old_pam_enabled
        except Exception:
            return None, None

    def _restore_gdal_pam(self, gdal, old_pam_enabled):
        if not gdal:
            return
        try:
            if old_pam_enabled is None:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', None)
            else:
                gdal.SetConfigOption('GDAL_PAM_ENABLED', old_pam_enabled)
        except Exception:
            _om_record_ignored_exception(__name__, 224)

    def load_view_cache_setting(self):
        try:
            value = QgsSettings().value("OrthoManager/view_cache_enabled", False)
            if isinstance(value, str):
                enabled = value.lower() in ("1", "true", "yes", "on")
            else:
                enabled = bool(value)
        except Exception:
            enabled = False
        self.apply_view_cache_enabled(enabled, save=False, show_status=False)

    def _apply_view_cache_to_canvas(self, canvas, enabled):
        if not canvas:
            return
        if enabled:
            if canvas not in self._view_cache_previous_canvas_settings:
                self._view_cache_previous_canvas_settings[canvas] = {
                    "preview": canvas.previewJobsEnabled() if hasattr(canvas, "previewJobsEnabled") else None,
                    "cache": canvas.isCachingEnabled() if hasattr(canvas, "isCachingEnabled") else None,
                    "parallel": canvas.isParallelRenderingEnabled() if hasattr(canvas, "isParallelRenderingEnabled") else None,
                }
            if hasattr(canvas, "setPreviewJobsEnabled"):
                canvas.setPreviewJobsEnabled(True)
            if hasattr(canvas, "setCachingEnabled"):
                canvas.setCachingEnabled(True)
            if hasattr(canvas, "setParallelRenderingEnabled"):
                canvas.setParallelRenderingEnabled(True)
        else:
            previous = self._view_cache_previous_canvas_settings.get(canvas, {})
            if hasattr(canvas, "setPreviewJobsEnabled"):
                canvas.setPreviewJobsEnabled(bool(previous.get("preview", False)))
            if hasattr(canvas, "setCachingEnabled") and previous.get("cache") is not None:
                canvas.setCachingEnabled(bool(previous.get("cache")))
            if hasattr(canvas, "setParallelRenderingEnabled") and previous.get("parallel") is not None:
                canvas.setParallelRenderingEnabled(bool(previous.get("parallel")))
            self._view_cache_previous_canvas_settings.pop(canvas, None)

    def apply_view_cache_enabled(self, enabled, save=True, show_status=True):
        enabled = bool(enabled)
        self.view_cache_enabled = enabled
        try:
            for canvas in self._map_canvases():
                self._apply_view_cache_to_canvas(canvas, enabled)
            if not enabled:
                self._view_cache_previous_canvas_settings = {}
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ビューキャッシュ設定に失敗しました: {e}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )
        self._update_canvas_refresh_timer()
        if save:
            try:
                QgsSettings().setValue("OrthoManager/view_cache_enabled", enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 281)
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_view_cache_button(enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 286)
        if show_status:
            self._set_status(tr_text("✅ ビューキャッシュ ON") if enabled else tr_text("ビューキャッシュ OFF"))

    def load_custom_cache_setting(self):
        try:
            value = QgsSettings().value("OrthoManager/custom_cache_enabled", False)
            if isinstance(value, str):
                enabled = value.lower() in ("1", "true", "yes", "on")
            else:
                enabled = bool(value)
        except Exception:
            enabled = False
        self.apply_custom_cache_enabled(enabled, save=False, show_status=False)

    def _connect_custom_cache_canvas(self, canvas):
        if not self._is_canvas_alive(canvas) or canvas in self._custom_cache_registered_canvases:
            return
        try:
            slot = lambda c=canvas: self._schedule_custom_cache_prefetch(c)
            canvas.extentsChanged.connect(slot)
            self._custom_cache_registered_canvases.append(canvas)
            self._custom_cache_canvas_slots[canvas] = slot
        except Exception:
            _om_record_ignored_exception(__name__, 310)

    def _disconnect_custom_cache_canvases(self):
        for canvas in list(self._custom_cache_registered_canvases):
            try:
                slot = self._custom_cache_canvas_slots.get(canvas)
                if slot:
                    canvas.extentsChanged.disconnect(slot)
            except Exception:
                _om_record_ignored_exception(__name__, 319)
        self._custom_cache_registered_canvases = []
        self._custom_cache_canvas_slots = {}

    def _refresh_custom_cache_canvases(self):
        if not self.custom_cache_enabled:
            return
        for canvas in self._map_canvases():
            self._connect_custom_cache_canvas(canvas)

    def apply_custom_cache_enabled(self, enabled, save=True, show_status=True):
        enabled = bool(enabled)
        if enabled == self.custom_cache_enabled:
            if enabled:
                self._refresh_custom_cache_canvases()
            if hasattr(self, "vrt_tab"):
                try:
                    self.vrt_tab.update_custom_cache_button(enabled)
                except Exception:
                    _om_record_ignored_exception(__name__, 338)
            return

        self.custom_cache_enabled = enabled
        if enabled:
            self._custom_cache_restore_view_cache_enabled = self.view_cache_enabled
            self.apply_view_cache_enabled(True, save=True, show_status=False)
            self._refresh_custom_cache_canvases()
            self._schedule_custom_cache_prefetch()
        else:
            if self._custom_cache_timer:
                try:
                    self._custom_cache_timer.stop()
                except RuntimeError:
                    self._custom_cache_timer = None
            self._custom_cache_pending = False
            self._custom_cache_last_key = None
            self._custom_cache_canvas = None
            self._custom_cache_job_canvas = None
            self._custom_cache_job_layer = None
            self._custom_cache_job_extent = None
            self._custom_cache_job_map_to_pixel = None
            if self._custom_cache_job:
                try:
                    self._custom_cache_job.cancelWithoutBlocking()
                except Exception:
                    _om_record_ignored_exception(__name__, 364)
                self._custom_cache_job = None
            self._disconnect_custom_cache_canvases()
            if self._custom_cache_restore_view_cache_enabled is not None:
                self.apply_view_cache_enabled(self._custom_cache_restore_view_cache_enabled, save=True, show_status=False)
            self._custom_cache_restore_view_cache_enabled = None

        self._update_canvas_refresh_timer()
        if save:
            try:
                QgsSettings().setValue("OrthoManager/custom_cache_enabled", enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 376)
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_custom_cache_button(enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 381)
        if show_status:
            self._set_status(tr_text("✅ 独自キャッシュ ON") if enabled else tr_text("独自キャッシュ OFF"))

    def _schedule_custom_cache_prefetch(self, canvas=None):
        if not self.custom_cache_enabled:
            return
        if canvas and self._is_canvas_alive(canvas):
            self._custom_cache_canvas = canvas
        elif not self._is_canvas_alive(self._custom_cache_canvas):
            self._custom_cache_canvas = self._first_alive_canvas()
        if self._custom_cache_timer:
            try:
                self._custom_cache_timer.start()
            except RuntimeError:
                self._custom_cache_timer = None

    def _invalidate_vrt_display_caches(self, refresh=True, schedule_prefetch=False):
        try:
            if self._mouse_pan_preview_timer and self._mouse_pan_preview_timer.isActive():
                self._mouse_pan_preview_timer.stop()
        except Exception:
            _om_record_ignored_exception(__name__, 403)
        self._mouse_pan_preview_pixmap = None
        self._mouse_pan_preview_margin = (0, 0)
        self._mouse_pan_preview_target_size = (0, 0)
        self._mouse_pan_preview_canvas = None
        self._mouse_pan_preview_target = None
        self._mouse_pan_preview_extent_key = None
        self._mouse_pan_preview_extent = None
        self._mouse_pan_preview_job_canvas = None
        self._mouse_pan_preview_job_target = None
        self._mouse_pan_preview_job_margin = (0, 0)
        self._mouse_pan_preview_job_size = (0, 0)
        self._mouse_pan_preview_job_key = None
        self._mouse_pan_preview_job_extent = None
        self._mouse_pan_preview_pending = False

        if self._mouse_pan_preview_job:
            try:
                self._mouse_pan_preview_job.cancelWithoutBlocking()
            except Exception:
                _om_record_ignored_exception(__name__, 423)
            self._mouse_pan_preview_job = None

        self._mouse_pan_snapshot_pixmap = None
        self._mouse_pan_snapshot_start_pos = None
        self._mouse_pan_snapshot_target = None
        self._mouse_pan_snapshot_margin = (0, 0)
        self._mouse_pan_current_pos = None
        self._mouse_pan_fallback_active = False
        try:
            self._hide_screen_shield_overlay()
        except Exception:
            _om_record_ignored_exception(__name__, 435)

        try:
            if self._custom_cache_timer and self._custom_cache_timer.isActive():
                self._custom_cache_timer.stop()
        except Exception:
            _om_record_ignored_exception(__name__, 441)
        self._custom_cache_pending = False
        self._custom_cache_last_key = None
        self._custom_cache_canvas = None
        self._custom_cache_job_canvas = None
        self._custom_cache_job_layer = None
        self._custom_cache_job_extent = None
        self._custom_cache_job_map_to_pixel = None
        if self._custom_cache_job:
            try:
                self._custom_cache_job.cancelWithoutBlocking()
            except Exception:
                _om_record_ignored_exception(__name__, 453)
            self._custom_cache_job = None

        if refresh:
            for canvas in self._map_canvases():
                try:
                    if hasattr(canvas, "clearCache"):
                        canvas.clearCache()
                except Exception:
                    _om_record_ignored_exception(__name__, 462)
                try:
                    canvas.refresh()
                except Exception:
                    _om_record_ignored_exception(__name__, 466)
            QApplication.processEvents()
        if schedule_prefetch and self.custom_cache_enabled:
            QTimer.singleShot(250, self._schedule_custom_cache_prefetch)

    def _reset_map_display_caches(self, reason="", schedule_prefetch=False, reload_layers=True):
        self._invalidate_vrt_display_caches(refresh=False, schedule_prefetch=False)
        if reload_layers:
            for layer in list(QgsProject.instance().mapLayers().values()):
                try:
                    if hasattr(layer, "reload"):
                        layer.reload()
                    else:
                        provider = layer.dataProvider() if hasattr(layer, "dataProvider") else None
                        if provider and hasattr(provider, "reloadData"):
                            provider.reloadData()
                except Exception:
                    _om_record_ignored_exception(__name__, 483)
                try:
                    if hasattr(layer, "triggerRepaint"):
                        layer.triggerRepaint()
                except Exception:
                    _om_record_ignored_exception(__name__, 488)
        for canvas in self._map_canvases():
            try:
                if hasattr(canvas, "cancelJobs"):
                    canvas.cancelJobs()
            except Exception:
                _om_record_ignored_exception(__name__, 494)
            try:
                if hasattr(canvas, "clearCache"):
                    canvas.clearCache()
            except Exception:
                _om_record_ignored_exception(__name__, 499)
            try:
                if hasattr(canvas, "redrawAllLayers"):
                    canvas.redrawAllLayers()
            except Exception:
                _om_record_ignored_exception(__name__, 504)
            try:
                if hasattr(canvas, "refreshAllLayers"):
                    canvas.refreshAllLayers()
                else:
                    canvas.refresh()
            except Exception:
                try:
                    canvas.refresh()
                except Exception:
                    _om_record_ignored_exception(__name__, 514)
        QApplication.processEvents()
        if schedule_prefetch and self.custom_cache_enabled:
            QTimer.singleShot(250, self._schedule_custom_cache_prefetch)

    def cleanup_before_unload(self):
        try:
            if hasattr(self, "inspection_tab"):
                self.inspection_tab.cleanup_before_unload()
        except Exception:
            _om_record_ignored_exception(__name__, 524)
        try:
            if self.layer_lock_manager is not None:
                self.layer_lock_manager.cleanup()
        except Exception:
            _om_record_ignored_exception(__name__, 529)
        try:
            self.custom_cache_enabled = False
            self._disconnect_custom_cache_canvases()
            self._remove_screen_shield_event_filter(None)
            if self._custom_cache_timer:
                try:
                    self._custom_cache_timer.stop()
                except RuntimeError:
                    _om_record_ignored_exception(__name__, 538)
                self._custom_cache_timer = None
            if self._custom_cache_job:
                try:
                    self._custom_cache_job.cancelWithoutBlocking()
                except Exception:
                    _om_record_ignored_exception(__name__, 544)
            self._custom_cache_job = None
            self._custom_cache_job_canvas = None
            self._custom_cache_job_layer = None
            self._custom_cache_job_extent = None
            self._custom_cache_job_map_to_pixel = None
        except Exception:
            _om_record_ignored_exception(__name__, 551)

    def _is_vrt_raster_visible_now(self, vrt_layer, canvas=None):
        if not vrt_layer:
            return False
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(vrt_layer.id())
            if node and not node.isVisible():
                return False
        except Exception:
            _om_record_ignored_exception(__name__, 561)
        try:
            active_canvas = canvas or self.iface.mapCanvas()
            scale = active_canvas.scale()
            if hasattr(vrt_layer, "isInScaleRange"):
                if not vrt_layer.isInScaleRange(scale):
                    return False
            elif vrt_layer.hasScaleBasedVisibility():
                min_scale = float(vrt_layer.minimumScale())
                max_scale = float(vrt_layer.maximumScale())
                if min_scale and scale > min_scale:
                    return False
                if max_scale and scale < max_scale:
                    return False
        except Exception:
            _om_record_ignored_exception(__name__, 576)
        try:
            active_canvas = canvas or self.iface.mapCanvas()
            return vrt_layer.extent().intersects(active_canvas.extent())
        except Exception:
            return True

    def _is_canvas_alive(self, canvas):
        if not canvas:
            return False
        try:
            canvas.width()
            canvas.height()
            canvas.extent()
            return True
        except RuntimeError:
            return False
        except Exception:
            return False

    def _first_alive_canvas(self):
        for canvas in self._map_canvases():
            if self._is_canvas_alive(canvas):
                return canvas
        try:
            canvas = self.iface.mapCanvas()
            if self._is_canvas_alive(canvas):
                return canvas
        except Exception:
            _om_record_ignored_exception(__name__, 605)
        return None

    def _expanded_extent_for_custom_cache(self, overlay_layer, canvas_extent):
        features = []
        try:
            request = QgsFeatureRequest().setFilterRect(canvas_extent)
            for feat in overlay_layer.getFeatures(request):
                geom = feat.geometry()
                if geom and not geom.isEmpty():
                    features.append(geom.boundingBox())
                    if len(features) >= 40:
                        break
        except Exception:
            features = []
        if not features:
            try:
                for feat in overlay_layer.getFeatures():
                    geom = feat.geometry()
                    if geom and not geom.isEmpty():
                        features.append(geom.boundingBox())
                        if len(features) >= 40:
                            break
            except Exception:
                return None
        if not features:
            return None
        widths = [r.width() for r in features if r.width() > 0]
        heights = [r.height() for r in features if r.height() > 0]
        canvas_width = canvas_extent.width()
        canvas_height = canvas_extent.height()
        if canvas_width <= 0 or canvas_height <= 0:
            return None
        tile_pad_x = (sum(widths) / len(widths)) if widths else 0
        tile_pad_y = (sum(heights) / len(heights)) if heights else 0
        pad_x = max(canvas_width * 4.0, tile_pad_x * 2.0)
        pad_y = max(canvas_height * 4.0, tile_pad_y * 2.0)
        expanded = QgsRectangle(
            canvas_extent.xMinimum() - pad_x,
            canvas_extent.yMinimum() - pad_y,
            canvas_extent.xMaximum() + pad_x,
            canvas_extent.yMaximum() + pad_y,
        )
        try:
            layer_extent = overlay_layer.extent()
            if layer_extent and not layer_extent.isEmpty():
                expanded = expanded.intersect(layer_extent)
        except Exception:
            _om_record_ignored_exception(__name__, 653)
        return expanded

    def _run_custom_cache_prefetch(self):
        if not self.custom_cache_enabled:
            return
        if self._custom_cache_job and self._custom_cache_job.isActive():
            self._custom_cache_pending = True
            return
        vrt_layer = self._get_vrt_layer(self.current_vrt_name)
        overlay_layer = self._get_overlay_layer(self.current_vrt_name)
        canvas = self._custom_cache_canvas if self._is_canvas_alive(self._custom_cache_canvas) else self._first_alive_canvas()
        self._custom_cache_canvas = canvas
        if not vrt_layer or not overlay_layer or not canvas or not self._is_vrt_raster_visible_now(vrt_layer, canvas):
            return
        try:
            canvas_extent = QgsRectangle(canvas.extent())
            expanded_extent = self._expanded_extent_for_custom_cache(overlay_layer, canvas_extent)
            if not expanded_extent or expanded_extent.isEmpty():
                return
            key = (
                self.current_vrt_name,
                round(expanded_extent.xMinimum(), 3), round(expanded_extent.yMinimum(), 3),
                round(expanded_extent.xMaximum(), 3), round(expanded_extent.yMaximum(), 3),
                round(canvas.scale(), 1),
            )
            if key == self._custom_cache_last_key:
                return
            self._custom_cache_last_key = key

            settings = QgsMapSettings(canvas.mapSettings())
            settings.setLayers([vrt_layer])
            settings.setExtent(expanded_extent)
            settings.setOutputSize(canvas.size())
            job = QgsMapRendererParallelJob(settings)
            job.finished.connect(self._on_custom_cache_job_finished)
            self._custom_cache_job = job
            self._custom_cache_job_canvas = canvas
            self._custom_cache_job_layer = vrt_layer
            self._custom_cache_job_extent = QgsRectangle(expanded_extent)
            self._custom_cache_job_map_to_pixel = settings.mapToPixel()
            job.start()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"独自キャッシュ先読みエラー: {e}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )
            self._custom_cache_job = None

    def _on_custom_cache_job_finished(self):
        job = self._custom_cache_job
        canvas = self._custom_cache_job_canvas
        vrt_layer = self._custom_cache_job_layer
        extent = self._custom_cache_job_extent
        map_to_pixel = self._custom_cache_job_map_to_pixel
        self._custom_cache_job = None
        self._custom_cache_job_canvas = None
        self._custom_cache_job_layer = None
        self._custom_cache_job_extent = None
        self._custom_cache_job_map_to_pixel = None
        try:
            if job and self._is_canvas_alive(canvas) and vrt_layer and extent and map_to_pixel:
                image = job.renderedImage()
                if image and not image.isNull():
                    cache = canvas.cache() if hasattr(canvas, "cache") else None
                    cache_key = vrt_layer.id()
                    if cache and hasattr(cache, "setCacheImageWithParameters"):
                        cache.setCacheImageWithParameters(cache_key, image, extent, map_to_pixel, [vrt_layer])
                        has_cache = cache.hasCacheImage(cache_key) if hasattr(cache, "hasCacheImage") else False

                    else:
                        QgsMessageLog.logMessage(
                            "CUSTOM_CACHE_STORE_SKIPPED cache_api_unavailable",
                            "OrthoManager", Qgis.MessageLevel.Warning
                        )
                else:
                    QgsMessageLog.logMessage(
                        "CUSTOM_CACHE_STORE_SKIPPED rendered_image_empty",
                        "OrthoManager", Qgis.MessageLevel.Warning
                    )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"CUSTOM_CACHE_STORE_FAILED {e}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )
        if self.custom_cache_enabled and self._custom_cache_pending:
            self._custom_cache_pending = False
            self._schedule_custom_cache_prefetch()

    def load_screen_shield_setting(self):
        try:
            value = QgsSettings().value("OrthoManager/screen_shield_enabled", False)
            if isinstance(value, str):
                enabled = value.lower() in ("1", "true", "yes", "on")
            else:
                enabled = bool(value)
        except Exception:
            enabled = False
        self.apply_screen_shield_enabled(enabled, save=False, show_status=False)

    def apply_screen_shield_enabled(self, enabled, save=True, show_status=True):
        enabled = bool(enabled)
        self.screen_shield_enabled = enabled
        canvas = self.iface.mapCanvas()
        if enabled or self.mouse_shield_enabled:
            self._install_screen_shield_event_filter(canvas)
        else:
            self._remove_screen_shield_event_filter(canvas)
            self._hide_screen_shield_overlay()
        if save:
            try:
                QgsSettings().setValue("OrthoManager/screen_shield_enabled", enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 767)
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_screen_shield_button(enabled)
            except Exception:
                _om_record_ignored_exception(__name__, 772)
        if show_status:
            self._set_status(tr_text("✅ 画面シールド ON") if enabled else tr_text("画面シールド OFF"))

    def load_mouse_shield_setting(self):
        try:
            enabled_value = QgsSettings().value("OrthoManager/mouse_shield_enabled", False)
            if isinstance(enabled_value, str):
                enabled = enabled_value.lower() in ("1", "true", "yes", "on")
            else:
                enabled = bool(enabled_value)
            scale_value = QgsSettings().value("OrthoManager/mouse_shield_scale", None)
            if scale_value is None or scale_value == "":
                scale = 5
            else:
                scale = self._normalize_mouse_shield_scale(scale_value, default=5)
        except Exception:
            enabled = False
            scale = 5
        self.mouse_shield_scale = scale if scale in (1, 2, 3, 4, 5, 6) else 5
        self.apply_mouse_shield_enabled(self.mouse_shield_scale if enabled else False, save=False, show_status=False)

    def _normalize_mouse_shield_scale(self, value, default=5):
        allowed = (1, 2, 3, 4, 5, 6)
        if isinstance(value, bool):
            return default if value and default in allowed else (4 if value else 0)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "on"):
                return default if default in allowed else 4
            if text in ("0", "false", "no", "off", ""):
                return 0
            try:
                value = int(float(text))
            except Exception:
                return default if default in allowed else 0
        try:
            scale = int(value)
        except Exception:
            return default if default in allowed else 0
        return scale if scale in allowed else (default if default in allowed else 0)

    def apply_mouse_shield_enabled(self, enabled, save=True, show_status=True):
        previous_scale = self.mouse_shield_scale
        if isinstance(enabled, bool):
            scale = self._normalize_mouse_shield_scale(enabled, default=previous_scale)
        else:
            scale = self._normalize_mouse_shield_scale(enabled, default=previous_scale)
        enabled = scale in (1, 2, 3, 4, 5, 6)
        self.mouse_shield_enabled = enabled
        self.mouse_shield_scale = scale if enabled else previous_scale if previous_scale in (1, 2, 3, 4, 5, 6) else 5
        if previous_scale != self.mouse_shield_scale:
            self._clear_mouse_pan_preview("shield_scale_changed")
            self._mouse_pan_preview_pending = False
        canvas = self.iface.mapCanvas()
        if enabled or self.screen_shield_enabled:
            self._install_screen_shield_event_filter(canvas)
            if enabled:
                self._mouse_diag_log(
                    f"ENABLED {self._mouse_diag_canvas_state(canvas)}"
                )
                self._queue_mouse_pan_wide_preview(canvas, delay_ms=120)
        else:
            self._remove_screen_shield_event_filter(canvas)
            self._hide_screen_shield_overlay()
            self._mouse_diag_log("DISABLED")
        if save:
            try:
                QgsSettings().setValue("OrthoManager/mouse_shield_enabled", enabled)
                QgsSettings().setValue("OrthoManager/mouse_shield_scale", self.mouse_shield_scale)
            except Exception:
                _om_record_ignored_exception(__name__, 843)
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_mouse_shield_controls(self.mouse_shield_enabled, self.mouse_shield_scale)
            except Exception:
                _om_record_ignored_exception(__name__, 848)
        if show_status:
            self._set_status(
                tr_text(f"✅ マウスシールド {self.mouse_shield_scale}x ON")
                if enabled
                else tr_text("マウスシールド OFF")
            )

    def _map_canvases(self):
        canvases = []
        try:
            for canvas in self.iface.mapCanvases() or []:
                if canvas and canvas not in canvases:
                    canvases.append(canvas)
        except Exception:
            _om_record_ignored_exception(__name__, 863)
        try:
            canvas = self.iface.mapCanvas()
            if canvas and canvas not in canvases:
                canvases.append(canvas)
        except Exception:
            _om_record_ignored_exception(__name__, 869)
        return canvases

    def _canvas_from_event_object(self, obj):
        for canvas in list(self._screen_shield_registered_canvases):
            try:
                if obj is canvas or obj is canvas.viewport():
                    return canvas
            except Exception:
                _om_record_ignored_exception(__name__, 878)
        return None

    def _mouse_diag_log(self, message, level=Qgis.MessageLevel.Info):
        return

    def _mouse_diag_extent_text(self, canvas):
        try:
            extent = canvas.extent()
            return (
                f"scale={canvas.scale():.1f} "
                f"extent=({extent.xMinimum():.2f},{extent.yMinimum():.2f},"
                f"{extent.xMaximum():.2f},{extent.yMaximum():.2f}) "
                f"size={canvas.width()}x{canvas.height()}"
            )
        except Exception as exc:
            return f"extent_error={exc}"

    def _mouse_diag_canvas_state(self, canvas):
        parts = [f"shield_scale={self.mouse_shield_scale}"]
        for label, method_name in (
            ("preview", "previewJobsEnabled"),
            ("cache", "isCachingEnabled"),
            ("parallel", "isParallelRenderingEnabled"),
            ("interval", "mapUpdateInterval"),
        ):
            try:
                method = getattr(canvas, method_name)
                parts.append(f"{label}={method()}")
            except Exception:
                _om_record_ignored_exception(__name__, 908)
        try:
            layer = self._get_vrt_layer(self.current_vrt_name)
            if layer:
                parts.append(f"layer={layer.id()}")
                cache = canvas.cache()
                if cache and hasattr(cache, "hasCacheImage"):
                    parts.append(f"layer_cache={cache.hasCacheImage(layer.id())}")
        except Exception:
            _om_record_ignored_exception(__name__, 917)
        parts.append(self._mouse_diag_extent_text(canvas))
        return " ".join(parts)

    def _connect_mouse_diag_canvas(self, canvas):
        if not self._is_canvas_alive(canvas) or canvas in self._mouse_diag_canvas_slots:
            return
        slots = []
        for signal_name, handler in (
            ("extentsChanged", self._on_mouse_diag_extent_changed),
            ("renderStarting", self._on_mouse_diag_render_start),
            ("renderComplete", self._on_mouse_diag_render_complete),
            ("mapCanvasRefreshed", self._on_mouse_diag_canvas_refreshed),
        ):
            try:
                signal = getattr(canvas, signal_name)
                slot = lambda *args, c=canvas, h=handler: h(c, *args)
                signal.connect(slot)
                slots.append((signal, slot))
            except Exception:
                _om_record_ignored_exception(__name__, 937)
        if slots:
            self._mouse_diag_canvas_slots[canvas] = slots

    def _disconnect_mouse_diag_canvases(self):
        for canvas, slots in list(self._mouse_diag_canvas_slots.items()):
            for signal, slot in slots:
                try:
                    signal.disconnect(slot)
                except Exception:
                    _om_record_ignored_exception(__name__, 947)
        self._mouse_diag_canvas_slots = {}
        self._mouse_diag_render_start_sec = {}

    def _clear_mouse_pan_preview(self, reason=None):
        self._mouse_pan_preview_pixmap = None
        self._mouse_pan_preview_margin = (0, 0)
        self._mouse_pan_preview_target_size = (0, 0)
        self._mouse_pan_preview_target = None
        self._mouse_pan_preview_extent_key = None
        self._mouse_pan_preview_extent = None
        self._mouse_pan_preview_scale = 0
        if reason:
            self._mouse_diag_log(f"PREVIEW_CLEAR reason={reason}")

    def invalidate_interaction_image_caches(self, reason=None):
        try:
            if self._mouse_pan_preview_timer:
                self._mouse_pan_preview_timer.stop()
        except Exception:
            _om_record_ignored_exception(__name__, 967)
        try:
            if self._mouse_pan_preview_job and self._mouse_pan_preview_job.isActive():
                self._mouse_pan_preview_job.cancelWithoutBlocking()
        except Exception:
            _om_record_ignored_exception(__name__, 972)
        self._mouse_pan_preview_job = None
        self._mouse_pan_preview_job_canvas = None
        self._mouse_pan_preview_job_target = None
        self._mouse_pan_preview_job_key = None
        self._mouse_pan_preview_job_extent = None
        self._mouse_pan_preview_pending = False
        self._clear_mouse_pan_preview(reason)
        self._mouse_pan_snapshot_pixmap = None
        self._mouse_pan_snapshot_start_pos = None
        self._mouse_pan_snapshot_target = None
        self._mouse_pan_snapshot_margin = (0, 0)
        self._mouse_pan_current_pos = None
        self._mouse_pan_fallback_active = False
        self._custom_cache_last_key = None

    def _mouse_pan_scale_matches(self, canvas, key=None):
        key = key or self._mouse_pan_preview_extent_key
        if key is None or len(key) < 7:
            return False
        try:
            current_scale = round(canvas.scale(), 1)
            preview_scale = float(key[6])
        except Exception:
            return False
        return abs(current_scale - preview_scale) <= max(0.2, preview_scale * 0.0005)

    def _on_mouse_diag_extent_changed(self, canvas, *args):
        if not self.mouse_shield_enabled:
            return
        if not self._mouse_pan_light_active and self._mouse_pan_preview_extent_key is not None:
            if not self._mouse_pan_scale_matches(canvas):
                self._clear_mouse_pan_preview("scale_changed")
                try:
                    if self._mouse_pan_preview_job and self._mouse_pan_preview_job.isActive():
                        self._mouse_pan_preview_job.cancelWithoutBlocking()
                except Exception:
                    _om_record_ignored_exception(__name__, 1009)
                self._queue_mouse_pan_wide_preview(canvas, delay_ms=120)
        now = time.perf_counter()
        if not self._mouse_pan_light_active and now - self._mouse_diag_last_extent_log_sec < 0.4:
            return
        self._mouse_diag_last_extent_log_sec = now
        phase = "drag" if self._mouse_pan_light_active else "idle"
        self._mouse_diag_log(
            f"EXTENT_CHANGED phase={phase} pan={self._mouse_diag_pan_id} "
            f"{self._mouse_diag_canvas_state(canvas)}"
        )

    def _on_mouse_diag_render_start(self, canvas, *args):
        if not self.mouse_shield_enabled:
            return
        self._mouse_diag_render_start_sec[canvas] = time.perf_counter()
        phase = "drag" if self._mouse_pan_light_active else "idle"
        self._mouse_diag_log(
            f"RENDER_START phase={phase} pan={self._mouse_diag_pan_id} "
            f"{self._mouse_diag_canvas_state(canvas)}"
        )

    def _on_mouse_diag_render_complete(self, canvas, *args):
        if not self.mouse_shield_enabled:
            return
        elapsed_ms = None
        start_sec = self._mouse_diag_render_start_sec.get(canvas)
        if start_sec is not None:
            elapsed_ms = int((time.perf_counter() - start_sec) * 1000)
        phase = "drag" if self._mouse_pan_light_active else "idle"
        elapsed = f" elapsed_ms={elapsed_ms}" if elapsed_ms is not None else ""
        self._mouse_diag_log(
            f"RENDER_COMPLETE phase={phase} pan={self._mouse_diag_pan_id}{elapsed} "
            f"{self._mouse_diag_canvas_state(canvas)}"
        )

    def _on_mouse_diag_canvas_refreshed(self, canvas, *args):
        if not self.mouse_shield_enabled:
            return
        if not self._mouse_pan_light_active:
            return
        phase = "drag" if self._mouse_pan_light_active else "idle"
        self._mouse_diag_log(
            f"CANVAS_REFRESHED phase={phase} pan={self._mouse_diag_pan_id} "
            f"{self._mouse_diag_canvas_state(canvas)}"
        )

    def _register_screen_shield_canvas(self, canvas):
        if not canvas or canvas in self._screen_shield_registered_canvases:
            return
        try:
            canvas.installEventFilter(self)
            if canvas.viewport():
                canvas.viewport().installEventFilter(self)
            self._screen_shield_registered_canvases.append(canvas)
            if self.mouse_shield_enabled:
                self._connect_mouse_diag_canvas(canvas)
        except Exception:
            _om_record_ignored_exception(__name__, 1067)

    def _update_canvas_refresh_timer(self):
        should_run = self.screen_shield_enabled or self.mouse_shield_enabled or self.view_cache_enabled or self.custom_cache_enabled
        if should_run:
            if not self._screen_shield_canvas_timer.isActive():
                self._screen_shield_canvas_timer.start()
        else:
            self._screen_shield_canvas_timer.stop()

    def _refresh_screen_shield_canvas_filters(self):
        for canvas in self._map_canvases():
            if self.view_cache_enabled:
                self._apply_view_cache_to_canvas(canvas, True)
            if self.custom_cache_enabled:
                self._connect_custom_cache_canvas(canvas)
            if self.screen_shield_enabled or self.mouse_shield_enabled:
                self._register_screen_shield_canvas(canvas)
            if self.mouse_shield_enabled:
                self._connect_mouse_diag_canvas(canvas)
                self._queue_mouse_pan_wide_preview(canvas, delay_ms=350)

    def _install_screen_shield_event_filter(self, canvas):
        try:
            self._refresh_screen_shield_canvas_filters()
            if not self._screen_shield_canvas_timer.isActive():
                self._screen_shield_canvas_timer.start()
            self._screen_shield_event_filter_installed = True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"画面シールド初期化エラー: {e}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )

    def _remove_screen_shield_event_filter(self, canvas):
        try:
            try:
                self._screen_shield_canvas_timer.stop()
            except RuntimeError:
                _om_record_ignored_exception(__name__, 1106)
            for map_canvas in list(self._screen_shield_registered_canvases):
                try:
                    map_canvas.removeEventFilter(self)
                    if map_canvas.viewport():
                        map_canvas.viewport().removeEventFilter(self)
                except Exception:
                    _om_record_ignored_exception(__name__, 1113)
            self._screen_shield_registered_canvases = []
            self._disconnect_mouse_diag_canvases()
        except Exception:
            _om_record_ignored_exception(__name__, 1117)
        self._screen_shield_event_filter_installed = False

    def _should_screen_shield_for_key(self, event, canvas):
        if not self.screen_shield_enabled:
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        if hasattr(event, "isAutoRepeat") and event.isAutoRepeat():
            return False
        if event.key() not in (
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Up, Qt.Key.Key_Down,
        ):
            return False
        return self._is_vrt_raster_visible_now(self._get_vrt_layer(self.current_vrt_name), canvas)

    def _apply_mouse_pan_light_mode(self, canvas):
        if not self._is_canvas_alive(canvas):
            return
        if canvas not in self._mouse_pan_light_canvas_settings:
            self._mouse_pan_light_canvas_settings[canvas] = {
                "preview": canvas.previewJobsEnabled() if hasattr(canvas, "previewJobsEnabled") else None,
                "cache": canvas.isCachingEnabled() if hasattr(canvas, "isCachingEnabled") else None,
                "parallel": canvas.isParallelRenderingEnabled() if hasattr(canvas, "isParallelRenderingEnabled") else None,
                "update_interval": canvas.mapUpdateInterval() if hasattr(canvas, "mapUpdateInterval") else None,
            }
        try:
            if hasattr(canvas, "setPreviewJobsEnabled"):
                canvas.setPreviewJobsEnabled(True)
            if hasattr(canvas, "setCachingEnabled"):
                canvas.setCachingEnabled(True)
            if hasattr(canvas, "setParallelRenderingEnabled"):
                canvas.setParallelRenderingEnabled(True)
            if hasattr(canvas, "setMapUpdateInterval"):
                canvas.setMapUpdateInterval(20)
        except Exception:
            _om_record_ignored_exception(__name__, 1154)

    def _restore_mouse_pan_light_mode(self, canvas=None):
        targets = [canvas] if canvas else list(self._mouse_pan_light_canvas_settings.keys())
        for target in targets:
            settings = self._mouse_pan_light_canvas_settings.pop(target, {})
            if not self._is_canvas_alive(target):
                continue
            try:
                if hasattr(target, "setPreviewJobsEnabled") and settings.get("preview") is not None:
                    target.setPreviewJobsEnabled(bool(settings.get("preview")))
                if hasattr(target, "setCachingEnabled") and settings.get("cache") is not None:
                    target.setCachingEnabled(bool(settings.get("cache")))
                if hasattr(target, "setParallelRenderingEnabled") and settings.get("parallel") is not None:
                    target.setParallelRenderingEnabled(bool(settings.get("parallel")))
                if hasattr(target, "setMapUpdateInterval") and settings.get("update_interval") is not None:
                    target.setMapUpdateInterval(int(settings.get("update_interval")))
                QTimer.singleShot(60, target.refresh)
            except Exception:
                _om_record_ignored_exception(__name__, 1173)

    def _mouse_event_xy(self, event):
        try:
            pos = event.position()
        except AttributeError:
            pos = event.pos()
        return int(pos.x()), int(pos.y())

    def _mouse_pan_label_for_target(self, target):
        label = self._screen_shield_labels.get(target)
        if label is None:
            label = QLabel(target)
            label.setObjectName("OrthoManagerMousePanShield")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setScaledContents(False)
            self._screen_shield_labels[target] = label
        return label

    def set_mouse_shield_scale(self, scale, save=True, show_status=True):
        scale = self._normalize_mouse_shield_scale(scale, default=self.mouse_shield_scale)
        if scale == 0:
            scale = 5
        previous_scale = self.mouse_shield_scale
        self.mouse_shield_scale = scale
        if previous_scale != scale:
            self._clear_mouse_pan_preview("shield_scale_changed")
            self._mouse_pan_preview_pending = False
            if self.mouse_shield_enabled:
                canvas = self.iface.mapCanvas()
                self._queue_mouse_pan_wide_preview(canvas, delay_ms=80)
        if save:
            try:
                QgsSettings().setValue("OrthoManager/mouse_shield_scale", self.mouse_shield_scale)
            except Exception:
                _om_record_ignored_exception(__name__, 1208)
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_mouse_shield_controls(self.mouse_shield_enabled, self.mouse_shield_scale)
            except Exception:
                _om_record_ignored_exception(__name__, 1213)
        if show_status:
            self._set_status(tr_text(f"マウスシールド倍率 {self.mouse_shield_scale}x"))

    def _mouse_pan_wide_settings(self, canvas, target):
        width = max(1, target.width())
        height = max(1, target.height())
        scale = self.mouse_shield_scale if self.mouse_shield_scale in (1, 2, 3, 4, 5, 6) else 5
        extent = QgsRectangle(canvas.extent())
        center_x = (extent.xMinimum() + extent.xMaximum()) / 2.0
        center_y = (extent.yMinimum() + extent.yMaximum()) / 2.0
        map_width = extent.width() * scale
        map_height = extent.height() * scale
        wide_extent = QgsRectangle(
            center_x - map_width / 2.0,
            center_y - map_height / 2.0,
            center_x + map_width / 2.0,
            center_y + map_height / 2.0,
        )
        key = (
            round(wide_extent.xMinimum(), 2),
            round(wide_extent.yMinimum(), 2),
            round(wide_extent.xMaximum(), 2),
            round(wide_extent.yMaximum(), 2),
            width,
            height,
            round(canvas.scale(), 1),
        )
        settings = QgsMapSettings(canvas.mapSettings())
        settings.setExtent(wide_extent)
        settings.setOutputSize(QSize(width * scale, height * scale))
        margin = (int(round(width * (scale - 1) / 2)), int(round(height * (scale - 1) / 2)))
        return settings, margin, (width, height), key, wide_extent, scale

    def _queue_mouse_pan_wide_preview(self, canvas=None, delay_ms=250):
        if not self.mouse_shield_enabled:
            return
        if self._mouse_pan_light_active:
            return
        canvas = canvas if self._is_canvas_alive(canvas) else self._first_alive_canvas()
        if not self._is_canvas_alive(canvas):
            return
        if not self._is_vrt_raster_visible_now(self._get_vrt_layer(self.current_vrt_name), canvas):
            return
        self._mouse_pan_preview_canvas = canvas
        try:
            if delay_ms <= 120 or self._mouse_pan_light_active:
                self._mouse_diag_log(
                    f"WIDE_PREVIEW_QUEUE delay_ms={delay_ms} "
                    f"active={self._mouse_pan_light_active} {self._mouse_diag_canvas_state(canvas)}"
                )
            self._mouse_pan_preview_timer.start(max(0, int(delay_ms)))
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"MOUSE_SHIELD_WIDE_PREVIEW_QUEUE_FAILED: {exc}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )

    def _start_mouse_pan_wide_preview(self):
        if not self.mouse_shield_enabled:
            return
        if self._mouse_pan_light_active:
            self._mouse_pan_preview_pending = True
            self._mouse_diag_log("WIDE_PREVIEW_DEFERRED active_drag=True")
            return
        if self._mouse_pan_preview_job and self._mouse_pan_preview_job.isActive():
            self._mouse_pan_preview_pending = True
            self._mouse_diag_log("WIDE_PREVIEW_PENDING existing_job_active=True")
            return
        canvas = self._mouse_pan_preview_canvas if self._is_canvas_alive(self._mouse_pan_preview_canvas) else self._first_alive_canvas()
        if not self._is_canvas_alive(canvas):
            return
        target = canvas.viewport() or canvas
        try:
            settings, margin, size, key, wide_extent, scale = self._mouse_pan_wide_settings(canvas, target)
            if key == self._mouse_pan_preview_extent_key and self._mouse_pan_preview_pixmap is not None and not self._mouse_pan_preview_pixmap.isNull():
                return
            self._mouse_diag_log(
                f"WIDE_PREVIEW_START key={key} margin={margin} size={size} "
                f"{self._mouse_diag_canvas_state(canvas)}"
            )
            job = QgsMapRendererParallelJob(settings)
            job.finished.connect(self._on_mouse_pan_wide_preview_finished)
            self._mouse_pan_preview_job = job
            self._mouse_pan_preview_job_canvas = canvas
            self._mouse_pan_preview_job_target = target
            self._mouse_pan_preview_job_margin = margin
            self._mouse_pan_preview_job_size = size
            self._mouse_pan_preview_job_key = key
            self._mouse_pan_preview_job_extent = QgsRectangle(wide_extent)
            self._mouse_pan_preview_job_scale = scale
            job.start()
        except Exception as exc:
            self._mouse_pan_preview_job = None
            QgsMessageLog.logMessage(
                f"MOUSE_SHIELD_WIDE_PREVIEW_START_FAILED: {exc}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )

    def _on_mouse_pan_wide_preview_finished(self):
        job = self._mouse_pan_preview_job
        if job is None:
            return
        try:
            image = job.renderedImage()
            if not image.isNull():
                if self._mouse_pan_preview_job_scale != self.mouse_shield_scale:
                    self._mouse_diag_log(
                        "WIDE_PREVIEW_DISCARD "
                        f"reason=shield_scale_changed job_scale={self._mouse_pan_preview_job_scale} "
                        f"current_scale={self.mouse_shield_scale}"
                    )
                    if not self._mouse_pan_light_active and self.mouse_shield_enabled:
                        self._mouse_pan_preview_pending = True
                    return
                if self._is_canvas_alive(self._mouse_pan_preview_job_canvas):
                    if not self._mouse_pan_scale_matches(
                        self._mouse_pan_preview_job_canvas,
                        self._mouse_pan_preview_job_key,
                    ):
                        self._mouse_diag_log(
                            f"WIDE_PREVIEW_DISCARD reason=scale_mismatch job_key={self._mouse_pan_preview_job_key}"
                        )
                        if not self._mouse_pan_light_active:
                            self._mouse_pan_preview_pending = True
                        return
                self._mouse_diag_log(
                    f"WIDE_PREVIEW_FINISH image={image.width()}x{image.height()} "
                    f"job_key={self._mouse_pan_preview_job_key}"
                )
                self._mouse_pan_preview_pixmap = QPixmap.fromImage(image)
                self._mouse_pan_preview_margin = self._mouse_pan_preview_job_margin
                self._mouse_pan_preview_target_size = self._mouse_pan_preview_job_size
                self._mouse_pan_preview_target = self._mouse_pan_preview_job_target
                self._mouse_pan_preview_extent_key = self._mouse_pan_preview_job_key
                self._mouse_pan_preview_extent = (
                    QgsRectangle(self._mouse_pan_preview_job_extent)
                    if self._mouse_pan_preview_job_extent is not None
                    else None
                )
                self._mouse_pan_preview_scale = self._mouse_pan_preview_job_scale
                current_margin = None
                if self._is_canvas_alive(self._mouse_pan_preview_job_canvas) and self._mouse_pan_preview_job_target is not None:
                    try:
                        current_margin = self._mouse_pan_preview_offset(
                            self._mouse_pan_preview_job_canvas,
                            self._mouse_pan_preview_job_target,
                        )
                    except Exception:
                        current_margin = None
                if (
                    current_margin is not None
                    and self._mouse_pan_light_active
                    and self._mouse_pan_snapshot_target is self._mouse_pan_preview_job_target
                ):
                    if self._mouse_pan_fallback_active:
                        self._mouse_diag_log(f"WIDE_PREVIEW_RECOVER_ACTIVE_DRAG accepted=True margin={current_margin}")
                        self._mouse_pan_snapshot_pixmap = self._mouse_pan_preview_pixmap
                        self._mouse_pan_snapshot_margin = current_margin
                        self._mouse_pan_fallback_active = False
                        if self._mouse_pan_current_pos is not None:
                            self._mouse_pan_snapshot_start_pos = self._mouse_pan_current_pos
                        target = self._mouse_pan_snapshot_target
                        if target is not None:
                            label = self._mouse_pan_label_for_target(target)
                            label.setPixmap(self._mouse_pan_snapshot_pixmap)
                            label.setGeometry(
                                -current_margin[0],
                                -current_margin[1],
                                self._mouse_pan_snapshot_pixmap.width(),
                                self._mouse_pan_snapshot_pixmap.height(),
                            )
                            label.raise_()
                            label.show()
                    else:
                        self._mouse_diag_log(f"WIDE_PREVIEW_READY_DURING_DRAG kept_for_next_pan=True margin={current_margin}")
                elif self._mouse_pan_light_active:
                    self._mouse_diag_log(
                        f"WIDE_PREVIEW_NOT_APPLIED active_drag=True reason=outside_preview "
                        f"job_key={self._mouse_pan_preview_job_key}"
                    )
            else:
                self._mouse_diag_log("WIDE_PREVIEW_FINISH image_is_null=True", Qgis.MessageLevel.Warning)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"MOUSE_SHIELD_WIDE_PREVIEW_FINISH_FAILED: {exc}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )
        finally:
            self._mouse_pan_preview_job = None
            self._mouse_pan_preview_job_canvas = None
            self._mouse_pan_preview_job_target = None
            self._mouse_pan_preview_job_extent = None
            if self._mouse_pan_preview_pending:
                self._mouse_pan_preview_pending = False
                self._queue_mouse_pan_wide_preview(delay_ms=80)

    def _mouse_pan_preview_offset(self, canvas, target):
        if self._mouse_pan_preview_extent is None:
            return None
        if self._mouse_pan_preview_pixmap is None or self._mouse_pan_preview_pixmap.isNull():
            return None
        if not self._mouse_pan_scale_matches(canvas):
            return None
        if self._mouse_pan_preview_target is not target:
            return None
        if self._mouse_pan_preview_target_size != (target.width(), target.height()):
            return None
        current = QgsRectangle(canvas.extent())
        preview = self._mouse_pan_preview_extent
        tolerance = max(preview.width(), preview.height()) * 0.0005
        if (
            current.xMinimum() < preview.xMinimum() - tolerance
            or current.xMaximum() > preview.xMaximum() + tolerance
            or current.yMinimum() < preview.yMinimum() - tolerance
            or current.yMaximum() > preview.yMaximum() + tolerance
        ):
            return None
        source = self._mouse_pan_preview_pixmap
        if preview.width() <= 0 or preview.height() <= 0:
            return None
        offset_x = int(round((current.xMinimum() - preview.xMinimum()) / preview.width() * source.width()))
        offset_y = int(round((preview.yMaximum() - current.yMaximum()) / preview.height() * source.height()))
        max_x = max(0, source.width() - target.width())
        max_y = max(0, source.height() - target.height())
        offset_x = min(max(offset_x, 0), max_x)
        offset_y = min(max(offset_y, 0), max_y)
        return offset_x, offset_y

    def _prepared_mouse_pan_wide_pixmap(self, canvas, target):
        if self._mouse_pan_preview_pixmap is None or self._mouse_pan_preview_pixmap.isNull():
            self._mouse_diag_log("PREVIEW_USE rejected=no_pixmap")
            return QPixmap(), (0, 0)
        if not self._mouse_pan_scale_matches(canvas):
            self._mouse_diag_log(
                f"PREVIEW_USE rejected=scale_mismatch cached_key={self._mouse_pan_preview_extent_key}"
            )
            self._clear_mouse_pan_preview("scale_mismatch")
            return QPixmap(), (0, 0)
        if self._mouse_pan_preview_scale != self.mouse_shield_scale:
            self._mouse_diag_log(
                f"PREVIEW_USE rejected=shield_scale_mismatch cached={self._mouse_pan_preview_scale} current={self.mouse_shield_scale}"
            )
            self._clear_mouse_pan_preview("shield_scale_mismatch")
            return QPixmap(), (0, 0)
        if self._mouse_pan_preview_target is not target:
            self._mouse_diag_log("PREVIEW_USE rejected=target_mismatch")
            return QPixmap(), (0, 0)
        size = self._mouse_pan_preview_target_size
        if size != (target.width(), target.height()):
            self._mouse_diag_log(f"PREVIEW_USE rejected=size_mismatch cached={size} target={(target.width(), target.height())}")
            return QPixmap(), (0, 0)
        margin = self._mouse_pan_preview_offset(canvas, target)
        if margin is None:
            self._mouse_diag_log(
                f"PREVIEW_USE rejected=outside_preview cached_key={self._mouse_pan_preview_extent_key}"
            )
            return QPixmap(), (0, 0)
        self._mouse_diag_log(f"PREVIEW_USE accepted=True margin={margin}")
        return self._mouse_pan_preview_pixmap, margin

    def _show_mouse_pan_snapshot_overlay(self, canvas, event):
        if not self._is_canvas_alive(canvas):
            return False
        target = canvas.viewport() or canvas
        self._mouse_pan_current_pos = self._mouse_event_xy(event)
        pixmap, margin = self._prepared_mouse_pan_wide_pixmap(canvas, target)
        if pixmap.isNull():
            pixmap = target.grab()
            margin = (0, 0)
        if pixmap.isNull():
            return False
        self._mouse_pan_snapshot_pixmap = pixmap
        self._mouse_pan_snapshot_start_pos = self._mouse_pan_current_pos
        self._mouse_pan_snapshot_target = target
        self._mouse_pan_snapshot_margin = margin
        self._mouse_pan_fallback_active = margin == (0, 0)
        label = self._mouse_pan_label_for_target(target)
        label.setPixmap(pixmap)
        label.setGeometry(-margin[0], -margin[1], pixmap.width(), pixmap.height())
        label.raise_()
        label.show()
        self._screen_shield_hide_timer.stop()
        return True

    def _shifted_mouse_pan_pixmap(self, dx, dy):
        source = self._mouse_pan_snapshot_pixmap
        if source is None or source.isNull():
            return QPixmap()
        target = self._mouse_pan_snapshot_target
        if target is None:
            return QPixmap()
        width = target.width()
        height = target.height()
        margin_x, margin_y = self._mouse_pan_snapshot_margin
        shifted = QPixmap(width, height)
        shifted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(shifted)
        painter.drawPixmap(dx - margin_x, dy - margin_y, source)
        painter.end()
        return shifted

    def _update_mouse_pan_snapshot_overlay(self, event):
        if self._mouse_pan_snapshot_start_pos is None or self._mouse_pan_snapshot_target is None:
            return
        self._mouse_pan_current_pos = self._mouse_event_xy(event)
        self._refresh_mouse_pan_snapshot_overlay()
        start_x, start_y = self._mouse_pan_snapshot_start_pos
        current_x, current_y = self._mouse_pan_current_pos
        margin_x, margin_y = self._mouse_pan_snapshot_margin
        if False and margin_x and margin_y and (abs(current_x - start_x) > margin_x * 0.35 or abs(current_y - start_y) > margin_y * 0.35):
            self._queue_mouse_pan_wide_preview(self._mouse_pan_light_canvas, delay_ms=0)

    def _refresh_mouse_pan_snapshot_overlay(self):
        if self._mouse_pan_snapshot_start_pos is None or self._mouse_pan_snapshot_target is None or self._mouse_pan_current_pos is None:
            return
        target = self._mouse_pan_snapshot_target
        if target is None:
            return
        current_x, current_y = self._mouse_pan_current_pos
        start_x, start_y = self._mouse_pan_snapshot_start_pos
        dx = current_x - start_x
        dy = current_y - start_y
        label = self._mouse_pan_label_for_target(target)
        source = self._mouse_pan_snapshot_pixmap
        if source is None or source.isNull():
            return
        margin_x, margin_y = self._mouse_pan_snapshot_margin
        label.setGeometry(dx - margin_x, dy - margin_y, source.width(), source.height())
        label.raise_()
        label.show()

    def _finish_mouse_pan_snapshot_overlay(self, duration_ms=180):
        self._mouse_pan_snapshot_pixmap = None
        self._mouse_pan_snapshot_start_pos = None
        self._mouse_pan_snapshot_target = None
        self._mouse_pan_snapshot_margin = (0, 0)
        self._mouse_pan_current_pos = None
        self._mouse_pan_fallback_active = False
        self._screen_shield_hide_timer.start(duration_ms)

    def _inspection_mode_blocks_mouse_shield(self):
        tab = getattr(self, "inspection_tab", None)
        if tab is None:
            return False
        try:
            if not getattr(tab, "inspection_enabled", False):
                return False
            mode = getattr(tab, "operation_mode", "")
            return mode not in ("", "pan", "pan_pending")
        except Exception:
            return False

    def _handle_mouse_pan_light_mode(self, event, canvas):
        if not self.mouse_shield_enabled:
            return
        event_type = event.type()
        if self._inspection_mode_blocks_mouse_shield():
            if event_type == QEvent.Type.MouseButtonPress:
                mode = getattr(getattr(self, "inspection_tab", None), "operation_mode", "")
                self._mouse_diag_log(f"SKIP reason=inspection_mode mode={mode}")
            return
        pan_buttons = (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton)
        if event_type == QEvent.Type.MouseButtonPress:
            if event.button() in pan_buttons:
                if not self._is_vrt_raster_visible_now(self._get_vrt_layer(self.current_vrt_name), canvas):
                    return
                self._mouse_diag_pan_id += 1
                self._mouse_diag_last_move_log_sec = 0.0
                if self._mouse_pan_preview_timer.isActive():
                    self._mouse_pan_preview_timer.stop()
                    self._mouse_pan_preview_pending = True
                self._mouse_diag_log(
                    f"PAN_PRESS id={self._mouse_diag_pan_id} pos={self._mouse_event_xy(event)} "
                    f"{self._mouse_diag_canvas_state(canvas)}"
                )
                self._screen_shield_mouse_drag_active = True
                self._screen_shield_mouse_shown_for_drag = True
                self._mouse_pan_light_active = True
                self._mouse_pan_light_canvas = canvas
                self._hide_screen_shield_overlay()
                shown = self._show_mouse_pan_snapshot_overlay(canvas, event)
                self._mouse_diag_log(
                    f"PAN_SNAPSHOT id={self._mouse_diag_pan_id} shown={shown} "
                    f"margin={self._mouse_pan_snapshot_margin}"
                )
                self._apply_mouse_pan_light_mode(canvas)
            return
        if event_type == QEvent.Type.MouseMove:
            if self._mouse_pan_light_active and self._is_canvas_alive(canvas):
                self._update_mouse_pan_snapshot_overlay(event)
                now = time.perf_counter()
                if now - self._mouse_diag_last_move_log_sec >= 0.2:
                    self._mouse_diag_last_move_log_sec = now
                    dx = dy = 0
                    if self._mouse_pan_snapshot_start_pos is not None and self._mouse_pan_current_pos is not None:
                        start_x, start_y = self._mouse_pan_snapshot_start_pos
                        current_x, current_y = self._mouse_pan_current_pos
                        dx = current_x - start_x
                        dy = current_y - start_y
                    self._mouse_diag_log(
                        f"PAN_MOVE id={self._mouse_diag_pan_id} pos={self._mouse_pan_current_pos} "
                        f"delta=({dx},{dy}) margin={self._mouse_pan_snapshot_margin} "
                        f"{self._mouse_diag_canvas_state(canvas)}"
                    )
                self._apply_mouse_pan_light_mode(canvas)
            return
        if event_type == QEvent.Type.MouseButtonRelease:
            if event.button() in pan_buttons:
                self._mouse_diag_log(
                    f"PAN_RELEASE id={self._mouse_diag_pan_id} pos={self._mouse_event_xy(event)} "
                    f"active={self._mouse_pan_light_active} {self._mouse_diag_canvas_state(canvas)}"
                )
                self._screen_shield_mouse_drag_active = False
                self._screen_shield_mouse_shown_for_drag = False
                if self._mouse_pan_light_active:
                    target = self._mouse_pan_light_canvas if self._is_canvas_alive(self._mouse_pan_light_canvas) else canvas
                    self._mouse_pan_light_active = False
                    self._mouse_pan_light_canvas = None
                    self._restore_mouse_pan_light_mode(target)
                    self._finish_mouse_pan_snapshot_overlay()
                    self._queue_mouse_pan_wide_preview(target, delay_ms=220)
            return

    def eventFilter(self, obj, event):
        try:
            canvas = self._canvas_from_event_object(obj)
            if canvas:
                if self._should_screen_shield_for_key(event, canvas):
                    self._show_screen_shield_overlay(canvas, 140)
                else:
                    self._handle_mouse_pan_light_mode(event, canvas)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"画面シールド処理エラー: {e}",
                "OrthoManager", Qgis.MessageLevel.Warning
            )
        return super().eventFilter(obj, event)

    def _show_screen_shield_overlay(self, canvas=None, duration_ms=90):
        canvas = canvas or self.iface.mapCanvas()
        if not canvas:
            return
        target = canvas.viewport() or canvas
        pixmap = target.grab()
        if pixmap.isNull():
            return
        label = self._screen_shield_labels.get(target)
        if label is None:
            label = QLabel(target)
            label.setObjectName("OrthoManagerScreenShield")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setScaledContents(False)
            self._screen_shield_labels[target] = label
        label.setPixmap(pixmap)
        label.setGeometry(0, 0, target.width(), target.height())
        label.raise_()
        label.show()
        if duration_ms is None:
            self._screen_shield_hide_timer.stop()
        else:
            self._screen_shield_hide_timer.start(duration_ms)

    def _extend_screen_shield_overlay(self, duration_ms=260):
        if any(label.isVisible() for label in self._screen_shield_labels.values()):
            self._screen_shield_hide_timer.start(duration_ms)

    def _hide_screen_shield_overlay(self):
        for label in list(self._screen_shield_labels.values()):
            try:
                label.hide()
                label.clear()
            except Exception:
                _om_record_ignored_exception(__name__, 1686)

    def _clean_tif_list_unique_names(self, tif_list):
        cleaned = []
        seen_paths = set()
        seen_names = {}
        duplicate_path_count = 0
        duplicate_name_count = 0

        for path in tif_list:
            norm_path = os.path.normpath(os.path.abspath(path))
            name_key = self._tif_basename_key(norm_path)

            if norm_path in seen_paths:
                duplicate_path_count += 1
                continue
            if name_key in seen_names:
                duplicate_name_count += 1
                continue

            cleaned.append(norm_path)
            seen_paths.add(norm_path)
            seen_names[name_key] = norm_path

        return cleaned, duplicate_path_count, duplicate_name_count

    def strip_vrt_display_prefix(self, name):
        text = (name or "").strip()
        while text.startswith(self.VRT_NAME_EMOJI) or text.startswith("🖼"):
            if text.startswith(self.VRT_NAME_EMOJI):
                text = text[len(self.VRT_NAME_EMOJI):].strip()
            elif text.startswith("🖼"):
                text = text[len("🖼"):].strip()
        return text

    def format_vrt_display_name(self, name):
        base_name = self.strip_vrt_display_prefix(name)
        if not base_name:
            return ""
        return f"{self.VRT_NAME_EMOJI} {base_name}"

    def overlay_layer_name(self, name):
        display_name = self.format_vrt_display_name(name)
        return f"{display_name}_overlay" if display_name else ""

    def validate_vrt_base_name(self, name):
        base_name = self.strip_vrt_display_prefix(name)
        if not base_name:
            return False, "VRT名を入力してください"
        invalid_chars = '<>:"/\\|?*'
        if any(ch in base_name for ch in invalid_chars):
            return False, f"VRT名には次の文字を使えません: {invalid_chars}"
        if base_name.endswith(".") or base_name.endswith(" "):
            return False, "VRT名の最後にピリオドや空白は使えません"
        if os.path.basename(base_name) != base_name:
            return False, "VRT名にフォルダ区切り文字は使えません"
        return True, ""

    def strip_vpc_display_prefix(self, name):
        text = (name or "").strip()
        while text.startswith(self.VPC_NAME_EMOJI) or text.startswith("☁"):
            if text.startswith(self.VPC_NAME_EMOJI):
                text = text[len(self.VPC_NAME_EMOJI):].strip()
            elif text.startswith("☁"):
                text = text[len("☁"):].strip()
        return text

    def format_vpc_display_name(self, name):
        base_name = self.strip_vpc_display_prefix(name)
        if not base_name:
            return ""
        return f"{self.VPC_NAME_EMOJI} {base_name}"

    def strip_point_cloud_display_prefix(self, name):
        text = (name or "").strip()
        while text.startswith(self.POINT_CLOUD_NAME_EMOJI) or text.startswith("🔹"):
            if text.startswith(self.POINT_CLOUD_NAME_EMOJI):
                text = text[len(self.POINT_CLOUD_NAME_EMOJI):].strip()
            elif text.startswith("🔹"):
                text = text[len("🔹"):].strip()
        return text

    def format_point_cloud_display_name(self, name):
        base_name = self.strip_point_cloud_display_prefix(name)
        if not base_name:
            return ""
        return f"{self.POINT_CLOUD_NAME_EMOJI} {base_name}"

    def validate_vpc_base_name(self, name):
        base_name = self.strip_vpc_display_prefix(name)
        if not base_name:
            return False, "VPC名を入力してください"
        invalid_chars = '<>:"/\\|?*'
        if any(ch in base_name for ch in invalid_chars):
            return False, f"VPC名には次の文字を使えません: {invalid_chars}"
        if base_name.endswith(".") or base_name.endswith(" "):
            return False, "VPC名の最後にピリオドや空白は使えません"
        if os.path.basename(base_name) != base_name:
            return False, "VPC名にフォルダ区切り文字は使えません"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", base_name):
            return False, "VPC名は英数字のみ使用できます。英字、数字、_、-、. の名前にしてください。"
        return True, ""

    def vpc_overlay_layer_name(self, name):
        display_name = self.format_vpc_display_name(name)
        return f"{display_name}_overlay" if display_name else ""

    def _vpc_overlay_path(self, vpc_path):
        if not vpc_path:
            return ""
        return os.path.splitext(vpc_path)[0] + "_overlay.gpkg"

    def _vpc_overlay_qml_path(self, vpc_path):
        if not vpc_path:
            return ""
        return os.path.splitext(vpc_path)[0] + "_overlay.qml"

    def _find_vpc_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        display_name = self.format_vpc_display_name(name)
        return root.findGroup(display_name) or root.findGroup(self.strip_vpc_display_prefix(name))

    def _vpc_group_index(self, name):
        group = self._find_vpc_group(name)
        if not group:
            return None
        root = QgsProject.instance().layerTreeRoot()
        try:
            return root.children().index(group)
        except ValueError:
            return None

    def _related_vpc_file_pairs(self, old_vpc_path, new_display_name):
        old_base, old_ext = os.path.splitext(old_vpc_path)
        ext = old_ext if old_ext else ".vpc"
        new_base_name = self.strip_vpc_display_prefix(new_display_name)
        new_base = os.path.join(os.path.dirname(old_vpc_path), new_base_name)
        new_vpc_path = new_base + ext
        return new_vpc_path, [
            (old_vpc_path, new_vpc_path),
            (old_base + "_overlay.gpkg", new_base + "_overlay.gpkg"),
            (old_base + ".qml", new_base + ".qml"),
            (old_base + "_overlay.qml", new_base + "_overlay.qml"),
        ]

    def _find_vrt_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        display_name = self.format_vrt_display_name(name)
        return root.findGroup(display_name) or root.findGroup(self.strip_vrt_display_prefix(name))

    def _vrt_group_index(self, name):
        group = self._find_vrt_group(name)
        if not group:
            return None
        root = QgsProject.instance().layerTreeRoot()
        try:
            return root.children().index(group)
        except ValueError:
            return None

    def _related_vrt_file_pairs(self, old_vrt_path, new_display_name):
        old_base, old_ext = os.path.splitext(old_vrt_path)
        ext = old_ext if old_ext else ".vrt"
        new_base_name = self.strip_vrt_display_prefix(new_display_name)
        new_base = os.path.join(os.path.dirname(old_vrt_path), new_base_name)
        new_vrt_path = new_base + ext
        return new_vrt_path, [
            (old_vrt_path, new_vrt_path),
            (old_base + "_tiles.gpkg", new_base + "_tiles.gpkg"),
            (old_base + ".qml", new_base + ".qml"),
            (old_base + "_overlay.qml", new_base + "_overlay.qml"),
            (old_base + ".ortho_crs.json", new_base + ".ortho_crs.json"),
        ]

    def _rename_vrt_layers_in_place(self, old_name, new_name):
        old_display = self.format_vrt_display_name(old_name)
        new_display = self.format_vrt_display_name(new_name)
        if not old_display or not new_display:
            return

        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(old_display) or root.findGroup(self.strip_vrt_display_prefix(old_name))
        if group:
            group.setName(new_display)

        candidates = [
            (old_display, new_display),
            (self.strip_vrt_display_prefix(old_name), new_display),
        ]
        for old_layer_name, new_layer_name in candidates:
            for lyr in QgsProject.instance().mapLayersByName(old_layer_name):
                if isinstance(lyr, QgsRasterLayer):
                    lyr.setName(new_layer_name)

        old_overlay = self.overlay_layer_name(old_name)
        new_overlay = self.overlay_layer_name(new_name)
        legacy_overlay = f"{self.strip_vrt_display_prefix(old_name)}_overlay"
        for old_layer_name in {old_overlay, legacy_overlay}:
            for lyr in QgsProject.instance().mapLayersByName(old_layer_name):
                if isinstance(lyr, QgsVectorLayer):
                    lyr.setName(new_overlay)

    def rename_vrt_entry(self, old_name, new_name):
        old_display = self.format_vrt_display_name(old_name)
        new_display = self.format_vrt_display_name(new_name)
        if not old_display or not new_display or old_display not in self.vrt_registry:
            return False, "not_found", None
        if old_display == new_display:
            return True, "", None
        if new_display in self.vrt_registry:
            return False, "duplicate", None

        ok, message = self.validate_vrt_base_name(new_display)
        if not ok:
            return False, "invalid", message

        entry = self.vrt_registry[old_display]
        old_vrt_path = entry.get("path", "")
        new_vrt_path = old_vrt_path
        group_index = self._vrt_group_index(old_display)
        vrt_layer = self._get_vrt_layer(old_display)
        overlay_layer = self._get_overlay_layer(old_display)
        saved_crs = vrt_layer.crs() if vrt_layer and vrt_layer.crs().isValid() else None
        saved_overlay_crs = overlay_layer.crs() if overlay_layer and overlay_layer.crs().isValid() else None
        should_reload = bool(vrt_layer or overlay_layer or self._find_vrt_group(old_display))

        if old_vrt_path:
            if not (saved_crs and saved_crs.isValid()):
                json_vrt_crs, json_overlay_crs = self._load_crs_json(old_vrt_path)
                if json_vrt_crs and json_vrt_crs.isValid():
                    saved_crs = json_vrt_crs
                if not (saved_overlay_crs and saved_overlay_crs.isValid()) and json_overlay_crs and json_overlay_crs.isValid():
                    saved_overlay_crs = json_overlay_crs
            new_vrt_path, file_pairs = self._related_vrt_file_pairs(old_vrt_path, new_display)
            conflicts = [
                dst for src, dst in file_pairs
                if os.path.exists(src)
                and os.path.exists(dst)
                and os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst))
            ]
            if conflicts:
                return False, "file_exists", conflicts

            if vrt_layer:
                try:
                    self._save_qml(vrt_layer, old_vrt_path, overlay_layer)
                except Exception:
                    _om_record_ignored_exception(__name__, 1933)
            if should_reload:
                self._disconnect_scale_signal(old_display)
                self._remove_vrt_group(old_display)
                QApplication.processEvents()

            renamed_pairs = []
            try:
                for src, dst in file_pairs:
                    if not os.path.exists(src):
                        continue
                    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
                        continue
                    os.rename(src, dst)
                    renamed_pairs.append((src, dst))
            except Exception as e:
                for src, dst in reversed(renamed_pairs):
                    try:
                        if os.path.exists(dst) and not os.path.exists(src):
                            os.rename(dst, src)
                    except Exception:
                        _om_record_ignored_exception(__name__, 1954)
                if should_reload and os.path.exists(old_vrt_path):
                    self._load_vrt_with_overlay(
                        old_vrt_path, old_display,
                        apply_default_style=False,
                        saved_crs=saved_crs,
                        saved_overlay_crs=saved_overlay_crs,
                        rebuild_gpkg=False,
                        insert_index=group_index,
                    )
                return False, "rename_failed", str(e)

        updated = {}
        for name, entry in self.vrt_registry.items():
            if name == old_display:
                entry = dict(entry)
                if old_vrt_path:
                    entry["path"] = new_vrt_path
                updated[new_display] = entry
            else:
                updated[name] = entry
        self.vrt_registry = updated
        self.current_vrt_name = new_display
        if should_reload and old_vrt_path and os.path.exists(new_vrt_path):
            self._load_vrt_with_overlay(
                new_vrt_path, new_display,
                apply_default_style=False,
                saved_crs=saved_crs,
                saved_overlay_crs=saved_overlay_crs,
                rebuild_gpkg=False,
                insert_index=group_index,
            )
        else:
            self._rename_vrt_layers_in_place(old_display, new_display)
        return True, "", None

    def rename_vpc_entry(self, old_name, new_name):
        old_display = self.format_vpc_display_name(old_name)
        new_display = self.format_vpc_display_name(new_name)
        if not old_display or not new_display or old_display not in self.vpc_registry:
            return False, "not_found", None
        if old_display == new_display:
            return True, "", None
        if new_display in self.vpc_registry:
            return False, "duplicate", None

        ok, message = self.validate_vpc_base_name(new_display)
        if not ok:
            return False, "invalid", message

        entry = self.vpc_registry[old_display]
        old_vpc_path = entry.get("path", "")
        new_vpc_path = old_vpc_path
        group_index = self._vpc_group_index(old_display)
        should_reload = bool(self._get_vpc_layer(old_display) or self._find_vpc_group(old_display))

        if old_vpc_path:
            new_vpc_path, file_pairs = self._related_vpc_file_pairs(old_vpc_path, new_display)
            old_copc_dir = self._copc_cache_root_for_vpc(old_vpc_path)
            new_copc_dir = self._copc_cache_root_for_vpc(new_vpc_path)
            if os.path.isdir(old_copc_dir):
                file_pairs.append((old_copc_dir, new_copc_dir))
            conflicts = [
                dst for src, dst in file_pairs
                if os.path.exists(src)
                and os.path.exists(dst)
                and os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst))
            ]
            if conflicts:
                return False, "file_exists", conflicts

            if should_reload:
                self._remove_vpc_group(old_display)
                QApplication.processEvents()

            renamed_pairs = []
            try:
                for src, dst in file_pairs:
                    if not os.path.exists(src):
                        continue
                    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
                        continue
                    os.rename(src, dst)
                    renamed_pairs.append((src, dst))
                if os.path.exists(new_vpc_path):
                    self._update_vpc_copc_folder_references(new_vpc_path, old_vpc_path, new_vpc_path)
            except Exception as e:
                for src, dst in reversed(renamed_pairs):
                    try:
                        if os.path.exists(dst) and not os.path.exists(src):
                            os.rename(dst, src)
                    except Exception:
                        _om_record_ignored_exception(__name__, 2046)
                if should_reload and os.path.exists(old_vpc_path):
                    self._load_vpc_layer(old_vpc_path, old_display, insert_index=group_index)
                return False, "rename_failed", str(e)

        updated = {}
        for name, item in self.vpc_registry.items():
            if name == old_display:
                item = dict(item)
                if old_vpc_path:
                    item["path"] = new_vpc_path
                    item = self._replace_copc_folder_refs_in_value(item, old_vpc_path, new_vpc_path)
                updated[new_display] = item
            else:
                updated[name] = item
        self.vpc_registry = updated
        self.current_vpc_name = new_display
        if should_reload and old_vpc_path and os.path.exists(new_vpc_path):
            self._load_vpc_layer(new_vpc_path, new_display, insert_index=group_index)
        else:
            group = self._find_vpc_group(old_display)
            if group:
                group.setName(new_display)
            for lyr in QgsProject.instance().mapLayersByName(old_display):
                lyr.setName(new_display)
            old_overlay = self.vpc_overlay_layer_name(old_display)
            new_overlay = self.vpc_overlay_layer_name(new_display)
            for lyr in QgsProject.instance().mapLayersByName(old_overlay):
                lyr.setName(new_overlay)
        return True, "", None

    def _replace_copc_folder_refs_in_value(self, value, old_vpc_path, new_vpc_path):
        old_folder = self._copc_cache_folder_name_for_vpc(old_vpc_path)
        new_folder = self._copc_cache_folder_name_for_vpc(new_vpc_path)
        old_dir = self._copc_cache_root_for_vpc(old_vpc_path)
        new_dir = self._copc_cache_root_for_vpc(new_vpc_path)
        if isinstance(value, dict):
            return {k: self._replace_copc_folder_refs_in_value(v, old_vpc_path, new_vpc_path) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_copc_folder_refs_in_value(v, old_vpc_path, new_vpc_path) for v in value]
        if not isinstance(value, str):
            return value
        text = value
        replacements = [
            (old_dir, new_dir),
            (old_dir.replace("\\", "/"), new_dir.replace("\\", "/")),
            (old_folder + "\\", new_folder + "\\"),
            (old_folder + "/", new_folder + "/"),
        ]
        for old_text, new_text in replacements:
            if old_text:
                text = text.replace(old_text, new_text)
        return text

    def _update_vpc_copc_folder_references(self, vpc_path, old_vpc_path, new_vpc_path):
        try:
            with open(vpc_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data = self._replace_copc_folder_refs_in_value(data, old_vpc_path, new_vpc_path)
            if isinstance(data, dict):
                meta = data.get("ortho_manager", {})
                if isinstance(meta, dict):
                    meta["copc_folder"] = self._copc_cache_folder_name_for_vpc(new_vpc_path)
                    data["ortho_manager"] = meta
            with open(vpc_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            QgsMessageLog.logMessage(
                f"VPC_COPC_FOLDER_REFERENCES_UPDATED path={vpc_path}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_FOLDER_REFERENCES_UPDATE_FAILED path={vpc_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def validate_tif_path_for_add(self, path):
        norm_path = os.path.normpath(os.path.abspath(path))
        name_key = self._tif_basename_key(norm_path)
        existing_paths = {os.path.normpath(os.path.abspath(p)) for p in self.tif_list}
        existing_names = {self._tif_basename_key(p): p for p in self.tif_list}

        if norm_path in existing_paths:
            return False, "same_path", None
        if name_key in existing_names:
            return False, "same_name", existing_names[name_key]
        return True, "", None

    def _warn_if_tif_duplicates_removed(self, context, duplicate_path_count, duplicate_name_count):
        if duplicate_path_count == 0 and duplicate_name_count == 0:
            return
        msg = (
            f"{context}に重複画像が含まれていました。\n\n"
            f"同じファイル: {duplicate_path_count} 件\n"
            f"同じ画像ファイル名: {duplicate_name_count} 件\n\n"
            "OrthoManager v2.8では、同じ画像ファイル名の登録は禁止です。\n"
            "安全のため、最初に見つかった画像だけを残しました。"
        )
        QMessageBox.warning(self, tr_text("同名画像を除外しました"), msg)

    # ==========================================
    # UI構築
    # ==========================================
    def _build_ui(self):
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # タブの構築と保持
        self.tabs = QTabWidget()
        self.vrt_tab = VrtTabWidget(self)
        self.inspection_tab = InspectionTabWidget(self)
        self.export_tab = ExportTabWidget(self)
        self.tools_tab = ToolsTabWidget(self)
        self.settings_tab = SettingsTabWidget(self)
        self.tabs.addTab(self.vrt_tab, tr("tab.vrt"))
        self.tabs.addTab(self.inspection_tab, tr("tab.inspection"))
        self.tabs.addTab(self.export_tab, tr("tab.export"))
        self.tabs.addTab(self.tools_tab, tr("tab.tools"))
        self.tabs.addTab(self.settings_tab, tr("tab.settings"))
        self.refresh_language()
        main_layout.addWidget(self.tabs)

        self.status_label = QLabel(tr("status.ready"))
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label.setStyleSheet(self._status_label_style("default"))
        main_layout.addWidget(self.status_label)
        container.setMinimumSize(0, 0)
        scroll = QScrollArea()
        scroll.setMinimumSize(0, 0)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(container)
        self.setWidget(scroll)

    def refresh_language(self):
        language = current_language()
        if not hasattr(self, "tabs"):
            return
        tab_defs = [
            ("vrt_tab", "tab.vrt", ""),
            ("inspection_tab", "tab.inspection", ""),
            ("export_tab", "tab.export", ""),
            ("tools_tab", "tab.tools", ""),
            ("settings_tab", "tab.settings", "tooltip.settings"),
        ]
        for attr_name, text_key, tooltip_key in tab_defs:
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            index = self.tabs.indexOf(widget)
            if index < 0:
                continue
            self.tabs.setTabText(index, tr(text_key, language))
            if tooltip_key:
                self.tabs.setTabToolTip(index, tr(tooltip_key, language))
        for attr_name in ("vrt_tab", "inspection_tab", "export_tab", "tools_tab", "settings_tab"):
            tab = getattr(self, attr_name, None)
            if tab is not None and hasattr(tab, "refresh_texts"):
                tab.refresh_texts()

    def set_status(self, msg):
        self._set_status(msg)

    def _status_label_style(self, style_name="default"):
        base = "padding:3px; border-radius:3px; font-size:11px;"
        styles = {
            "default": "background:#ecf0f1; color:#111827;",
            "busy": "background:#fff3cd; color:#5c3b00; border:1px solid #f0c36d;",
            "success": "background:#e8f5e9; color:#1b5e20; border:1px solid #a5d6a7;",
            "error": "background:#fdecea; color:#7f1d1d; border:1px solid #f5c2c7;",
        }
        return styles.get(style_name, styles["default"]) + base

    def _status_style_from_message(self, msg):
        text = str(msg or "")
        if text.startswith("⏳"):
            return "busy"
        if text.startswith("✅"):
            return "success"
        if text.startswith("❌"):
            return "error"
        return "default"

    def _set_status(self, msg, log=True, style=None):
        self._last_status_message = msg
        self.status_label.setStyleSheet(self._status_label_style(style or self._status_style_from_message(msg)))
        self.status_label.setToolTip(msg)
        self.status_label.setText(self._elide_text_for_width(msg, self.status_label, 280))
        QApplication.processEvents()
        if log:
            QgsMessageLog.logMessage(msg, "OrthoManager", Qgis.MessageLevel.Info)

    def _set_vpc_progress(self, percent, message, log=False):
        try:
            percent = int(round(float(percent)))
        except Exception:
            percent = 0
        percent = max(0, min(100, percent))
        self._set_status(tr_text(f"⏳ VPC処理中 {percent}%: {message}"), log=log, style="busy")

    def _emit_vpc_progress(self, progress_callback, percent, message):
        if not callable(progress_callback):
            return
        try:
            progress_callback(percent, message)
        except Exception:
            _om_record_ignored_exception(__name__, 2264)

    def _log_vpc_verbose(self, message):
        if not getattr(self, "_vpc_verbose_logs_enabled", False):
            return
        QgsMessageLog.logMessage(str(message), "OrthoManager", Qgis.MessageLevel.Info)

    def _elide_text_for_width(self, text, widget, fallback_width):
        width = widget.width() if widget and widget.width() > 20 else fallback_width
        return widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, max(40, width - 8))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "status_label") and hasattr(self, "_last_status_message"):
            self.status_label.setText(self._elide_text_for_width(self._last_status_message, self.status_label, 280))

    # ==========================================
    # プロジェクト保存・復元 (State Management)
    # ==========================================
    def save_to_project(self):
        entries = {}
        for name, entry in self.vrt_registry.items():
            entries[name] = {
                "path": entry["path"],
                "tif_list": entry["tif_list"],
                "group_crs_authid": entry.get("group_crs_authid", ""),
                "initial_crs_pending": bool(entry.get("initial_crs_pending", False)),
            }
        vpc_entries = {}
        for name, entry in self.vpc_registry.items():
            if not isinstance(entry, dict):
                continue
            vpc_entries[name] = {
                "path": entry.get("path", ""),
                "source_list": list(entry.get("source_list", []) or []),
                "processing_source_list": list(entry.get("processing_source_list", []) or []),
                "copc_source_list": list(entry.get("copc_source_list", []) or []),
                "source_records": list(entry.get("source_records", []) or []),
                "orphaned_copc_records": list(entry.get("orphaned_copc_records", []) or []),
                "scale": int(entry.get("scale", 0) or 0),
                "scale_mode": str(entry.get("scale_mode", "") or ""),
                "group_crs_authid": str(entry.get("group_crs_authid", "") or ""),
                "initial_crs_pending": bool(entry.get("initial_crs_pending", False)),
            }
        data = {
            "version": 3,
            "current_vrt_name": self.current_vrt_name,
            "vrt_registry": entries,
            "current_vpc_name": self.current_vpc_name,
            "vpc_registry": vpc_entries,
            "inspection": self.inspection_tab.save_state() if hasattr(self, "inspection_tab") else {},
        }
        QgsProject.instance().writeEntry(PROJECT_KEY, PROJECT_ENTRY, json.dumps(data, ensure_ascii=False))

    def restore_from_project(self):
        raw, ok = QgsProject.instance().readEntry(PROJECT_KEY, PROJECT_ENTRY)
        if not ok or not raw:
            return False
        try:
            data = json.loads(raw)
        except Exception:
            return False

        current_name = ""
        current_vpc_name = ""
        vpc_entries = {}
        if isinstance(data, dict) and "vrt_registry" in data:
            current_name = self.format_vrt_display_name(data.get("current_vrt_name", ""))
            entries = data.get("vrt_registry", {})
            current_vpc_name = self.format_vpc_display_name(data.get("current_vpc_name", ""))
            vpc_entries = data.get("vpc_registry", {})
            inspection_state = data.get("inspection", {})
            has_project_state = bool(entries) or bool(vpc_entries) or self._has_inspection_project_state(inspection_state)
        else:
            entries = data if isinstance(data, dict) else {}
            inspection_state = {}
            has_project_state = bool(entries)

        self._reset_ui()
        for name, entry in entries.items():
            display_name = self.format_vrt_display_name(name)
            if not display_name:
                continue
            if display_name in self.vrt_registry:
                QgsMessageLog.logMessage(
                    f"重複VRT名のため復元をスキップしました: {display_name}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                continue
            if isinstance(entry, dict):
                entry_path = entry.get("path", "")
                raw_tif_list = entry.get("tif_list", [])
                group_crs_authid = entry.get("group_crs_authid", "")
                initial_crs_pending = bool(entry.get("initial_crs_pending", False))
            else:
                entry_path = ""
                raw_tif_list = entry if isinstance(entry, list) else []
                group_crs_authid = ""
                initial_crs_pending = False
            tif_list, dup_paths, dup_names = self._clean_tif_list_unique_names(raw_tif_list)
            self.vrt_registry[display_name] = {
                "path": entry_path,
                "tif_list": tif_list,
                "group_crs_authid": group_crs_authid,
                "initial_crs_pending": initial_crs_pending,
            }
            self._rename_vrt_layers_in_place(name, display_name)
            self._restore_group_crs_property(display_name)
            self._warn_if_tif_duplicates_removed(f"プロジェクト内の「{display_name}」", dup_paths, dup_names)

        if isinstance(vpc_entries, dict):
            for name, entry in vpc_entries.items():
                display_name = self.format_vpc_display_name(name)
                if not display_name:
                    continue
                if display_name in self.vpc_registry:
                    QgsMessageLog.logMessage(
                        f"重複VPC名のため復元をスキップしました: {display_name}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    continue
                if isinstance(entry, dict):
                    entry_path = entry.get("path", "")
                    raw_source_list = entry.get("source_list", [])
                else:
                    entry_path = ""
                    raw_source_list = entry if isinstance(entry, list) else []
                source_list = []
                seen = set()
                for path in raw_source_list:
                    path = os.path.normpath(os.path.abspath(str(path))) if path else ""
                    if not path:
                        continue
                    key = os.path.normcase(path)
                    if key in seen:
                        continue
                    seen.add(key)
                    source_list.append(path)
                self.vpc_registry[display_name] = {
                    "path": entry_path,
                    "source_list": source_list,
                    "subst_mappings": [],
                    "runtime_vpc_path": "",
                    "processing_source_list": list(entry.get("processing_source_list", []) or []) if isinstance(entry, dict) else [],
                    "copc_source_list": list(entry.get("copc_source_list", []) or []) if isinstance(entry, dict) else [],
                    "source_records": list(entry.get("source_records", []) or []) if isinstance(entry, dict) else [],
                    "orphaned_copc_records": list(entry.get("orphaned_copc_records", []) or []) if isinstance(entry, dict) else [],
                    "scale": int(entry.get("scale", 0) or 0) if isinstance(entry, dict) else 0,
                    "scale_mode": str(entry.get("scale_mode", "") or "") if isinstance(entry, dict) else "",
                    "group_crs_authid": str(entry.get("group_crs_authid", "") or "") if isinstance(entry, dict) else "",
                    "initial_crs_pending": bool(entry.get("initial_crs_pending", False)) if isinstance(entry, dict) else False,
                }
                self._restore_vpc_group_crs_property(display_name)
             
        synced_path_count = self._sync_registry_paths_from_project_layers()

        # VRTタブのコンボボックスを更新
        self.vrt_tab.populate_vrt_combo()
        if getattr(self.vrt_tab, "vpc_manager", None) is not None:
            self.vrt_tab.vpc_manager.populate_combo()
        
        if self.vrt_registry:
            selected = current_name if current_name in self.vrt_registry else list(self.vrt_registry.keys())[0]
            self.current_vrt_name = selected
            self.vrt_tab.set_current_vrt_name(selected)
            self.vrt_tab.reload_tif_listwidget()
            self.vrt_tab.update_path_display()
            self._reconnect_scale_signals()
            self.vrt_tab.sync_scale_highlight_from_current_vrt()
            if synced_path_count:
                self.save_to_project()

        if self.vpc_registry and getattr(self.vrt_tab, "vpc_manager", None) is not None:
            selected_vpc = current_vpc_name if current_vpc_name in self.vpc_registry else list(self.vpc_registry.keys())[0]
            self.current_vpc_name = selected_vpc
            self.vrt_tab.vpc_manager.set_current_vpc_name(selected_vpc)
            self.vrt_tab.vpc_manager.reload_source_listwidget()
            self.vrt_tab.vpc_manager.update_path_display()
            self.vrt_tab.vpc_manager.refresh_action_buttons()
            self.scale_target_mode = "vpc"
            self.vrt_tab.sync_scale_highlight_from_current_target()

        if hasattr(self, "inspection_tab"):
            self.inspection_tab.restore_state(inspection_state)
        if self.layer_lock_manager is not None:
            self.layer_lock_manager.refresh()
             
        self._set_status(tr_text(f"✅ プロジェクトから VRT {len(self.vrt_registry)} 件 / VPC {len(self.vpc_registry)} 件を復元"))
        if self.vpc_registry:
            self._schedule_vpc_project_restore_source_audit()
        return has_project_state

    def _schedule_vpc_project_restore_source_audit(self):
        if getattr(self, "_vpc_project_restore_source_audit_scheduled", False):
            return
        self._vpc_project_restore_source_audit_scheduled = True
        QTimer.singleShot(700, self._audit_vpc_project_restore_sources)

    def _audit_vpc_project_restore_sources(self):
        self._vpc_project_restore_source_audit_scheduled = False
        if getattr(self, "_vpc_project_restore_source_audit_running", False):
            return
        vpc_manager = getattr(self.vrt_tab, "vpc_manager", None)
        if vpc_manager is None or not self.vpc_registry:
            return

        self._vpc_project_restore_source_audit_running = True
        project_state_changed = False
        removed_current_session = []
        try:
            for name in list(self.vpc_registry.keys()):
                entry = self.vpc_registry.get(name, {})
                if not isinstance(entry, dict):
                    continue
                vpc_path = entry.get("path", "")
                if not vpc_path or not os.path.exists(vpc_path):
                    continue

                source_list = list(entry.get("source_list", []) or [])
                if not source_list:
                    source_list = self.read_point_cloud_sources_from_vpc(vpc_path)
                source_list = vpc_manager.restore_original_sources_from_managed_copc(source_list, vpc_path)
                source_records = self._read_vpc_source_records(vpc_path) or list(entry.get("source_records", []) or [])
                orphaned_copc_records = (
                    self._read_vpc_orphaned_copc_records(vpc_path)
                    or list(entry.get("orphaned_copc_records", []) or [])
                )
                group_crs_authid = self._read_vpc_group_crs_authid(vpc_path) or str(entry.get("group_crs_authid", "") or "")

                orphan_result = vpc_manager._audit_orphaned_copc_on_load(orphaned_copc_records, vpc_path, vpc_name=name)
                if isinstance(orphan_result, dict):
                    if orphan_result.get("action") == "cancel":
                        self._remove_vpc_group(name)
                        self.vpc_registry.pop(name, None)
                        removed_current_session.append(name)
                        project_state_changed = True
                        continue
                    orphaned_copc_records = list(orphan_result.get("orphaned_copc_records", orphaned_copc_records) or [])
                else:
                    orphan_result = {"action": "continue", "save_metadata": False}

                audit_result = vpc_manager._audit_vpc_sources_on_load(
                    source_list,
                    source_records,
                    vpc_path,
                    orphaned_copc_records=orphaned_copc_records,
                    vpc_name=name,
                )
                if isinstance(audit_result, dict):
                    if audit_result.get("action") == "cancel":
                        self._remove_vpc_group(name)
                        self.vpc_registry.pop(name, None)
                        removed_current_session.append(name)
                        project_state_changed = True
                        continue
                    source_list = list(audit_result.get("source_list", source_list) or [])
                    source_records = list(audit_result.get("source_records", source_records) or [])
                    orphaned_copc_records = list(audit_result.get("orphaned_copc_records", orphaned_copc_records) or [])
                else:
                    audit_result = {"action": "continue", "save_metadata": False}

                entry.update({
                    "path": vpc_path,
                    "source_list": source_list,
                    "source_records": source_records,
                    "orphaned_copc_records": orphaned_copc_records,
                    "group_crs_authid": group_crs_authid,
                    "initial_crs_pending": not bool(group_crs_authid),
                })
                self.vpc_registry[name] = entry

                if audit_result.get("save_metadata") or orphan_result.get("save_metadata"):
                    self.write_vpc_embedded_metadata(vpc_path, entry)
                    project_state_changed = True

                if audit_result.get("action") == "exclude":
                    self.current_vpc_name = name
                    vpc_manager.set_current_vpc_name(name)
                    if audit_result.get("delete_copc"):
                        self._remove_vpc_group(name)
                        deleted, failed, skipped = vpc_manager._delete_vpc_copc_paths(
                            audit_result.get("delete_copc_paths", []),
                            vpc_path,
                            label="VPC_PROJECT_RESTORE_SOURCE_MISSING_COPC_DELETE",
                        )
                        if failed:
                            QMessageBox.warning(
                                self.vrt_tab,
                                tr_text("警告"),
                                tr_text(f"対応COPCの一部を削除できませんでした。\n\n削除: {deleted} 件\n失敗: {failed} 件\nスキップ: {skipped} 件"),
                            )
                    if not source_list:
                        ok, err_msg = self.write_empty_vpc_file(vpc_path, group_crs_authid)
                        if not ok:
                            QMessageBox.warning(self.vrt_tab, tr_text("警告"), tr_text(f"空VPCとして保存できませんでした。\n\n{err_msg}"))
                            continue
                        self.write_vpc_embedded_metadata(vpc_path, entry)
                        self._remove_vpc_group(name)
                    else:
                        vpc_manager.build_vpc()
                    project_state_changed = True

            if removed_current_session:
                QgsMessageLog.logMessage(
                    f"VPC_PROJECT_RESTORE_SOURCE_AUDIT_CANCELLED names={','.join(removed_current_session)}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            if getattr(self.vrt_tab, "vpc_manager", None) is not None:
                self.vrt_tab.vpc_manager.populate_combo()
                if self.vpc_registry:
                    selected_vpc = self.current_vpc_name if self.current_vpc_name in self.vpc_registry else list(self.vpc_registry.keys())[0]
                    self.current_vpc_name = selected_vpc
                    self.vrt_tab.vpc_manager.set_current_vpc_name(selected_vpc)
                    self.vrt_tab.vpc_manager.reload_source_listwidget()
                    self.vrt_tab.vpc_manager.update_path_display()
                    self.vrt_tab.vpc_manager.refresh_action_buttons()
                else:
                    self.current_vpc_name = ""
                    self.vrt_tab.vpc_manager.reload_source_listwidget()
                    self.vrt_tab.vpc_manager.update_path_display()
                    self.vrt_tab.vpc_manager.refresh_action_buttons()
            if project_state_changed:
                self.save_to_project()
        finally:
            self._vpc_project_restore_source_audit_running = False

    def _has_inspection_project_state(self, inspection_state):
        if not isinstance(inspection_state, dict):
            return False
        gpkg_path = str(inspection_state.get("gpkg_path", "") or "").strip()
        if gpkg_path:
            return True
        gpkg_paths = inspection_state.get("gpkg_paths", {})
        if isinstance(gpkg_paths, dict):
            return any(str(path or "").strip() for path in gpkg_paths.values())
        return False

    def reset_all(self):
        self._disconnect_all_scale_signals()
        if hasattr(self, "inspection_tab"):
            self.inspection_tab.clear_inspection_state(remove_layers=False)
        if self.layer_lock_manager is not None:
            self.layer_lock_manager.schedule_refresh()
        self._reset_ui()
        self.vrt_registry.clear()
        self.current_vrt_name = ""
        self.vpc_registry.clear()
        self.current_vpc_name = ""
        self.scale_target_mode = "vrt"
        now = time.monotonic()
        should_log = (now - self._last_reset_completed_log_sec) >= self._reset_completed_log_interval_sec
        self._set_status(tr_text("🆕 リセット完了"), log=should_log)
        if should_log:
            self._last_reset_completed_log_sec = now

    def _reset_ui(self):
        self.vrt_tab.vrt_combo.blockSignals(True)
        self.vrt_tab.vrt_combo.clear()
        self.vrt_tab.vrt_combo.blockSignals(False)
        self.vrt_registry.clear()
        self.current_vrt_name = ""
        self.vpc_registry.clear()
        self.current_vpc_name = ""
        self.scale_target_mode = "vrt"
        self.vrt_tab.reload_tif_listwidget()
        self.vrt_tab.update_path_display()
        self.vrt_tab._refresh_vrt_action_buttons()
        if getattr(self.vrt_tab, "vpc_manager", None) is not None:
            self.vrt_tab.vpc_manager.populate_combo()
            self.vrt_tab.vpc_manager.reload_source_listwidget()
            self.vrt_tab.vpc_manager.update_path_display()
            self.vrt_tab.vpc_manager.refresh_action_buttons()

    # ==========================================
    # 共通ユーティリティ (レイヤ操作, スタイル保存)
    # ==========================================
    def _get_vrt_layer(self, name):
        for layer_name in {self.format_vrt_display_name(name), self.strip_vrt_display_prefix(name)}:
            if not layer_name:
                continue
            for lyr in QgsProject.instance().mapLayersByName(layer_name):
                if isinstance(lyr, QgsRasterLayer): return lyr
        return None

    def _get_vpc_layer(self, name):
        for layer_name in {self.format_vpc_display_name(name), self.strip_vpc_display_prefix(name)}:
            if not layer_name:
                continue
            for lyr in QgsProject.instance().mapLayersByName(layer_name):
                if self._is_point_cloud_layer(lyr):
                    return lyr
        return None

    def _point_cloud_layer_class(self):
        try:
            from qgis.core import QgsPointCloudLayer
            return QgsPointCloudLayer
        except Exception:
            return None

    def _is_ascii_path(self, path):
        try:
            str(path or "").encode("ascii")
            return True
        except Exception:
            return False

    def _run_hidden_process(self, args, cwd=None):
        kwargs = {
            "capture_output": True,
            "text": True,
            "shell": False,
        }
        if cwd:
            kwargs["cwd"] = cwd
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(validated_process_args(args), **kwargs)  # nosec B603 # validated argv; shell=False in kwargs.

    def _query_subst_mappings(self):
        return {}

    def _ensure_subst_drive_for_folder(self, folder, preferred_drive=None):
        raise RuntimeError("v4.88以降、VPC作成時の仮想ドライブ自動作成は無効です。")

    def _ensure_saved_vpc_subst_mappings(self, entry):
        # v4.88以降は、ユーザーPCへ仮想ドライブを残す可能性があるため
        # 保存済みの旧subst設定を自動復元しません。
        return

    def _vpc_cache_dir(self, output_path):
        output_path = os.path.normpath(os.path.abspath(str(output_path or "")))
        base_dir = os.path.dirname(output_path) or os.getcwd()
        key = hashlib.sha1(os.path.normcase(output_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:16]
        cache_dir = os.path.join(base_dir, "_ortho_manager_vpc_work", key)
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _runtime_vpc_path(self, vpc_path, entry=None):
        vpc_path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        return vpc_path if vpc_path else ""

    def _vpc_processing_sources(self, source_list):
        sources = []
        for path in source_list:
            path = os.path.normpath(os.path.abspath(str(path or "")))
            if path:
                sources.append(path)
        return sources, []

    def _alias_path_from_saved_subst(self, path):
        path = os.path.normpath(os.path.abspath(str(path or "")))
        return path

    def _vpc_sources_need_copc_conversion(self, source_list):
        for path in source_list or []:
            name = str(path or "").lower()
            if name.endswith(".las") or (name.endswith(".laz") and not name.endswith(".copc.laz")):
                return True
        return False

    def _vpc_sources_are_copc(self, source_list):
        sources = [str(path or "").lower() for path in source_list or [] if path]
        return bool(sources) and all(path.endswith(".copc.laz") for path in sources)

    def _qgis_install_root(self):
        try:
            prefix = QgsApplication.prefixPath()
        except Exception:
            prefix = ""
        if prefix:
            prefix = os.path.normpath(prefix)
            if os.path.basename(prefix).lower() == "qgis":
                apps_dir = os.path.dirname(prefix)
                if os.path.basename(apps_dir).lower() == "apps":
                    return os.path.dirname(apps_dir)
        return ""

    def _pdal_exe_path(self):
        root = self._qgis_install_root()
        candidates = []
        if root:
            candidates.append(os.path.join(root, "bin", "pdal.exe"))
        candidates.append("pdal")
        for path in candidates:
            if path == "pdal" or os.path.exists(path):
                return path
        return "pdal"

    def _pdal_wrench_path(self):
        try:
            prefix = QgsApplication.prefixPath()
        except Exception:
            prefix = ""
        candidates = []
        if prefix:
            candidates.append(os.path.join(os.path.normpath(prefix), "pdal_wrench.exe"))
        for path in candidates:
            if os.path.exists(path):
                return path
        return "pdal_wrench"

    def _process_relative_arg(self, path, cwd):
        path = os.path.normpath(os.path.abspath(str(path or "")))
        if not cwd:
            return path
        try:
            rel = os.path.relpath(path, os.path.normpath(os.path.abspath(cwd)))
        except Exception:
            return path
        if rel and not rel.startswith(".."):
            return rel
        return path

    def _windows_short_path(self, path):
        if os.name != "nt":
            return ""
        path = os.path.normpath(os.path.abspath(str(path or "")))
        if not path or not os.path.exists(path):
            return ""
        try:
            import ctypes
            from ctypes import wintypes

            get_short = ctypes.windll.kernel32.GetShortPathNameW
            get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            get_short.restype = wintypes.DWORD
            needed = get_short(path, None, 0)
            if needed <= 0:
                return ""
            buffer = ctypes.create_unicode_buffer(needed + 1)
            result = get_short(path, buffer, len(buffer))
            if result <= 0:
                return ""
            short_path = os.path.normpath(buffer.value)
            if short_path and os.path.exists(short_path):
                return short_path
        except Exception:
            return ""
        return ""

    def _windows_short_child_path(self, path):
        path = os.path.normpath(os.path.abspath(str(path or "")))
        parent = os.path.dirname(path)
        filename = os.path.basename(path)
        short_parent = self._windows_short_path(parent)
        if short_parent and filename and self._is_ascii_path(filename):
            return os.path.normpath(os.path.join(short_parent, filename))
        return ""

    def _pdal_translate_attempts(self, input_path, output_path):
        input_path = os.path.normpath(os.path.abspath(str(input_path or "")))
        output_path = os.path.normpath(os.path.abspath(str(output_path or "")))
        candidates = [
            os.path.dirname(input_path),
            os.path.dirname(output_path),
        ]
        try:
            common = os.path.commonpath([input_path, output_path])
            if not os.path.isdir(common):
                common = os.path.dirname(common)
            candidates.append(common)
        except Exception:
            _om_record_ignored_exception(__name__, 2833)
        candidates.append(None)

        path_pairs = [(input_path, output_path)]
        short_input = self._windows_short_path(input_path)
        short_output = self._windows_short_child_path(output_path)
        if short_input and short_output and self._is_ascii_path(short_input) and self._is_ascii_path(short_output):
            path_pairs.append((short_input, short_output))

        attempts = []
        seen = set()
        for pair_input, pair_output in path_pairs:
            pair_candidates = list(candidates)
            if pair_input != input_path:
                pair_candidates.insert(0, os.path.dirname(pair_input))
            if pair_output != output_path:
                pair_candidates.insert(0, os.path.dirname(pair_output))
            for cwd in pair_candidates:
                in_arg = self._process_relative_arg(pair_input, cwd)
                out_arg = self._process_relative_arg(pair_output, cwd)
                key = (cwd or "", in_arg, out_arg)
                if key in seen:
                    continue
                seen.add(key)
                attempts.append((cwd, in_arg, out_arg))
        return attempts

    def _copc_cache_name_parts_for_source(self, source_path, output_path):
        source_path = os.path.normpath(os.path.abspath(str(source_path)))
        output_path = os.path.normpath(os.path.abspath(str(output_path)))
        cache_root = self._copc_cache_root_for_vpc(output_path)
        os.makedirs(cache_root, exist_ok=True)
        key = hashlib.sha1(os.path.normcase(source_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:12]
        stem = self._safe_ascii_file_stem(os.path.splitext(os.path.basename(source_path))[0])
        return cache_root, stem, key

    def _copc_cache_folder_name_for_vpc(self, output_path):
        output_path = os.path.normpath(os.path.abspath(str(output_path or "")))
        stem = self._safe_ascii_file_stem(os.path.splitext(os.path.basename(output_path))[0], fallback="vpc")
        return f"{stem}_copc"

    def _copc_cache_root_for_vpc(self, output_path):
        output_path = os.path.normpath(os.path.abspath(str(output_path or "")))
        return os.path.join(os.path.dirname(output_path), self._copc_cache_folder_name_for_vpc(output_path))

    def _copc_cache_path_for_source(self, source_path, output_path):
        source_path = os.path.normpath(os.path.abspath(str(source_path)))
        cache_root, stem, _key = self._copc_cache_name_parts_for_source(source_path, output_path)
        return os.path.join(cache_root, f"{stem}.copc.laz")

    def _copc_cache_paths_for_source(self, source_path, output_path):
        cache_root, stem, key = self._copc_cache_name_parts_for_source(source_path, output_path)
        paths = []
        for pattern in (
            os.path.join(cache_root, f"{stem}.copc.laz"),
            os.path.join(cache_root, f"{stem}_{key}.copc.laz"),
            os.path.join(cache_root, f"{stem}_{key}_*.copc.laz"),
            os.path.join(cache_root, f"pc_{key}.copc.laz"),
        ):
            try:
                paths.extend(glob.glob(pattern))
            except Exception:
                _om_record_ignored_exception(__name__, 2895)
        paths.append(self._copc_cache_path_for_source(source_path, output_path))
        unique = []
        seen = set()
        for path in paths:
            norm = os.path.normcase(os.path.abspath(os.path.normpath(str(path))))
            if norm in seen:
                continue
            seen.add(norm)
            unique.append(path)
        return unique

    def _safe_ascii_file_stem(self, text, fallback="pc", max_len=48):
        stem = str(text or "").strip()
        stem = stem.encode("ascii", "ignore").decode("ascii")
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
        if not stem:
            stem = fallback
        return stem[:max_len]

    def _las_scale_offset_values(self, source_path):
        try:
            with open(source_path, "rb") as f:
                header = f.read(179)
            if len(header) < 179 or header[:4] != b"LASF":
                return None
            scale_x, scale_y, scale_z = struct.unpack_from("<ddd", header, 131)
            offset_x, offset_y, offset_z = struct.unpack_from("<ddd", header, 155)
            values = (scale_x, scale_y, scale_z, offset_x, offset_y, offset_z)
            if not all(isinstance(v, float) and abs(v) < 1.0e20 for v in values):
                return None
            if scale_x <= 0 or scale_y <= 0 or scale_z <= 0:
                return None
            return values
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_SCALE_OFFSET_READ_FAILED src={source_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return None

    def _las_point_count(self, source_path):
        try:
            with open(source_path, "rb") as f:
                header = f.read(375)
            if len(header) < 111 or header[:4] != b"LASF":
                return None
            major = header[24]
            minor = header[25]
            legacy_count = struct.unpack_from("<I", header, 107)[0]
            if (major, minor) >= (1, 4) and len(header) >= 255:
                extended_count = struct.unpack_from("<Q", header, 247)[0]
                return int(extended_count or legacy_count)
            return int(legacy_count)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_POINT_COUNT_READ_FAILED path={source_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return None

    def _copc_matches_source_point_count(self, source_path, copc_path):
        source_count = self._las_point_count(source_path)
        copc_count = self._las_point_count(copc_path)
        if source_count is None or copc_count is None:
            return True
        return source_count == copc_count

    def _las_scale_offset_options(self, source_path):
        values = self._las_scale_offset_values(source_path)
        if not values:
            return []
        scale_x, scale_y, scale_z, offset_x, offset_y, offset_z = values
        return [
            f"--writers.copc.scale_x={scale_x:.17g}",
            f"--writers.copc.scale_y={scale_y:.17g}",
            f"--writers.copc.scale_z={scale_z:.17g}",
            f"--writers.copc.offset_x={offset_x:.17g}",
            f"--writers.copc.offset_y={offset_y:.17g}",
            f"--writers.copc.offset_z={offset_z:.17g}",
        ]

    def _scale_offset_values_match(self, source_values, copc_values):
        if not source_values or not copc_values:
            return False
        for source_value, copc_value in zip(source_values, copc_values):
            tolerance = max(1.0e-12, abs(source_value) * 1.0e-12)
            if abs(source_value - copc_value) > tolerance:
                return False
        return True

    def _copc_matches_source_scale_offset(self, source_path, copc_path):
        source_values = self._las_scale_offset_values(source_path)
        copc_values = self._las_scale_offset_values(copc_path)
        return self._scale_offset_values_match(source_values, copc_values)

    def _point_cloud_source_record(self, source_path, copc_path=""):
        source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
        record = {
            "source_path": source_path,
            "copc_path": os.path.normpath(os.path.abspath(str(copc_path or ""))) if copc_path else "",
            "exists": os.path.exists(source_path),
        }
        if not record["exists"]:
            return record
        try:
            stat = os.stat(source_path)
            record["size"] = int(stat.st_size)
            record["mtime"] = float(stat.st_mtime)
            record["mtime_ns"] = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000)))
        except Exception:
            _om_record_ignored_exception(__name__, 3008)
        point_count = self._las_point_count(source_path)
        if point_count is not None:
            record["point_count"] = int(point_count)
        scale_offset = self._las_scale_offset_values(source_path)
        if scale_offset:
            record["scale_offset"] = [float(v) for v in scale_offset]
        return record

    def _vpc_source_records(self, source_list, copc_source_list=None):
        records = []
        copc_source_list = list(copc_source_list or [])
        for index, source_path in enumerate(source_list or []):
            copc_path = copc_source_list[index] if index < len(copc_source_list) else ""
            records.append(self._point_cloud_source_record(source_path, copc_path))
        return records

    def _read_vpc_source_records(self, vpc_path):
        path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("ortho_manager", {}) if isinstance(data, dict) else {}
            records = meta.get("source_records", []) if isinstance(meta, dict) else []
            return records if isinstance(records, list) else []
        except Exception:
            return []

    def _read_vpc_orphaned_copc_records(self, vpc_path):
        path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("ortho_manager", {}) if isinstance(data, dict) else {}
            records = meta.get("orphaned_copc_records", []) if isinstance(meta, dict) else []
            return records if isinstance(records, list) else []
        except Exception:
            return []

    def _read_vpc_group_crs_authid(self, vpc_path):
        path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        if not path or not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("ortho_manager", {}) if isinstance(data, dict) else {}
            if not isinstance(meta, dict):
                return ""
            authid = str(meta.get("group_crs_authid", "") or meta.get("crs_authid", "") or "").strip()
            if not authid:
                return ""
            crs = QgsCoordinateReferenceSystem(authid)
            return authid if crs.isValid() else ""
        except Exception:
            return ""

    def _vpc_source_change_overrides(self, source_list, output_path):
        previous_records = self._read_vpc_source_records(output_path)
        previous_by_path = {}
        for record in previous_records:
            if not isinstance(record, dict):
                continue
            source_path = record.get("source_path", "")
            if not source_path:
                continue
            previous_by_path[os.path.normcase(os.path.normpath(os.path.abspath(str(source_path))))] = record
        if not previous_by_path:
            return set()
        changed = set()
        for source_path in source_list or []:
            source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
            if not source_path or source_path.lower().endswith(".copc.laz") or not os.path.exists(source_path):
                continue
            key = os.path.normcase(source_path)
            previous = previous_by_path.get(key)
            if not previous:
                continue
            current = self._point_cloud_source_record(source_path)
            reasons = []
            for field in ("size", "mtime_ns", "point_count"):
                if previous.get(field) is not None and current.get(field) is not None and previous.get(field) != current.get(field):
                    reasons.append(field)
            previous_scale = previous.get("scale_offset")
            current_scale = current.get("scale_offset")
            if previous_scale and current_scale and not self._scale_offset_values_match(previous_scale, current_scale):
                reasons.append("scale_offset")
            if reasons:
                changed.add(key)
                QgsMessageLog.logMessage(
                    f"VPC_SOURCE_CHANGED src={source_path} reasons={','.join(reasons)}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
        return changed

    def _ascii_qgis_index_work_dir(self, copc_path):
        copc_path = os.path.normpath(os.path.abspath(str(copc_path or "")))
        key = hashlib.sha1(os.path.normcase(copc_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:16]
        folder = os.path.dirname(copc_path)
        candidates = []
        while folder:
            if self._is_ascii_path(folder):
                candidates.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        for candidate in candidates:
            work_dir = os.path.join(candidate, "_ortho_manager_vpc_work_ascii", key, "qgis_index_ascii")
            if not self._is_ascii_path(work_dir):
                continue
            try:
                os.makedirs(work_dir, exist_ok=True)
                return work_dir
            except Exception:
                _om_record_ignored_exception(__name__, 3128); continue
        return ""

    def _point_cloud_index_layer_options(self):
        options = self._point_cloud_layer_options()
        if options is None:
            point_cloud_cls = self._point_cloud_layer_class()
            options_cls = getattr(point_cloud_cls, "LayerOptions", None) if point_cloud_cls else None
            if options_cls is None:
                return None
            try:
                options = options_cls(QgsProject.instance().transformContext())
            except Exception:
                try:
                    options = options_cls()
                except Exception:
                    return None
        try:
            if hasattr(options, "skipIndexGeneration"):
                options.skipIndexGeneration = False
        except Exception:
            _om_record_ignored_exception(__name__, 3149)
        try:
            if hasattr(options, "skipStatisticsCalculation"):
                options.skipStatisticsCalculation = True
        except Exception:
            _om_record_ignored_exception(__name__, 3154)
        return options

    def _point_cloud_layer_error_text(self, layer):
        try:
            err = layer.error()
            try:
                text = err.message()
            except Exception:
                text = str(err)
            return str(text or "").strip()
        except Exception:
            return ""

    def _create_qgis_index_layer_direct(self, path_candidates, layer_name, errors):
        point_cloud_cls = self._point_cloud_layer_class()
        if point_cloud_cls is None:
            errors.append("direct unavailable: QgsPointCloudLayer unavailable")
            return None
        options = self._point_cloud_index_layer_options()
        for path in path_candidates:
            constructor_attempts = []
            if options is not None:
                constructor_attempts.append((path, layer_name, "pdal", options))
                constructor_attempts.append((path, layer_name, options))
            constructor_attempts.append((path, layer_name, "pdal"))
            constructor_attempts.append((path, layer_name))
            for args in constructor_attempts:
                try:
                    layer = point_cloud_cls(*args)
                    if layer and layer.isValid() and self._is_point_cloud_layer(layer):
                        return layer
                    detail = self._point_cloud_layer_error_text(layer) if layer else ""
                    errors.append(f"direct args={len(args)} path={path} invalid{': ' + detail if detail else ''}")
                except Exception as e:
                    errors.append(f"direct args={len(args)} path={path} error={e!r}")
        return None

    def _create_qgis_index_layer_from_sublayers(self, path_candidates, layer_name, errors):
        try:
            registry = QgsProviderRegistry.instance()
        except Exception as e:
            errors.append(f"sublayer provider registry unavailable error={e!r}")
            return None

        options = self._provider_sublayer_options()
        for path in path_candidates:
            try:
                provider_info = []
                for provider in registry.preferredProvidersForUri(path):
                    try:
                        provider_key = provider.metadata().key()
                    except Exception:
                        provider_key = ""
                    try:
                        layer_types = ",".join(str(layer_type) for layer_type in provider.layerTypes())
                    except Exception:
                        layer_types = ""
                    provider_info.append(f"{provider_key}:{layer_types}")
                if provider_info:
                    errors.append(f"sublayer providers path={path} {','.join(provider_info[:4])}")
            except Exception as e:
                errors.append(f"sublayer providers path={path} error={e!r}")

            try:
                sublayers = registry.querySublayers(path)
            except Exception as e:
                errors.append(f"sublayer query path={path} error={e!r}")
                continue
            errors.append(f"sublayer query path={path} count={len(sublayers)}")

            for index, detail in enumerate(sublayers):
                try:
                    provider_key = detail.providerKey()
                except Exception:
                    provider_key = ""
                try:
                    layer_type = detail.type()
                except Exception:
                    layer_type = ""
                try:
                    uri = detail.uri()
                except Exception:
                    uri = ""
                try:
                    layer = detail.toLayer(options)
                except TypeError:
                    try:
                        layer = detail.toLayer()
                    except Exception as e:
                        errors.append(f"sublayer index={index} provider={provider_key} type={layer_type} error={e!r}")
                        continue
                except Exception as e:
                    errors.append(f"sublayer index={index} provider={provider_key} type={layer_type} error={e!r}")
                    continue
                if layer and layer.isValid() and self._is_point_cloud_layer(layer):
                    try:
                        layer.setName(layer_name)
                    except Exception:
                        _om_record_ignored_exception(__name__, 3253)
                    errors.append(f"sublayer ok provider={provider_key} type={layer_type} uri={uri}")
                    return layer
                detail_text = self._point_cloud_layer_error_text(layer) if layer else ""
                errors.append(f"sublayer index={index} provider={provider_key} type={layer_type} invalid{': ' + detail_text if detail_text else ''}")
        return None

    def _create_qgis_index_layer_with_iface(self, path_candidates, layer_name, errors):
        if not getattr(self, "iface", None):
            errors.append("iface unavailable")
            return None
        for path in path_candidates:
            try:
                layer = self.iface.addPointCloudLayer(path, layer_name, "pdal")
                if layer and layer.isValid() and self._is_point_cloud_layer(layer):
                    errors.append(f"iface ok path={path}")
                    return layer
                detail = self._point_cloud_layer_error_text(layer) if layer else ""
                errors.append(f"iface path={path} invalid{': ' + detail if detail else ''}")
            except Exception as e:
                errors.append(f"iface path={path} error={e!r}")
        return None

    def _create_copc_with_qgis_index(self, source_path, copc_path):
        point_cloud_cls = self._point_cloud_layer_class()
        if point_cloud_cls is None:
            return False, "QgsPointCloudLayer unavailable"

        source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
        copc_path = os.path.normpath(os.path.abspath(str(copc_path or "")))
        if not os.path.exists(source_path):
            return False, "source missing"

        copc_dir = os.path.dirname(copc_path)
        os.makedirs(copc_dir, exist_ok=True)
        qgis_work_dir = self._ascii_qgis_index_work_dir(copc_path)
        if not qgis_work_dir:
            return False, "QGIS ascii work dir unavailable"
        source_ext = os.path.splitext(source_path)[1].lower() or ".las"
        copc_name = os.path.basename(copc_path)
        if copc_name.lower().endswith(".copc.laz"):
            temp_stem = copc_name[:-len(".copc.laz")] + "_src"
        else:
            temp_stem = os.path.splitext(copc_name)[0] + "_src"
        temp_base = os.path.join(qgis_work_dir, temp_stem)
        temp_source = temp_base + source_ext
        temp_copc = temp_base + ".copc.laz"
        source_key = os.path.normcase(os.path.abspath(source_path))
        temp_key = os.path.normcase(os.path.abspath(temp_source))

        if source_key == temp_key:
            return False, "temporary source equals source"

        made_link = False
        layer = None
        provider = None
        added_project_layer_id = ""
        timing = {
            "link": 0.0,
            "layer": 0.0,
            "generate": 0.0,
            "wait": 0.0,
            "release": 0.0,
            "move": 0.0,
            "move_attempts": 0,
        }
        stable_checks = 0
        try:
            link_started = time.perf_counter()
            if os.path.exists(temp_copc):
                os.remove(temp_copc)
            if os.path.exists(temp_source):
                os.remove(temp_source)
            os.link(source_path, temp_source)
            made_link = True
            timing["link"] = time.perf_counter() - link_started
        except Exception as e:
            try:
                if made_link and os.path.exists(temp_source):
                    os.remove(temp_source)
            except Exception:
                _om_record_ignored_exception(__name__, 3334)
            return False, f"hardlink failed: {e}"

        try:
            started = time.time()
            perf_started = time.perf_counter()
            layer_name = os.path.basename(temp_source)
            path_candidates = []
            for path in (temp_source, temp_source.replace("\\", "/")):
                if path not in path_candidates:
                    path_candidates.append(path)

            errors = []
            route = "direct"
            layer_started = time.perf_counter()
            layer = self._create_qgis_index_layer_direct(path_candidates, layer_name, errors)
            if not (layer and layer.isValid()):
                route = "sublayer"
                layer = self._create_qgis_index_layer_from_sublayers(path_candidates, layer_name, errors)
            if not (layer and layer.isValid()):
                route = "iface"
                layer = self._create_qgis_index_layer_with_iface(path_candidates, layer_name, errors)
                if layer and layer.isValid():
                    try:
                        added_project_layer_id = layer.id()
                    except Exception:
                        added_project_layer_id = ""
            if not (layer and layer.isValid()):
                detail = " | ".join(errors[-8:]) if errors else "QGIS point cloud layer unavailable"
                return False, detail
            timing["layer"] = time.perf_counter() - layer_started

            provider = layer.dataProvider()
            if provider is not None:
                try:
                    generate_started = time.perf_counter()
                    provider.generateIndex()
                    timing["generate"] = time.perf_counter() - generate_started
                except Exception as e:
                    errors.append(f"generateIndex route={route} error={e!r}")

            last_size = -1
            stable_count = 0
            timeout_sec = 180.0
            wait_started = time.perf_counter()
            while time.time() - started < timeout_sec:
                if os.path.exists(temp_copc):
                    try:
                        size = os.path.getsize(temp_copc)
                    except Exception:
                        size = 0
                    if size > 0 and size == last_size:
                        stable_count += 1
                        stable_checks = stable_count
                        if stable_count >= 3:
                            break
                    else:
                        stable_count = 0
                    last_size = size
                QApplication.processEvents()
                time.sleep(0.25)
            timing["wait"] = time.perf_counter() - wait_started

            if not os.path.exists(temp_copc):
                return False, "COPC not created"

            release_started = time.perf_counter()
            if added_project_layer_id:
                try:
                    QgsProject.instance().removeMapLayer(added_project_layer_id)
                    added_project_layer_id = ""
                except Exception:
                    _om_record_ignored_exception(__name__, 3406)
            provider = None
            layer = None
            for _ in range(5):
                QApplication.processEvents()
                time.sleep(0.1)
            timing["release"] = time.perf_counter() - release_started

            move_started = time.perf_counter()
            if os.path.normcase(os.path.abspath(temp_copc)) != os.path.normcase(os.path.abspath(copc_path)):
                try:
                    timing["move_attempts"] = self._replace_file_with_retry(
                        temp_copc,
                        copc_path,
                        "QGIS COPC",
                        attempts=40,
                        sleep_seconds=0.25,
                    )
                except Exception as move_error:
                    QgsMessageLog.logMessage(
                        (
                            "VPC_FILE_LOCK_NOTICE "
                            f"src={os.path.basename(source_path)} target={os.path.basename(copc_path)} "
                            "message=表示用COPCの保存待ちが発生しましたが、処理は継続中です。"
                            "対象ファイルを他のソフトで開いている場合は、閉じると安定する場合があります。 "
                            f"error={move_error}"
                        ),
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    raise
            timing["move"] = time.perf_counter() - move_started
            if timing["move_attempts"] > 1:
                QgsMessageLog.logMessage(
                    (
                        "VPC_FILE_LOCK_NOTICE "
                        f"src={os.path.basename(source_path)} target={os.path.basename(copc_path)} "
                        f"move_attempts={timing['move_attempts']} "
                        "message=表示用COPCの保存待ちが発生しましたが、処理は継続中です。"
                        "対象ファイルを他のソフトで開いている場合は、閉じると安定する場合があります。"
                    ),
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

            size = os.path.getsize(copc_path)
            seconds = time.perf_counter() - perf_started
            self._log_vpc_verbose(
                (
                    "VPC_COPC_QGIS_TIMING "
                    f"route={route} src={os.path.basename(source_path)} "
                    f"size={size} seconds={seconds:.1f} "
                    f"link={timing['link']:.2f} layer={timing['layer']:.2f} "
                    f"generate={timing['generate']:.2f} wait={timing['wait']:.2f} "
                    f"release={timing['release']:.2f} move={timing['move']:.2f} "
                    f"stable={stable_checks} move_attempts={timing['move_attempts']}"
                )
            )
            return True, ""
        except Exception as e:
            return False, str(e)
        finally:
            if added_project_layer_id:
                try:
                    QgsProject.instance().removeMapLayer(added_project_layer_id)
                    QApplication.processEvents()
                except Exception:
                    _om_record_ignored_exception(__name__, 3473)
            provider = None
            layer = None
            try:
                if os.path.exists(temp_source):
                    os.remove(temp_source)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_COPC_TEMP_SOURCE_CLEAN_FAILED path={temp_source} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
            try:
                work_parent = os.path.dirname(qgis_work_dir)
                ascii_parent = os.path.dirname(work_parent)
                self._cleanup_vpc_work_dir(work_parent, label="VPC_QGIS_INDEX_ASCII_WORK")
                self._cleanup_empty_vpc_work_parent(ascii_parent, "_ortho_manager_vpc_work_ascii")
            except Exception:
                _om_record_ignored_exception(__name__, 3491)

    def _prepare_qgis_copc_index_job(self, source_path, copc_path):
        point_cloud_cls = self._point_cloud_layer_class()
        if point_cloud_cls is None:
            return None, "QgsPointCloudLayer unavailable"

        source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
        copc_path = os.path.normpath(os.path.abspath(str(copc_path or "")))
        if not os.path.exists(source_path):
            return None, "source missing"

        os.makedirs(os.path.dirname(copc_path), exist_ok=True)
        qgis_work_dir = self._ascii_qgis_index_work_dir(copc_path)
        if not qgis_work_dir:
            return None, "QGIS ascii work dir unavailable"

        source_ext = os.path.splitext(source_path)[1].lower() or ".las"
        copc_name = os.path.basename(copc_path)
        if copc_name.lower().endswith(".copc.laz"):
            temp_stem = copc_name[:-len(".copc.laz")] + "_src"
        else:
            temp_stem = os.path.splitext(copc_name)[0] + "_src"
        temp_base = os.path.join(qgis_work_dir, temp_stem)
        temp_source = temp_base + source_ext
        temp_copc = temp_base + ".copc.laz"
        if os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(os.path.abspath(temp_source)):
            return None, "temporary source equals source"

        job = {
            "source_path": source_path,
            "copc_path": copc_path,
            "qgis_work_dir": qgis_work_dir,
            "temp_source": temp_source,
            "temp_copc": temp_copc,
            "layer": None,
            "provider": None,
            "added_project_layer_id": "",
            "route": "direct",
            "errors": [],
            "last_size": -1,
            "stable_count": 0,
            "stable_checks": 0,
            "started": time.time(),
            "perf_started": time.perf_counter(),
            "ready": False,
            "released": False,
            "timing": {
                "link": 0.0,
                "layer": 0.0,
                "generate": 0.0,
                "wait": 0.0,
                "release": 0.0,
                "move": 0.0,
                "move_attempts": 0,
            },
        }
        made_link = False
        try:
            link_started = time.perf_counter()
            if os.path.exists(temp_copc):
                os.remove(temp_copc)
            if os.path.exists(temp_source):
                os.remove(temp_source)
            os.link(source_path, temp_source)
            made_link = True
            job["timing"]["link"] = time.perf_counter() - link_started

            layer_name = os.path.basename(temp_source)
            path_candidates = []
            for path in (temp_source, temp_source.replace("\\", "/")):
                if path not in path_candidates:
                    path_candidates.append(path)

            errors = job["errors"]
            layer_started = time.perf_counter()
            layer = self._create_qgis_index_layer_direct(path_candidates, layer_name, errors)
            if not (layer and layer.isValid()):
                job["route"] = "sublayer"
                layer = self._create_qgis_index_layer_from_sublayers(path_candidates, layer_name, errors)
            if not (layer and layer.isValid()):
                job["route"] = "iface"
                layer = self._create_qgis_index_layer_with_iface(path_candidates, layer_name, errors)
                if layer and layer.isValid():
                    try:
                        job["added_project_layer_id"] = layer.id()
                    except Exception:
                        job["added_project_layer_id"] = ""
            if not (layer and layer.isValid()):
                detail = " | ".join(errors[-8:]) if errors else "QGIS point cloud layer unavailable"
                self._cleanup_qgis_copc_index_job(job)
                return None, detail
            job["layer"] = layer
            job["timing"]["layer"] = time.perf_counter() - layer_started

            provider = layer.dataProvider()
            job["provider"] = provider
            if provider is not None:
                try:
                    generate_started = time.perf_counter()
                    provider.generateIndex()
                    job["timing"]["generate"] = time.perf_counter() - generate_started
                except Exception as e:
                    errors.append(f"generateIndex route={job['route']} error={e!r}")
            return job, ""
        except Exception as e:
            try:
                if made_link and os.path.exists(temp_source):
                    os.remove(temp_source)
            except Exception:
                _om_record_ignored_exception(__name__, 3601)
            self._cleanup_qgis_copc_index_job(job)
            return None, str(e)

    def _poll_qgis_copc_index_job(self, job):
        if job.get("ready"):
            return True
        temp_copc = job.get("temp_copc", "")
        if os.path.exists(temp_copc):
            try:
                size = os.path.getsize(temp_copc)
            except Exception:
                size = 0
            if size > 0 and size == job.get("last_size", -1):
                job["stable_count"] = int(job.get("stable_count", 0)) + 1
                job["stable_checks"] = job["stable_count"]
                if job["stable_count"] >= 3:
                    job["ready"] = True
                    job["timing"]["wait"] = time.perf_counter() - job["perf_started"] - job["timing"]["link"] - job["timing"]["layer"] - job["timing"]["generate"]
                    return True
            else:
                job["stable_count"] = 0
            job["last_size"] = size
        return False

    def _release_qgis_copc_index_job(self, job):
        if not job or job.get("released"):
            return 0.0
        release_started = time.perf_counter()
        if job.get("added_project_layer_id"):
            try:
                QgsProject.instance().removeMapLayer(job["added_project_layer_id"])
                job["added_project_layer_id"] = ""
            except Exception:
                _om_record_ignored_exception(__name__, 3635)
        job["provider"] = None
        job["layer"] = None
        for _ in range(5):
            QApplication.processEvents()
            time.sleep(0.1)
        release_seconds = time.perf_counter() - release_started
        job["timing"]["release"] = release_seconds
        job["released"] = True
        return release_seconds

    def _cleanup_qgis_copc_index_job(self, job):
        if not job:
            return
        added_project_layer_id = job.get("added_project_layer_id", "")
        if added_project_layer_id:
            try:
                QgsProject.instance().removeMapLayer(added_project_layer_id)
                QApplication.processEvents()
            except Exception:
                _om_record_ignored_exception(__name__, 3655)
            job["added_project_layer_id"] = ""
        job["provider"] = None
        job["layer"] = None
        temp_source = job.get("temp_source", "")
        try:
            if temp_source and os.path.exists(temp_source):
                os.remove(temp_source)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_TEMP_SOURCE_CLEAN_FAILED path={temp_source} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        try:
            qgis_work_dir = job.get("qgis_work_dir", "")
            work_parent = os.path.dirname(qgis_work_dir)
            ascii_parent = os.path.dirname(work_parent)
            self._cleanup_vpc_work_dir(work_parent, label="VPC_QGIS_INDEX_ASCII_WORK")
            self._cleanup_empty_vpc_work_parent(ascii_parent, "_ortho_manager_vpc_work_ascii")
        except Exception:
            _om_record_ignored_exception(__name__, 3676)

    def _finish_qgis_copc_index_job(self, job, route_prefix="parallel"):
        source_path = job["source_path"]
        copc_path = job["copc_path"]
        temp_copc = job["temp_copc"]
        timing = job["timing"]
        try:
            self._release_qgis_copc_index_job(job)

            move_started = time.perf_counter()
            if os.path.normcase(os.path.abspath(temp_copc)) != os.path.normcase(os.path.abspath(copc_path)):
                try:
                    timing["move_attempts"] = self._replace_file_with_retry(
                        temp_copc,
                        copc_path,
                        "QGIS COPC",
                        attempts=40,
                        sleep_seconds=0.25,
                    )
                except Exception as move_error:
                    QgsMessageLog.logMessage(
                        (
                            "VPC_FILE_LOCK_NOTICE "
                            f"src={os.path.basename(source_path)} target={os.path.basename(copc_path)} "
                            "message=表示用COPCの保存待ちが発生しましたが、処理は継続中です。"
                            "対象ファイルを他のソフトで開いている場合は、閉じると安定する場合があります。 "
                            f"error={move_error}"
                        ),
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    raise
            timing["move"] = time.perf_counter() - move_started
            if timing["move_attempts"] > 1:
                QgsMessageLog.logMessage(
                    (
                        "VPC_FILE_LOCK_NOTICE "
                        f"src={os.path.basename(source_path)} target={os.path.basename(copc_path)} "
                        f"move_attempts={timing['move_attempts']} "
                        "message=表示用COPCの保存待ちが発生しましたが、処理は継続中です。"
                        "対象ファイルを他のソフトで開いている場合は、閉じると安定する場合があります。"
                    ),
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

            size = os.path.getsize(copc_path)
            seconds = time.perf_counter() - job["perf_started"]
            self._log_vpc_verbose(
                (
                    "VPC_COPC_QGIS_TIMING "
                    f"route={route_prefix}_{job.get('route', 'direct')} src={os.path.basename(source_path)} "
                    f"size={size} seconds={seconds:.1f} "
                    f"link={timing['link']:.2f} layer={timing['layer']:.2f} "
                    f"generate={timing['generate']:.2f} wait={timing['wait']:.2f} "
                    f"release={timing['release']:.2f} move={timing['move']:.2f} "
                    f"stable={job.get('stable_checks', 0)} move_attempts={timing['move_attempts']}"
                )
            )
            return True, ""
        except Exception as e:
            return False, str(e)
        finally:
            self._cleanup_qgis_copc_index_job(job)

    def _first_existing_path(self, candidates):
        for path in candidates or []:
            if path and os.path.exists(path):
                return path
        return ""

    def _qgis_external_worker_env(self):
        try:
            prefix = os.path.normpath(str(QgsApplication.prefixPath() or ""))
        except Exception:
            prefix = ""
        if not prefix:
            return None, "", "QGIS prefix unavailable"

        root = os.path.dirname(os.path.dirname(prefix))
        if not root or not os.path.isdir(root):
            return None, "", f"QGIS root unavailable: {root}"

        python_exe = os.path.join(root, "bin", "python.exe")
        if not os.path.exists(python_exe):
            return None, "", f"QGIS python unavailable: {python_exe}"

        apps_dir = os.path.join(root, "apps")
        python_home = self._first_existing_path(
            [
                os.path.join(apps_dir, "Python312"),
                os.path.join(apps_dir, "Python311"),
                os.path.join(apps_dir, "Python310"),
            ]
        )
        qt_bin = self._first_existing_path(
            [
                os.path.join(apps_dir, "qt6", "bin"),
                os.path.join(apps_dir, "Qt6", "bin"),
            ]
        )
        qgis_bin = os.path.join(prefix, "bin")
        qgis_python = os.path.join(prefix, "python")
        if not python_home or not os.path.isdir(python_home):
            return None, "", f"QGIS Python home unavailable: {python_home}"
        if not os.path.isdir(qgis_python):
            return None, "", f"QGIS Python path unavailable: {qgis_python}"

        windir = os.environ.get("WINDIR", r"C:\Windows")
        path_parts = [
            qgis_bin,
            qt_bin,
            os.path.join(python_home, "Scripts"),
            os.path.join(root, "bin"),
            os.path.join(windir, "system32"),
            windir,
            os.path.join(windir, "system32", "WBem"),
        ]
        env = os.environ.copy()
        env["PATH"] = ";".join(path for path in path_parts if path)
        env["PYTHONHOME"] = python_home
        env["PYTHONPATH"] = qgis_python
        env["PYTHONUTF8"] = "1"
        env["QGIS_PREFIX_PATH"] = prefix.replace("\\", "/")
        env["GDAL_FILENAME_IS_UTF8"] = "YES"
        env["VSI_CACHE"] = "TRUE"
        env["VSI_CACHE_SIZE"] = "1000000"
        env["QT_PLUGIN_PATH"] = ";".join(
            path
            for path in (
                os.path.join(prefix, "qtplugins"),
                os.path.join(apps_dir, "qgis", "qtplugins"),
                os.path.join(apps_dir, "qt6", "plugins"),
                os.path.join(apps_dir, "Qt6", "plugins"),
            )
            if os.path.isdir(path)
        )
        env["ORTHO_QGIS_ROOT"] = root
        return env, python_exe, ""

    def _qgis_external_copc_worker_script_text(self):
        return r'''
import json
import os
import sys
import time

qgis_root = os.environ.get("ORTHO_QGIS_ROOT", "")
for dll_dir in (
    os.path.join(qgis_root, "bin"),
    os.path.join(qgis_root, "apps", "qt6", "bin"),
    os.path.join(qgis_root, "apps", "Qt6", "bin"),
    os.path.join(qgis_root, "apps", "qgis", "bin"),
    os.environ.get("PYTHONHOME", ""),
):
    if dll_dir and os.path.isdir(dll_dir) and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(dll_dir)

from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsApplication, QgsPointCloudLayer, QgsProject


def wait_for_stable(path, timeout_sec=180.0):
    started = time.time()
    last_size = -1
    stable_count = 0
    while time.time() - started < timeout_sec:
        QApplication.processEvents()
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > 0 and size == last_size:
                stable_count += 1
                if stable_count >= 3:
                    return size
            else:
                stable_count = 0
            last_size = size
        time.sleep(0.25)
    raise TimeoutError("timeout waiting for COPC")


def create_copc_job(job):
    source_path = os.path.abspath(job["source_path"])
    temp_source = os.path.abspath(job["temp_source"])
    temp_copc = os.path.abspath(job["temp_copc"])
    result = {
        "source_path": source_path,
        "copc_path": job.get("copc_path", ""),
        "temp_copc": temp_copc,
        "ok": False,
        "error": "",
        "seconds": 0.0,
        "size": 0,
    }
    started = time.perf_counter()
    provider = None
    layer = None
    try:
        os.makedirs(os.path.dirname(temp_source), exist_ok=True)
        for path in (temp_copc, temp_source):
            if os.path.exists(path):
                os.remove(path)
        os.link(source_path, temp_source)

        options_cls = getattr(QgsPointCloudLayer, "LayerOptions", None)
        options = None
        if options_cls is not None:
            try:
                options = options_cls(QgsProject.instance().transformContext())
            except Exception:
                options = options_cls()
            if hasattr(options, "skipIndexGeneration"):
                options.skipIndexGeneration = False
            if hasattr(options, "skipStatisticsCalculation"):
                options.skipStatisticsCalculation = True

        attempts = []
        layer_name = os.path.basename(temp_source)
        if options is not None:
            attempts.append((temp_source, layer_name, "pdal", options))
            attempts.append((temp_source, layer_name, options))
        attempts.append((temp_source, layer_name, "pdal"))
        attempts.append((temp_source, layer_name))
        errors = []
        for args in attempts:
            try:
                candidate = QgsPointCloudLayer(*args)
                if candidate and candidate.isValid():
                    layer = candidate
                    break
                errors.append("invalid args={}".format(len(args)))
            except Exception as exc:
                errors.append("error args={} {!r}".format(len(args), exc))
        if not (layer and layer.isValid()):
            raise RuntimeError("layer invalid: " + " | ".join(errors[-4:]))

        provider = layer.dataProvider()
        if provider is None:
            raise RuntimeError("provider missing")
        provider.generateIndex()
        size = wait_for_stable(temp_copc)
        result["ok"] = True
        result["seconds"] = time.perf_counter() - started
        result["size"] = size
        return result
    except Exception as exc:
        result["seconds"] = time.perf_counter() - started
        result["error"] = repr(exc)
        return result
    finally:
        provider = None
        layer = None
        for _ in range(5):
            QApplication.processEvents()
            time.sleep(0.1)
        try:
            if os.path.exists(temp_source):
                os.remove(temp_source)
        except Exception:
            pass


def write_results(results_path, results):
    if not results_path:
        return
    temp_path = results_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"results": results}, f, ensure_ascii=False)
    os.replace(temp_path, results_path)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: qgis_copc_worker.py MANIFEST_JSON")
    manifest_path = os.path.abspath(sys.argv[1])
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    jobs = manifest.get("jobs", [])
    results_path = manifest.get("results_path", "")

    prefix = os.environ.get("QGIS_PREFIX_PATH", "")
    QgsApplication.setPrefixPath(prefix, True)
    app = QgsApplication([], False)
    app.initQgis()
    results = []
    try:
        for index, job in enumerate(jobs, start=1):
            print("JOB_START index={} src={}".format(index, os.path.basename(job.get("source_path", ""))), flush=True)
            result = create_copc_job(job)
            results.append(result)
            write_results(results_path, results)
            status = "JOB_OK" if result.get("ok") else "JOB_FAIL"
            print(
                "{} index={} seconds={:.3f} size={} src={} error={}".format(
                    status,
                    index,
                    float(result.get("seconds") or 0.0),
                    int(result.get("size") or 0),
                    os.path.basename(job.get("source_path", "")),
                    result.get("error", ""),
                ),
                flush=True,
            )
    finally:
        try:
            app.exitQgis()
        finally:
            if results_path:
                write_results(results_path, results)
    if any(not result.get("ok") for result in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
'''.lstrip()

    def _ensure_qgis_external_copc_worker_script(self, qgis_work_dir):
        try:
            os.makedirs(qgis_work_dir, exist_ok=True)
            script_path = os.path.join(qgis_work_dir, "_ortho_qgis_copc_worker.py")
            content = self._qgis_external_copc_worker_script_text()
            current = ""
            if os.path.exists(script_path):
                try:
                    with open(script_path, "r", encoding="utf-8") as f:
                        current = f.read()
                except Exception:
                    current = ""
            if current != content:
                with open(script_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            return script_path
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_QGIS_EXTERNAL_WORKER_SCRIPT_FAILED dir={qgis_work_dir} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return ""

    def _prepare_qgis_external_copc_worker_job(self, entry):
        source_path = os.path.normpath(os.path.abspath(str(entry.get("original_path") or "")))
        copc_path = os.path.normpath(os.path.abspath(str(entry.get("copc_path") or "")))
        qgis_work_dir = self._ascii_qgis_index_work_dir(copc_path)
        if not qgis_work_dir:
            return None, "QGIS external ascii work dir unavailable"
        script_path = self._ensure_qgis_external_copc_worker_script(qgis_work_dir)
        if not script_path:
            return None, "QGIS external worker script unavailable"

        source_ext = os.path.splitext(source_path)[1].lower() or ".las"
        copc_name = os.path.basename(copc_path)
        if copc_name.lower().endswith(".copc.laz"):
            temp_stem = copc_name[:-len(".copc.laz")] + "_external"
        else:
            temp_stem = os.path.splitext(copc_name)[0] + "_external"
        temp_source = os.path.join(qgis_work_dir, temp_stem + source_ext)
        temp_copc = os.path.join(qgis_work_dir, temp_stem + ".copc.laz")
        for path in (temp_copc, temp_source):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                _om_record_ignored_exception(__name__, 4041)

        return {
            "entry": entry,
            "source_path": source_path,
            "copc_path": copc_path,
            "qgis_work_dir": qgis_work_dir,
            "script_path": script_path,
            "temp_source": temp_source,
            "temp_copc": temp_copc,
        }, ""

    def _start_qgis_external_copc_worker_group(self, group_index, jobs, env, python_exe):
        if not jobs:
            return None, "empty external worker group"
        qgis_work_dir = jobs[0]["qgis_work_dir"]
        manifest_path = os.path.join(qgis_work_dir, f"_ortho_qgis_copc_worker_group_{group_index}.json")
        results_path = os.path.join(qgis_work_dir, f"_ortho_qgis_copc_worker_group_{group_index}_results.json")
        for path in (manifest_path, results_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                _om_record_ignored_exception(__name__, 4064)
        manifest = {
            "results_path": results_path,
            "jobs": [
                {
                    "source_path": job["source_path"],
                    "copc_path": job["copc_path"],
                    "temp_source": job["temp_source"],
                    "temp_copc": job["temp_copc"],
                }
                for job in jobs
            ],
        }
        try:
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(manifest, f, ensure_ascii=False)
        except Exception as e:
            return None, str(e)

        args = [python_exe, jobs[0]["script_path"], manifest_path]
        kwargs = {
            "cwd": qgis_work_dir,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "shell": False,
        }
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            started = time.perf_counter()
            proc = subprocess.Popen(validated_process_args(args), **kwargs)  # nosec B603 # validated argv; shell=False in kwargs.
            return {
                "process": proc,
                "jobs": jobs,
                "group_index": group_index,
                "qgis_work_dir": qgis_work_dir,
                "manifest_path": manifest_path,
                "results_path": results_path,
                "started": started,
                "last_progress_at": started,
                "last_result_count": 0,
            }, ""
        except Exception as e:
            return None, str(e)

    def _cleanup_qgis_external_copc_worker_job(self, job):
        for key in ("temp_source",):
            path = job.get(key, "") if job else ""
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                _om_record_ignored_exception(__name__, 4121)
        try:
            qgis_work_dir = job.get("qgis_work_dir", "") if job else ""
            work_parent = os.path.dirname(qgis_work_dir)
            ascii_parent = os.path.dirname(work_parent)
            self._cleanup_vpc_work_dir(work_parent, label="VPC_QGIS_EXTERNAL_WORK")
            self._cleanup_empty_vpc_work_parent(ascii_parent, "_ortho_manager_vpc_work_ascii")
        except Exception:
            _om_record_ignored_exception(__name__, 4129)

    def _read_qgis_external_copc_worker_results(self, results_path):
        worker_results = {}
        if not results_path or not os.path.exists(results_path):
            return worker_results, ""
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            for item in payload.get("results", []):
                key = os.path.normcase(os.path.abspath(str(item.get("copc_path") or "")))
                if key:
                    worker_results[key] = item
            return worker_results, ""
        except Exception as e:
            return worker_results, str(e)

    def _finish_qgis_external_copc_worker_group(self, group):
        proc = group["process"]
        stdout, stderr = proc.communicate()
        elapsed = time.perf_counter() - group["started"]
        detail = (stderr or stdout or "").strip()
        results = {}
        worker_results = {}
        try:
            worker_results, read_error = self._read_qgis_external_copc_worker_results(group["results_path"])
            if read_error:
                detail = f"worker results read failed: {read_error}; {detail}"

            for job in group["jobs"]:
                source_path = job["source_path"]
                copc_path = job["copc_path"]
                temp_copc = job["temp_copc"]
                key = os.path.normcase(os.path.abspath(copc_path))
                worker_result = worker_results.get(key)
                if not worker_result:
                    missing_detail = group.get("timeout_error") or detail[-1000:] or f"worker exit={proc.returncode}"
                    results[copc_path] = (False, missing_detail)
                    continue
                if not worker_result.get("ok"):
                    results[copc_path] = (False, str(worker_result.get("error") or detail or "worker job failed")[-1000:])
                    continue
                if not os.path.exists(temp_copc):
                    results[copc_path] = (False, "worker COPC missing")
                    continue

                move_started = time.perf_counter()
                move_attempts = self._replace_file_with_retry(
                    temp_copc,
                    copc_path,
                    "QGIS external COPC",
                    attempts=40,
                    sleep_seconds=0.25,
                )
                move_seconds = time.perf_counter() - move_started
                if not self._copc_matches_source_scale_offset(source_path, copc_path):
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4189)
                    results[copc_path] = (False, "worker scale/offset mismatch")
                    continue
                if not self._copc_matches_source_point_count(source_path, copc_path):
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4197)
                    results[copc_path] = (False, "worker point count mismatch")
                    continue
                size = os.path.getsize(copc_path)
                self._log_vpc_verbose(
                    (
                        "VPC_COPC_QGIS_EXTERNAL_TIMING "
                        f"worker={group['group_index']} src={os.path.basename(source_path)} size={size} "
                        f"worker_seconds={float(worker_result.get('seconds') or 0.0):.1f} "
                        f"group_seconds={elapsed:.1f} move={move_seconds:.2f} move_attempts={move_attempts}"
                    )
                )
                results[copc_path] = (True, "")
            return results
        finally:
            for job in group.get("jobs", []):
                self._cleanup_qgis_external_copc_worker_job(job)

    def _create_copc_with_qgis_external_worker_parallel(
        self,
        entries,
        max_parallel=7,
        progress_callback=None,
        progress_start=10,
        progress_end=70,
        progress_completed_offset=0,
        progress_total_override=None,
        progress_label="COPC作成中",
        max_jobs_per_process=1,
    ):
        max_parallel = max(1, min(7, int(max_parallel or 1)))
        max_jobs_per_process = max(1, min(2, int(max_jobs_per_process or 1)))
        pending = list(entries or [])
        active = []
        results = {}
        reported_worker_results = set()
        reported_worker_count = 0
        progress_completed_offset = max(0, int(progress_completed_offset or 0))
        progress_total = max(1, int(progress_total_override or len(pending)))
        progress_span = max(1, int(progress_end) - int(progress_start))
        env, python_exe, env_error = self._qgis_external_worker_env()
        started_at = time.perf_counter()
        mode_name = "isolated_pool" if max_jobs_per_process == 1 else "bounded_pool"
        self._log_vpc_verbose(
            (
                "VPC_COPC_QGIS_EXTERNAL_START "
                f"count={len(pending)} max_parallel={max_parallel} mode={mode_name} "
                f"max_jobs_per_process={max_jobs_per_process}"
            ),
        )
        if env is None:
            QgsMessageLog.logMessage(
                f"VPC_COPC_QGIS_EXTERNAL_UNAVAILABLE error={env_error}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return {entry["copc_path"]: (False, env_error) for entry in pending}
        waiting_jobs = []
        try:
            for entry in pending:
                job, error = self._prepare_qgis_external_copc_worker_job(entry)
                if job is None:
                    results[entry["copc_path"]] = (False, error)
                else:
                    waiting_jobs.append(job)

            worker_sequence = 0

            def start_available_workers():
                nonlocal worker_sequence
                while waiting_jobs and len(active) < max_parallel:
                    jobs = [waiting_jobs.pop(0)]
                    while waiting_jobs and len(jobs) < max_jobs_per_process:
                        jobs.append(waiting_jobs.pop(0))
                    worker_sequence += 1
                    group, error = self._start_qgis_external_copc_worker_group(
                        worker_sequence,
                        jobs,
                        env,
                        python_exe,
                    )
                    if group is None:
                        for job in jobs:
                            results[job["copc_path"]] = (False, error)
                            self._cleanup_qgis_external_copc_worker_job(job)
                    else:
                        self._log_vpc_verbose(
                            f"VPC_COPC_QGIS_EXTERNAL_WORKER_START worker={worker_sequence} jobs={len(jobs)}",
                        )
                        active.append(group)

            def report_external_progress():
                nonlocal reported_worker_count
                for group in active:
                    worker_results, _read_error = self._read_qgis_external_copc_worker_results(group.get("results_path", ""))
                    result_count = len(worker_results)
                    if result_count > int(group.get("last_result_count", 0) or 0):
                        group["last_result_count"] = result_count
                        group["last_progress_at"] = time.perf_counter()
                    for key in worker_results:
                        if key in reported_worker_results:
                            continue
                        reported_worker_results.add(key)
                        reported_worker_count += 1
                        overall_completed = min(progress_completed_offset + reported_worker_count, progress_total)
                        current_percent = int(progress_start) + int(
                            progress_span * overall_completed / progress_total
                        )
                        self._emit_vpc_progress(
                            progress_callback,
                            current_percent,
                            f"{progress_label} {overall_completed}/{progress_total}",
                        )

            while waiting_jobs or active:
                start_available_workers()
                report_external_progress()
                next_active = []
                for group in active:
                    proc = group["process"]
                    if proc.poll() is None:
                        now = time.perf_counter()
                        job_count = len(group.get("jobs", []))
                        completed_count = int(group.get("last_result_count", 0) or 0)
                        idle_elapsed = now - float(group.get("last_progress_at", group["started"]))
                        total_elapsed = now - group["started"]
                        idle_timeout_seconds = max(90.0, min(240.0, 45.0 + 15.0 * max(1, job_count)))
                        absolute_timeout_seconds = max(300.0, 75.0 * max(1, job_count))
                        timeout_reason = ""
                        if idle_elapsed > idle_timeout_seconds:
                            timeout_reason = "idle"
                        elif total_elapsed > absolute_timeout_seconds:
                            timeout_reason = "absolute"
                        if timeout_reason:
                            report_external_progress()
                            now = time.perf_counter()
                            idle_elapsed = now - float(group.get("last_progress_at", group["started"]))
                            total_elapsed = now - group["started"]
                            if timeout_reason == "idle" and idle_elapsed <= idle_timeout_seconds:
                                next_active.append(group)
                                continue
                            if timeout_reason == "absolute" and total_elapsed <= absolute_timeout_seconds:
                                next_active.append(group)
                                continue
                            completed_count = int(group.get("last_result_count", completed_count) or 0)
                            pending_count = max(0, job_count - completed_count)
                            group["timeout_error"] = f"external worker {timeout_reason} timeout"
                            QgsMessageLog.logMessage(
                                (
                                    "VPC_COPC_QGIS_EXTERNAL_TIMEOUT "
                                    f"worker={group.get('group_index')} jobs={job_count} "
                                    f"completed={completed_count} pending={pending_count} "
                                    f"seconds={total_elapsed:.1f} idle={idle_elapsed:.1f} "
                                    f"limit_idle={idle_timeout_seconds:.1f} limit_absolute={absolute_timeout_seconds:.1f} "
                                    f"reason={timeout_reason}"
                                ),
                                "OrthoManager",
                                Qgis.MessageLevel.Warning,
                            )
                            try:
                                proc.kill()
                            except Exception:
                                _om_record_ignored_exception(__name__, 4359)
                            results.update(self._finish_qgis_external_copc_worker_group(group))
                        else:
                            next_active.append(group)
                        continue
                    report_external_progress()
                    results.update(self._finish_qgis_external_copc_worker_group(group))
                active = next_active
                report_external_progress()
                QApplication.processEvents()
                time.sleep(0.1)
        finally:
            for group in active:
                try:
                    if group["process"].poll() is None:
                        group["process"].kill()
                except Exception:
                    _om_record_ignored_exception(__name__, 4376)
                for job in group.get("jobs", []):
                    self._cleanup_qgis_external_copc_worker_job(job)
            for job in waiting_jobs:
                self._cleanup_qgis_external_copc_worker_job(job)
            self._log_vpc_verbose(
                f"VPC_COPC_QGIS_EXTERNAL_DONE count={len(entries or [])} seconds={time.perf_counter() - started_at:.1f}",
            )
        return results

    def _create_copc_with_qgis_index_parallel(self, entries, max_parallel=2):
        max_parallel = max(1, min(2, int(max_parallel or 1)))
        pending = list(entries or [])
        active = []
        ready_to_move = []
        results = {}
        started_at = time.perf_counter()
        self._log_vpc_verbose(
            f"VPC_COPC_QGIS_PARALLEL_START count={len(pending)} max_parallel={max_parallel}",
        )
        try:
            while pending or active:
                while pending and len(active) < max_parallel:
                    entry = pending.pop(0)
                    job, error = self._prepare_qgis_copc_index_job(entry["original_path"], entry["copc_path"])
                    if job is None:
                        results[entry["copc_path"]] = (False, error)
                    else:
                        job["entry"] = entry
                        active.append(job)
                if not active:
                    continue

                now = time.time()
                next_active = []
                for job in active:
                    if now - job["started"] > 180.0:
                        results[job["copc_path"]] = (False, "COPC not created")
                        self._cleanup_qgis_copc_index_job(job)
                        continue
                    if self._poll_qgis_copc_index_job(job):
                        self._release_qgis_copc_index_job(job)
                        ready_to_move.append(job)
                        self._log_vpc_verbose(
                            (
                                "VPC_COPC_QGIS_PARALLEL_PIPELINE_RELEASE "
                                f"src={os.path.basename(job.get('source_path', ''))} "
                                f"ready={len(ready_to_move)} pending={len(pending)} active={len(active) - 1}"
                            )
                        )
                    else:
                        next_active.append(job)
                active = next_active
                QApplication.processEvents()
                time.sleep(0.25)
            self._log_vpc_verbose(
                f"VPC_COPC_QGIS_PARALLEL_MOVE_START count={len(ready_to_move)}",
            )
            for job in ready_to_move:
                ok, error = self._finish_qgis_copc_index_job(job, route_prefix="parallel_pipeline")
                results[job["copc_path"]] = (ok, error)
        except Exception as e:
            for job in active:
                self._cleanup_qgis_copc_index_job(job)
            for job in ready_to_move:
                self._cleanup_qgis_copc_index_job(job)
            raise
        finally:
            self._log_vpc_verbose(
                f"VPC_COPC_QGIS_PARALLEL_DONE count={len(entries or [])} seconds={time.perf_counter() - started_at:.1f}",
            )
        return results

    def _prepare_pdal_ascii_source_link(self, source_path, work_dir):
        if not work_dir:
            return ""
        source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
        if not os.path.exists(source_path):
            return ""
        try:
            source_drive = os.path.splitdrive(source_path)[0].lower()
            work_drive = os.path.splitdrive(os.path.abspath(work_dir))[0].lower()
            if source_drive and work_drive and source_drive != work_drive:
                return ""
        except Exception:
            _om_record_ignored_exception(__name__, 4461)
        ext = os.path.splitext(source_path)[1].lower()
        if ext not in (".las", ".laz"):
            ext = ".las"
        key = hashlib.sha1(os.path.normcase(source_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:12]
        link_dir = os.path.join(work_dir, "pdal_ascii")
        link_path = os.path.join(link_dir, f"src_{key}{ext}")
        try:
            os.makedirs(link_dir, exist_ok=True)
            if os.path.exists(link_path):
                try:
                    if os.path.getsize(link_path) == os.path.getsize(source_path):
                        return link_path
                except Exception:
                    _om_record_ignored_exception(__name__, 4475)
                os.remove(link_path)
            os.link(source_path, link_path)
            return link_path
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_COPC_ASCII_LINK_FAILED src={source_path} link={link_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return ""

    def _cleanup_vpc_work_dir(self, work_dir, label="VPC_WORK"):
        work_dir = os.path.normpath(os.path.abspath(str(work_dir or "")))
        if not work_dir or not os.path.isdir(work_dir):
            return False
        try:
            shutil.rmtree(work_dir)
            self._log_vpc_verbose(f"{label}_CLEANED path={work_dir}")
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"{label}_CLEAN_FAILED path={work_dir} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def _cleanup_empty_vpc_work_parent(self, folder, expected_name):
        folder = os.path.normpath(os.path.abspath(str(folder or "")))
        if not folder or os.path.basename(folder) != expected_name:
            return
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except Exception:
            _om_record_ignored_exception(__name__, 4511)

    def _ensure_copc_sources_for_vpc(
        self,
        original_sources,
        processing_sources,
        output_path,
        work_dir=None,
        progress_callback=None,
        progress_start=10,
        progress_end=70,
        force_convert_sources=None,
    ):
        if not self._vpc_sources_need_copc_conversion(original_sources):
            return list(processing_sources)
        pdal_path = self._pdal_exe_path()
        converted = []
        prep_started = time.perf_counter()
        created_count = 0
        reused_count = 0
        qgis_created_count = 0
        pdal_created_count = 0
        total_count = max(1, len(original_sources))
        span = max(1, progress_end - progress_start)
        force_convert_sources = set(force_convert_sources or [])
        self._log_vpc_verbose(
            f"⏳ 表示用COPC作成開始: {len(original_sources)} ファイル",
        )
        parallel_qgis_results = {}
        parallel_qgis_routes = {}
        parallel_qgis_entries = []
        for preview_index, (original_path, _processing_path) in enumerate(zip(original_sources, processing_sources), start=1):
            preview_name = str(original_path or "").lower()
            if not (preview_name.endswith(".las") or (preview_name.endswith(".laz") and not preview_name.endswith(".copc.laz"))):
                continue
            preview_copc_path = self._copc_cache_path_for_source(original_path, output_path)
            preview_key = os.path.normcase(os.path.normpath(os.path.abspath(str(original_path))))
            preview_need_convert = preview_key in force_convert_sources
            if os.path.exists(preview_copc_path):
                try:
                    preview_need_convert = preview_need_convert or os.path.getmtime(preview_copc_path) < os.path.getmtime(original_path)
                except Exception:
                    preview_need_convert = preview_need_convert or False
                if not preview_need_convert and not self._copc_matches_source_scale_offset(original_path, preview_copc_path):
                    preview_need_convert = True
                if not preview_need_convert and not self._copc_matches_source_point_count(original_path, preview_copc_path):
                    preview_need_convert = True
            else:
                preview_need_convert = True
            if preview_need_convert:
                parallel_qgis_entries.append(
                    {
                        "source_index": preview_index,
                        "total_count": total_count,
                        "original_path": original_path,
                        "copc_path": preview_copc_path,
                    }
                )
        if parallel_qgis_entries:
            if len(parallel_qgis_entries) > 1:
                self._emit_vpc_progress(progress_callback, progress_start, f"COPC作成中 0/{len(parallel_qgis_entries)}")
                self._log_vpc_verbose(
                    f"⏳ 表示用COPC外部分離ローリング並列作成開始: {len(parallel_qgis_entries)} ファイル（最大7件・1プロセス1ファイル）",
                )
            external_results = self._create_copc_with_qgis_external_worker_parallel(
                parallel_qgis_entries,
                max_parallel=7 if len(parallel_qgis_entries) > 1 else 1,
                progress_callback=progress_callback,
                progress_start=progress_start,
                progress_end=progress_end,
                max_jobs_per_process=1,
            )
            fallback_entries = []
            for entry in parallel_qgis_entries:
                result = external_results.get(entry["copc_path"], (False, "external worker result missing"))
                if result[0]:
                    parallel_qgis_results[entry["copc_path"]] = result
                    parallel_qgis_routes[entry["copc_path"]] = "qgis_external"
                else:
                    fallback_entries.append(entry)
                    QgsMessageLog.logMessage(
                        (
                            "VPC_COPC_QGIS_EXTERNAL_FAILED "
                            f"src={os.path.basename(str(entry.get('original_path', '')))} "
                            f"error={result[1]}"
                        ),
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
            if fallback_entries:
                fallback_done = max(0, len(parallel_qgis_entries) - len(fallback_entries))
                fallback_percent = progress_start + int(span * fallback_done / max(1, len(parallel_qgis_entries)))
                self._emit_vpc_progress(
                    progress_callback,
                    fallback_percent,
                    f"COPC再作成中 {fallback_done}/{len(parallel_qgis_entries)}",
                )
                self._log_vpc_verbose(
                    f"⏳ 表示用COPC外部分離再作成開始: {len(fallback_entries)} ファイル（最大2件）",
                )
                retry_results = self._create_copc_with_qgis_external_worker_parallel(
                    fallback_entries,
                    max_parallel=min(2, len(fallback_entries)),
                    progress_callback=progress_callback,
                    progress_start=progress_start,
                    progress_end=progress_end,
                    progress_completed_offset=fallback_done,
                    progress_total_override=len(parallel_qgis_entries),
                    progress_label="COPC再作成中",
                    max_jobs_per_process=1,
                )
                for entry in fallback_entries:
                    result = retry_results.get(entry["copc_path"], (False, "isolated external retry result missing"))
                    parallel_qgis_results[entry["copc_path"]] = result
                    parallel_qgis_routes[entry["copc_path"]] = "qgis_external_retry"
                    if not result[0]:
                        QgsMessageLog.logMessage(
                            (
                                "VPC_COPC_QGIS_EXTERNAL_RETRY_FAILED "
                                f"src={os.path.basename(str(entry.get('original_path', '')))} "
                                f"error={result[1]} fallback=pdal_ascii"
                            ),
                            "OrthoManager",
                            Qgis.MessageLevel.Warning,
                        )
        for source_index, (original_path, processing_path) in enumerate(zip(original_sources, processing_sources), start=1):
            current_percent = progress_start + int(span * (source_index - 1) / total_count)
            name = str(original_path or "").lower()
            if name.endswith(".copc.laz"):
                self._emit_vpc_progress(progress_callback, current_percent, f"COPC確認中 {source_index}/{total_count}")
                converted.append(processing_path)
                reused_count += 1
                continue
            if not (name.endswith(".las") or name.endswith(".laz")):
                self._emit_vpc_progress(progress_callback, current_percent, f"COPC確認中 {source_index}/{total_count}")
                converted.append(processing_path)
                reused_count += 1
                continue
            copc_path = self._copc_cache_path_for_source(original_path, output_path)
            source_key = os.path.normcase(os.path.normpath(os.path.abspath(str(original_path))))
            need_convert = source_key in force_convert_sources
            if os.path.exists(copc_path):
                try:
                    need_convert = need_convert or os.path.getmtime(copc_path) < os.path.getmtime(original_path)
                except Exception:
                    need_convert = need_convert or False
                if not need_convert and not self._copc_matches_source_scale_offset(original_path, copc_path):
                    need_convert = True
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_RECONVERT_SCALE_OFFSET_MISMATCH src={original_path} out={copc_path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Info,
                    )
                if not need_convert and not self._copc_matches_source_point_count(original_path, copc_path):
                    need_convert = True
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_RECONVERT_POINT_COUNT_MISMATCH src={original_path} out={copc_path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
            else:
                need_convert = True
            if copc_path in parallel_qgis_results:
                need_convert = True
            if need_convert:
                self._emit_vpc_progress(progress_callback, current_percent, f"COPC作成中 {source_index}/{total_count}")
                self._log_vpc_verbose(
                    f"⏳ 表示用COPC作成中 {source_index}/{total_count}: {os.path.basename(str(original_path))}",
                )
                scale_offset_options = self._las_scale_offset_options(original_path)
                self._log_vpc_verbose(
                    f"VPC_COPC_CONVERT_START src={original_path} out={copc_path} scale_offset={'on' if scale_offset_options else 'off'}"
                )
                errors = []
                creation_route = ""
                qgis_route_name = "qgis"
                if copc_path in parallel_qgis_results:
                    qgis_ok, qgis_error = parallel_qgis_results.get(copc_path, (False, "parallel qgis result missing"))
                    qgis_route_name = parallel_qgis_routes.get(copc_path, "qgis_parallel")
                else:
                    qgis_ok = False
                    qgis_error = "external QGIS result missing; skipped unsafe in-process fallback"
                    qgis_route_name = "qgis_external_missing"
                if not qgis_ok:
                    errors.append(f"qgis_index error={qgis_error}")
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_QGIS_INDEX_FAILED src={original_path} out={copc_path} error={qgis_error}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4705)
                elif not self._copc_matches_source_scale_offset(original_path, copc_path):
                    errors.append("qgis_index scale/offset mismatch")
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_QGIS_INDEX_SCALE_OFFSET_MISMATCH src={original_path} out={copc_path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4717)
                elif not self._copc_matches_source_point_count(original_path, copc_path):
                    errors.append("qgis_index point count mismatch")
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_QGIS_INDEX_POINT_COUNT_MISMATCH src={original_path} out={copc_path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4729)
                if qgis_ok and os.path.exists(copc_path):
                    creation_route = qgis_route_name
                ascii_link = ""
                if not os.path.exists(copc_path):
                    ascii_link = self._prepare_pdal_ascii_source_link(processing_path, work_dir)
                if ascii_link:
                    temp_copc_path = os.path.join(os.path.dirname(ascii_link), f"out_{os.path.splitext(os.path.basename(ascii_link))[0][4:]}.copc.laz")
                    try:
                        if os.path.exists(temp_copc_path):
                            os.remove(temp_copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4741)
                    if not os.path.exists(copc_path):
                        result = self._run_hidden_process(
                            [pdal_path, "translate", os.path.basename(ascii_link), os.path.basename(temp_copc_path), *scale_offset_options],
                            cwd=os.path.dirname(ascii_link),
                        )
                        if result.returncode == 0 and os.path.exists(temp_copc_path):
                            try:
                                if os.path.exists(copc_path):
                                    os.remove(copc_path)
                                shutil.move(temp_copc_path, copc_path)
                                creation_route = "pdal_ascii"
                            except Exception:
                                shutil.copy2(temp_copc_path, copc_path)
                                creation_route = "pdal_ascii_copy"
                                try:
                                    os.remove(temp_copc_path)
                                except Exception:
                                    _om_record_ignored_exception(__name__, 4759)
                        else:
                            detail = (result.stderr or result.stdout or "").strip()
                            errors.append(f"ascii_work cwd={os.path.dirname(ascii_link)} error={detail}")
                            QgsMessageLog.logMessage(
                                f"VPC_COPC_CONVERT_ATTEMPT_FAILED attempt=ascii_work cwd={os.path.dirname(ascii_link)} src={original_path}",
                                "OrthoManager",
                                Qgis.MessageLevel.Warning,
                            )
                for index, (cwd, input_arg, output_arg) in enumerate(self._pdal_translate_attempts(processing_path, copc_path), start=1):
                    if os.path.exists(copc_path):
                        break
                    try:
                        if os.path.exists(copc_path):
                            os.remove(copc_path)
                    except Exception:
                        _om_record_ignored_exception(__name__, 4775)
                    result = self._run_hidden_process([pdal_path, "translate", input_arg, output_arg, *scale_offset_options], cwd=cwd)
                    if result.returncode == 0 and os.path.exists(copc_path):
                        creation_route = f"pdal_attempt_{index}"
                        break
                    detail = (result.stderr or result.stdout or "").strip()
                    errors.append(f"attempt={index} cwd={cwd or ''} error={detail}")
                    QgsMessageLog.logMessage(
                        f"VPC_COPC_CONVERT_ATTEMPT_FAILED attempt={index} cwd={cwd or ''} src={original_path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
                if not os.path.exists(copc_path):
                    detail = "\n".join(errors[-3:]) if errors else "原因不明"
                    raise RuntimeError(
                        "COPC変換に失敗しました。\n"
                        "安全のため仮想ドライブは作成していません。\n"
                        "PDALが日本語パスを処理できず、内部の英数字作業リンクでも回避できませんでした。\n"
                        "VPC保存先を元点群と同じドライブに置くか、案件フォルダまたは点群フォルダを英数字パスへ置いて再実行してください。\n\n"
                        f"{os.path.basename(original_path)}\n\n{detail}"
                    )
                created_count += 1
                if creation_route.startswith("qgis"):
                    qgis_created_count += 1
                else:
                    pdal_created_count += 1
                self._log_vpc_verbose(
                    (
                        "VPC_COPC_CREATE_RESULT "
                        f"src={os.path.basename(str(original_path))} route={creation_route or 'unknown'} "
                        f"qgis_ok={1 if qgis_ok else 0} out={os.path.basename(copc_path)}"
                    )
                )
                self._log_vpc_verbose(
                    f"✅ 表示用COPC作成完了 {source_index}/{total_count}: {os.path.basename(copc_path)}",
                )
            else:
                reused_count += 1
                self._log_vpc_verbose(
                    f"✅ 表示用COPC再利用 {source_index}/{total_count}: {os.path.basename(copc_path)}",
                )
            converted.append(copc_path)
            done_percent = progress_start + int(span * source_index / total_count)
            self._emit_vpc_progress(progress_callback, done_percent, f"COPC準備完了 {source_index}/{total_count}")
        self._emit_vpc_progress(progress_callback, progress_end, "COPC準備完了")
        QgsMessageLog.logMessage(
            (
                "VPC_COPC_PREP_TIME "
                f"count={len(original_sources)} created={created_count} reused={reused_count} "
                f"qgis={qgis_created_count} pdal={pdal_created_count} "
                f"seconds={time.perf_counter() - prep_started:.1f}"
            ),
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return converted

    def _prepare_pdal_ascii_vpc_build(self, processing_sources, runtime_output_path, work_dir, reference_output_path=None):
        build_dir = self._ascii_vpc_build_dir(runtime_output_path)
        if not build_dir:
            raise RuntimeError(
                "VPC作成用の英数字作業フォルダを作成できませんでした。\n"
                "PDAL Wrenchが日本語パスを処理できない環境では、VPC保存先ドライブ内に英数字だけの親フォルダが必要です。"
            )
        copc_folder_name = self._copc_cache_folder_name_for_vpc(reference_output_path or runtime_output_path)
        build_copc_dir = os.path.join(build_dir, copc_folder_name)
        os.makedirs(build_copc_dir, exist_ok=True)
        input_list_path = os.path.join(build_dir, "inputFiles.txt")
        for path in processing_sources:
            source_path = os.path.normpath(os.path.abspath(str(path or "")))
            if not os.path.exists(source_path):
                raise RuntimeError(f"COPCファイルが見つかりません。\n{source_path}")
            filename = os.path.basename(source_path)
            if not self._is_ascii_path(filename):
                raise RuntimeError(f"COPCファイル名が英数字ではありません。\n{filename}")
            link_path = os.path.join(build_copc_dir, filename)
            try:
                if os.path.exists(link_path):
                    try:
                        if os.path.getsize(link_path) == os.path.getsize(source_path):
                            continue
                    except Exception:
                        _om_record_ignored_exception(__name__, 4857)
                    os.remove(link_path)
                os.link(source_path, link_path)
            except Exception as e:
                raise RuntimeError(
                    "VPC作成用の英数字作業リンクを作成できませんでした。\n"
                    "VPC保存先はCOPCファイルと同じドライブ上に置いてください。\n\n"
                    f"{source_path}\n\n{e}"
                )
        with open(input_list_path, "w", encoding="ascii", newline="\n") as f:
            for path in processing_sources:
                f.write(copc_folder_name + "/" + os.path.basename(str(path)).replace("\\", "/") + "\n")
        temp_output_path = os.path.join(build_dir, os.path.basename(runtime_output_path))
        return build_dir, input_list_path, temp_output_path

    def _ascii_vpc_build_dir(self, runtime_output_path):
        runtime_output_path = os.path.normpath(os.path.abspath(str(runtime_output_path or "")))
        key = hashlib.sha1(os.path.normcase(runtime_output_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:16]
        folder = os.path.dirname(runtime_output_path)
        candidates = []
        while folder:
            if self._is_ascii_path(folder):
                candidates.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        for candidate in candidates:
            build_dir = os.path.join(candidate, "_ortho_manager_vpc_work_ascii", key, "pdal_vpc_ascii")
            if not self._is_ascii_path(build_dir):
                continue
            try:
                os.makedirs(build_dir, exist_ok=True)
                return build_dir
            except Exception:
                _om_record_ignored_exception(__name__, 4892); continue
        return ""

    def _normalize_vpc_asset_hrefs(self, vpc_path):
        path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        temp_path = path + ".href_tmp"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise RuntimeError("VPCファイルのJSON形式が正しくありません。")

            changed = 0
            for feature in data.get("features", []) or []:
                if not isinstance(feature, dict):
                    continue
                assets = feature.get("assets", {})
                if not isinstance(assets, dict):
                    continue
                for asset in assets.values():
                    if not isinstance(asset, dict):
                        continue
                    href = asset.get("href")
                    if not isinstance(href, str):
                        continue
                    normalized = href.replace("\\", "/")
                    if normalized != href:
                        asset["href"] = normalized
                        changed += 1

            if changed:
                with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                os.replace(temp_path, path)
            return changed
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                _om_record_ignored_exception(__name__, 4933)
            raise

    def _build_vpc_with_pdal_wrench(self, processing_sources, runtime_output_path, work_dir=None, reference_output_path=None):
        output_dir = os.path.dirname(os.path.normpath(os.path.abspath(runtime_output_path)))
        work_dir = work_dir or output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(work_dir, exist_ok=True)
        build_dir, input_list_path, temp_output_path = self._prepare_pdal_ascii_vpc_build(
            processing_sources,
            runtime_output_path,
            work_dir,
            reference_output_path=reference_output_path,
        )
        if os.path.exists(runtime_output_path):
            os.remove(runtime_output_path)
        if os.path.exists(temp_output_path):
            os.remove(temp_output_path)
        wrench_path = self._pdal_wrench_path()
        threads = max(1, min(24, (os.cpu_count() or 4)))
        result = self._run_hidden_process(
            [
                wrench_path,
                "build_vpc",
                f"--output={os.path.basename(temp_output_path)}",
                f"--threads={threads}",
                f"--input-file-list={os.path.basename(input_list_path)}",
            ],
            cwd=build_dir,
        )
        if result.returncode != 0 or not os.path.exists(temp_output_path):
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"VPC作成に失敗しました。\n\n{detail}")
        self._normalize_vpc_asset_hrefs(temp_output_path)
        shutil.copy2(temp_output_path, runtime_output_path)
        ascii_parent = os.path.dirname(os.path.dirname(build_dir))
        self._cleanup_vpc_work_dir(os.path.dirname(build_dir), label="VPC_ASCII_WORK")
        self._cleanup_empty_vpc_work_parent(ascii_parent, "_ortho_manager_vpc_work_ascii")
        return runtime_output_path

    def _copy_vpc_copc_folder_to_output(self, runtime_output_path, output_path, copc_source_list=None):
        src_dir = os.path.join(
            os.path.dirname(os.path.abspath(runtime_output_path)),
            self._copc_cache_folder_name_for_vpc(output_path),
        )
        dst_dir = self._copc_cache_root_for_vpc(output_path)
        if not os.path.isdir(src_dir):
            return []
        os.makedirs(dst_dir, exist_ok=True)
        copied = []
        sources = copc_source_list or [os.path.join(src_dir, filename) for filename in os.listdir(src_dir)]
        for src in sources:
            filename = os.path.basename(str(src))
            if not filename.lower().endswith(".copc.laz"):
                continue
            src = os.path.join(src_dir, filename)
            if not os.path.exists(src):
                continue
            dst = os.path.join(dst_dir, filename)
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst)):
                shutil.copy2(src, dst)
            copied.append(dst)
        return copied

    def _get_vpc_layer(self, name, vpc_path=None):
        point_cloud_cls = self._point_cloud_layer_class()
        target_path = ""
        if vpc_path:
            try:
                target_path = os.path.normcase(os.path.abspath(os.path.normpath(vpc_path)))
            except Exception:
                target_path = os.path.normcase(os.path.normpath(str(vpc_path)))

        if target_path:
            for lyr in QgsProject.instance().mapLayers().values():
                if point_cloud_cls is None:
                    try:
                        if getattr(lyr, "type", lambda: None)() != getattr(Qgis.LayerType, "PointCloud", object()):
                            continue
                    except Exception:
                        _om_record_ignored_exception(__name__, 5013); continue
                elif not isinstance(lyr, point_cloud_cls):
                    continue
                try:
                    source_path = os.path.normcase(os.path.abspath(self._resolved_layer_source_path(lyr)))
                except Exception:
                    source_path = os.path.normcase(self._resolved_layer_source_path(lyr))
                if source_path and source_path == target_path:
                    return lyr

        for layer_name in {self.format_vpc_display_name(name), self.strip_vpc_display_prefix(name)}:
            if not layer_name:
                continue
            for lyr in QgsProject.instance().mapLayersByName(layer_name):
                if point_cloud_cls is None:
                    try:
                        if getattr(lyr, "type", lambda: None)() == getattr(Qgis.LayerType, "PointCloud", object()):
                            return lyr
                    except Exception:
                        _om_record_ignored_exception(__name__, 5032)
                elif isinstance(lyr, point_cloud_cls):
                    return lyr
        return None

    def read_point_cloud_sources_from_vpc(self, vpc_path):
        sources = []
        seen = set()

        def add_path(value):
            text = str(value or "").strip()
            if not text:
                return
            lower = text.lower()
            if not lower.endswith((".las", ".laz", ".copc.laz")):
                return
            path = text
            if not os.path.isabs(path):
                path = os.path.join(os.path.dirname(os.path.abspath(vpc_path)), path)
            path = os.path.normpath(path)
            key = os.path.normcase(path)
            if key in seen:
                return
            seen.add(key)
            sources.append(path)

        def walk_fallback(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk_fallback(item)
            elif isinstance(value, list):
                for item in value:
                    walk_fallback(item)
            elif isinstance(value, str):
                add_path(value)

        try:
            with open(vpc_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                meta = data.get("ortho_manager", {})
                if isinstance(meta, dict):
                    saved_sources = meta.get("source_list") or meta.get("original_source_list")
                    if isinstance(saved_sources, list):
                        for source_path in saved_sources:
                            add_path(source_path)
                        if sources:
                            return sources
                for feature in data.get("features", []) or []:
                    if not isinstance(feature, dict):
                        continue
                    assets = feature.get("assets", {})
                    if not isinstance(assets, dict):
                        continue
                    for asset in assets.values():
                        if isinstance(asset, dict):
                            add_path(asset.get("href", ""))
                if not sources:
                    walk_fallback(data)
            else:
                walk_fallback(data)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_SOURCE_READ_FAILED path={vpc_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        return sources

    def write_vpc_embedded_metadata(self, vpc_path, entry):
        path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            meta = data.get("ortho_manager", {})
            if not isinstance(meta, dict):
                meta = {}
            group_crs_authid = str(entry.get("group_crs_authid", "") or "")
            meta.update({
                "version": 1,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_count": len(entry.get("source_list", []) or []),
                "source_list": [os.path.normpath(str(p)) for p in entry.get("source_list", []) if str(p or "").strip()],
                "processing_source_list": [os.path.normpath(str(p)) for p in entry.get("processing_source_list", []) if str(p or "").strip()],
                "copc_source_list": [os.path.normpath(str(p)) for p in entry.get("copc_source_list", []) if str(p or "").strip()],
                "source_records": list(entry.get("source_records", []) or self._vpc_source_records(entry.get("source_list", []) or [], entry.get("copc_source_list", []) or [])),
                "orphaned_copc_records": list(entry.get("orphaned_copc_records", []) or []),
                "copc_folder": self._copc_cache_folder_name_for_vpc(path),
                "group_crs_authid": group_crs_authid,
                "crs_authid": group_crs_authid,
            })
            data["ortho_manager"] = meta
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_EMBEDDED_METADATA_WRITE_FAILED path={path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def write_empty_vpc_file(self, vpc_path, crs_authid=""):
        vpc_path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        if not vpc_path:
            return False, "VPCパスがありません"
        try:
            folder = os.path.dirname(vpc_path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            data = {
                "type": "FeatureCollection",
                "features": [],
                "ortho_manager": {
                    "source_count": 0,
                    "group_crs_authid": str(crs_authid or ""),
                    "crs_authid": str(crs_authid or ""),
                },
            }
            with open(vpc_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return True, ""
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_EMPTY_WRITE_FAILED path={vpc_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False, str(e)

    def run_virtual_point_cloud_algorithm(self, source_list, output_path, progress_callback=None):
        import processing

        self._emit_vpc_progress(progress_callback, 5, "入力ファイル確認中")
        alg = QgsApplication.processingRegistry().algorithmById("pdal:virtualpointcloud")
        if alg is None:
            raise RuntimeError("QGISの処理アルゴリズム pdal:virtualpointcloud が見つかりません。PDAL/点群処理プロバイダを確認してください。")

        source_list = [os.path.normpath(os.path.abspath(str(p))) for p in source_list if p]
        missing_paths = [p for p in source_list if not os.path.exists(p)]
        if missing_paths:
            sample = "\n".join(missing_paths[:5])
            raise RuntimeError(f"点群ファイルが見つかりません。\n\n{sample}")
        processing_source_list, subst_mappings = self._vpc_processing_sources(source_list)
        output_path = os.path.normpath(os.path.abspath(str(output_path)))
        output_dir = os.path.dirname(output_path)
        output_base = os.path.splitext(os.path.basename(output_path))[0] or "layer"
        runtime_base = self._safe_ascii_file_stem(output_base, fallback="vpc")
        runtime_key = hashlib.sha1(os.path.normcase(output_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:8]
        runtime_output_path = os.path.join(output_dir, f".{runtime_base}_{runtime_key}_build.vpc")
        work_dir = self._vpc_cache_dir(output_path)

        need_copc_conversion = self._vpc_sources_need_copc_conversion(source_list)
        copc_only_sources = self._vpc_sources_are_copc(source_list)
        force_convert_sources = self._vpc_source_change_overrides(source_list, output_path)

        if need_copc_conversion or copc_only_sources:
            if need_copc_conversion:
                copc_source_list = self._ensure_copc_sources_for_vpc(
                    source_list,
                    processing_source_list,
                    output_path,
                    work_dir=work_dir,
                    progress_callback=progress_callback,
                    progress_start=10,
                    progress_end=82,
                    force_convert_sources=force_convert_sources,
                )
                build_mode = "per_file_copc"
            else:
                self._emit_vpc_progress(progress_callback, 82, "COPC確認完了")
                copc_source_list = list(processing_source_list)
                build_mode = "copc_only"
            self._emit_vpc_progress(progress_callback, 84, "VPCファイル作成中")
            self._build_vpc_with_pdal_wrench(copc_source_list, runtime_output_path, work_dir=work_dir, reference_output_path=output_path)
            self._emit_vpc_progress(progress_callback, 88, "VPCファイル保存中")
            shutil.copy2(runtime_output_path, output_path)
            saved_copc_source_list = list(copc_source_list)
            try:
                if os.path.exists(runtime_output_path):
                    os.remove(runtime_output_path)
            except Exception:
                _om_record_ignored_exception(__name__, 5221)
            self._log_vpc_verbose(
                f"VPC_BUILD_DONE mode={build_mode} output={output_path} count={len(source_list)} subst_count={len(subst_mappings)} copc_saved={len(saved_copc_source_list)} work_dir={work_dir}"
            )
            self._emit_vpc_progress(progress_callback, 89, "一時ファイル整理中")
            cleaned = self._cleanup_vpc_work_dir(work_dir, label="VPC_WORK")
            if cleaned:
                self._cleanup_empty_vpc_work_parent(os.path.dirname(work_dir), "_ortho_manager_vpc_work")
            self._emit_vpc_progress(progress_callback, 90, "VPCファイル作成完了")
            return {
                "OUTPUT": output_path,
                "_ORTHO_VPC_RUNTIME_PATH": output_path,
                "_ORTHO_VPC_SUBST_MAPPINGS": subst_mappings,
                "_ORTHO_VPC_PROCESSING_SOURCES": saved_copc_source_list or copc_source_list,
                "_ORTHO_VPC_COPC_SOURCES": saved_copc_source_list or copc_source_list,
                "_ORTHO_VPC_SOURCE_RECORDS": self._vpc_source_records(source_list, saved_copc_source_list or copc_source_list),
            }

        input_param = None
        output_param = None
        params = {}
        param_info = []
        for definition in alg.parameterDefinitions():
            name = definition.name()
            upper = name.upper()
            try:
                param_type = definition.type()
            except Exception:
                param_type = ""
            param_info.append(f"{name}:{param_type}")
            if input_param is None and upper in ("LAYERS", "INPUT", "INPUTS", "POINTCLOUDS", "POINT_CLOUDS", "POINTCLOUD"):
                input_param = name
                continue
            if output_param is None and upper in ("OUTPUT", "VPC", "OUTPUT_FILE"):
                output_param = name
                continue
            if upper == "CONVERT_COPC" and "boolean" in str(param_type).lower():
                params[name] = self._vpc_sources_need_copc_conversion(source_list)
                continue
            if ("BOUNDARY" in upper or "STATISTIC" in upper or "OVERVIEW" in upper) and "boolean" in str(param_type).lower():
                params[name] = False

        if input_param is None or output_param is None:
            names = ", ".join(d.name() for d in alg.parameterDefinitions())
            raise RuntimeError(f"pdal:virtualpointcloud の入力/出力パラメータを判定できません: {names}")

        point_cloud_cls = self._point_cloud_layer_class()
        point_cloud_layers = []
        layer_errors = []
        if point_cloud_cls is not None:
            for path in processing_source_list:
                layer = None
                layer_name = os.path.splitext(os.path.basename(path))[0] or os.path.basename(path)
                for args in ((path, layer_name, "pdal"), (path, layer_name)):
                    try:
                        candidate = point_cloud_cls(*args)
                        if candidate and candidate.isValid():
                            layer = candidate
                            break
                    except Exception as e:
                        layer_errors.append(f"{os.path.basename(path)} args={len(args)} error={e!r}")
                if layer is None:
                    layer_errors.append(f"{os.path.basename(path)} を点群レイヤとして読み込めません")
                else:
                    point_cloud_layers.append(layer)

        self._log_vpc_verbose(
            "VPC_BUILD_PARAMS "
            f"input={input_param} output={output_param} params={';'.join(param_info)} "
            f"values={params} count={len(source_list)} layer_count={len(point_cloud_layers)} subst_count={len(subst_mappings)}"
        )
        if layer_errors:
            QgsMessageLog.logMessage(
                "VPC_POINT_CLOUD_LAYER_WARN " + " | ".join(layer_errors[:8]),
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

        attempts = []
        if point_cloud_layers and len(point_cloud_layers) == len(processing_source_list):
            attempts.append(("layer_objects", list(point_cloud_layers), False))
        attempts.append(("path_list", list(processing_source_list), False))
        attempts.append(("path_semicolon", ";".join(processing_source_list), False))
        if point_cloud_layers and len(point_cloud_layers) == len(processing_source_list):
            attempts.append(("registered_layer_ids", list(point_cloud_layers), True))

        temp_output_path = runtime_output_path
        errors = []
        for mode, input_value, register_layers in attempts:
            self._emit_vpc_progress(progress_callback, 84, "VPCファイル作成中")
            registered_ids = []
            run_params = dict(params)
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
                if register_layers:
                    project = QgsProject.instance()
                    for layer in point_cloud_layers:
                        project.addMapLayer(layer, False)
                        registered_ids.append(layer.id())
                    input_value = list(registered_ids)
                run_params[input_param] = input_value
                run_params[output_param] = temp_output_path
                result = processing.run("pdal:virtualpointcloud", run_params)
                result_path = ""
                if isinstance(result, dict):
                    result_path = result.get(output_param) or result.get("OUTPUT") or ""
                produced_path = result_path if result_path and os.path.exists(result_path) else temp_output_path
                if produced_path and os.path.exists(produced_path) and os.path.normcase(produced_path) != os.path.normcase(runtime_output_path):
                    shutil.copy2(produced_path, runtime_output_path)
                    produced_path = runtime_output_path
                if produced_path and os.path.exists(produced_path):
                    shutil.copy2(produced_path, output_path)
                if not isinstance(result, dict):
                    result = {}
                result[output_param] = output_path
                result["OUTPUT"] = output_path
                result["_ORTHO_VPC_RUNTIME_PATH"] = output_path
                result["_ORTHO_VPC_SUBST_MAPPINGS"] = subst_mappings
                result["_ORTHO_VPC_PROCESSING_SOURCES"] = processing_source_list
                self._log_vpc_verbose(
                    f"VPC_BUILD_DONE mode={mode} output={output_path} count={len(source_list)} subst_count={len(subst_mappings)} work_dir={work_dir}"
                )
                self._emit_vpc_progress(progress_callback, 90, "VPCファイル作成完了")
                return result
            except Exception as e:
                detail = f"{mode}: {e!r}"
                errors.append(detail)
                QgsMessageLog.logMessage(
                    f"VPC_BUILD_ATTEMPT_FAILED mode={mode} error={e!r}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
            finally:
                if registered_ids:
                    try:
                        QgsProject.instance().removeMapLayers(registered_ids)
                    except Exception:
                        _om_record_ignored_exception(__name__, 5359)
        detail = "\n".join(errors[-4:]) if errors else "原因不明"
        raise RuntimeError(f"QGISのVPC作成処理が失敗しました。\n\n{detail}")

    def _resolved_layer_source_path(self, layer):
        if not layer:
            return ""
        try:
            source = layer.source() or ""
        except Exception:
            return ""
        source_path = source.split("|", 1)[0].strip()
        if not source_path:
            return ""
        if not os.path.isabs(source_path):
            home_path = QgsProject.instance().homePath()
            if home_path:
                source_path = os.path.join(home_path, source_path)
        return os.path.normpath(source_path)

    def _sync_registry_paths_from_project_layers(self):
        updated_count = 0
        for name, entry in list(self.vrt_registry.items()):
            if not isinstance(entry, dict):
                continue
            layer = self._get_vrt_layer(name)
            resolved_path = self._resolved_layer_source_path(layer)
            if not resolved_path:
                continue
            old_path = os.path.normpath(entry.get("path", ""))
            if old_path and os.path.normcase(old_path) == os.path.normcase(resolved_path):
                continue
            entry["path"] = resolved_path
            updated_count += 1
        if updated_count:
            QgsMessageLog.logMessage(
                f"VRTパス同期: QGISレイヤの現在パスへ {updated_count} 件更新しました",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        return updated_count

    def _get_overlay_layer(self, name):
        for layer_name in {self.overlay_layer_name(name), f"{self.strip_vrt_display_prefix(name)}_overlay"}:
            if not layer_name:
                continue
            for lyr in QgsProject.instance().mapLayersByName(layer_name):
                if isinstance(lyr, QgsVectorLayer): return lyr
        return None

    def _get_vpc_overlay_layer(self, name):
        for layer_name in {self.vpc_overlay_layer_name(name), f"{self.strip_vpc_display_prefix(name)}_overlay"}:
            if not layer_name:
                continue
            for lyr in QgsProject.instance().mapLayersByName(layer_name):
                if isinstance(lyr, QgsVectorLayer):
                    return lyr
        return None

    def _registry_group_crs_authid(self, name):
        entry = self.vrt_registry.get(self.format_vrt_display_name(name), {})
        authid = entry.get("group_crs_authid", "") if isinstance(entry, dict) else ""
        return authid if isinstance(authid, str) else ""

    def _group_crs_from_registry(self, name):
        authid = self._registry_group_crs_authid(name)
        crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
        return crs if crs.isValid() else QgsCoordinateReferenceSystem()

    def _registry_vpc_crs_authid(self, name):
        entry = self.vpc_registry.get(self.format_vpc_display_name(name), {})
        authid = entry.get("group_crs_authid", "") if isinstance(entry, dict) else ""
        return authid if isinstance(authid, str) else ""

    def _vpc_crs_from_registry(self, name):
        authid = self._registry_vpc_crs_authid(name)
        crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
        return crs if crs.isValid() else QgsCoordinateReferenceSystem()

    def _vpc_crs_from_path(self, vpc_path):
        if not vpc_path:
            return QgsCoordinateReferenceSystem()
        try:
            target = os.path.normcase(os.path.abspath(vpc_path))
        except Exception:
            target = os.path.normcase(str(vpc_path))
        for name, entry in self.vpc_registry.items():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", "")
            try:
                key = os.path.normcase(os.path.abspath(path))
            except Exception:
                key = os.path.normcase(str(path))
            if key == target:
                return self._vpc_crs_from_registry(name)
        return QgsCoordinateReferenceSystem()

    def _group_crs_from_tree(self, name):
        group = self._find_vrt_group(name)
        if not group:
            return QgsCoordinateReferenceSystem()
        try:
            authid = group.customProperty(self.GROUP_CRS_PROPERTY, "")
        except Exception:
            authid = ""
        crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
        return crs if crs.isValid() else QgsCoordinateReferenceSystem()

    def _vpc_crs_from_tree(self, name):
        group = self._find_vpc_group(name)
        if not group:
            return QgsCoordinateReferenceSystem()
        try:
            authid = group.customProperty(self.GROUP_CRS_PROPERTY, "")
        except Exception:
            authid = ""
        crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
        return crs if crs.isValid() else QgsCoordinateReferenceSystem()

    def _restore_group_crs_property(self, name):
        group = self._find_vrt_group(name)
        crs = self._group_crs_from_registry(name)
        if group and crs.isValid():
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, crs.authid())
            except Exception:
                _om_record_ignored_exception(__name__, 5486)
        if crs.isValid():
            vrt_layer = self._get_vrt_layer(name)
            overlay_layer = self._get_overlay_layer(name)
            try:
                if vrt_layer:
                    vrt_layer.setCrs(crs)
                if overlay_layer:
                    overlay_layer.setCrs(crs)
            except Exception:
                _om_record_ignored_exception(__name__, 5496)

    def _restore_vpc_group_crs_property(self, name):
        group = self._find_vpc_group(name)
        crs = self._vpc_crs_from_registry(name)
        if group and crs.isValid():
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, crs.authid())
            except Exception:
                _om_record_ignored_exception(__name__, 5505)
        if crs.isValid():
            vpc_layer = self._get_vpc_layer(name)
            overlay_layer = self._get_vpc_overlay_layer(name)
            try:
                if vpc_layer:
                    vpc_layer.setCrs(crs)
                if overlay_layer and not self._layer_has_valid_crs(overlay_layer):
                    overlay_layer.setCrs(crs)
            except Exception:
                _om_record_ignored_exception(__name__, 5515)

    def _maybe_set_project_crs_from_vrt(self, crs):
        if not crs or not crs.isValid():
            return False
        try:
            project = QgsProject.instance()
            current = project.crs()
            current_authid = current.authid() if current and current.isValid() else ""
            target_authid = crs.authid()
            if current_authid == target_authid:
                return False
            if current_authid and current_authid not in {"EPSG:4326", "OGC:CRS84"}:
                return False
            project.setCrs(crs)
            QgsMessageLog.logMessage(
                f"PROJECT_CRS_SET_FROM_VRT crs={target_authid}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"PROJECT_CRS_SET_FROM_VRT_FAILED crs={crs.authid()} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def _set_group_crs(self, name, crs, show_message=False):
        apply_start = time.perf_counter()
        name = self.format_vrt_display_name(name)
        if not name or not crs or not crs.isValid():
            return False

        entry = self.vrt_registry.get(name)
        if isinstance(entry, dict):
            entry["group_crs_authid"] = crs.authid()

        group = self._find_vrt_group(name)
        if group:
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, crs.authid())
            except Exception:
                _om_record_ignored_exception(__name__, 5559)

        vrt_layer = self._get_vrt_layer(name)
        overlay_layer = self._get_overlay_layer(name)
        try:
            if vrt_layer:
                vrt_layer.setCrs(crs)
            if overlay_layer:
                overlay_layer.setCrs(crs)
        except Exception as e:
            QgsMessageLog.logMessage(f"グループCRS適用エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)

        vrt_path = self.vrt_registry.get(name, {}).get("path", "")
        if vrt_layer and vrt_path:
            self._save_qml(vrt_layer, vrt_path, overlay_layer)

        self._maybe_set_project_crs_from_vrt(crs)

        if show_message:
            self._show_map_center_alert(f"CRS: {crs.authid()}", duration_ms=3000)
        self._last_group_crs_apply_sec = getattr(self, "_last_group_crs_apply_sec", 0.0) + (time.perf_counter() - apply_start)
        return True

    def _set_vpc_group_crs(self, name, crs, show_message=False):
        apply_start = time.perf_counter()
        name = self.format_vpc_display_name(name)
        if not name or not crs or not crs.isValid():
            return False

        entry = self.vpc_registry.get(name)
        if isinstance(entry, dict):
            entry["group_crs_authid"] = crs.authid()

        group = self._find_vpc_group(name)
        if group:
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, crs.authid())
            except Exception:
                _om_record_ignored_exception(__name__, 5597)

        vpc_layer = self._get_vpc_layer(name)
        overlay_layer = self._get_vpc_overlay_layer(name)
        try:
            if vpc_layer:
                vpc_layer.setCrs(crs)
            if overlay_layer and not self._layer_has_valid_crs(overlay_layer):
                overlay_layer.setCrs(crs)
        except Exception as e:
            QgsMessageLog.logMessage(f"VPCグループCRS適用エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)

        if show_message:
            self._show_map_center_alert(f"CRS: {crs.authid()}", duration_ms=3000)
        self._last_group_crs_apply_sec = getattr(self, "_last_group_crs_apply_sec", 0.0) + (time.perf_counter() - apply_start)
        return True

    def _open_group_crs_dialog(self, name, initial_crs=None):
        try:
            dialog = QgsProjectionSelectionDialog(self.iface.mainWindow())
            dialog.setWindowTitle(tr_text("グループのCRSを設定"))
            if initial_crs and initial_crs.isValid():
                try:
                    dialog.setCrs(initial_crs)
                except Exception:
                    _om_record_ignored_exception(__name__, 5622)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            crs = dialog.crs()
            if crs and crs.isValid():
                self._set_group_crs(name, crs)
                return crs
        except Exception as e:
            QgsMessageLog.logMessage(f"CRS選択ダイアログエラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
        return None

    def _open_vpc_crs_dialog(self, name, initial_crs=None):
        try:
            dialog = QgsProjectionSelectionDialog(self.iface.mainWindow())
            dialog.setWindowTitle(tr_text("点群グループのCRSを設定"))
            if initial_crs and initial_crs.isValid():
                try:
                    dialog.setCrs(initial_crs)
                except Exception:
                    _om_record_ignored_exception(__name__, 5641)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            crs = dialog.crs()
            if crs and crs.isValid():
                self._set_vpc_group_crs(name, crs)
                return crs
        except Exception as e:
            QgsMessageLog.logMessage(f"VPC_CRS_SELECT_DIALOG_FAILED error={e}", "OrthoManager", Qgis.MessageLevel.Warning)
        return None

    def _handle_group_crs_after_vrt_update(self, name):
        self._last_group_crs_apply_sec = 0.0
        self._last_group_crs_dialog_sec = 0.0
        name = self.format_vrt_display_name(name)
        entry = self.vrt_registry.get(name, {})
        if not isinstance(entry, dict):
            return

        registry_crs = self._group_crs_from_registry(name)
        tree_crs = self._group_crs_from_tree(name)
        if registry_crs.isValid():
            self._set_group_crs(name, registry_crs)
            entry["initial_crs_pending"] = False
            return
        if tree_crs.isValid():
            self._set_group_crs(name, tree_crs)
            entry["initial_crs_pending"] = False
            return

        vrt_layer = self._get_vrt_layer(name)
        layer_crs = vrt_layer.crs() if self._layer_has_valid_crs(vrt_layer) else QgsCoordinateReferenceSystem()
        is_new_initial = bool(entry.get("initial_crs_pending", False))

        if is_new_initial and layer_crs.isValid():
            self._set_group_crs(name, layer_crs, show_message=True)
            entry["initial_crs_pending"] = False
            return

        dialog_start = time.perf_counter()
        selected_crs = self._open_group_crs_dialog(name, layer_crs)
        self._last_group_crs_dialog_sec += time.perf_counter() - dialog_start
        if selected_crs and selected_crs.isValid():
            entry["initial_crs_pending"] = False
            return

        entry["initial_crs_pending"] = False

    def _handle_vpc_crs_before_overlay_build(self, name):
        self._last_group_crs_apply_sec = 0.0
        self._last_group_crs_dialog_sec = 0.0
        name = self.format_vpc_display_name(name)
        entry = self.vpc_registry.get(name, {})
        if not isinstance(entry, dict):
            return QgsCoordinateReferenceSystem()

        registry_crs = self._vpc_crs_from_registry(name)
        tree_crs = self._vpc_crs_from_tree(name)
        if registry_crs.isValid():
            self._set_vpc_group_crs(name, registry_crs)
            entry["initial_crs_pending"] = False
            return registry_crs
        if tree_crs.isValid():
            self._set_vpc_group_crs(name, tree_crs)
            entry["initial_crs_pending"] = False
            return tree_crs

        try:
            project_crs = QgsProject.instance().crs()
        except Exception:
            project_crs = QgsCoordinateReferenceSystem()

        dialog_start = time.perf_counter()
        selected_crs = self._open_vpc_crs_dialog(name, project_crs)
        self._last_group_crs_dialog_sec += time.perf_counter() - dialog_start

        if selected_crs and selected_crs.isValid():
            self._set_vpc_group_crs(name, selected_crs, show_message=True)
            entry["initial_crs_pending"] = False
            return selected_crs

        entry["initial_crs_pending"] = False
        return QgsCoordinateReferenceSystem()

    def _get_tif_list_from_vrt(self, vrt_path):
        try:
            from osgeo import gdal
            ds = gdal.Open(vrt_path)
            if ds:
                files = ds.GetFileList()
                ds = None
                if files:
                    tif_list = [f for f in files[1:] if is_supported_raster_path(f)]
                    cleaned, dup_paths, dup_names = self._clean_tif_list_unique_names(tif_list)
                    self._warn_if_tif_duplicates_removed(os.path.basename(vrt_path), dup_paths, dup_names)
                    return cleaned
        except: _om_record_ignored_exception(__name__, 5737)
        return []

    def _path_key(self, path):
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))

    def _source_path_key(self, source_elem, vrt_path):
        if source_elem is None or not source_elem.text:
            return ""
        path = source_elem.text
        if source_elem.get("relativeToVRT") == "1":
            path = os.path.join(os.path.dirname(vrt_path), path)
        return self._path_key(path)

    def _remove_vrt_sources_from_xml(self, vrt_path, paths_to_remove=None, clear_all=False):
        if not vrt_path or not os.path.exists(vrt_path):
            return 0

        remove_keys = {self._path_key(p) for p in (paths_to_remove or [])}
        tree = parse_vrt_xml(vrt_path)
        root = tree.getroot()
        removed_count = 0

        for band in root.findall("VRTRasterBand"):
            for src in list(band.findall("SimpleSource")) + list(band.findall("ComplexSource")):
                fname_elem = src.find("SourceFilename")
                should_remove = clear_all or self._source_path_key(fname_elem, vrt_path) in remove_keys
                if should_remove:
                    band.remove(src)
                    removed_count += 1

        tree.write(vrt_path, encoding="UTF-8", xml_declaration=True)
        return removed_count

    def _delete_overlay_features_for_tifs(self, overlay_layer, paths_to_remove=None, clear_all=False):
        if not overlay_layer:
            return 0

        remove_keys = {self._path_key(p) for p in (paths_to_remove or [])}
        fids = []
        for feat in overlay_layer.getFeatures():
            loc = feat.attribute("location")
            if clear_all or (loc and self._path_key(loc) in remove_keys):
                fids.append(feat.id())

        if not fids:
            overlay_layer.removeSelection()
            overlay_layer.triggerRepaint()
            return 0

        was_editable = overlay_layer.isEditable()
        if not was_editable and not overlay_layer.startEditing():
            raise Exception("overlayレイヤの編集開始に失敗しました")

        ok = True
        for fid in fids:
            ok = overlay_layer.deleteFeature(fid) and ok

        if not ok:
            if not was_editable:
                overlay_layer.rollBack()
            raise Exception("overlay featureの削除に失敗しました")

        if not was_editable and not overlay_layer.commitChanges():
            overlay_layer.rollBack()
            raise Exception("overlayレイヤの保存に失敗しました")

        overlay_layer.removeSelection()
        overlay_layer.updateExtents()
        if hasattr(overlay_layer, "dataProvider") and overlay_layer.dataProvider():
            try: overlay_layer.dataProvider().reloadData()
            except: _om_record_ignored_exception(__name__, 5808)
        overlay_layer.triggerRepaint()
        return len(fids)

    def _detach_vrt_raster_layer_for_xml_update(self, display_name, vrt_layer, vrt_path):
        if not vrt_layer:
            return None

        root = QgsProject.instance().layerTreeRoot()
        old_node = root.findLayer(vrt_layer.id())
        parent = old_node.parent() if old_node else None
        if not parent:
            parent = root

        try:
            insert_index = parent.children().index(old_node) if old_node else len(parent.children())
        except Exception:
            insert_index = len(parent.children())

        state = {
            "name": vrt_layer.name(),
            "parent": parent,
            "parent_group_name": parent.name() if parent and parent != root else "",
            "display_name": display_name,
            "insert_index": insert_index,
            "crs": None,
            "scale_based": False,
            "min_scale": 0,
            "max_scale": 0,
            "visible": None,
        }

        try:
            state["crs"] = vrt_layer.crs()
            state["scale_based"] = vrt_layer.hasScaleBasedVisibility()
            state["min_scale"] = vrt_layer.minimumScale()
            state["max_scale"] = vrt_layer.maximumScale()
        except Exception:
            _om_record_ignored_exception(__name__, 5846)

        try:
            if old_node and hasattr(old_node, "itemVisibilityChecked"):
                state["visible"] = old_node.itemVisibilityChecked()
        except Exception:
            _om_record_ignored_exception(__name__, 5852)

        try:
            vrt_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + ".qml")
        except Exception:
            _om_record_ignored_exception(__name__, 5857)

        self._disconnect_scale_signal(display_name)
        QgsProject.instance().removeMapLayer(vrt_layer.id())
        QApplication.processEvents()
        return state

    def _restore_vrt_raster_layer_after_xml_update(self, display_name, vrt_path, overlay_layer, state):
        if not state or not vrt_path or not os.path.exists(vrt_path):
            return None

        gdal, old_pam_enabled = self._disable_gdal_pam("VRTラスタ再読込")
        new_layer = QgsRasterLayer(vrt_path, state.get("name") or display_name, "gdal")
        if not new_layer.isValid():
            self._restore_gdal_pam(gdal, old_pam_enabled)
            raise Exception("VRTラスタレイヤの再読み込みに失敗しました")

        qml_path = os.path.splitext(vrt_path)[0] + ".qml"
        try:
            if os.path.exists(qml_path):
                new_layer.loadNamedStyle(qml_path)
        except Exception:
            _om_record_ignored_exception(__name__, 5879)

        try:
            saved_crs = state.get("crs")
            if saved_crs and saved_crs.isValid():
                new_layer.setCrs(saved_crs)
            new_layer.setScaleBasedVisibility(bool(state.get("scale_based")))
            new_layer.setMinimumScale(state.get("min_scale", 0))
            new_layer.setMaximumScale(state.get("max_scale", 0))
        except Exception:
            _om_record_ignored_exception(__name__, 5889)

        try:
            from qgis.core import QgsRasterDataProvider
            provider = new_layer.dataProvider()
            if provider and hasattr(provider, "setZoomedInResamplingMethod"):
                provider.setZoomedInResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
                provider.setZoomedOutResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
        except Exception:
            _om_record_ignored_exception(__name__, 5898)

        root = QgsProject.instance().layerTreeRoot()
        parent = None
        for group_name in (state.get("display_name"), state.get("parent_group_name"), display_name, self.strip_vrt_display_prefix(display_name)):
            if group_name:
                parent = root.findGroup(group_name)
                if parent:
                    break
        if parent is None:
            parent = root.insertGroup(0, display_name)
            parent.setExpanded(False)
        insert_index = max(0, min(state.get("insert_index", len(parent.children())), len(parent.children())))
        QgsProject.instance().addMapLayer(new_layer, False)
        new_node = parent.insertLayer(insert_index, new_layer)
        try:
            if state.get("visible") is not None and hasattr(new_node, "setItemVisibilityChecked"):
                new_node.setItemVisibilityChecked(state["visible"])
        except Exception:
            _om_record_ignored_exception(__name__, 5917)

        self._connect_scale_signal(new_layer, overlay_layer)
        self._connect_property_changed(new_layer, vrt_path, overlay_layer)
        try:
            new_layer.triggerRepaint()
        except Exception:
            _om_record_ignored_exception(__name__, 5924)
        self._restore_gdal_pam(gdal, old_pam_enabled)
        return new_layer

    def _target_tif_list_after_removal(self, display_name, paths_to_remove=None, clear_all=False):
        if clear_all:
            return []
        remove_keys = {self._path_key(p) for p in (paths_to_remove or [])}
        return [
            p for p in self.vrt_registry.get(display_name, {}).get("tif_list", [])
            if self._path_key(p) not in remove_keys
        ]

    def _replace_file_with_retry(self, src_path, dest_path, label, attempts=10, sleep_seconds=0.2):
        if not src_path or not os.path.exists(src_path):
            return False
        last_error = None
        try:
            attempts = max(1, int(attempts))
        except Exception:
            attempts = 10
        try:
            sleep_seconds = max(0.05, float(sleep_seconds))
        except Exception:
            sleep_seconds = 0.2
        for _attempt in range(attempts):
            try:
                os.replace(src_path, dest_path)
                return _attempt + 1
            except Exception as e:
                last_error = e
                QApplication.processEvents()
                time.sleep(sleep_seconds)
        raise Exception(f"{label}の差し替えに失敗しました: {last_error}")

    def _update_vrt_contents_after_tif_removal_external(self, display_name, entry, paths_to_remove, clear_all, engine_path):
        vrt_path = entry.get("path", "")
        if not vrt_path or not os.path.exists(vrt_path):
            return False, "VRTファイルが見つかりません"

        gpkg_path = os.path.splitext(vrt_path)[0] + "_tiles.gpkg"
        original_tif_list = list(entry.get("tif_list", []))
        target_tif_list = self._target_tif_list_after_removal(display_name, paths_to_remove, clear_all)
        remove_count = len(original_tif_list) - len(target_tif_list)
        insert_index = self._vrt_group_insert_index(display_name)
        vrt_layer = self._get_vrt_layer(display_name)
        overlay_layer = self._get_overlay_layer(display_name)
        saved_crs = None
        saved_overlay_crs = None
        temp_vrt = vrt_path + ".tmp.vrt"
        temp_gpkg = gpkg_path + ".tmp.gpkg"
        total_start = time.perf_counter()

        try:
            if vrt_layer:
                try:
                    saved_crs = vrt_layer.crs()
                    vrt_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + ".qml")
                except Exception:
                    _om_record_ignored_exception(__name__, 5983)
            if overlay_layer:
                try:
                    saved_overlay_crs = overlay_layer.crs()
                    overlay_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + "_overlay.qml")
                except Exception:
                    _om_record_ignored_exception(__name__, 5989)
            if not (saved_crs and saved_crs.isValid()):
                saved_crs, saved_overlay_crs_from_json = self._load_crs_json(vrt_path)
                if not (saved_overlay_crs and saved_overlay_crs.isValid()):
                    saved_overlay_crs = saved_overlay_crs_from_json

            self._set_status(tr_text("⏳ 外部VRTエンジンで削除更新中..."))
            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=False)
            self._disconnect_scale_signal(display_name)
            self._remove_vrt_group(display_name)
            QApplication.processEvents()

            QgsMessageLog.logMessage(
                f"VRT_ENGINE_MODE external path={engine_path}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            success, err_msg, temp_vrt, temp_gpkg, timing = run_external_vrt_engine_sync(
                target_tif_list,
                vrt_path,
                gpkg_path,
                True,
                engine_path,
            )
            if not success:
                raise Exception(err_msg or "外部VRTエンジンで削除更新に失敗しました")

            move_start = time.perf_counter()
            if not self._replace_file_with_retry(temp_vrt, vrt_path, "VRT"):
                raise Exception("外部VRTエンジンの一時VRTが見つかりません")
            self._replace_file_with_retry(temp_gpkg, gpkg_path, "GPKG")
            move_sec = time.perf_counter() - move_start

            entry["tif_list"] = list(target_tif_list)
            self.vrt_registry[display_name] = entry
            self._load_vrt_with_overlay(
                vrt_path,
                display_name,
                apply_default_style=False,
                saved_crs=saved_crs,
                saved_overlay_crs=saved_overlay_crs,
                rebuild_gpkg=False,
                insert_index=insert_index,
            )
            self._handle_group_crs_after_vrt_update(display_name)
            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=True)
            total_sec = time.perf_counter() - total_start
            QgsMessageLog.logMessage(
                "VRT_DELETE_ENGINE_SUMMARY "
                f"layer={display_name} remove_count={max(0, remove_count)} "
                f"tif_count={len(target_tif_list)} total_sec={total_sec:.2f} "
                f"mode={str(timing.get('vrt_update_mode', 'VRT更新')).replace(' ', '_')} "
                f"vrt_update_sec={float(timing.get('vrt_update_sec', 0.0)):.2f} "
                f"gpkg_sec={float(timing.get('gpkg_sec', 0.0)):.2f} "
                f"move_sec={move_sec:.2f} pam_disabled={bool(timing.get('pam_disabled', False))}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return True, ""
        except Exception as e:
            try:
                entry["tif_list"] = original_tif_list
                self.vrt_registry[display_name] = entry
            except Exception:
                _om_record_ignored_exception(__name__, 6053)
            for tmp_path in (temp_vrt, temp_gpkg):
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    _om_record_ignored_exception(__name__, 6059)
            try:
                if not self._get_vrt_layer(display_name) and os.path.exists(vrt_path):
                    self._load_vrt_with_overlay(
                        vrt_path,
                        display_name,
                        apply_default_style=False,
                        saved_crs=saved_crs,
                        saved_overlay_crs=saved_overlay_crs,
                        rebuild_gpkg=False,
                        insert_index=insert_index,
                    )
            except Exception:
                _om_record_ignored_exception(__name__, 6072)
            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=True)
            QgsMessageLog.logMessage(f"外部VRT削除更新エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False, str(e)
    def update_vrt_contents_after_tif_removal(self, name, paths_to_remove=None, clear_all=False):
        display_name = self.format_vrt_display_name(name)
        entry = self.vrt_registry.get(display_name)
        if not entry:
            return False, "VRT登録が見つかりません"

        vrt_path = entry.get("path", "")
        engine_path = find_external_vrt_engine_path()
        if engine_path:
            return self._update_vrt_contents_after_tif_removal_external(
                display_name,
                entry,
                paths_to_remove,
                clear_all,
                engine_path,
            )

        vrt_layer = self._get_vrt_layer(display_name)
        overlay_layer = self._get_overlay_layer(display_name)
        original_xml = None
        vrt_layer_state = None

        try:
            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=False)
            if vrt_layer:
                vrt_layer_state = self._detach_vrt_raster_layer_for_xml_update(display_name, vrt_layer, vrt_path)
                vrt_layer = None

            if vrt_path and os.path.exists(vrt_path):
                with open(vrt_path, "r", encoding="utf-8") as f:
                    original_xml = f.read()
                self._remove_vrt_sources_from_xml(vrt_path, paths_to_remove, clear_all)

            self._delete_overlay_features_for_tifs(overlay_layer, paths_to_remove, clear_all)

            if vrt_layer_state:
                vrt_layer = self._restore_vrt_raster_layer_after_xml_update(display_name, vrt_path, overlay_layer, vrt_layer_state)
            if overlay_layer:
                overlay_layer.triggerRepaint()

            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=True)
            return True, ""
        except Exception as e:
            if original_xml is not None and vrt_path:
                try:
                    with open(vrt_path, "w", encoding="utf-8") as f:
                        f.write(original_xml)
                except Exception:
                    _om_record_ignored_exception(__name__, 6124)
            if vrt_layer:
                try: vrt_layer.triggerRepaint()
                except Exception: _om_record_ignored_exception(__name__, 6127)
            elif vrt_layer_state:
                try: self._restore_vrt_raster_layer_after_xml_update(display_name, vrt_path, overlay_layer, vrt_layer_state)
                except Exception: _om_record_ignored_exception(__name__, 6130)
            if overlay_layer:
                try: overlay_layer.triggerRepaint()
                except Exception: _om_record_ignored_exception(__name__, 6133)
            self._invalidate_vrt_display_caches(refresh=True, schedule_prefetch=True)
            QgsMessageLog.logMessage(f"VRT中身更新エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
            return False, str(e)

    def _vrt_group_insert_index(self, name):
        root = QgsProject.instance().layerTreeRoot()
        display_name = self.format_vrt_display_name(name)
        base_name = self.strip_vrt_display_prefix(name)
        group = root.findGroup(display_name) or root.findGroup(base_name)
        if not group:
            return None
        try:
            return root.children().index(group)
        except ValueError:
            return None

    def _remove_vrt_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        display_name = self.format_vrt_display_name(name)
        base_name = self.strip_vrt_display_prefix(name)
        group = root.findGroup(display_name) or root.findGroup(base_name)
        if group:
            layer_ids = [child.layerId() for child in group.children() if isinstance(child, QgsLayerTreeLayer)]
            for lid in layer_ids:
                lyr = QgsProject.instance().mapLayer(lid)
                if lyr:
                    if hasattr(lyr, 'dataProvider') and lyr.dataProvider():
                        try: lyr.dataProvider().reloadData()
                        except: _om_record_ignored_exception(__name__, 6162)
                    QgsProject.instance().removeMapLayer(lid)
            root.removeChildNode(group)
        else:
            for lyr in QgsProject.instance().mapLayersByName(display_name) + QgsProject.instance().mapLayersByName(base_name):
                if isinstance(lyr, QgsRasterLayer): QgsProject.instance().removeMapLayer(lyr.id())
            for lyr in QgsProject.instance().mapLayersByName(self.overlay_layer_name(name)) + QgsProject.instance().mapLayersByName(f"{base_name}_overlay"):
                if hasattr(lyr, 'dataProvider') and lyr.dataProvider():
                    try: lyr.dataProvider().reloadData()
                    except: _om_record_ignored_exception(__name__, 6171)
                QgsProject.instance().removeMapLayer(lyr.id())
        self.iface.mapCanvas().refresh()
        QApplication.processEvents()

    def _remove_vpc_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        display_name = self.format_vpc_display_name(name)
        base_name = self.strip_vpc_display_prefix(name)
        group = root.findGroup(display_name) or root.findGroup(base_name)
        if group:
            layer_ids = [child.layerId() for child in group.children() if isinstance(child, QgsLayerTreeLayer)]
            for lid in layer_ids:
                lyr = QgsProject.instance().mapLayer(lid)
                if lyr and hasattr(lyr, "dataProvider") and lyr.dataProvider():
                    try:
                        lyr.dataProvider().reloadData()
                    except Exception:
                        _om_record_ignored_exception(__name__, 6189)
                QgsProject.instance().removeMapLayer(lid)
            root.removeChildNode(group)
        else:
            overlay_names = [self.vpc_overlay_layer_name(display_name), f"{base_name}_overlay"]
            for lyr in (
                QgsProject.instance().mapLayersByName(display_name)
                + QgsProject.instance().mapLayersByName(base_name)
                + [layer for name in overlay_names for layer in QgsProject.instance().mapLayersByName(name)]
            ):
                if lyr and hasattr(lyr, "dataProvider") and lyr.dataProvider():
                    try:
                        lyr.dataProvider().reloadData()
                    except Exception:
                        _om_record_ignored_exception(__name__, 6203)
                QgsProject.instance().removeMapLayer(lyr.id())
        self.iface.mapCanvas().refresh()
        QApplication.processEvents()
        time.sleep(0.1)
        QApplication.processEvents()

    def _vpc_path_match_keys(self, path_text):
        text = str(path_text or "").strip()
        if not text:
            return []
        normalized = text.replace("/", os.sep).replace("\\", os.sep)
        base = os.path.basename(normalized)
        values = [text, base]
        lower_base = base.lower()
        if lower_base.endswith(".copc.laz"):
            values.append(base[:-9])
        if lower_base.endswith(".copc"):
            values.append(base[:-5])
        root, _ext = os.path.splitext(base)
        if root and root != base:
            values.append(root)
        keys = []
        for value in values:
            key = os.path.normcase(str(value).strip()).lower()
            if key and key not in keys:
                keys.append(key)
        return keys

    def _vpc_source_lookup(self, source_list, vpc_path):
        lookup = {}
        output_path = os.path.normpath(os.path.abspath(str(vpc_path or "")))
        for source_path in source_list or []:
            source_path = os.path.normpath(os.path.abspath(str(source_path or ""))) if source_path else ""
            if not source_path:
                continue
            for key in self._vpc_path_match_keys(source_path):
                lookup.setdefault(key, source_path)
            try:
                source_key = hashlib.sha1(os.path.normcase(source_path).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:12]
                copc_name = f"pc_{source_key}.copc.laz"
                for key in self._vpc_path_match_keys(copc_name):
                    lookup.setdefault(key, source_path)
                if output_path:
                    for key in self._vpc_path_match_keys(os.path.join(self._copc_cache_root_for_vpc(output_path), copc_name)):
                        lookup.setdefault(key, source_path)
                for managed_copc_path in self._copc_cache_paths_for_source(source_path, output_path):
                    for key in self._vpc_path_match_keys(managed_copc_path):
                        lookup.setdefault(key, source_path)
            except Exception:
                _om_record_ignored_exception(__name__, 6253)
        return lookup

    def _vpc_feature_string_candidates(self, value):
        candidates = []
        def collect(item):
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                for child in item.values():
                    collect(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    collect(child)
        collect(value)
        return candidates

    def _vpc_source_path_for_feature(self, feature, source_lookup, fallback_id):
        candidates = [fallback_id]
        candidates.extend(self._vpc_feature_string_candidates(feature))
        for candidate in candidates:
            for key in self._vpc_path_match_keys(candidate):
                source_path = source_lookup.get(key)
                if source_path:
                    return source_path
        return fallback_id

    def _build_vpc_overlay_gpkg(self, vpc_path, source_list, fallback_layer=None):
        overlay_path = self._vpc_overlay_path(vpc_path)
        if not overlay_path:
            return ""

        records = []
        overlay_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        source_lookup = self._vpc_source_lookup(source_list or [], vpc_path)

        def crs_from_wkt(wkt_text):
            wkt_text = str(wkt_text or "").strip()
            if not wkt_text:
                return QgsCoordinateReferenceSystem()
            crs = QgsCoordinateReferenceSystem()
            try:
                crs.createFromWkt(wkt_text)
                if crs.isValid():
                    return crs
            except Exception:
                _om_record_ignored_exception(__name__, 6299)
            try:
                crs = QgsCoordinateReferenceSystem(wkt_text)
                if crs.isValid():
                    return crs
            except Exception:
                _om_record_ignored_exception(__name__, 6305)
            return QgsCoordinateReferenceSystem()

        def valid_polygon_geometry(geom):
            if not isinstance(geom, dict):
                return None
            coords = geom.get("coordinates", [])
            if geom.get("type") != "Polygon" or not coords:
                return None
            ring_coords = coords[0] if coords else []
            return ring_coords or None

        if vpc_path and os.path.exists(vpc_path):
            try:
                with open(vpc_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    meta = data.get("ortho_manager", {})
                    if isinstance(meta, dict):
                        crs_authid = str(meta.get("crs_authid", "") or "").strip()
                        if crs_authid:
                            crs = QgsCoordinateReferenceSystem(crs_authid)
                            if crs.isValid():
                                overlay_crs = crs
                        else:
                            registry_crs = self._vpc_crs_from_path(vpc_path)
                            if registry_crs.isValid():
                                overlay_crs = registry_crs
                            else:
                                project_crs = QgsProject.instance().crs()
                                if project_crs.isValid():
                                    overlay_crs = project_crs
                for index, feature in enumerate(data.get("features", []) if isinstance(data, dict) else []):
                    if not isinstance(feature, dict):
                        continue
                    props = feature.get("properties", {})
                    if not isinstance(props, dict):
                        props = {}
                    proj_ring = valid_polygon_geometry(props.get("proj:geometry"))
                    if proj_ring:
                        ring_coords = proj_ring
                        proj_crs = crs_from_wkt(props.get("proj:wkt2"))
                        if proj_crs.isValid():
                            overlay_crs = proj_crs
                    else:
                        ring_coords = valid_polygon_geometry(feature.get("geometry", {}))
                    if not ring_coords:
                        continue
                    item_id = str(feature.get("id", f"tile_{index + 1}"))
                    source_path = self._vpc_source_path_for_feature(feature, source_lookup, item_id)
                    records.append({
                        "name": os.path.basename(source_path),
                        "path": source_path,
                        "ring": ring_coords,
                    })
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_OVERLAY_READ_VPC_FAILED path={vpc_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

        if not records:
            return ""

        try:
            from osgeo import ogr, osr
            driver = ogr.GetDriverByName("GPKG")
            if driver is None:
                return ""
            base, _ext = os.path.splitext(overlay_path)
            temp_overlay_path = f"{base}_tmp_{int(time.time() * 1000)}.gpkg"
            ds = driver.CreateDataSource(temp_overlay_path)
            if ds is None:
                return ""
            srs = None
            if overlay_crs.isValid():
                srs = osr.SpatialReference()
                try:
                    srs.ImportFromWkt(overlay_crs.toWkt())
                except Exception:
                    srs = None
            layer = ds.CreateLayer("vpc_overlay", srs, ogr.wkbPolygon)
            layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
            path_field = ogr.FieldDefn("path", ogr.OFTString)
            path_field.SetWidth(1024)
            layer.CreateField(path_field)

            definition = layer.GetLayerDefn()
            for rec in records:
                ring = ogr.Geometry(ogr.wkbLinearRing)
                for point in rec["ring"]:
                    if len(point) >= 2:
                        ring.AddPoint(float(point[0]), float(point[1]))
                if ring.GetPointCount() < 4:
                    continue
                polygon = ogr.Geometry(ogr.wkbPolygon)
                polygon.AddGeometry(ring)

                feature = ogr.Feature(definition)
                feature.SetField("name", rec["name"])
                feature.SetField("path", rec["path"])
                feature.SetGeometry(polygon)
                layer.CreateFeature(feature)
                feature = None
            ds = None
            self._replace_file_with_retry(temp_overlay_path, overlay_path, "VPCオーバーレイ")
            return overlay_path
        except Exception as e:
            try:
                if "temp_overlay_path" in locals() and os.path.exists(temp_overlay_path):
                    os.remove(temp_overlay_path)
            except Exception:
                _om_record_ignored_exception(__name__, 6418)
            QgsMessageLog.logMessage(
                f"VPC_OVERLAY_CREATE_FAILED path={overlay_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return ""

    def _apply_default_vpc_overlay_style(self, overlay_layer):
        orange = QColor(0xF2, 0x8C, 0x28, 255)
        try:
            dot = QgsPointPatternFillSymbolLayer()
            dot.setColor(orange)
            dot.setDistanceX(3.0)
            dot.setDistanceY(3.0)
            dot.setOutputUnit(Qgis.RenderUnit.Millimeters)
            marker = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": "242,140,40,255",
                "outline_color": "242,140,40,255",
                "size": "0.45",
            })
            dot.setSubSymbol(marker)

            outline = QgsSimpleLineSymbolLayer()
            outline.setColor(orange)
            outline.setWidth(0.35)

            symbol = QgsFillSymbol()
            symbol.changeSymbolLayer(0, dot)
            symbol.appendSymbolLayer(outline)
            symbol.setOpacity(1.0)
            overlay_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPCオーバーレイスタイル適用エラー: {e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            symbol = QgsFillSymbol.createSimple({
                "color": "242,140,40,0",
                "outline_color": "242,140,40,255",
                "outline_width": "0.35",
                "style": "dense6",
            })
            overlay_layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _connect_vpc_overlay_style_save(self, overlay_layer, qml_path):
        if not overlay_layer or not qml_path:
            return

        def save_vpc_overlay_style():
            try:
                overlay_layer.saveNamedStyle(qml_path)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_OVERLAY_QML_SAVE_FAILED path={qml_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

        try:
            overlay_layer.rendererChanged.connect(save_vpc_overlay_style)
        except Exception:
            _om_record_ignored_exception(__name__, 6482)
        try:
            overlay_layer.styleChanged.connect(save_vpc_overlay_style)
        except Exception:
            _om_record_ignored_exception(__name__, 6486)

    def _apply_or_load_vpc_overlay_style(self, overlay_layer, vpc_path, preserve_current_style=False):
        qml_path = self._vpc_overlay_qml_path(vpc_path)
        loaded = False
        if qml_path and os.path.exists(qml_path):
            try:
                overlay_layer.loadNamedStyle(qml_path)
                loaded = True
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"VPC_OVERLAY_QML_LOAD_FAILED path={qml_path} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
        if not loaded:
            if not preserve_current_style:
                self._apply_default_vpc_overlay_style(overlay_layer)
            if qml_path:
                try:
                    overlay_layer.saveNamedStyle(qml_path)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"VPC_OVERLAY_QML_SAVE_FAILED path={qml_path} error={e}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
        self._connect_vpc_overlay_style_save(overlay_layer, qml_path)

    def _register_vpc_point_cloud_layer(self, layer):
        if layer is None:
            return None
        try:
            if QgsProject.instance().mapLayer(layer.id()) is None:
                QgsProject.instance().addMapLayer(layer, False)
        except Exception:
            try:
                QgsProject.instance().addMapLayer(layer, False)
            except Exception:
                _om_record_ignored_exception(__name__, 6525)
        return layer

    def _point_cloud_layer_options(self):
        point_cloud_cls = self._point_cloud_layer_class()
        options_cls = getattr(point_cloud_cls, "LayerOptions", None) if point_cloud_cls else None
        if options_cls is None:
            return None
        try:
            options = options_cls(QgsProject.instance().transformContext())
        except Exception:
            try:
                options = options_cls()
            except Exception:
                return None
        try:
            if hasattr(options, "skipIndexGeneration"):
                options.skipIndexGeneration = True
        except Exception:
            _om_record_ignored_exception(__name__, 6544)
        try:
            if hasattr(options, "skipStatisticsCalculation"):
                options.skipStatisticsCalculation = True
        except Exception:
            _om_record_ignored_exception(__name__, 6549)
        return options

    def _provider_sublayer_options(self):
        options_cls = getattr(QgsProviderSublayerDetails, "LayerOptions", None)
        if options_cls is None:
            return None
        try:
            return options_cls(QgsProject.instance().transformContext())
        except Exception:
            try:
                return options_cls()
            except Exception:
                return None

    def _is_point_cloud_layer(self, layer):
        if layer is None:
            return False
        point_cloud_cls = self._point_cloud_layer_class()
        if point_cloud_cls is not None:
            try:
                if isinstance(layer, point_cloud_cls):
                    return True
            except Exception:
                _om_record_ignored_exception(__name__, 6573)
        try:
            return getattr(layer, "type", lambda: None)() == getattr(Qgis.LayerType, "PointCloud", object())
        except Exception:
            return False

    def _tune_vpc_point_cloud_renderer(self, renderer):
        if renderer is None:
            return False
        changed = False
        try:
            if hasattr(renderer, "setMaximumScreenErrorUnit"):
                renderer.setMaximumScreenErrorUnit(Qgis.RenderUnit.Pixels)
                changed = True
        except Exception:
            _om_record_ignored_exception(__name__, 6588)
        try:
            if hasattr(renderer, "setMaximumScreenError"):
                renderer.setMaximumScreenError(0.25)
                changed = True
        except Exception:
            _om_record_ignored_exception(__name__, 6594)
        try:
            if hasattr(renderer, "setOverviewSwitchingScale"):
                renderer.setOverviewSwitchingScale(1000000.0)
                changed = True
        except Exception:
            _om_record_ignored_exception(__name__, 6600)
        try:
            if hasattr(renderer, "setShowLabels"):
                renderer.setShowLabels(False)
                changed = True
        except Exception:
            _om_record_ignored_exception(__name__, 6606)
        return changed

    def _point_cloud_z_range(self, layer):
        if not self._is_point_cloud_layer(layer):
            return None
        try:
            statistics = layer.statistics()
        except Exception:
            statistics = None
        if statistics is None:
            return None
        for attr in ("Z", "z"):
            try:
                minimum = float(statistics.minimum(attr))
                maximum = float(statistics.maximum(attr))
            except Exception:
                _om_record_ignored_exception(__name__, 6623); continue
            if minimum != minimum or maximum != maximum:
                continue
            if minimum < maximum:
                return attr, minimum, maximum
        return None

    def _apply_vpc_point_cloud_z_renderer(self, layer):
        z_range = self._point_cloud_z_range(layer)
        if not z_range:
            return False
        attr, minimum, maximum = z_range
        try:
            from qgis.core import (
                QgsColorRampShader,
                QgsGradientColorRamp,
                QgsGradientStop,
                QgsPointCloudAttributeByRampRenderer,
            )
            color_ramp = QgsGradientColorRamp(
                QColor("#440154"),
                QColor("#fde725"),
                False,
                [QgsGradientStop(0.50, QColor("#21918c"))],
            )
            shader = QgsColorRampShader(
                minimum,
                maximum,
                color_ramp,
                Qgis.ShaderInterpolationMethod.Linear,
                Qgis.ShaderClassificationMethod.Continuous,
            )
            renderer = QgsPointCloudAttributeByRampRenderer()
            renderer.setAttribute(attr)
            renderer.setMinimum(minimum)
            renderer.setMaximum(maximum)
            renderer.setColorRampShader(shader)
            self._tune_vpc_point_cloud_renderer(renderer)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_Z_RENDERER_FAILED layer={getattr(layer, 'name', lambda: '')()} error={e!r}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def _apply_vpc_point_cloud_render_detail(self, layer):
        if not self._is_point_cloud_layer(layer):
            return
        if self._apply_vpc_point_cloud_z_renderer(layer):
            return
        try:
            renderer = layer.renderer()
        except Exception:
            renderer = None
        if renderer is None:
            return

        changed = self._tune_vpc_point_cloud_renderer(renderer)

        if changed:
            try:
                layer.setRenderer(renderer)
            except Exception:
                _om_record_ignored_exception(__name__, 6690)
            try:
                layer.triggerRepaint()
            except Exception:
                _om_record_ignored_exception(__name__, 6694)

    def _create_vpc_point_cloud_layer(self, vpc_path, layer_name):
        path_candidates = []
        for path in (
            os.path.normpath(vpc_path),
            os.path.normpath(vpc_path).replace("\\", "/"),
        ):
            if path not in path_candidates:
                path_candidates.append(path)

        errors = []
        point_cloud_cls = self._point_cloud_layer_class()
        if point_cloud_cls is None:
            errors.append("QgsPointCloudLayer unavailable")
        options = self._point_cloud_layer_options() if point_cloud_cls is not None else None
        if point_cloud_cls is not None and options is None:
            errors.append("QgsPointCloudLayer.LayerOptions unavailable")

        if point_cloud_cls is not None and options is not None:
            for path in path_candidates:
                try:
                    layer = point_cloud_cls(path, layer_name, "vpc", options)
                except Exception as e:
                    errors.append(f"class provider=vpc path={path} error={e!r}")
                    continue

                try:
                    valid = bool(layer and layer.isValid() and self._is_point_cloud_layer(layer))
                except Exception:
                    valid = False
                try:
                    provider_type = str(layer.providerType() or "") if layer else ""
                except Exception:
                    provider_type = ""
                try:
                    is_vpc = bool(layer.isVpc()) if layer and hasattr(layer, "isVpc") else None
                except Exception:
                    is_vpc = False
                try:
                    point_count = int(layer.pointCount()) if layer else -1
                except Exception:
                    point_count = -1
                try:
                    subindex_count = len(layer.subIndexes()) if layer and hasattr(layer, "subIndexes") else -1
                except Exception:
                    subindex_count = -1

                if valid and is_vpc:
                    QgsMessageLog.logMessage(
                        f"VPC_LAYER_LOAD_NATIVE_OK provider={provider_type or 'vpc'} "
                        f"is_vpc={1 if is_vpc else 0} skip_index=1 "
                        f"points={point_count} subindexes={subindex_count} path={path}",
                        "OrthoManager",
                        Qgis.MessageLevel.Info,
                    )
                    return self._register_vpc_point_cloud_layer(layer)
                errors.append(
                    f"class provider=vpc path={path} valid={int(valid)} "
                    f"provider_type={provider_type or '-'} is_vpc={is_vpc}"
                )

        QgsMessageLog.logMessage(
            "VPC_LAYER_LOAD_FAILED_ALL " + " | ".join(errors[:8]),
            "OrthoManager",
            Qgis.MessageLevel.Warning,
        )
        return None

    def _reload_vpc_point_cloud_provider(self, layer, reason=""):
        """Requests a fresh point-cloud read after an on-disk VPC rebuild."""
        if layer is None:
            return False
        try:
            provider = layer.dataProvider()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_POINT_PROVIDER_RELOAD_FAILED reason={reason} step=provider error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False
        if provider is None or not hasattr(provider, "reloadData"):
            QgsMessageLog.logMessage(
                f"VPC_POINT_PROVIDER_RELOAD_SKIPPED reason={reason} provider_available={int(provider is not None)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return False
        try:
            provider.reloadData()
            layer.triggerRepaint(False)
            QApplication.processEvents()
            QgsMessageLog.logMessage(
                f"VPC_POINT_PROVIDER_RELOAD_REQUESTED reason={reason}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"VPC_POINT_PROVIDER_RELOAD_FAILED reason={reason} step=reload_data error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def _load_vpc_layer(self, vpc_path, layer_name, insert_index=None, progress_percent=None, overlay_vpc_path=None):
        layer_name = self.format_vpc_display_name(layer_name)
        if not layer_name:
            return None
        if not vpc_path or not os.path.exists(vpc_path):
            self._set_status(tr_text("❌ VPCファイルが見つかりません"))
            return None
        entry = self.vpc_registry.get(layer_name, {})

        if progress_percent is None:
            self._set_status(tr_text("⏳ VPCレイヤ読み込み中..."), log=False, style="busy")
        else:
            self._set_vpc_progress(progress_percent, "VPCレイヤ読み込み中")
        QApplication.processEvents()

        layer = self._create_vpc_point_cloud_layer(vpc_path, layer_name)
        if layer is None or not layer.isValid():
            self._set_status(tr_text("❌ VPCレイヤの読み込みに失敗しました"))
            return None
        self._apply_vpc_point_cloud_render_detail(layer)

        source_list = entry.get("source_list", []) if isinstance(entry, dict) else []
        if not source_list:
            source_list = self.read_point_cloud_sources_from_vpc(vpc_path)
            if isinstance(entry, dict):
                entry["source_list"] = source_list
        overlay_source_path = overlay_vpc_path if overlay_vpc_path and os.path.exists(overlay_vpc_path) else vpc_path
        overlay_path = self._build_vpc_overlay_gpkg(overlay_source_path, source_list, fallback_layer=layer)
        overlay_layer = None
        if overlay_path and os.path.exists(overlay_path):
            overlay_layer = QgsVectorLayer(overlay_path, self.vpc_overlay_layer_name(layer_name), "ogr")
            if overlay_layer and overlay_layer.isValid():
                group_crs = self._vpc_crs_from_registry(layer_name)
                if group_crs.isValid() and not self._layer_has_valid_crs(overlay_layer):
                    overlay_layer.setCrs(group_crs)
                self._apply_or_load_vpc_overlay_style(overlay_layer, vpc_path)
            else:
                overlay_layer = None

        root = QgsProject.instance().layerTreeRoot()
        if insert_index is None:
            insert_index = 0
        insert_index = max(0, min(insert_index, len(root.children())))
        group = root.insertGroup(insert_index, layer_name)
        group.setExpanded(False)
        for node in list(root.findLayers()):
            if node.layerId() == layer.id() and node.parent() is not group:
                parent = node.parent()
                if parent is not None:
                    parent.removeChildNode(node)
        if overlay_layer:
            QgsProject.instance().addMapLayer(overlay_layer, False)
            group.addLayer(overlay_layer)
        group.addLayer(layer)
        self._restore_vpc_group_crs_property(layer_name)
        self._apply_saved_vpc_scale(layer, overlay_layer, layer_name)
        self.iface.mapCanvas().refresh()
        self._reset_map_display_caches("vpc_layer_loaded", schedule_prefetch=True)
        count = len(self.vpc_registry.get(layer_name, {}).get("source_list", []))
        self._set_status(tr_text(f"✅ VPC読み込み完了: {layer_name}（{count} ファイル）"))
        return layer

    def _place_layer_in_group(self, group, layer, index=None):
        if group is None or layer is None:
            return False
        root = QgsProject.instance().layerTreeRoot()
        layer_id = layer.id()
        try:
            if QgsProject.instance().mapLayer(layer_id) is None:
                QgsProject.instance().addMapLayer(layer, False)
        except Exception:
            _om_record_ignored_exception(__name__, 6872)
        nodes = [node for node in list(root.findLayers()) if node.layerId() == layer_id]
        group_nodes = [node for node in nodes if node.parent() == group]
        if group_nodes:
            keep_node = group_nodes[0]
            for node in list(nodes):
                if node is keep_node:
                    continue
                parent = node.parent()
                if parent is not None:
                    try:
                        parent.removeChildNode(node)
                    except Exception:
                        _om_record_ignored_exception(__name__, 6885)
            return True
        if nodes:
            try:
                clone_node = nodes[0].clone()
                if index is None:
                    group.addChildNode(clone_node)
                else:
                    index = max(0, min(index, len(group.children())))
                    group.insertChildNode(index, clone_node)
                for node in list(nodes):
                    parent = node.parent()
                    if parent is not None:
                        try:
                            parent.removeChildNode(node)
                        except Exception:
                            _om_record_ignored_exception(__name__, 6901)
                return True
            except Exception:
                _om_record_ignored_exception(__name__, 6904)
        try:
            if index is None:
                group.addLayer(layer)
            else:
                index = max(0, min(index, len(group.children())))
                group.insertLayer(index, layer)
            return True
        except Exception:
            try:
                group.addLayer(layer)
                return True
            except Exception:
                return False

    def _organize_vpc_group_layers(self, name, vpc_path):
        layer_name = self.format_vpc_display_name(name)
        if not layer_name:
            return None
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(layer_name) or root.findGroup(self.strip_vpc_display_prefix(name))
        if group is None:
            group = root.insertGroup(0, layer_name)
        else:
            try:
                group.setName(layer_name)
            except Exception:
                _om_record_ignored_exception(__name__, 6931)
        group.setExpanded(False)

        point_layer = self._get_vpc_layer(layer_name, vpc_path)
        if point_layer is None:
            return None

        overlay_layer = self._get_vpc_overlay_layer(layer_name)
        if overlay_layer is None:
            entry = self.vpc_registry.get(layer_name, {})
            source_list = entry.get("source_list", []) if isinstance(entry, dict) else []
            overlay_path = self._build_vpc_overlay_gpkg(vpc_path, source_list, fallback_layer=point_layer)
            if overlay_path and os.path.exists(overlay_path):
                overlay_layer = QgsVectorLayer(overlay_path, self.vpc_overlay_layer_name(layer_name), "ogr")
                if overlay_layer and overlay_layer.isValid():
                    group_crs = self._vpc_crs_from_registry(layer_name)
                    if group_crs.isValid() and not self._layer_has_valid_crs(overlay_layer):
                        overlay_layer.setCrs(group_crs)
                    self._apply_or_load_vpc_overlay_style(overlay_layer, vpc_path)
                    QgsProject.instance().addMapLayer(overlay_layer, False)
                else:
                    overlay_layer = None

        allowed_ids = {lyr.id() for lyr in (overlay_layer, point_layer) if lyr is not None}
        removed_extra = 0
        for child in list(group.children()):
            if isinstance(child, QgsLayerTreeLayer) and child.layerId() not in allowed_ids:
                try:
                    clone = child.clone()
                    insert_index = len(root.children())
                    try:
                        insert_index = root.children().index(group) + 1
                    except Exception:
                        _om_record_ignored_exception(__name__, 6964)
                    root.insertChildNode(insert_index, clone)
                    group.removeChildNode(child)
                    removed_extra += 1
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        f"VPCレイヤ整理: 余計なレイヤの移動失敗: {exc}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )

        moved = 0
        if overlay_layer is not None:
            self._apply_or_load_vpc_overlay_style(overlay_layer, vpc_path, preserve_current_style=True)
            if self._place_layer_in_group(group, overlay_layer, 0):
                moved += 1
        self._apply_vpc_point_cloud_render_detail(point_layer)
        if self._place_layer_in_group(group, point_layer, 1 if overlay_layer is not None else 0):
            moved += 1
        self._restore_vpc_group_crs_property(layer_name)
        self._apply_saved_vpc_scale(point_layer, overlay_layer, layer_name)
        self.iface.mapCanvas().refresh()
        self._reset_map_display_caches("vpc_group_organized", schedule_prefetch=True)
        return {"layer": point_layer, "moved": moved, "removed_extra": removed_extra}

    def _load_vpc_overlay_only(self, vpc_path, layer_name, insert_index=None):
        layer_name = self.format_vpc_display_name(layer_name)
        if not layer_name or not vpc_path or not os.path.exists(vpc_path):
            return None
        entry = self.vpc_registry.get(layer_name, {})
        source_list = entry.get("source_list", []) if isinstance(entry, dict) else []
        overlay_path = self._build_vpc_overlay_gpkg(vpc_path, source_list)
        if not overlay_path or not os.path.exists(overlay_path):
            self._set_status(tr_text("⚠️ VPCは作成済みですが、範囲オーバーレイを作成できませんでした"))
            return None
        overlay_layer = QgsVectorLayer(overlay_path, self.vpc_overlay_layer_name(layer_name), "ogr")
        if not overlay_layer or not overlay_layer.isValid():
            self._set_status(tr_text("⚠️ VPC範囲オーバーレイの読み込みに失敗しました"))
            return None
        group_crs = self._vpc_crs_from_registry(layer_name)
        if group_crs.isValid() and not self._layer_has_valid_crs(overlay_layer):
            overlay_layer.setCrs(group_crs)
        self._apply_or_load_vpc_overlay_style(overlay_layer, vpc_path)

        root = QgsProject.instance().layerTreeRoot()
        if insert_index is None:
            insert_index = 0
        insert_index = max(0, min(insert_index, len(root.children())))
        group = root.findGroup(layer_name) or root.insertGroup(insert_index, layer_name)
        group.setExpanded(False)
        QgsProject.instance().addMapLayer(overlay_layer, False)
        group.addLayer(overlay_layer)
        self._restore_vpc_group_crs_property(layer_name)
        self.iface.mapCanvas().refresh()
        self._reset_map_display_caches("vpc_overlay_loaded", schedule_prefetch=True)
        count = len(source_list)
        self._set_status(tr_text(f"✅ VPC範囲を表示しました: {layer_name}（{count} ファイル）※点群本体は未読込"))
        return overlay_layer

    # --- QMLとCRSの保存・復元 ---
    def _save_qml(self, vrt_layer, vrt_path, overlay_layer):
        try:
            vrt_qml = os.path.splitext(vrt_path)[0] + ".qml"
            vrt_layer.saveNamedStyle(vrt_qml)
            if overlay_layer:
                overlay_qml = os.path.splitext(vrt_path)[0] + "_overlay.qml"
                overlay_layer.saveNamedStyle(overlay_qml)
            self._save_crs_json(vrt_path, vrt_layer, overlay_layer)
        except: _om_record_ignored_exception(__name__, 7032)

    def _save_crs_json(self, vrt_path, vrt_layer, overlay_layer):
        try:
            crs_path = os.path.splitext(vrt_path)[0] + ".ortho_crs.json"
            layer_name = vrt_layer.name() if vrt_layer else ""
            group_crs_authid = self._registry_group_crs_authid(layer_name)
            data = {
                "vrt_crs": vrt_layer.crs().authid() if vrt_layer.crs().isValid() else "",
                "overlay_crs": overlay_layer.crs().authid() if overlay_layer and overlay_layer.crs().isValid() else "",
                "group_crs": group_crs_authid,
            }
            with open(crs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except: _om_record_ignored_exception(__name__, 7046)

    def _load_crs_json(self, vrt_path):
        vrt_crs = QgsCoordinateReferenceSystem()
        overlay_crs = QgsCoordinateReferenceSystem()
        try:
            crs_path = os.path.splitext(vrt_path)[0] + ".ortho_crs.json"
            if not os.path.exists(crs_path): return vrt_crs, overlay_crs
            with open(crs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("vrt_crs"):
                crs = QgsCoordinateReferenceSystem(data["vrt_crs"])
                if crs.isValid(): vrt_crs = crs
            if data.get("overlay_crs"):
                crs = QgsCoordinateReferenceSystem(data["overlay_crs"])
                if crs.isValid(): overlay_crs = crs
        except: _om_record_ignored_exception(__name__, 7062)
        return vrt_crs, overlay_crs

    def _load_group_crs_authid_from_json(self, vrt_path):
        try:
            crs_path = os.path.splitext(vrt_path)[0] + ".ortho_crs.json"
            if not os.path.exists(crs_path):
                return ""
            with open(crs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for key in ("group_crs", "vrt_crs", "overlay_crs"):
                authid = data.get(key, "")
                crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
                if crs.isValid():
                    return crs.authid()
        except Exception:
            _om_record_ignored_exception(__name__, 7078)
        return ""

    def _layer_has_valid_crs(self, layer):
        try:
            return bool(layer and layer.crs() and layer.crs().isValid())
        except Exception:
            return False

    def _warn_if_vrt_crs_missing(self, layer_name, vrt_layer, overlay_layer):
        missing = []
        if not self._layer_has_valid_crs(vrt_layer):
            missing.append("VRTラスタ")
        if overlay_layer and not self._layer_has_valid_crs(overlay_layer):
            missing.append("オーバーレイ")
        if not missing:
            return
        self._show_map_center_alert(
            f"CRS未設定: {layer_name}\n{', '.join(missing)} のCRSを確認してください"
        )

    def _show_map_center_alert(self, message, duration_ms=2000):
        canvas = self.iface.mapCanvas()
        if not canvas:
            return

        if self._crs_alert_label:
            try:
                self._crs_alert_label.deleteLater()
            except Exception:
                _om_record_ignored_exception(__name__, 7108)
            self._crs_alert_label = None
        if self._crs_alert_timer:
            try:
                self._crs_alert_timer.stop()
                self._crs_alert_timer.deleteLater()
            except Exception:
                _om_record_ignored_exception(__name__, 7115)
            self._crs_alert_timer = None

        label = QLabel(message, canvas)
        label.setObjectName("OrthoManagerCrsAlert")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(
            "QLabel#OrthoManagerCrsAlert {"
            "background: rgba(255, 193, 7, 230);"
            "color: #1f2933;"
            "border: 1px solid rgba(120, 82, 0, 180);"
            "border-radius: 6px;"
            "padding: 10px 14px;"
            "font-size: 14px;"
            "font-weight: bold;"
            "}"
        )
        label.adjustSize()
        max_width = max(240, min(520, int(canvas.width() * 0.7)))
        label.setFixedWidth(max_width)
        label.adjustSize()
        x = max(0, int((canvas.width() - label.width()) / 2))
        y = max(0, int((canvas.height() - label.height()) / 2))
        label.move(x, y)
        label.show()
        label.raise_()

        effect = QGraphicsOpacityEffect(label)
        effect.setOpacity(1.0)
        label.setGraphicsEffect(effect)

        self._crs_alert_label = label
        self._crs_alert_animation = QPropertyAnimation(effect, b"opacity", self)
        self._crs_alert_animation.setDuration(900)
        self._crs_alert_animation.setStartValue(1.0)
        self._crs_alert_animation.setEndValue(0.0)
        self._crs_alert_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._crs_alert_animation.finished.connect(label.deleteLater)
        self._crs_alert_animation.finished.connect(lambda: setattr(self, "_crs_alert_label", None))

        self._crs_alert_timer = QTimer(self)
        self._crs_alert_timer.setSingleShot(True)
        self._crs_alert_timer.timeout.connect(self._crs_alert_animation.start)
        self._crs_alert_timer.start(duration_ms)

    # --- 縮尺シグナル管理 ---
    def _set_scale_to_layers(self, vrt_layer, overlay_layer, min_scale):
        vrt_layer.setScaleBasedVisibility(True)
        vrt_layer.setMinimumScale(min_scale)
        vrt_layer.setMaximumScale(0)
        vrt_layer.triggerRepaint()
        if overlay_layer:
            overlay_layer.setScaleBasedVisibility(True)
            overlay_layer.setMinimumScale(0)
            overlay_layer.setMaximumScale(min_scale)
            overlay_layer.triggerRepaint()
        self.iface.mapCanvas().refresh()

    def _effective_vpc_switch_scale(self, scale_value):
        try:
            scale = int(scale_value)
        except Exception:
            scale = DEFAULT_MIN_SCALE
        if scale <= 0:
            return 0
        return min(scale, VPC_POINT_CLOUD_SCALE_CAP)

    def _set_layer_tree_layer_visible(self, layer, visible):
        if not layer:
            return False
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if not node:
                return False
            visible = bool(visible)
            if node.itemVisibilityChecked() != visible:
                node.setItemVisibilityChecked(visible)
                return True
            return False
        except Exception:
            return False

    def _ensure_vpc_scale_canvas_signal(self):
        if self._vpc_scale_canvas_connected:
            return
        try:
            self.iface.mapCanvas().scaleChanged.connect(self._on_vpc_canvas_scale_changed)
            self._vpc_scale_canvas_connected = True
        except Exception:
            _om_record_ignored_exception(__name__, 7205)

    def _on_vpc_canvas_scale_changed(self, *args):
        self._apply_all_vpc_tree_visibility(refresh=True)

    def _apply_all_vpc_tree_visibility(self, refresh=False):
        changed = False
        for name in list(self.vpc_registry.keys()):
            changed = self._apply_vpc_tree_visibility_for_scale(name, refresh=False) or changed
        if refresh and changed:
            try:
                self.iface.mapCanvas().refresh()
            except Exception:
                _om_record_ignored_exception(__name__, 7218)

    def _apply_vpc_tree_visibility_for_scale(self, name, refresh=True):
        display_name = self.format_vpc_display_name(name)
        if not display_name:
            return False
        vpc_layer = self._get_vpc_layer(display_name)
        overlay_layer = self._get_vpc_overlay_layer(display_name)
        if not vpc_layer:
            if overlay_layer:
                try:
                    overlay_layer.setScaleBasedVisibility(False)
                    overlay_layer.triggerRepaint()
                except Exception:
                    _om_record_ignored_exception(__name__, 7232)
                changed = self._set_layer_tree_layer_visible(overlay_layer, True)
                if refresh:
                    try:
                        self.iface.mapCanvas().refresh()
                    except Exception:
                        _om_record_ignored_exception(__name__, 7238)
                return changed
            return False
        entry = self.vpc_registry.get(display_name, {})
        scale_mode = str(entry.get("scale_mode", "") or "") if isinstance(entry, dict) else ""
        if scale_mode == "all":
            try:
                current_scale = float(self.iface.mapCanvas().scale())
            except Exception:
                current_scale = VPC_POINT_CLOUD_SCALE_CAP
            point_visible = current_scale <= VPC_POINT_CLOUD_SCALE_CAP
        else:
            try:
                saved_scale = int(entry.get("scale", DEFAULT_MIN_SCALE) or DEFAULT_MIN_SCALE)
            except Exception:
                saved_scale = DEFAULT_MIN_SCALE
            switch_scale = self._effective_vpc_switch_scale(saved_scale)
            try:
                current_scale = float(self.iface.mapCanvas().scale())
            except Exception:
                current_scale = switch_scale
            point_visible = current_scale <= switch_scale
        changed = False
        changed = self._set_layer_tree_layer_visible(vpc_layer, point_visible) or changed
        if overlay_layer:
            changed = self._set_layer_tree_layer_visible(overlay_layer, not point_visible) or changed
        if changed:
            try:
                vpc_layer.triggerRepaint()
                if overlay_layer:
                    overlay_layer.triggerRepaint()
            except Exception:
                _om_record_ignored_exception(__name__, 7270)
            if refresh:
                try:
                    self.iface.mapCanvas().refresh()
                except Exception:
                    _om_record_ignored_exception(__name__, 7275)
        return changed

    def _set_vpc_scale_to_layers(self, vpc_layer, overlay_layer, min_scale):
        effective_scale = self._effective_vpc_switch_scale(min_scale)
        if vpc_layer:
            vpc_layer.setScaleBasedVisibility(True)
            vpc_layer.setMinimumScale(effective_scale)
            vpc_layer.setMaximumScale(0)
            vpc_layer.triggerRepaint()
        if overlay_layer:
            overlay_layer.setScaleBasedVisibility(True)
            overlay_layer.setMinimumScale(0)
            overlay_layer.setMaximumScale(effective_scale)
            overlay_layer.triggerRepaint()
        self._ensure_vpc_scale_canvas_signal()
        self.iface.mapCanvas().refresh()

    def _set_vpc_scale_all(self, vpc_layer, overlay_layer):
        if vpc_layer:
            vpc_layer.setScaleBasedVisibility(True)
            vpc_layer.setMinimumScale(VPC_POINT_CLOUD_SCALE_CAP)
            vpc_layer.setMaximumScale(0)
            vpc_layer.triggerRepaint()
        if overlay_layer:
            overlay_layer.setScaleBasedVisibility(True)
            overlay_layer.setMinimumScale(0)
            overlay_layer.setMaximumScale(VPC_POINT_CLOUD_SCALE_CAP)
            overlay_layer.triggerRepaint()
        self._ensure_vpc_scale_canvas_signal()
        self.iface.mapCanvas().refresh()

    def _apply_saved_vpc_scale(self, vpc_layer, overlay_layer, name):
        entry = self.vpc_registry.get(self.format_vpc_display_name(name), {})
        if not isinstance(entry, dict):
            return
        try:
            scale = int(entry.get("scale", 0) or 0)
        except Exception:
            scale = 0
        if str(entry.get("scale_mode", "") or "") == "all":
            self._set_vpc_scale_all(vpc_layer, overlay_layer)
            self._apply_vpc_tree_visibility_for_scale(name)
            return
        if scale <= 0:
            scale = 500
            entry["scale"] = scale
            entry["scale_mode"] = "preset"
        self._set_vpc_scale_to_layers(vpc_layer, overlay_layer, scale)
        self._apply_vpc_tree_visibility_for_scale(name)

    def apply_vpc_scale(self, name, scale_value):
        display_name = self.format_vpc_display_name(name)
        if not display_name:
            return False
        entry = self.vpc_registry.setdefault(display_name, {})
        vpc_layer = self._get_vpc_layer(display_name)
        overlay_layer = self._get_vpc_overlay_layer(display_name)
        if not vpc_layer:
            if overlay_layer:
                try:
                    overlay_layer.setScaleBasedVisibility(False)
                    overlay_layer.triggerRepaint()
                except Exception:
                    _om_record_ignored_exception(__name__, 7339)
                self._set_layer_tree_layer_visible(overlay_layer, True)
                entry["scale"] = 0
                entry["scale_mode"] = "overlay_only"
                self.scale_target_mode = "vpc"
                self.vrt_tab.sync_scale_highlight_from_current_target()
                self.save_to_project()
                self.iface.mapCanvas().refresh()
                self._set_status(tr_text("✅ VPC範囲オーバーレイのみ全表示します"))
                return True
            QMessageBox.information(
                self,
                tr_text("情報"),
                tr_text("VPC点群本体レイヤが見つかりません。VPCを作成・読込してから縮尺を設定してください。"),
            )
            return False
        try:
            scale = int(scale_value)
        except Exception:
            return False
        if scale > 0:
            self._set_vpc_scale_to_layers(vpc_layer, overlay_layer, scale)
            entry["scale"] = scale
            entry["scale_mode"] = "preset"
            effective_scale = self._effective_vpc_switch_scale(scale)
            if effective_scale != scale:
                self._set_status(tr_text(f"✅ VPC縮尺 1:{scale:,} を適用しました（点群表示は 1:{effective_scale:,} 以下に補正）"))
            else:
                self._set_status(tr_text(f"✅ VPC縮尺 1:{scale:,} を適用しました"))
        else:
            self._set_vpc_scale_all(vpc_layer, overlay_layer)
            entry["scale"] = 0
            entry["scale_mode"] = "all"
            self._set_status(tr_text("✅ VPC全域表示（広域はオーバーレイ、1:2,500以下は点群）を適用しました"))
        self._apply_vpc_tree_visibility_for_scale(display_name)
        self.scale_target_mode = "vpc"
        self.vrt_tab.sync_scale_highlight_from_current_target()
        self.save_to_project()
        return True

    def _connect_scale_signal(self, vrt_layer, overlay_layer):
        if not vrt_layer or not overlay_layer: return
        def on_scale_changed():
            if not vrt_layer or not overlay_layer: return
            try:
                if vrt_layer.hasScaleBasedVisibility():
                    min_s = vrt_layer.minimumScale()
                    overlay_layer.setScaleBasedVisibility(True)
                    overlay_layer.setMinimumScale(0)
                    overlay_layer.setMaximumScale(min_s)
                else:
                    overlay_layer.setScaleBasedVisibility(False)
                overlay_layer.triggerRepaint()
                self.iface.mapCanvas().refresh()
            except: _om_record_ignored_exception(__name__, 7393)
        try:
            vrt_layer.scaleBasedVisibilityChanged.connect(on_scale_changed)
            self._scale_timer[vrt_layer.id()] = on_scale_changed
        except: _om_record_ignored_exception(__name__, 7397)

    def _disconnect_scale_signal(self, name):
        vrt_layer = self._get_vrt_layer(name)
        if vrt_layer and vrt_layer.id() in self._scale_timer:
            try: vrt_layer.scaleBasedVisibilityChanged.disconnect(self._scale_timer[vrt_layer.id()])
            except: _om_record_ignored_exception(__name__, 7403)
            del self._scale_timer[vrt_layer.id()]

    def _disconnect_all_scale_signals(self):
        for name in list(self.vrt_registry.keys()):
            self._disconnect_scale_signal(name)
            
    def _reconnect_scale_signals(self):
        for name in self.vrt_registry:
            vrt_layer = self._get_vrt_layer(name)
            overlay_layer = self._get_overlay_layer(name)
            if vrt_layer and overlay_layer:
                self._connect_scale_signal(vrt_layer, overlay_layer)

    # --- VRT読み込みコア処理 (タスクやファイルから呼ばれる) ---
    def _load_vrt_with_overlay(self, vrt_path, layer_name, apply_default_style=True, saved_crs=None, saved_overlay_crs=None, rebuild_gpkg=True, insert_index=None):
        layer_name = self.format_vrt_display_name(layer_name)
        if not layer_name:
            return
        gdal, old_pam_enabled = self._disable_gdal_pam("VRTレイヤ読込")
        gpkg_path = os.path.splitext(vrt_path)[0] + "_tiles.gpkg"
        self._set_status(tr_text("⏳ レイヤ読み込み中..."))
        QApplication.processEvents()
        
        gpkg_ok = os.path.exists(gpkg_path)

        vrt_layer = QgsRasterLayer(vrt_path, layer_name, "gdal")
        if not vrt_layer.isValid():
            self._restore_gdal_pam(gdal, old_pam_enabled)
            self._set_status(tr_text("❌ VRTレイヤの読み込みに失敗しました"))
            return

        vrt_qml = os.path.splitext(vrt_path)[0] + ".qml"
        if os.path.exists(vrt_qml) and not apply_default_style:
            vrt_layer.loadNamedStyle(vrt_qml)
        else:
            vrt_layer.setScaleBasedVisibility(True)
            vrt_layer.setMinimumScale(DEFAULT_MIN_SCALE)
            vrt_layer.setMaximumScale(0)
        
        # ニアレストネイバーの適用
        try:
            from qgis.core import QgsRasterDataProvider
            provider = vrt_layer.dataProvider()
            if provider and hasattr(provider, 'setZoomedInResamplingMethod'):
                provider.setZoomedInResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
                provider.setZoomedOutResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
        except: _om_record_ignored_exception(__name__, 7450)
        
        if saved_crs and saved_crs.isValid():
            vrt_layer.setCrs(saved_crs)

        overlay_layer = None
        if gpkg_ok and os.path.exists(gpkg_path):
            overlay_name = self.overlay_layer_name(layer_name)
            overlay_layer = QgsVectorLayer(gpkg_path, overlay_name, "ogr")
            if not overlay_layer.isValid():
                overlay_layer = None
            else:
                overlay_qml = os.path.splitext(vrt_path)[0] + "_overlay.qml"
                if os.path.exists(overlay_qml) and not apply_default_style:
                    overlay_layer.loadNamedStyle(overlay_qml)
                else:
                    self._apply_default_overlay_style(overlay_layer)
                    overlay_layer.setScaleBasedVisibility(True)
                    overlay_layer.setMinimumScale(0)
                    overlay_layer.setMaximumScale(DEFAULT_MIN_SCALE)

        root = QgsProject.instance().layerTreeRoot()
        if insert_index is None:
            insert_index = 0
        insert_index = max(0, min(insert_index, len(root.children())))
        group = root.insertGroup(insert_index, layer_name)
        group.setExpanded(False)
        group_crs = self._group_crs_from_registry(layer_name)
        if group_crs.isValid():
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, group_crs.authid())
            except Exception:
                _om_record_ignored_exception(__name__, 7482)
            vrt_layer.setCrs(group_crs)
        
        if overlay_layer:
            QgsProject.instance().addMapLayer(overlay_layer, False)
            group.addLayer(overlay_layer)
            overlay_qml_path = os.path.splitext(vrt_path)[0] + "_overlay.qml"
            overlay_layer.rendererChanged.connect(
                lambda qml=overlay_qml_path, lyr=overlay_layer: self._on_overlay_renderer_changed(lyr, qml)
            )
            
        QgsProject.instance().addMapLayer(vrt_layer, False)
        group.addLayer(vrt_layer)

        if saved_overlay_crs and saved_overlay_crs.isValid() and overlay_layer:
            overlay_layer.setCrs(saved_overlay_crs)
        if group_crs.isValid() and overlay_layer:
            overlay_layer.setCrs(group_crs)

        self._connect_scale_signal(vrt_layer, overlay_layer)
        self._connect_property_changed(vrt_layer, vrt_path, overlay_layer)
        self._save_qml(vrt_layer, vrt_path, overlay_layer)

        if vrt_layer.hasScaleBasedVisibility():
            self.vrt_tab.update_scale_btn_highlight(int(vrt_layer.minimumScale()))
        else:
            self.vrt_tab.update_scale_btn_highlight(0)

        self.iface.mapCanvas().refresh()
        self._schedule_custom_cache_prefetch()
        self._restore_gdal_pam(gdal, old_pam_enabled)
        count = len(self.vrt_registry.get(layer_name, {}).get("tif_list", []))
        overlay_msg = "＋オーバーレイ" if overlay_layer else "（オーバーレイなし）"
        self._set_status(tr_text(f"✅ 完了: {layer_name} {overlay_msg}（{count} ファイル）"))

    def _apply_default_overlay_style(self, overlay_layer):
        try:
            hatch = QgsLinePatternFillSymbolLayer()
            hatch.setColor(QColor(0x76, 0xa3, 0x2a, 255))
            hatch.setLineAngle(45.0)
            hatch.setDistance(3.0)
            hatch.setLineWidth(0.5)

            outline = QgsSimpleLineSymbolLayer()
            outline.setColor(QColor(0x76, 0xa3, 0x2a, 255))
            outline.setWidth(0.5)

            symbol = QgsFillSymbol()
            symbol.changeSymbolLayer(0, hatch)
            symbol.appendSymbolLayer(outline)
            symbol.setOpacity(1.0)
            overlay_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        except Exception as e:
            QgsMessageLog.logMessage(f"ハッチングスタイル適用エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
            symbol = QgsFillSymbol.createSimple({"color": "118,163,42,180", "outline_color": "118,163,42,255", "outline_width": "0.5"})
            overlay_layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _connect_property_changed(self, vrt_layer, vrt_path, overlay_layer):
        overlay_layer_ref = overlay_layer
        def on_vrt_style_changed():
            try: self._save_qml(vrt_layer, vrt_path, overlay_layer_ref)
            except: _om_record_ignored_exception(__name__, 7543)
        def on_vrt_crs_changed():
            try: self._save_qml(vrt_layer, vrt_path, overlay_layer_ref)
            except: _om_record_ignored_exception(__name__, 7546)
        try: vrt_layer.styleChanged.connect(on_vrt_style_changed)
        except: _om_record_ignored_exception(__name__, 7548)
        try: vrt_layer.crsChanged.connect(on_vrt_crs_changed)
        except: _om_record_ignored_exception(__name__, 7550)
        if overlay_layer_ref:
            def on_overlay_crs_changed():
                try: self._save_qml(vrt_layer, vrt_path, overlay_layer_ref)
                except: _om_record_ignored_exception(__name__, 7554)
            try: overlay_layer_ref.crsChanged.connect(on_overlay_crs_changed)
            except: _om_record_ignored_exception(__name__, 7556)

    def _on_overlay_renderer_changed(self, overlay_layer, qml_path):
        try: overlay_layer.saveNamedStyle(qml_path)
        except: _om_record_ignored_exception(__name__, 7560)



















