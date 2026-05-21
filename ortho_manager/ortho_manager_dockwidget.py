import os
import json
import xml.etree.ElementTree as ET
from .safe_xml import parse_vrt_xml
import time
import shutil
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QLabel, QTabWidget, QApplication,
    QMessageBox, QSizePolicy, QGraphicsOpacityEffect, QScrollArea, QFrame, QDialog
)
from qgis.PyQt.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap, QPainter
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMessageLog, Qgis,
    QgsLayerTreeLayer, QgsFillSymbol, QgsSingleSymbolRenderer,
    QgsLinePatternFillSymbolLayer, QgsSimpleLineSymbolLayer, QgsSettings,
    QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob, QgsFeatureRequest,
    QgsCoordinateReferenceSystem
)

from qgis.gui import QgsMapCanvas, QgsProjectionSelectionDialog

from .utils import PROJECT_KEY, PROJECT_ENTRY, DEFAULT_MIN_SCALE
from .vrt_tab import VrtTabWidget
from .export_tab import ExportTabWidget
from .inspection_tab import InspectionTabWidget
from .settings_tab import SettingsTabWidget
from .i18n import current_language, tr
from .layer_lock import LayerLockManager
from .tasks import find_external_vrt_engine_path, run_external_vrt_engine_sync

class OrthoManagerDockWidget(QDockWidget):
    VRT_NAME_EMOJI = "🖼️"
    GROUP_CRS_PROPERTY = "OrthoManager/group_crs_authid"

    def __init__(self, iface, parent=None):
        super().__init__("OrthoManager v3.27.1", parent)
        self.iface = iface
        self.setWindowTitle("OrthoManager v3.27.1")
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
        self._scale_timer = {}      # 縮尺シグナル用の辞書
        self._last_status_message = "準備完了"
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
            "OrthoManagerを閉じますか？",
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
            pass

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
                pass
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_view_cache_button(enabled)
            except Exception:
                pass
        if show_status:
            self._set_status("✅ ビューキャッシュ ON" if enabled else "ビューキャッシュ OFF")

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
            pass

    def _disconnect_custom_cache_canvases(self):
        for canvas in list(self._custom_cache_registered_canvases):
            try:
                slot = self._custom_cache_canvas_slots.get(canvas)
                if slot:
                    canvas.extentsChanged.disconnect(slot)
            except Exception:
                pass
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
                    pass
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
                    pass
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
                pass
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_custom_cache_button(enabled)
            except Exception:
                pass
        if show_status:
            self._set_status("✅ 独自キャッシュ ON" if enabled else "独自キャッシュ OFF")

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

    def cleanup_before_unload(self):
        try:
            if hasattr(self, "inspection_tab"):
                self.inspection_tab.cleanup_before_unload()
        except Exception:
            pass
        try:
            if self.layer_lock_manager is not None:
                self.layer_lock_manager.cleanup()
        except Exception:
            pass
        try:
            self.custom_cache_enabled = False
            self._disconnect_custom_cache_canvases()
            self._remove_screen_shield_event_filter(None)
            if self._custom_cache_timer:
                try:
                    self._custom_cache_timer.stop()
                except RuntimeError:
                    pass
                self._custom_cache_timer = None
            if self._custom_cache_job:
                try:
                    self._custom_cache_job.cancelWithoutBlocking()
                except Exception:
                    pass
            self._custom_cache_job = None
            self._custom_cache_job_canvas = None
            self._custom_cache_job_layer = None
            self._custom_cache_job_extent = None
            self._custom_cache_job_map_to_pixel = None
        except Exception:
            pass

    def _is_vrt_raster_visible_now(self, vrt_layer, canvas=None):
        if not vrt_layer:
            return False
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(vrt_layer.id())
            if node and not node.isVisible():
                return False
        except Exception:
            pass
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
            pass
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
            pass
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
            pass
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
                pass
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_screen_shield_button(enabled)
            except Exception:
                pass
        if show_status:
            self._set_status("✅ 画面シールド ON" if enabled else "画面シールド OFF")

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
                pass
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_mouse_shield_controls(self.mouse_shield_enabled, self.mouse_shield_scale)
            except Exception:
                pass
        if show_status:
            self._set_status(
                f"✅ マウスシールド {self.mouse_shield_scale}x ON"
                if enabled
                else "マウスシールド OFF"
            )

    def _map_canvases(self):
        canvases = []
        try:
            for canvas in self.iface.mapCanvases() or []:
                if canvas and canvas not in canvases:
                    canvases.append(canvas)
        except Exception:
            pass
        try:
            canvas = self.iface.mapCanvas()
            if canvas and canvas not in canvases:
                canvases.append(canvas)
        except Exception:
            pass
        return canvases

    def _canvas_from_event_object(self, obj):
        for canvas in list(self._screen_shield_registered_canvases):
            try:
                if obj is canvas or obj is canvas.viewport():
                    return canvas
            except Exception:
                pass
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
                pass
        try:
            layer = self._get_vrt_layer(self.current_vrt_name)
            if layer:
                parts.append(f"layer={layer.id()}")
                cache = canvas.cache()
                if cache and hasattr(cache, "hasCacheImage"):
                    parts.append(f"layer_cache={cache.hasCacheImage(layer.id())}")
        except Exception:
            pass
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
                pass
        if slots:
            self._mouse_diag_canvas_slots[canvas] = slots

    def _disconnect_mouse_diag_canvases(self):
        for canvas, slots in list(self._mouse_diag_canvas_slots.items()):
            for signal, slot in slots:
                try:
                    signal.disconnect(slot)
                except Exception:
                    pass
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
                    pass
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
            pass

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
                pass
            for map_canvas in list(self._screen_shield_registered_canvases):
                try:
                    map_canvas.removeEventFilter(self)
                    if map_canvas.viewport():
                        map_canvas.viewport().removeEventFilter(self)
                except Exception:
                    pass
            self._screen_shield_registered_canvases = []
            self._disconnect_mouse_diag_canvases()
        except Exception:
            pass
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
            pass

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
                pass

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
                pass
        if hasattr(self, "vrt_tab"):
            try:
                self.vrt_tab.update_mouse_shield_controls(self.mouse_shield_enabled, self.mouse_shield_scale)
            except Exception:
                pass
        if show_status:
            self._set_status(f"マウスシールド倍率 {self.mouse_shield_scale}x")

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
                pass

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
                    pass
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
                        pass
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
            f"{context}に重複TIFが含まれていました。\n\n"
            f"同じファイル: {duplicate_path_count} 件\n"
            f"同じTIF名: {duplicate_name_count} 件\n\n"
            "OrthoManager v2.8では、同じTIF名の登録は禁止です。\n"
            "安全のため、最初に見つかったTIFだけを残しました。"
        )
        QMessageBox.warning(self, "同名TIFを除外しました", msg)

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
        self.settings_tab = SettingsTabWidget(self)
        self.tabs.addTab(self.vrt_tab, tr("tab.vrt"))
        self.tabs.addTab(self.inspection_tab, tr("tab.inspection"))
        self.tabs.addTab(self.export_tab, tr("tab.export"))
        self.tabs.addTab(self.settings_tab, tr("tab.settings"))
        self.refresh_language()
        main_layout.addWidget(self.tabs)

        self.status_label = QLabel(tr("status.ready"))
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label.setStyleSheet("background:#ecf0f1; padding:3px; border-radius:3px; font-size:11px;")
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
        for attr_name in ("vrt_tab", "inspection_tab", "export_tab", "settings_tab"):
            tab = getattr(self, attr_name, None)
            if tab is not None and hasattr(tab, "refresh_texts"):
                tab.refresh_texts()

    def set_status(self, msg):
        self._set_status(msg)

    def _set_status(self, msg):
        self._last_status_message = msg
        self.status_label.setToolTip(msg)
        self.status_label.setText(self._elide_text_for_width(msg, self.status_label, 280))
        QApplication.processEvents()
        QgsMessageLog.logMessage(msg, "OrthoManager", Qgis.MessageLevel.Info)

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
        data = {
            "version": 2,
            "current_vrt_name": self.current_vrt_name,
            "vrt_registry": entries,
            "inspection": self.inspection_tab.save_state() if hasattr(self, "inspection_tab") else {},
        }
        QgsProject.instance().writeEntry(PROJECT_KEY, PROJECT_ENTRY, json.dumps(data, ensure_ascii=False))

    def restore_from_project(self):
        raw, ok = QgsProject.instance().readEntry(PROJECT_KEY, PROJECT_ENTRY)
        if not ok or not raw: return
        try:
            data = json.loads(raw)
        except Exception:
            return

        current_name = ""
        if isinstance(data, dict) and "vrt_registry" in data:
            current_name = self.format_vrt_display_name(data.get("current_vrt_name", ""))
            entries = data.get("vrt_registry", {})
            inspection_state = data.get("inspection", {})
        else:
            entries = data if isinstance(data, dict) else {}
            inspection_state = {}

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
             
        synced_path_count = self._sync_registry_paths_from_project_layers()

        # VRTタブのコンボボックスを更新
        self.vrt_tab.populate_vrt_combo()
        
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

        if hasattr(self, "inspection_tab"):
            self.inspection_tab.restore_state(inspection_state)
        if self.layer_lock_manager is not None:
            self.layer_lock_manager.refresh()
            
        self._set_status(f"✅ プロジェクトから {len(self.vrt_registry)} 件を復元")

    def reset_all(self):
        self._disconnect_all_scale_signals()
        if hasattr(self, "inspection_tab"):
            self.inspection_tab.clear_inspection_state(remove_layers=False)
        if self.layer_lock_manager is not None:
            self.layer_lock_manager.schedule_refresh()
        self._reset_ui()
        self.vrt_registry.clear()
        self.current_vrt_name = ""
        self._set_status("🆕 リセット完了")

    def _reset_ui(self):
        self.vrt_tab.vrt_combo.blockSignals(True)
        self.vrt_tab.vrt_combo.clear()
        self.vrt_tab.vrt_combo.blockSignals(False)
        self.vrt_registry.clear()
        self.current_vrt_name = ""
        self.vrt_tab.reload_tif_listwidget()
        self.vrt_tab.update_path_display()
        self.vrt_tab._refresh_vrt_action_buttons()

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

    def _registry_group_crs_authid(self, name):
        entry = self.vrt_registry.get(self.format_vrt_display_name(name), {})
        authid = entry.get("group_crs_authid", "") if isinstance(entry, dict) else ""
        return authid if isinstance(authid, str) else ""

    def _group_crs_from_registry(self, name):
        authid = self._registry_group_crs_authid(name)
        crs = QgsCoordinateReferenceSystem(authid) if authid else QgsCoordinateReferenceSystem()
        return crs if crs.isValid() else QgsCoordinateReferenceSystem()

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

    def _restore_group_crs_property(self, name):
        group = self._find_vrt_group(name)
        crs = self._group_crs_from_registry(name)
        if group and crs.isValid():
            try:
                group.setCustomProperty(self.GROUP_CRS_PROPERTY, crs.authid())
            except Exception:
                pass
        if crs.isValid():
            vrt_layer = self._get_vrt_layer(name)
            overlay_layer = self._get_overlay_layer(name)
            try:
                if vrt_layer:
                    vrt_layer.setCrs(crs)
                if overlay_layer:
                    overlay_layer.setCrs(crs)
            except Exception:
                pass

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
                pass

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

        if show_message:
            self._show_map_center_alert(f"CRS: {crs.authid()}", duration_ms=3000)
        self._last_group_crs_apply_sec = getattr(self, "_last_group_crs_apply_sec", 0.0) + (time.perf_counter() - apply_start)
        return True

    def _open_group_crs_dialog(self, name, initial_crs=None):
        try:
            dialog = QgsProjectionSelectionDialog(self.iface.mainWindow())
            dialog.setWindowTitle("グループのCRSを設定")
            if initial_crs and initial_crs.isValid():
                try:
                    dialog.setCrs(initial_crs)
                except Exception:
                    pass
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            crs = dialog.crs()
            if crs and crs.isValid():
                self._set_group_crs(name, crs)
                return crs
        except Exception as e:
            QgsMessageLog.logMessage(f"CRS選択ダイアログエラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
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

    def _get_tif_list_from_vrt(self, vrt_path):
        try:
            from osgeo import gdal
            ds = gdal.Open(vrt_path)
            if ds:
                files = ds.GetFileList()
                ds = None
                if files:
                    tif_list = [f for f in files[1:] if f.lower().endswith((".tif", ".tiff"))]
                    cleaned, dup_paths, dup_names = self._clean_tif_list_unique_names(tif_list)
                    self._warn_if_tif_duplicates_removed(os.path.basename(vrt_path), dup_paths, dup_names)
                    return cleaned
        except: pass
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
            except: pass
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
            pass

        try:
            if old_node and hasattr(old_node, "itemVisibilityChecked"):
                state["visible"] = old_node.itemVisibilityChecked()
        except Exception:
            pass

        try:
            vrt_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + ".qml")
        except Exception:
            pass

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
            pass

        try:
            saved_crs = state.get("crs")
            if saved_crs and saved_crs.isValid():
                new_layer.setCrs(saved_crs)
            new_layer.setScaleBasedVisibility(bool(state.get("scale_based")))
            new_layer.setMinimumScale(state.get("min_scale", 0))
            new_layer.setMaximumScale(state.get("max_scale", 0))
        except Exception:
            pass

        try:
            from qgis.core import QgsRasterDataProvider
            provider = new_layer.dataProvider()
            if provider and hasattr(provider, "setZoomedInResamplingMethod"):
                provider.setZoomedInResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
                provider.setZoomedOutResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Nearest)
        except Exception:
            pass

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
            pass

        self._connect_scale_signal(new_layer, overlay_layer)
        self._connect_property_changed(new_layer, vrt_path, overlay_layer)
        try:
            new_layer.triggerRepaint()
        except Exception:
            pass
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

    def _replace_file_with_retry(self, src_path, dest_path, label):
        if not src_path or not os.path.exists(src_path):
            return False
        last_error = None
        for _attempt in range(10):
            try:
                os.replace(src_path, dest_path)
                return True
            except Exception as e:
                last_error = e
                QApplication.processEvents()
                time.sleep(0.2)
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
                    pass
            if overlay_layer:
                try:
                    saved_overlay_crs = overlay_layer.crs()
                    overlay_layer.saveNamedStyle(os.path.splitext(vrt_path)[0] + "_overlay.qml")
                except Exception:
                    pass
            if not (saved_crs and saved_crs.isValid()):
                saved_crs, saved_overlay_crs_from_json = self._load_crs_json(vrt_path)
                if not (saved_overlay_crs and saved_overlay_crs.isValid()):
                    saved_overlay_crs = saved_overlay_crs_from_json

            self._set_status("⏳ 外部VRTエンジンで削除更新中...")
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
                pass
            for tmp_path in (temp_vrt, temp_gpkg):
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
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
                pass
            self.iface.mapCanvas().refresh()
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

            try:
                if hasattr(self.iface.mapCanvas(), "clearCache"):
                    self.iface.mapCanvas().clearCache()
            except Exception:
                pass
            self.iface.mapCanvas().refresh()
            QApplication.processEvents()
            return True, ""
        except Exception as e:
            if original_xml is not None and vrt_path:
                try:
                    with open(vrt_path, "w", encoding="utf-8") as f:
                        f.write(original_xml)
                except Exception:
                    pass
            if vrt_layer:
                try: vrt_layer.triggerRepaint()
                except Exception: pass
            elif vrt_layer_state:
                try: self._restore_vrt_raster_layer_after_xml_update(display_name, vrt_path, overlay_layer, vrt_layer_state)
                except Exception: pass
            if overlay_layer:
                try: overlay_layer.triggerRepaint()
                except Exception: pass
            self.iface.mapCanvas().refresh()
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
                        except: pass
                    QgsProject.instance().removeMapLayer(lid)
            root.removeChildNode(group)
        else:
            for lyr in QgsProject.instance().mapLayersByName(display_name) + QgsProject.instance().mapLayersByName(base_name):
                if isinstance(lyr, QgsRasterLayer): QgsProject.instance().removeMapLayer(lyr.id())
            for lyr in QgsProject.instance().mapLayersByName(self.overlay_layer_name(name)) + QgsProject.instance().mapLayersByName(f"{base_name}_overlay"):
                if hasattr(lyr, 'dataProvider') and lyr.dataProvider():
                    try: lyr.dataProvider().reloadData()
                    except: pass
                QgsProject.instance().removeMapLayer(lyr.id())
        self.iface.mapCanvas().refresh()
        QApplication.processEvents()

    # --- QMLとCRSの保存・復元 ---
    def _save_qml(self, vrt_layer, vrt_path, overlay_layer):
        try:
            vrt_qml = os.path.splitext(vrt_path)[0] + ".qml"
            vrt_layer.saveNamedStyle(vrt_qml)
            if overlay_layer:
                overlay_qml = os.path.splitext(vrt_path)[0] + "_overlay.qml"
                overlay_layer.saveNamedStyle(overlay_qml)
            self._save_crs_json(vrt_path, vrt_layer, overlay_layer)
        except: pass

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
        except: pass

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
        except: pass
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
            pass
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
                pass
            self._crs_alert_label = None
        if self._crs_alert_timer:
            try:
                self._crs_alert_timer.stop()
                self._crs_alert_timer.deleteLater()
            except Exception:
                pass
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
            except: pass
        try:
            vrt_layer.scaleBasedVisibilityChanged.connect(on_scale_changed)
            self._scale_timer[vrt_layer.id()] = on_scale_changed
        except: pass

    def _disconnect_scale_signal(self, name):
        vrt_layer = self._get_vrt_layer(name)
        if vrt_layer and vrt_layer.id() in self._scale_timer:
            try: vrt_layer.scaleBasedVisibilityChanged.disconnect(self._scale_timer[vrt_layer.id()])
            except: pass
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
        self._set_status("⏳ レイヤ読み込み中...")
        QApplication.processEvents()
        
        gpkg_ok = os.path.exists(gpkg_path)

        vrt_layer = QgsRasterLayer(vrt_path, layer_name, "gdal")
        if not vrt_layer.isValid():
            self._restore_gdal_pam(gdal, old_pam_enabled)
            self._set_status("❌ VRTレイヤの読み込みに失敗しました")
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
        except: pass
        
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
                pass
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
        self._set_status(f"✅ 完了: {layer_name} {overlay_msg}（{count} ファイル）")

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
            except: pass
        def on_vrt_crs_changed():
            try: self._save_qml(vrt_layer, vrt_path, overlay_layer_ref)
            except: pass
        try: vrt_layer.styleChanged.connect(on_vrt_style_changed)
        except: pass
        try: vrt_layer.crsChanged.connect(on_vrt_crs_changed)
        except: pass
        if overlay_layer_ref:
            def on_overlay_crs_changed():
                try: self._save_qml(vrt_layer, vrt_path, overlay_layer_ref)
                except: pass
            try: overlay_layer_ref.crsChanged.connect(on_overlay_crs_changed)
            except: pass

    def _on_overlay_renderer_changed(self, overlay_layer, qml_path):
        try: overlay_layer.saveNamedStyle(qml_path)
        except: pass



















