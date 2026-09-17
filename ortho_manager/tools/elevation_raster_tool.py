from ..process_args import validated_process_args
from ..diagnostics import record_ignored_exception as _om_record_ignored_exception
import json
import hashlib
import math
import os
import shutil
import subprocess  # nosec B404 # local GIS helpers use validated argument lists and shell=False.
import struct
import time

from osgeo import gdal
try:
    import numpy as np
except Exception:
    np = None
from qgis.PyQt.QtCore import QTimer, Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton,
    QSizePolicy, QListWidget, QFileDialog, QLineEdit, QDoubleSpinBox,
    QComboBox, QCheckBox, QProgressBar, QMessageBox, QGridLayout,
    QAbstractItemView, QDialog
)
from qgis.core import (
    QgsElevationShadingRenderer,
    QgsApplication, QgsFeature, QgsField, QgsFillSymbol,
    QgsGeometry, QgsGradientColorRamp, QgsGradientStop, QgsMessageLog, QgsPalLayerSettings, Qgis, QgsPointXY,
    QgsProject, QgsCubicRasterResampler, QgsRasterLayer, QgsSingleBandPseudoColorRenderer,
    QgsTask, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling
)
from qgis.gui import QgsProjectionSelectionDialog

from ..i18n import tr


ELEVATION_RASTER_METADATA_FLAG = "ORTHO_MANAGER_ELEVATION_RASTER"
ELEVATION_RASTER_METADATA_STYLE = "ORTHO_MANAGER_ELEVATION_STYLE"
ELEVATION_RASTER_LAYER_PENDING_PROPERTY = "ortho_manager/elevation_style_pending"
ELEVATION_RASTER_LAYER_APPLIED_PROPERTY = "ortho_manager/elevation_style_applied"


class ElevationRasterTask(QgsTask):
    SPLIT_TIN_MAX_PARALLEL = 8

    def __init__(
        self,
        pdal_path,
        input_paths,
        output_path,
        resolution,
        output_type,
        fill_method,
        fill_distance,
        tin_edge_mode,
        tin_edge_distance,
        nodata,
        fallback_crs_wkt="",
    ):
        super().__init__("OrthoManager: 標高ラスタ作成", QgsTask.Flag.CanCancel)
        self.pdal_path = pdal_path
        self.input_paths = list(input_paths)
        self.output_path = os.path.normpath(os.path.abspath(output_path))
        self.resolution = float(resolution)
        self.output_type = output_type
        self.fill_method = fill_method
        self.fill_distance = float(fill_distance)
        self.tin_edge_mode = tin_edge_mode
        self.tin_edge_distance = float(tin_edge_distance)
        self.nodata = float(nodata)
        self.fallback_crs_wkt = str(fallback_crs_wkt or "")
        self.error_msg = ""
        self.elapsed_sec = 0.0
        self.work_dir = ""
        self.work_root = ""
        self.work_parent = ""
        self.temp_output_path = ""
        self.finished_callback = None
        self._proc = None
        self._procs = []
        self.quality_summary = {}

    def _is_ascii_path(self, path):
        try:
            str(path or "").encode("ascii")
            return True
        except Exception:
            return False

    def _validate_input_paths(self):
        valid_paths = []
        for source_path in self.input_paths:
            source_path = os.path.normpath(os.path.abspath(str(source_path or "")))
            if not os.path.exists(source_path):
                raise RuntimeError(f"入力LAS/LAZが見つかりません。\n{source_path}")
            ext = os.path.splitext(source_path)[1].lower()
            if ext not in (".las", ".laz"):
                raise RuntimeError(f"LAS/LAZ以外のファイルです。\n{source_path}")
            valid_paths.append(source_path)
        return valid_paths

    def _ascii_parent_candidates(self, path):
        folder = os.path.dirname(os.path.normpath(os.path.abspath(path)))
        candidates = []
        seen = set()
        while folder:
            key = os.path.normcase(folder)
            if key not in seen and self._is_ascii_path(folder):
                candidates.append(folder)
                seen.add(key)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        return candidates

    def _prepare_inputs_in_work_dir(self, work_dir, input_paths):
        input_dir = os.path.join(work_dir, "inputs")
        os.makedirs(input_dir, exist_ok=True)
        link_paths = []
        for index, source_path in enumerate(input_paths, start=1):
            ext = os.path.splitext(source_path)[1].lower()
            link_path = os.path.join(input_dir, f"src_{index:05d}{ext}")
            if os.path.exists(link_path):
                os.remove(link_path)
            os.link(source_path, link_path)
            link_paths.append(link_path)
        return link_paths

    def _prepare_ascii_work_inputs(self, input_paths):
        key_src = self.output_path + "|" + "|".join(input_paths)
        key = hashlib.sha1(os.path.normcase(key_src).encode("utf-8", "ignore"), usedforsecurity=False).hexdigest()[:16]
        errors = []
        for parent in self._ascii_parent_candidates(input_paths[0]):
            work_root = os.path.join(parent, "_ortho_manager_elevation_work_ascii", key)
            work_dir = os.path.join(work_root, "pdal_raster_ascii")
            if not self._is_ascii_path(work_dir):
                continue
            try:
                if os.path.isdir(work_root):
                    shutil.rmtree(work_root, ignore_errors=True)
                os.makedirs(work_dir, exist_ok=True)
                link_paths = self._prepare_inputs_in_work_dir(work_dir, input_paths)
                self.work_parent = os.path.dirname(work_root)
                self.work_root = work_root
                self.work_dir = work_dir
                return link_paths
            except Exception as e:
                errors.append(f"{work_dir}: {e}")
                try:
                    shutil.rmtree(work_root, ignore_errors=True)
                except Exception:
                    _om_record_ignored_exception(__name__, 151)
        detail = "\n".join(errors[-3:])
        raise RuntimeError(
            "PDAL用の英数字一時作業フォルダを作成できませんでした。\n"
            "元LAS/LAZと同じサーバー共有内、または同じドライブ上に、英数字名の親フォルダと書き込み権限が必要です。\n"
            "大容量LAS/LAZを自動コピーしないため、一時ハードリンクを作れない場所では処理できません。"
            + (f"\n\n{detail}" if detail else "")
        )

    def _read_las_bounds(self, path):
        with open(path, "rb") as f:
            header = f.read(227)
        if len(header) < 227 or header[:4] != b"LASF":
            raise RuntimeError(f"LAS/LAZヘッダを読めません。\n{path}")
        max_x, min_x, max_y, min_y = struct.unpack_from("<dddd", header, 179)
        return {
            "minx": float(min_x),
            "maxx": float(max_x),
            "miny": float(min_y),
            "maxy": float(max_y),
        }

    def _combined_bounds(self, input_paths):
        bounds = [self._read_las_bounds(path) for path in input_paths]
        return {
            "minx": min(item["minx"] for item in bounds),
            "maxx": max(item["maxx"] for item in bounds),
            "miny": min(item["miny"] for item in bounds),
            "maxy": max(item["maxy"] for item in bounds),
        }

    def _grid_spec(self, bounds):
        res = float(self.resolution)
        if not math.isfinite(res) or res <= 0:
            raise RuntimeError("解像度が不正です。")
        width = max(1, int(round((bounds["maxx"] - bounds["minx"]) / res)) + 1)
        height = max(1, int(round((bounds["maxy"] - bounds["miny"]) / res)) + 1)
        return {
            "origin_x": bounds["minx"] - res / 2.0,
            "origin_y": bounds["miny"] - res / 2.0,
            "width": width,
            "height": height,
        }

    def _tin_max_edge_length(self):
        if self.tin_edge_mode == "auto":
            return max(float(self.resolution) * 2.0, float(self.resolution))
        if self.tin_edge_mode == "manual":
            if self.tin_edge_distance <= 0:
                raise RuntimeError("TINの補間距離が不正です。")
            return self.tin_edge_distance
        return None

    def _input_reader_stages(self, work_dir, input_paths):
        pipeline = []
        for input_path in input_paths:
            pipeline.append(
                {
                    "type": "readers.las",
                    "filename": os.path.relpath(input_path, work_dir).replace("\\", "/"),
                }
            )
        if len(input_paths) > 1:
            pipeline.append({"type": "filters.merge"})
        return pipeline

    def _write_pipeline_file(self, work_dir, pipeline, filename):
        pipeline_path = os.path.join(work_dir, filename)
        with open(pipeline_path, "w", encoding="ascii", newline="\n") as f:
            json.dump({"pipeline": pipeline}, f, ensure_ascii=True, indent=2)
        return pipeline_path

    def _append_tin_raster_stages(self, pipeline, temp_output_path, grid):
        pipeline.append({"type": "filters.delaunay"})
        face_raster = {
            "type": "filters.faceraster",
            "resolution": self.resolution,
            "nodata": self.nodata,
            "origin_x": grid["origin_x"],
            "origin_y": grid["origin_y"],
            "width": grid["width"],
            "height": grid["height"],
        }
        max_edge = self._tin_max_edge_length()
        if max_edge is not None:
            face_raster["max_triangle_edge_length"] = max_edge
        pipeline.append(face_raster)
        pipeline.append(
            {
                "type": "writers.raster",
                "filename": os.path.basename(temp_output_path),
                "gdaldriver": "GTiff",
                "nodata": self.nodata,
                "data_type": "float",
                "gdalopts": "BIGTIFF=IF_SAFER",
            }
        )
        return pipeline

    def _build_direct_tin_pipeline(self, work_dir, input_paths, temp_output_path, grid):
        pipeline = self._input_reader_stages(work_dir, input_paths)
        self._append_tin_raster_stages(pipeline, temp_output_path, grid)
        return self._write_pipeline_file(work_dir, pipeline, "pipeline_tin_direct.json")

    def _build_split_tin_jobs(self, work_dir, input_paths):
        split_dir = os.path.join(work_dir, "split_tin")
        os.makedirs(split_dir, exist_ok=True)
        jobs = []
        for index, input_path in enumerate(input_paths, start=1):
            bounds = self._read_las_bounds(input_path)
            grid = self._grid_spec(bounds)
            tile_name = f"tile_{index:05d}.tif"
            tile_path = os.path.join(split_dir, tile_name)
            if os.path.exists(tile_path):
                os.remove(tile_path)
            pipeline = [
                {
                    "type": "readers.las",
                    "filename": os.path.relpath(input_path, split_dir).replace("\\", "/"),
                }
            ]
            self._append_tin_raster_stages(pipeline, tile_path, grid)
            pipeline_path = self._write_pipeline_file(split_dir, pipeline, f"pipeline_tile_{index:05d}.json")
            jobs.append(
                {
                    "name": os.path.basename(input_path),
                    "work_dir": split_dir,
                    "pipeline_path": pipeline_path,
                    "output_path": tile_path,
                }
            )
        return jobs

    def _build_aggregate_grid_pipeline(self, work_dir, input_paths, aggregate_path, grid):
        pipeline = self._input_reader_stages(work_dir, input_paths)
        writer = {
            "type": "writers.gdal",
            "filename": os.path.basename(aggregate_path),
            "resolution": self.resolution,
            "output_type": self.output_type,
            "nodata": self.nodata,
            "gdalopts": "BIGTIFF=IF_SAFER",
            "origin_x": grid["origin_x"],
            "origin_y": grid["origin_y"],
            "width": grid["width"],
            "height": grid["height"],
            "binmode": True,
        }
        pipeline.append(writer)
        return self._write_pipeline_file(work_dir, pipeline, "pipeline_aggregate_grid.json")

    def _representative_points_from_raster(self, raster_path, csv_path):
        dataset = gdal.OpenEx(raster_path, gdal.OF_RASTER)
        if dataset is None:
            raise RuntimeError("代表点作成用の中間ラスタを開けません。")
        point_count = 0
        try:
            transform = dataset.GetGeoTransform()
            band = dataset.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            width = dataset.RasterXSize
            height = dataset.RasterYSize
            with open(csv_path, "w", encoding="ascii", newline="\n") as f:
                f.write("X,Y,Z\n")
                for row in range(height):
                    if self.isCanceled():
                        self.error_msg = "標高ラスタ作成をキャンセルしました。"
                        return 0
                    values = band.ReadAsArray(0, row, width, 1)
                    if values is None:
                        continue
                    row_values = values[0]
                    lines = []
                    for col, value in enumerate(row_values):
                        z = float(value)
                        if not math.isfinite(z):
                            continue
                        if nodata is not None and z == float(nodata):
                            continue
                        x = transform[0] + (col + 0.5) * transform[1] + (row + 0.5) * transform[2]
                        y = transform[3] + (col + 0.5) * transform[4] + (row + 0.5) * transform[5]
                        lines.append(f"{x:.3f},{y:.3f},{z:.6f}\n")
                    if lines:
                        f.writelines(lines)
                        point_count += len(lines)
                    if row % 100 == 0 and height > 0:
                        self.setProgress(min(70, 45 + int(row / height * 25)))
        finally:
            dataset = None
        if point_count < 3:
            raise RuntimeError("TINを作るための代表点が不足しています。")
        return point_count

    def _build_representative_tin_pipeline(self, work_dir, csv_path, temp_output_path, grid):
        pipeline = [
            {
                "type": "readers.text",
                "filename": os.path.basename(csv_path),
                "separator": ",",
            }
        ]
        self._append_tin_raster_stages(pipeline, temp_output_path, grid)
        return self._write_pipeline_file(work_dir, pipeline, "pipeline_tin_representative.json")

    def _copy_raster_projection(self, source_path, target_path):
        source = gdal.OpenEx(source_path, gdal.OF_RASTER)
        target = gdal.OpenEx(target_path, gdal.OF_RASTER | gdal.OF_UPDATE)
        if source is None or target is None:
            return
        try:
            projection = source.GetProjection()
            if projection:
                target.SetProjection(projection)
            target.FlushCache()
        finally:
            source = None
            target = None

    def _raster_projection(self, raster_path):
        dataset = gdal.OpenEx(raster_path, gdal.OF_RASTER)
        if dataset is None:
            return ""
        try:
            return dataset.GetProjection() or ""
        finally:
            dataset = None

    def _set_raster_projection(self, raster_path, projection):
        if not projection:
            return False
        dataset = gdal.OpenEx(raster_path, gdal.OF_RASTER | gdal.OF_UPDATE)
        if dataset is None:
            return False
        try:
            dataset.SetProjection(projection)
            dataset.FlushCache()
            return True
        finally:
            dataset = None

    def _sync_split_tin_tile_projection(self, tile_paths):
        projection = ""
        source = ""
        for tile_path in tile_paths:
            projection = self._raster_projection(tile_path)
            if projection:
                source = os.path.basename(tile_path)
                break
        if not projection and self.fallback_crs_wkt:
            projection = self.fallback_crs_wkt
            source = "project_crs"
        if not projection:
            QgsMessageLog.logMessage(
                "ELEVATION_RASTER_SPLIT_TIN_CRS_SKIP reason=no_projection",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return ""
        updated = 0
        missing = 0
        for tile_path in tile_paths:
            tile_projection = self._raster_projection(tile_path)
            if tile_projection == projection:
                continue
            if self._set_raster_projection(tile_path, projection):
                updated += 1
            else:
                missing += 1
        QgsMessageLog.logMessage(
            f"ELEVATION_RASTER_SPLIT_TIN_CRS_SYNC source={source} updated={updated} failed={missing}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )
        return projection

    def _merge_split_tin_tiles(self, tile_paths, output_path):
        if self.isCanceled():
            self.error_msg = "標高ラスタ作成をキャンセルしました。"
            return False
        self.setProgress(90)
        vrt_path = os.path.join(os.path.dirname(output_path), "split_tin_merge.vrt")
        if os.path.exists(vrt_path):
            os.remove(vrt_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        try:
            vrt_options = gdal.BuildVRTOptions(srcNodata=self.nodata, VRTNodata=self.nodata)
            vrt_dataset = gdal.BuildVRT(vrt_path, tile_paths, options=vrt_options)
            if vrt_dataset is None:
                raise RuntimeError("分割TINの結合VRTを作成できません。")
            vrt_dataset.FlushCache()
            vrt_dataset = None
            if self.isCanceled():
                self.error_msg = "標高ラスタ作成をキャンセルしました。"
                return False
            self.setProgress(94)
            translate_options = gdal.TranslateOptions(
                format="GTiff",
                noData=self.nodata,
                creationOptions=["BIGTIFF=IF_SAFER"],
            )
            dataset = gdal.Translate(output_path, vrt_path, options=translate_options)
            if dataset is None:
                raise RuntimeError("分割TINをGeoTIFFへ結合できません。")
            dataset.FlushCache()
            dataset = None
            projection = self._raster_projection(vrt_path)
            if projection:
                self._set_raster_projection(output_path, projection)
            self.setProgress(98)
            return True
        finally:
            try:
                if os.path.exists(vrt_path):
                    os.remove(vrt_path)
            except Exception:
                _om_record_ignored_exception(__name__, 467)

    def _run_pdal_jobs_parallel(self, jobs, start_progress=5, end_progress=90):
        if not jobs:
            return True
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        env = os.environ.copy()
        env["GDAL_PAM_ENABLED"] = "NO"
        pending = list(jobs)
        active = []
        finished = 0
        total = len(jobs)
        max_parallel = max(1, min(self.SPLIT_TIN_MAX_PARALLEL, total))
        self.setProgress(start_progress)
        try:
            while pending or active:
                while pending and len(active) < max_parallel:
                    job = pending.pop(0)
                    proc = subprocess.Popen(  # nosec B603 # validated local executable; argv list; shell=False.
                        validated_process_args([self.pdal_path, "pipeline", os.path.basename(job["pipeline_path"])]),
                        shell=False,
                        cwd=job["work_dir"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=creationflags,
                    )
                    active.append((job, proc, time.perf_counter()))
                    self._procs.append(proc)
                if self.isCanceled():
                    for _job, proc, _started in active:
                        if proc.poll() is None:
                            proc.kill()
                    self.error_msg = "標高ラスタ作成をキャンセルしました。"
                    return False
                still_active = []
                for job, proc, started in active:
                    if proc.poll() is None:
                        still_active.append((job, proc, started))
                        continue
                    stdout, stderr = proc.communicate()
                    try:
                        self._procs.remove(proc)
                    except ValueError:
                        _om_record_ignored_exception(__name__, 513)
                    if stdout.strip():
                        QgsMessageLog.logMessage(stdout.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Info)
                    if stderr.strip():
                        QgsMessageLog.logMessage(stderr.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Warning)
                    if proc.returncode != 0:
                        self.error_msg = (stderr or stdout or "分割TINのPDAL処理に失敗しました。").strip()
                        for _job, active_proc, _started in still_active:
                            if active_proc.poll() is None:
                                active_proc.kill()
                        return False
                    if not os.path.exists(job["output_path"]):
                        self.error_msg = f"分割TINの出力GeoTIFFが作成されていません。\n{job['output_path']}"
                        return False
                    finished += 1
                    elapsed = time.perf_counter() - started
                    QgsMessageLog.logMessage(
                        f"ELEVATION_RASTER_SPLIT_TIN_TILE_DONE src={job['name']} seconds={elapsed:.1f}",
                        "OrthoManager",
                        Qgis.MessageLevel.Info,
                    )
                    progress = start_progress + int((end_progress - start_progress) * finished / total)
                    self.setProgress(min(end_progress, progress))
                active = still_active
                time.sleep(0.2)
            self.setProgress(end_progress)
            return True
        finally:
            self._procs = [proc for proc in self._procs if proc.poll() is None]

    def _run_pdal(self, work_dir, pipeline_path, start_progress=5, end_progress=90):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        env = os.environ.copy()
        env["GDAL_PAM_ENABLED"] = "NO"
        proc = subprocess.Popen(  # nosec B603 # validated local executable; argv list; shell=False.
            validated_process_args([self.pdal_path, "pipeline", os.path.basename(pipeline_path)]),
            shell=False,
            cwd=work_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self._proc = proc
        self.setProgress(start_progress)
        started = time.perf_counter()
        try:
            while proc.poll() is None:
                if self.isCanceled():
                    proc.kill()
                    try:
                        proc.communicate(timeout=5)
                    except Exception:
                        _om_record_ignored_exception(__name__, 568)
                    self.error_msg = "標高ラスタ作成をキャンセルしました。"
                    return False
                elapsed = time.perf_counter() - started
                self.setProgress(min(end_progress - 5, start_progress + int(elapsed)))
                time.sleep(0.3)
            stdout, stderr = proc.communicate()
        finally:
            self._proc = None
        if stdout.strip():
            QgsMessageLog.logMessage(stdout.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Info)
        if stderr.strip():
            QgsMessageLog.logMessage(stderr.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Warning)
        if proc.returncode != 0:
            self.error_msg = (stderr or stdout or "PDAL処理に失敗しました。").strip()
            return False
        self.setProgress(end_progress)
        return True

    def cancel(self):
        super().cancel()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                _om_record_ignored_exception(__name__, 594)
        for proc in list(self._procs):
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    _om_record_ignored_exception(__name__, 600)

    def _fill_nodata_nearest(self, raster_path):
        if self.output_type == "tin" or self.fill_method != "nearest":
            return True
        if self.isCanceled():
            self.error_msg = "標高ラスタ作成をキャンセルしました。"
            return False
        max_search_pixels = 1
        if self.fill_distance > 0:
            max_search_pixels = max(1, int(math.ceil((self.fill_distance / 2.0) / self.resolution)))
        try:
            version_num = int(gdal.VersionInfo("VERSION_NUM") or "0")
        except Exception:
            version_num = 0
        if version_num and version_num < 3090000:
            raise RuntimeError("最近傍で空白セルを埋めるには GDAL 3.9 以上が必要です。")

        dataset = gdal.OpenEx(raster_path, gdal.OF_RASTER | gdal.OF_UPDATE)
        if dataset is None:
            raise RuntimeError("空白セル処理用にGeoTIFFを開けません。")
        try:
            band = dataset.GetRasterBand(1)
            band.SetNoDataValue(self.nodata)

            def progress_callback(complete, _message, _data):
                if self.isCanceled():
                    return 0
                self.setProgress(min(98, 65 + int(float(complete) * 30)))
                return 1

            options = [f"NODATA={self.nodata}", "INTERPOLATION=NEAREST", "TEMP_FILE_DRIVER=MEM"]
            try:
                err = gdal.FillNodata(band, None, max_search_pixels, 0, options, progress_callback, None)
            except TypeError:
                err = gdal.FillNodata(band, None, max_search_pixels, 0, 0, options, progress_callback, None)
            if self.isCanceled():
                self.error_msg = "標高ラスタ作成をキャンセルしました。"
                return False
            if err != 0:
                raise RuntimeError("最近傍による空白セル処理に失敗しました。")
            band.FlushCache()
            dataset.FlushCache()
            self.setProgress(98)
            return True
        finally:
            dataset = None

    def _cleanup_work_dirs(self):
        try:
            if self.work_root and os.path.isdir(self.work_root):
                shutil.rmtree(self.work_root, ignore_errors=True)
                if os.path.isdir(self.work_root):
                    QgsMessageLog.logMessage(
                        f"ELEVATION_RASTER_WORK_CLEAN_FAILED path={self.work_root}",
                        "OrthoManager",
                        Qgis.MessageLevel.Warning,
                    )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_WORK_CLEAN_FAILED path={self.work_root} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

        try:
            if self.work_parent and os.path.isdir(self.work_parent) and not os.listdir(self.work_parent):
                os.rmdir(self.work_parent)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_WORK_PARENT_CLEAN_FAILED path={self.work_parent} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _summarize_output_raster(self, raster_path):
        summary = {}
        dataset = None
        try:
            if np is None:
                QgsMessageLog.logMessage(
                    "ELEVATION_RASTER_QUALITY_SKIPPED reason=numpy_not_available",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
                return summary
            dataset = gdal.Open(str(raster_path), gdal.GA_ReadOnly)
            if dataset is None:
                return summary
            band = dataset.GetRasterBand(1)
            if band is None:
                return summary
            width = int(dataset.RasterXSize)
            height = int(dataset.RasterYSize)
            total_cells = width * height
            nodata = band.GetNoDataValue()
            min_z = None
            max_z = None
            nodata_cells = 0
            valid_cells = 0
            block_size = band.GetBlockSize() or [width, 256]
            rows_per_chunk = min(max(int(block_size[1] or 256), 128), 512)
            for y_off in range(0, height, rows_per_chunk):
                rows = min(rows_per_chunk, height - y_off)
                array = band.ReadAsArray(0, y_off, width, rows)
                if array is None:
                    continue
                invalid_mask = ~np.isfinite(array)
                if nodata is not None:
                    invalid_mask |= array == nodata
                nodata_cells += int(invalid_mask.sum())
                valid_values = array[~invalid_mask]
                if valid_values.size <= 0:
                    continue
                valid_cells += int(valid_values.size)
                chunk_min = float(valid_values.min())
                chunk_max = float(valid_values.max())
                min_z = chunk_min if min_z is None else min(min_z, chunk_min)
                max_z = chunk_max if max_z is None else max(max_z, chunk_max)
            try:
                geotransform = dataset.GetGeoTransform(can_return_null=True)
            except TypeError:
                geotransform = dataset.GetGeoTransform()
            extent = None
            if geotransform:
                corners = [(0, 0), (width, 0), (width, height), (0, height)]
                xs = [geotransform[0] + x * geotransform[1] + y * geotransform[2] for x, y in corners]
                ys = [geotransform[3] + x * geotransform[4] + y * geotransform[5] for x, y in corners]
                extent = (min(xs), min(ys), max(xs), max(ys))
            nodata_percent = (nodata_cells / total_cells * 100.0) if total_cells else 0.0
            summary = {
                "width": width,
                "height": height,
                "total_cells": total_cells,
                "valid_cells": valid_cells,
                "nodata_cells": nodata_cells,
                "nodata_percent": nodata_percent,
                "min_z": min_z,
                "max_z": max_z,
                "nodata": nodata,
                "extent": extent,
            }
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_QUALITY_FAILED out={raster_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return {}
        finally:
            dataset = None
        return summary

    def run(self):
        started = time.perf_counter()
        try:
            input_paths = self._validate_input_paths()
            bounds = self._combined_bounds(input_paths)
            grid = self._grid_spec(bounds)
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            link_paths = self._prepare_ascii_work_inputs(input_paths)
            self.temp_output_path = os.path.join(self.work_dir, "elevation_raster_tmp.tif")
            if os.path.exists(self.temp_output_path):
                os.remove(self.temp_output_path)
            QgsMessageLog.logMessage(
                (
                    "ELEVATION_RASTER_PDAL_START "
                    f"count={len(self.input_paths)} resolution={self.resolution} "
                    f"z_method={self.output_type} "
                    f"tin_edge_mode={self.tin_edge_mode} tin_edge_distance={self.tin_edge_distance} "
                    f"origin_x={grid['origin_x']:.3f} origin_y={grid['origin_y']:.3f} "
                    f"width={grid['width']} height={grid['height']} route=ascii_link"
                ),
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            if self.output_type == "tin":
                use_split_tin = self.tin_edge_mode in ("auto", "manual") and len(link_paths) > 1
                if use_split_tin:
                    split_jobs = self._build_split_tin_jobs(self.work_dir, link_paths)
                    QgsMessageLog.logMessage(
                        (
                            "ELEVATION_RASTER_SPLIT_TIN_START "
                            f"count={len(split_jobs)} max_parallel={self.SPLIT_TIN_MAX_PARALLEL} "
                            f"tin_edge_mode={self.tin_edge_mode}"
                        ),
                        "OrthoManager",
                        Qgis.MessageLevel.Info,
                    )
                    if not self._run_pdal_jobs_parallel(split_jobs, 5, 88):
                        return False
                    split_tile_paths = [job["output_path"] for job in split_jobs]
                    self._sync_split_tin_tile_projection(split_tile_paths)
                    if not self._merge_split_tin_tiles(split_tile_paths, self.temp_output_path):
                        return False
                else:
                    pipeline_path = self._build_direct_tin_pipeline(self.work_dir, link_paths, self.temp_output_path, grid)
                    if not self._run_pdal(self.work_dir, pipeline_path, 5, 90):
                        return False
            else:
                aggregate_path = os.path.join(self.work_dir, "representative_grid.tif")
                if os.path.exists(aggregate_path):
                    os.remove(aggregate_path)
                aggregate_pipeline = self._build_aggregate_grid_pipeline(self.work_dir, link_paths, aggregate_path, grid)
                if not self._run_pdal(self.work_dir, aggregate_pipeline, 5, 45):
                    return False
                representative_csv = os.path.join(self.work_dir, "representative_points.csv")
                if os.path.exists(representative_csv):
                    os.remove(representative_csv)
                representative_count = self._representative_points_from_raster(aggregate_path, representative_csv)
                if representative_count <= 0:
                    return False
                QgsMessageLog.logMessage(
                    f"ELEVATION_RASTER_REPRESENTATIVE_POINTS count={representative_count} method={self.output_type}",
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                tin_pipeline = self._build_representative_tin_pipeline(self.work_dir, representative_csv, self.temp_output_path, grid)
                if not self._run_pdal(self.work_dir, tin_pipeline, 70, 90):
                    return False
                self._copy_raster_projection(aggregate_path, self.temp_output_path)
            if not os.path.exists(self.temp_output_path):
                raise RuntimeError("PDAL処理は終了しましたが、出力GeoTIFFが作成されていません。")
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
            shutil.copy2(self.temp_output_path, self.output_path)
            self._write_output_metadata_marker()
            self.quality_summary = self._summarize_output_raster(self.output_path)
            self.elapsed_sec = time.perf_counter() - started
            self.setProgress(100)
            QgsMessageLog.logMessage(
                (
                    "ELEVATION_RASTER_PDAL_DONE "
                    f"count={len(self.input_paths)} seconds={self.elapsed_sec:.1f} "
                    f"out={self.output_path}"
                ),
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
            if self.quality_summary:
                extent = self.quality_summary.get("extent")
                extent_text = ""
                if extent:
                    extent_text = (
                        f" extent_minx={extent[0]:.3f} extent_miny={extent[1]:.3f}"
                        f" extent_maxx={extent[2]:.3f} extent_maxy={extent[3]:.3f}"
                    )
                QgsMessageLog.logMessage(
                    (
                        "ELEVATION_RASTER_QUALITY "
                        f"width={self.quality_summary.get('width')} "
                        f"height={self.quality_summary.get('height')} "
                        f"valid={self.quality_summary.get('valid_cells')} "
                        f"nodata={self.quality_summary.get('nodata_cells')} "
                        f"nodata_percent={self.quality_summary.get('nodata_percent', 0.0):.3f} "
                        f"min_z={self.quality_summary.get('min_z')} "
                        f"max_z={self.quality_summary.get('max_z')}"
                        f"{extent_text}"
                    ),
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
                width = int(self.quality_summary.get("width") or 0)
                height = int(self.quality_summary.get("height") or 0)
                width_m = width * float(self.resolution)
                height_m = height * float(self.resolution)
                min_z = self.quality_summary.get("min_z")
                max_z = self.quality_summary.get("max_z")
                z_text = "有効セルなし"
                if min_z is not None and max_z is not None:
                    z_text = f"{float(min_z):.3f} m 〜 {float(max_z):.3f} m"
                extent_summary = ""
                if extent:
                    extent_summary = (
                        f"\n  範囲: X {extent[0]:.3f} 〜 {extent[2]:.3f} m / "
                        f"Y {extent[1]:.3f} 〜 {extent[3]:.3f} m"
                    )
                QgsMessageLog.logMessage(
                    (
                        "ELEVATION_RASTER_QUALITY_SUMMARY\n"
                        f"  出力サイズ: {width} x {height} px "
                        f"({width_m:.3f} m x {height_m:.3f} m)\n"
                        f"  解像度: {self.resolution:.3f} m/px\n"
                        f"  有効セル: {self.quality_summary.get('valid_cells')} px\n"
                        f"  NoData: {self.quality_summary.get('nodata_cells')} px "
                        f"({self.quality_summary.get('nodata_percent', 0.0):.1f}%)\n"
                        f"  Z範囲: {z_text}"
                        f"{extent_summary}"
                    ),
                    "OrthoManager",
                    Qgis.MessageLevel.Info,
                )
            return True
        except Exception as e:
            self.error_msg = str(e)
            QgsMessageLog.logMessage(f"ELEVATION_RASTER_PDAL_FAILED error={e}", "OrthoManager", Qgis.MessageLevel.Critical)
            return False
        finally:
            self._cleanup_work_dirs()

    def _write_output_metadata_marker(self):
        old_pam = gdal.GetConfigOption("GDAL_PAM_ENABLED")
        dataset = None
        try:
            gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
            dataset = gdal.Open(self.output_path, gdal.GA_Update)
            if dataset is None:
                return
            dataset.SetMetadataItem(ELEVATION_RASTER_METADATA_FLAG, "1")
            dataset.SetMetadataItem(ELEVATION_RASTER_METADATA_STYLE, "pseudocolor_hillshade_cubic_v1")
            dataset.SetMetadataItem("ORTHO_MANAGER_ELEVATION_CREATED", time.strftime("%Y-%m-%dT%H:%M:%S"))
            dataset.FlushCache()
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_METADATA_MARKED out={self.output_path}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_METADATA_MARK_FAILED out={self.output_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        finally:
            dataset = None
            gdal.SetConfigOption("GDAL_PAM_ENABLED", old_pam)

    def finished(self, result):
        if callable(self.finished_callback):
            self.finished_callback(self, result)


class ElevationRasterToolWidget(QWidget):
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self.dock = dock
        self._task = None
        self._last_input_dir = ""
        self._last_output_dir = ""
        self._extent_layer_id = ""
        self._styled_elevation_layer_ids = set()
        self._build_ui()
        self.refresh_texts()
        self._install_project_layer_monitor()

    def _install_project_layer_monitor(self):
        try:
            QgsProject.instance().layersAdded.connect(self._on_project_layers_added)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_LAYER_MONITOR_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _on_project_layers_added(self, layers):
        for layer in list(layers or []):
            try:
                if not isinstance(layer, QgsRasterLayer):
                    continue
                if bool(layer.customProperty(ELEVATION_RASTER_LAYER_PENDING_PROPERTY, False)):
                    continue
                if layer.id() in self._styled_elevation_layer_ids:
                    continue
                if not self._is_ortho_elevation_raster_layer(layer):
                    continue
                QTimer.singleShot(0, lambda lyr=layer: self._apply_imported_elevation_raster_style(lyr))
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"ELEVATION_RASTER_LAYER_MONITOR_ITEM_FAILED error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )

    def _layer_source_path(self, layer):
        try:
            source = str(layer.source() or "").split("|", 1)[0]
            if source.lower().startswith("file:///"):
                source = source[8:]
            return os.path.normpath(source)
        except Exception:
            return ""

    def _is_ortho_elevation_raster_layer(self, layer):
        source_path = self._layer_source_path(layer)
        if not source_path or not os.path.exists(source_path):
            return False
        dataset = None
        try:
            dataset = gdal.Open(source_path, gdal.GA_ReadOnly)
            if dataset is None:
                return False
            value = str(dataset.GetMetadataItem(ELEVATION_RASTER_METADATA_FLAG) or "").strip()
            return value in ("1", "true", "True", "yes", "YES")
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_METADATA_READ_FAILED path={source_path} error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False
        finally:
            dataset = None

    def _apply_imported_elevation_raster_style(self, layer):
        try:
            if layer is None or not layer.isValid():
                return
            if layer.id() in self._styled_elevation_layer_ids:
                return
            self._apply_elevation_pseudocolor(layer)
            self._enable_elevation_hillshading(layer)
            self._refresh_elevation_display_after_add(layer)
            self._styled_elevation_layer_ids.add(layer.id())
            layer.setCustomProperty(ELEVATION_RASTER_LAYER_APPLIED_PROPERTY, True)
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_IMPORTED_STYLE_APPLIED layer={layer.name()} source={self._layer_source_path(layer)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except RuntimeError:
            return
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_IMPORTED_STYLE_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

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
        input_layout = QVBoxLayout(self.input_group)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(6)
        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(6)
        button_grid.setVerticalSpacing(5)
        self.add_files_button = QPushButton()
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button = QPushButton()
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_selected_button = QPushButton()
        self.remove_selected_button.clicked.connect(self._remove_selected_inputs)
        self.clear_inputs_button = QPushButton()
        self.clear_inputs_button.clicked.connect(self._clear_inputs)
        self.show_extent_button = QPushButton()
        self.show_extent_button.clicked.connect(lambda: self._show_input_extents())
        self.clear_extent_button = QPushButton()
        self.clear_extent_button.clicked.connect(self._clear_input_extents)
        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_selected_button,
            self.clear_inputs_button,
            self.show_extent_button,
            self.clear_extent_button,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button_grid.addWidget(self.add_files_button, 0, 0)
        button_grid.addWidget(self.add_folder_button, 0, 1)
        button_grid.addWidget(self.remove_selected_button, 0, 2)
        button_grid.addWidget(self.clear_inputs_button, 1, 0)
        button_grid.addWidget(self.show_extent_button, 1, 1)
        button_grid.addWidget(self.clear_extent_button, 1, 2)
        input_layout.addLayout(button_grid)
        self.auto_extent_check = QCheckBox()
        self.auto_extent_check.setChecked(True)
        self.auto_extent_check.toggled.connect(self._auto_extent_toggled)
        input_layout.addWidget(self.auto_extent_check)
        self.input_list = QListWidget()
        self.input_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.input_list.setMinimumHeight(70)
        input_layout.addWidget(self.input_list)
        layout.addWidget(self.input_group)

        self.output_group = QGroupBox()
        output_layout = QVBoxLayout(self.output_group)
        output_layout.setContentsMargins(8, 8, 8, 8)
        output_layout.setSpacing(6)
        output_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        self.output_browse_button = QPushButton()
        self.output_browse_button.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_path_edit, 1)
        output_row.addWidget(self.output_browse_button)
        output_layout.addLayout(output_row)

        settings_grid = QGridLayout()
        settings_grid.setHorizontalSpacing(6)
        settings_grid.setVerticalSpacing(5)
        self.resolution_label = QLabel()
        self.resolution_spin = QDoubleSpinBox()
        self.resolution_spin.setRange(0.01, 1000.0)
        self.resolution_spin.setDecimals(3)
        self.resolution_spin.setSingleStep(0.1)
        self.resolution_spin.setValue(0.5)
        self.resolution_spin.setSuffix(" m")
        self.output_type_label = QLabel()
        self.output_type_combo = QComboBox()
        for value in ("tin", "max", "min", "mean"):
            self.output_type_combo.addItem(value, value)
        self.output_type_combo.currentIndexChanged.connect(self._update_method_controls)
        self.tin_edge_label = QLabel()
        self.tin_edge_combo = QComboBox()
        for value in ("auto", "manual", "unlimited"):
            self.tin_edge_combo.addItem(value, value)
        self.tin_edge_combo.currentIndexChanged.connect(self._update_method_controls)
        self.tin_edge_distance_label = QLabel()
        self.tin_edge_distance_spin = QDoubleSpinBox()
        self.tin_edge_distance_spin.setRange(0.001, 100000.0)
        self.tin_edge_distance_spin.setDecimals(3)
        self.tin_edge_distance_spin.setSingleStep(0.1)
        self.tin_edge_distance_spin.setValue(1.0)
        self.tin_edge_distance_spin.setSuffix(" m")
        self.fill_method_label = QLabel()
        self.fill_method_combo = QComboBox()
        for value in ("none", "nearest"):
            self.fill_method_combo.addItem(value, value)
        self.fill_method_combo.currentIndexChanged.connect(self._update_method_controls)
        self.fill_distance_label = QLabel()
        self.fill_distance_spin = QDoubleSpinBox()
        self.fill_distance_spin.setRange(0.0, 10000.0)
        self.fill_distance_spin.setDecimals(3)
        self.fill_distance_spin.setSingleStep(0.1)
        self.fill_distance_spin.setValue(0.0)
        self.fill_distance_spin.setSuffix(" m")
        settings_grid.addWidget(self.resolution_label, 0, 0)
        settings_grid.addWidget(self.resolution_spin, 0, 1)
        settings_grid.addWidget(self.output_type_label, 1, 0)
        settings_grid.addWidget(self.output_type_combo, 1, 1)
        settings_grid.addWidget(self.tin_edge_label, 2, 0)
        settings_grid.addWidget(self.tin_edge_combo, 2, 1)
        settings_grid.addWidget(self.tin_edge_distance_label, 3, 0)
        settings_grid.addWidget(self.tin_edge_distance_spin, 3, 1)
        settings_grid.addWidget(self.fill_method_label, 4, 0)
        settings_grid.addWidget(self.fill_method_combo, 4, 1)
        settings_grid.addWidget(self.fill_distance_label, 5, 0)
        settings_grid.addWidget(self.fill_distance_spin, 5, 1)
        settings_grid.setColumnStretch(1, 1)
        output_layout.addLayout(settings_grid)

        self.auto_load_check = QCheckBox()
        self.auto_load_check.setChecked(True)
        output_layout.addWidget(self.auto_load_check)
        layout.addWidget(self.output_group)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color:#4b5563;")
        self.run_button = QPushButton()
        self.run_button.clicked.connect(self._run)
        self.run_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.run_button.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border:none;border-radius:4px;padding:5px 12px;}"
            "QPushButton:disabled{background:#cbd5e1;color:#64748b;}"
        )
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.cancel_button.setStyleSheet(
            "QPushButton{background:#b91c1c;color:white;border:none;border-radius:4px;padding:5px 10px;}"
            "QPushButton:disabled{background:#e5e7eb;color:#9ca3af;}"
        )
        progress_row.addWidget(self.progress_bar, 1)
        layout.addLayout(progress_row)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.cancel_button)
        layout.addLayout(action_row)

        self.apply_selected_style_button = QPushButton()
        self.apply_selected_style_button.clicked.connect(self._apply_style_to_selected_raster)
        self.apply_selected_style_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.apply_selected_style_button)

        layout.addStretch(1)

    def _input_paths(self):
        paths = []
        for index in range(self.input_list.count()):
            path = self.input_list.item(index).data(256)
            if path:
                paths.append(path)
        return paths

    def _project_folder(self):
        project_path = QgsProject.instance().fileName()
        if project_path:
            folder = os.path.dirname(os.path.abspath(project_path))
            if os.path.isdir(folder):
                return folder
        return ""

    def _home_folder(self):
        folder = os.path.expanduser("~")
        return folder if os.path.isdir(folder) else ""

    def _first_input_folder(self):
        for path in self._input_paths():
            folder = os.path.dirname(os.path.abspath(path))
            if os.path.isdir(folder):
                return folder
        return ""

    def _valid_folder_from_candidates(self, candidates):
        for folder in candidates:
            if folder and os.path.isdir(folder):
                return folder
        return ""

    def _initial_input_dir(self):
        return self._valid_folder_from_candidates(
            [self._last_input_dir, self._project_folder(), self._first_input_folder(), self._home_folder()]
        )

    def _initial_output_dir(self):
        current = self.output_path_edit.text().strip()
        current_folder = os.path.dirname(os.path.abspath(current)) if current else ""
        return self._valid_folder_from_candidates(
            [self._last_output_dir, current_folder, self._project_folder(), self._first_input_folder(), self._home_folder()]
        )

    def _add_input_paths(self, paths):
        existing = {os.path.normcase(os.path.abspath(path)) for path in self._input_paths()}
        added = 0
        for path in paths:
            path = os.path.normpath(os.path.abspath(str(path or "")))
            if not path or not os.path.exists(path):
                continue
            if os.path.splitext(path)[1].lower() not in (".las", ".laz"):
                continue
            key = os.path.normcase(path)
            if key in existing:
                continue
            self.input_list.addItem(os.path.basename(path))
            item = self.input_list.item(self.input_list.count() - 1)
            item.setData(256, path)
            item.setToolTip(path)
            existing.add(key)
            folder = os.path.dirname(path)
            if os.path.isdir(folder):
                self._last_input_dir = folder
            added += 1
        self.status_label.setText(tr("tools.elevation_raster.input_count").format(count=self.input_list.count()))
        if added and self.auto_extent_check.isChecked():
            self._refresh_input_extents_auto()

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("tools.elevation_raster.dialog_add_files"),
            self._initial_input_dir(),
            tr("tools.elevation_raster.las_filter"),
        )
        self._add_input_paths(paths)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("tools.elevation_raster.dialog_add_folder"),
            self._initial_input_dir(),
        )
        if not folder:
            return
        self._last_input_dir = folder
        paths = []
        for filename in os.listdir(folder):
            path = os.path.join(folder, filename)
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in (".las", ".laz"):
                paths.append(path)
        self._add_input_paths(sorted(paths))

    def _remove_selected_inputs(self):
        for item in self.input_list.selectedItems():
            row = self.input_list.row(item)
            self.input_list.takeItem(row)
        self.status_label.setText(tr("tools.elevation_raster.input_count").format(count=self.input_list.count()))
        self._refresh_input_extents_after_list_change()

    def _clear_inputs(self):
        self.input_list.clear()
        self.status_label.setText(tr("tools.elevation_raster.input_count").format(count=0))
        self._clear_input_extents()

    def _browse_output(self):
        initial_dir = self._initial_output_dir()
        initial_path = self.output_path_edit.text().strip()
        if not initial_path and initial_dir:
            initial_path = os.path.join(initial_dir, tr("tools.elevation_raster.default_output_name"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("tools.elevation_raster.dialog_output"),
            initial_path,
            tr("tools.elevation_raster.tif_filter"),
        )
        if not path:
            return
        if not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        self.output_path_edit.setText(os.path.normpath(path))
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.isdir(folder):
            self._last_output_dir = folder

    def _ensure_extent_crs(self):
        project = QgsProject.instance()
        crs = project.crs()
        if crs and crs.isValid() and not crs.isGeographic():
            return crs
        dialog = QgsProjectionSelectionDialog(self)
        if crs and crs.isValid():
            try:
                dialog.setCrs(crs)
            except Exception:
                _om_record_ignored_exception(__name__, 1334)
        dialog.setWindowTitle(tr("tools.elevation_raster.extent_crs_title"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected_crs = dialog.crs()
        if not (selected_crs and selected_crs.isValid()):
            return None
        project.setCrs(selected_crs)
        return selected_crs

    def _refresh_canvas_after_extent_change(self):
        if not (self.dock and hasattr(self.dock, "iface")):
            return
        try:
            canvas = self.dock.iface.mapCanvas()
            if hasattr(canvas, "refreshAllLayers"):
                canvas.refreshAllLayers()
            canvas.refresh()
        except Exception:
            _om_record_ignored_exception(__name__, 1353)

    def _clear_input_extents(self):
        if not self._extent_layer_id:
            self._refresh_canvas_after_extent_change()
            return
        layer = QgsProject.instance().mapLayer(self._extent_layer_id)
        if layer:
            QgsProject.instance().removeMapLayer(layer.id())
        self._extent_layer_id = ""
        self._refresh_canvas_after_extent_change()

    def _refresh_input_extents_auto(self):
        if not self._input_paths():
            self._clear_input_extents()
            return
        self._show_input_extents(silent=True, zoom_to_extent=False)

    def _refresh_input_extents_after_list_change(self):
        if not self._input_paths():
            self._clear_input_extents()
            return
        if self.auto_extent_check.isChecked():
            self._refresh_input_extents_auto()
        else:
            self._clear_input_extents()

    def _auto_extent_toggled(self, checked):
        if checked:
            self._refresh_input_extents_auto()
        else:
            self._clear_input_extents()

    def _show_input_extents(self, silent=False, zoom_to_extent=True):
        input_paths = self._input_paths()
        if not input_paths:
            if not silent:
                QMessageBox.warning(self, tr("tools.elevation_raster.warning_title"), tr("tools.elevation_raster.error_no_input"))
            return
        crs = self._ensure_extent_crs()
        if not (crs and crs.isValid()):
            return
        features = []
        skipped = 0
        for path in input_paths:
            try:
                bounds = ElevationRasterTask("", [], "", 1.0, "max", "none", 0.0, "unlimited", 1.0, -9999.0)._read_las_bounds(path)
                points = [
                    QgsPointXY(bounds["minx"], bounds["miny"]),
                    QgsPointXY(bounds["maxx"], bounds["miny"]),
                    QgsPointXY(bounds["maxx"], bounds["maxy"]),
                    QgsPointXY(bounds["minx"], bounds["maxy"]),
                    QgsPointXY(bounds["minx"], bounds["miny"]),
                ]
                feature = QgsFeature()
                feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
                feature.setAttributes([os.path.splitext(os.path.basename(path))[0], path])
                features.append(feature)
            except Exception as e:
                skipped += 1
                QgsMessageLog.logMessage(
                    f"ELEVATION_RASTER_EXTENT_READ_FAILED file={os.path.basename(path)} error={e}",
                    "OrthoManager",
                    Qgis.MessageLevel.Warning,
                )
        if not features:
            self._clear_input_extents()
            if not silent:
                QMessageBox.warning(self, tr("tools.elevation_raster.warning_title"), tr("tools.elevation_raster.error_extent_failed"))
            self.status_label.setText(tr("tools.elevation_raster.error_extent_failed"))
            return
        self._clear_input_extents()
        layer = QgsVectorLayer(f"Polygon?crs={crs.authid()}", tr("tools.elevation_raster.extent_layer_name"), "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("name", QVariant.String),
                QgsField("path", QVariant.String),
            ]
        )
        layer.updateFields()
        provider.addFeatures(features)
        layer.updateExtents()
        symbol = QgsFillSymbol.createSimple(
            {
                "color": "255,140,0,25",
                "outline_color": "255,90,0,255",
                "outline_width": "0.5",
            }
        )
        layer.renderer().setSymbol(symbol)
        try:
            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = "name"
            text_format = QgsTextFormat()
            text_format.setSize(9)
            label_settings.setFormat(text_format)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
            layer.setLabelsEnabled(True)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_EXTENT_LABEL_SETUP_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        QgsProject.instance().addMapLayer(layer)
        self._extent_layer_id = layer.id()
        if self.dock and hasattr(self.dock, "iface"):
            try:
                canvas = self.dock.iface.mapCanvas()
                if zoom_to_extent:
                    canvas.setExtent(layer.extent())
                if hasattr(canvas, "refreshAllLayers"):
                    canvas.refreshAllLayers()
                canvas.refresh()
            except Exception:
                _om_record_ignored_exception(__name__, 1469)
        message = tr("tools.elevation_raster.extent_done").format(count=len(features))
        if skipped:
            message += " " + tr("tools.elevation_raster.extent_skipped").format(count=skipped)
        self.status_label.setText(message)

    def _validate(self):
        input_paths = self._input_paths()
        if not input_paths:
            return False, tr("tools.elevation_raster.error_no_input")
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            return False, tr("tools.elevation_raster.error_no_output")
        if not os.path.isdir(os.path.dirname(os.path.abspath(output_path))):
            return False, tr("tools.elevation_raster.error_output_dir")
        return True, ""

    def _set_busy(self, busy):
        self.add_files_button.setEnabled(not busy)
        self.add_folder_button.setEnabled(not busy)
        self.remove_selected_button.setEnabled(not busy)
        self.clear_inputs_button.setEnabled(not busy)
        self.show_extent_button.setEnabled(not busy)
        self.clear_extent_button.setEnabled(not busy)
        self.auto_extent_check.setEnabled(not busy)
        self.output_browse_button.setEnabled(not busy)
        self.resolution_spin.setEnabled(not busy)
        self.fill_distance_spin.setEnabled(not busy)
        self.tin_edge_combo.setEnabled(not busy)
        self.tin_edge_distance_spin.setEnabled(not busy)
        self.output_type_combo.setEnabled(not busy)
        self.fill_method_combo.setEnabled(not busy)
        self.auto_load_check.setEnabled(not busy)
        self.apply_selected_style_button.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _cancel(self):
        if self._task is not None:
            self.cancel_button.setEnabled(False)
            self.status_label.setText(tr("tools.elevation_raster.status_canceling"))
            self._task.cancel()

    def _projected_project_crs_wkt(self):
        crs = QgsProject.instance().crs()
        if not (crs and crs.isValid()):
            return ""
        try:
            if crs.isGeographic():
                return ""
        except Exception:
            _om_record_ignored_exception(__name__, 1520)
        try:
            return crs.toWkt() or ""
        except Exception:
            return ""

    def _run(self):
        ok, message = self._validate()
        if not ok:
            QMessageBox.warning(self, tr("tools.elevation_raster.warning_title"), message)
            return
        pdal_path = self.dock._pdal_exe_path() if hasattr(self.dock, "_pdal_exe_path") else "pdal"
        self.progress_bar.setValue(0)
        self.status_label.setText(tr("tools.elevation_raster.status_running"))
        self._set_busy(True)
        task = ElevationRasterTask(
            pdal_path=pdal_path,
            input_paths=self._input_paths(),
            output_path=self.output_path_edit.text().strip(),
            resolution=self.resolution_spin.value(),
            output_type=self.output_type_combo.currentData(),
            fill_method=self.fill_method_combo.currentData(),
            fill_distance=self.fill_distance_spin.value(),
            tin_edge_mode=self.tin_edge_combo.currentData(),
            tin_edge_distance=self.tin_edge_distance_spin.value(),
            nodata=-9999.0,
            fallback_crs_wkt=self._projected_project_crs_wkt(),
        )
        self._task = task
        task.finished_callback = self._task_finished
        task.progressChanged.connect(lambda value: self.progress_bar.setValue(int(value)))
        QgsApplication.taskManager().addTask(task)

    def _load_result_layer(self, output_path):
        layer_name = os.path.splitext(os.path.basename(output_path))[0]
        layer = QgsRasterLayer(output_path, layer_name, "gdal")
        if not layer.isValid():
            QMessageBox.warning(self, tr("tools.elevation_raster.warning_title"), tr("tools.elevation_raster.error_load_failed"))
            return
        layer.setCustomProperty(ELEVATION_RASTER_LAYER_PENDING_PROPERTY, True)
        self._apply_elevation_pseudocolor(layer)
        self._enable_elevation_hillshading(layer)
        QgsProject.instance().addMapLayer(layer)
        self._refresh_elevation_display_after_add(layer)
        layer.setCustomProperty(ELEVATION_RASTER_LAYER_PENDING_PROPERTY, False)
        layer.setCustomProperty(ELEVATION_RASTER_LAYER_APPLIED_PROPERTY, True)
        self._styled_elevation_layer_ids.add(layer.id())

    def _selected_qgis_raster_layer(self):
        iface = getattr(self.dock, "iface", None)
        if iface is not None:
            try:
                layer = iface.activeLayer()
                if isinstance(layer, QgsRasterLayer):
                    return layer
            except Exception:
                _om_record_ignored_exception(__name__, 1576)
        selected = []
        if iface is not None:
            try:
                selected = iface.layerTreeView().selectedLayers()
            except Exception:
                selected = []
        for layer in selected:
            if isinstance(layer, QgsRasterLayer):
                return layer
        return None

    def _apply_style_to_selected_raster(self):
        layer = self._selected_qgis_raster_layer()
        if layer is None or not layer.isValid():
            QMessageBox.warning(
                self,
                tr("tools.elevation_raster.warning_title"),
                tr("tools.elevation_raster.error_no_selected_raster"),
            )
            return
        try:
            self._apply_elevation_pseudocolor(layer)
            self._enable_elevation_hillshading(layer)
            self._refresh_elevation_display_after_add(layer)
            self._styled_elevation_layer_ids.add(layer.id())
            layer.setCustomProperty(ELEVATION_RASTER_LAYER_APPLIED_PROPERTY, True)
            self.status_label.setText(tr("tools.elevation_raster.status_style_applied").format(name=layer.name()))
            if hasattr(self.dock, "set_status"):
                self.dock.set_status(tr("tools.elevation_raster.status_style_applied").format(name=layer.name()))
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_SELECTED_STYLE_APPLIED layer={layer.name()} source={self._layer_source_path(layer)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                tr("tools.elevation_raster.warning_title"),
                tr("tools.elevation_raster.error_style_apply_failed").format(error=e),
            )

    def _enable_elevation_hillshading(self, layer):
        try:
            props = layer.elevationProperties()
            if props is not None:
                props.setEnabled(True)
                props.setBandNumber(1)
                props.setMode(Qgis.RasterElevationMode.RepresentsElevationSurface)

            renderer = QgsElevationShadingRenderer()
            renderer.setActive(True)
            renderer.setActiveHillshading(True)
            renderer.setLightAzimuth(300.0)
            renderer.setLightAltitude(40.0)
            renderer.setHillshadingZFactor(1.0)
            renderer.setHillshadingMultidirectional(False)
            QgsProject.instance().setElevationShadingRenderer(renderer)
            QgsMessageLog.logMessage(
                "ELEVATION_RASTER_PROJECT_HILLSHADING_APPLIED azimuth=300 altitude=40 z_factor=1.0 band=1",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_PROJECT_HILLSHADING_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _apply_elevation_display_smoothing(self, layer):
        try:
            stage_ok = False
            if hasattr(layer, "setResamplingStage"):
                layer.setResamplingStage(Qgis.RasterResamplingStage.ResampleFilter)
                stage_ok = True

            filter_ok = False
            resample_filter = layer.resampleFilter()
            if resample_filter is not None:
                resample_filter.setZoomedInResampler(QgsCubicRasterResampler())
                resample_filter.setZoomedOutResampler(QgsCubicRasterResampler())
                resample_filter.setMaxOversampling(2.0)
                filter_ok = True

            provider_ok = False
            provider = layer.dataProvider()
            if provider is not None:
                if hasattr(provider, "setZoomedInResamplingMethod"):
                    provider.setZoomedInResamplingMethod(Qgis.RasterResamplingMethod.Cubic)
                    provider_ok = True
                if hasattr(provider, "setZoomedOutResamplingMethod"):
                    provider.setZoomedOutResamplingMethod(Qgis.RasterResamplingMethod.Cubic)
                    provider_ok = True
                if hasattr(provider, "setMaxOversampling"):
                    provider.setMaxOversampling(2.0)
                    provider_ok = True
                if hasattr(provider, "enableProviderResampling"):
                    provider.enableProviderResampling(True)
                    provider_ok = True

            brightness_filter = layer.brightnessFilter()
            if brightness_filter is not None:
                brightness_filter.setBrightness(50)

            renderer_rebuilt = self._rebuild_elevation_raster_renderer(layer)
            self._notify_elevation_display_changed(layer)
            QgsMessageLog.logMessage(
                "ELEVATION_RASTER_DISPLAY_SMOOTHING_APPLIED zoom_in=cubic zoom_out=cubic "
                f"oversampling=2.0 brightness=50 stage={int(stage_ok)} filter={int(filter_ok)} "
                f"provider={int(provider_ok)} renderer_rebuilt={int(renderer_rebuilt)}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_DISPLAY_SMOOTHING_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _rebuild_elevation_raster_renderer(self, layer):
        try:
            renderer = layer.renderer()
            if renderer is None or not hasattr(renderer, "clone"):
                return False
            cloned = renderer.clone()
            if cloned is None:
                return False
            layer.setRenderer(cloned)
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_RENDERER_REBUILD_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
            return False

    def _refresh_elevation_display_after_add(self, layer):
        try:
            self._apply_elevation_display_smoothing(layer)
            QTimer.singleShot(250, lambda lyr=layer: self._delayed_elevation_display_refresh(lyr))
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_DISPLAY_REFRESH_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _delayed_elevation_display_refresh(self, layer):
        try:
            if layer is None or not layer.isValid():
                return
            self._apply_elevation_display_smoothing(layer)
            QgsMessageLog.logMessage(
                "ELEVATION_RASTER_DISPLAY_REFRESH_APPLIED delay_ms=250",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except RuntimeError:
            return
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_DISPLAY_REFRESH_DELAYED_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _notify_elevation_display_changed(self, layer):
        try:
            if hasattr(layer, "emitStyleChanged"):
                layer.emitStyleChanged()
            layer.triggerRepaint(False)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_LAYER_REFRESH_NOTIFY_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )
        self._refresh_canvas_for_elevation_display()

    def _refresh_canvas_for_elevation_display(self):
        if not (self.dock and hasattr(self.dock, "iface")):
            return
        try:
            canvas = self.dock.iface.mapCanvas()
            if canvas is None:
                return
            if hasattr(canvas, "clearCache"):
                canvas.clearCache()
            if hasattr(canvas, "refreshAllLayers"):
                canvas.refreshAllLayers()
            if hasattr(canvas, "layerRepaintRequested"):
                canvas.layerRepaintRequested(False)
            canvas.refresh()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_CANVAS_REFRESH_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _raster_min_max_with_gdal(self, source):
        if np is None:
            return None
        path = (source or "").split("|", 1)[0].strip()
        if not path or not os.path.exists(path):
            return None
        old_pam = gdal.GetConfigOption("GDAL_PAM_ENABLED")
        dataset = None
        try:
            gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
            dataset = gdal.Open(path, gdal.GA_ReadOnly)
            if dataset is None or dataset.RasterCount < 1:
                return None
            band = dataset.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            width = dataset.RasterXSize
            height = dataset.RasterYSize
            block_x, block_y = band.GetBlockSize()
            block_x = max(1, int(block_x or 512))
            block_y = max(1, int(block_y or 512))
            min_value = None
            max_value = None
            for y in range(0, height, block_y):
                y_size = min(block_y, height - y)
                for x in range(0, width, block_x):
                    x_size = min(block_x, width - x)
                    array = band.ReadAsArray(x, y, x_size, y_size)
                    if array is None:
                        continue
                    array = array.astype(np.float64, copy=False)
                    mask = np.isfinite(array)
                    if nodata is not None:
                        try:
                            mask &= ~np.isclose(array, float(nodata))
                        except Exception:
                            _om_record_ignored_exception(__name__, 1814)
                    if not np.any(mask):
                        continue
                    values = array[mask]
                    block_min = float(np.min(values))
                    block_max = float(np.max(values))
                    min_value = block_min if min_value is None else min(min_value, block_min)
                    max_value = block_max if max_value is None else max(max_value, block_max)
            if min_value is None or max_value is None:
                return None
            return min_value, max_value
        finally:
            dataset = None
            gdal.SetConfigOption("GDAL_PAM_ENABLED", old_pam)

    def _apply_elevation_pseudocolor(self, layer):
        try:
            provider = layer.dataProvider()
            min_max = self._raster_min_max_with_gdal(layer.source())
            if not min_max:
                return
            min_value, max_value = min_max
            if not math.isfinite(min_value) or not math.isfinite(max_value) or min_value >= max_value:
                return
            color_ramp = QgsGradientColorRamp(
                QColor(35, 70, 170),
                QColor(210, 45, 30),
                False,
                [
                    QgsGradientStop(0.25, QColor(0, 170, 150)),
                    QgsGradientStop(0.50, QColor(120, 190, 40)),
                    QgsGradientStop(0.75, QColor(235, 190, 45)),
                ],
            )
            renderer = QgsSingleBandPseudoColorRenderer(provider, 1)
            renderer.setClassificationMin(min_value)
            renderer.setClassificationMax(max_value)
            renderer.createShader(
                color_ramp,
                Qgis.ShaderInterpolationMethod.Linear,
                Qgis.ShaderClassificationMethod.Continuous,
                5,
                False,
                layer.extent(),
            )
            layer.setRenderer(renderer)
            layer.triggerRepaint()
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_STYLE_APPLIED type=pseudocolor min_z={min_value:.3f} max_z={max_value:.3f}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ELEVATION_RASTER_STYLE_FAILED error={e}",
                "OrthoManager",
                Qgis.MessageLevel.Warning,
            )

    def _done_status_text(self, task):
        summary = getattr(task, "quality_summary", {}) or {}
        if not summary:
            return tr("tools.elevation_raster.status_done").format(seconds=task.elapsed_sec)
        min_z = summary.get("min_z")
        max_z = summary.get("max_z")
        if min_z is None or max_z is None:
            return tr("tools.elevation_raster.status_done_quality_no_valid").format(seconds=task.elapsed_sec)
        return tr("tools.elevation_raster.status_done_quality").format(
            seconds=task.elapsed_sec,
            nodata_percent=float(summary.get("nodata_percent", 0.0)),
            min_z=float(min_z),
            max_z=float(max_z),
        )

    def _task_finished(self, task, result):
        self._set_busy(False)
        self.progress_bar.setValue(100 if result else 0)
        if result:
            if self.auto_load_check.isChecked():
                self._load_result_layer(task.output_path)
            status_text = self._done_status_text(task)
            self.status_label.setText(status_text)
            if hasattr(self.dock, "set_status"):
                self.dock.set_status(status_text)
        else:
            msg = task.error_msg or tr("tools.elevation_raster.status_failed")
            if task.isCanceled() or msg == "標高ラスタ作成をキャンセルしました。":
                self.status_label.setText(tr("tools.elevation_raster.status_canceled"))
            else:
                self.status_label.setText(tr("tools.elevation_raster.status_failed"))
                QMessageBox.critical(self, tr("tools.elevation_raster.warning_title"), msg)
            if hasattr(self.dock, "set_status"):
                self.dock.set_status(self.status_label.text())
        self._task = None

    def refresh_texts(self):
        self.title_label.setText(tr("tools.elevation_raster.title"))
        self.note_label.setText(tr("tools.elevation_raster.note"))
        self.input_group.setTitle(tr("tools.elevation_raster.input_group"))
        self.add_files_button.setText(tr("tools.elevation_raster.add_files"))
        self.add_folder_button.setText(tr("tools.elevation_raster.add_folder"))
        self.remove_selected_button.setText(tr("tools.elevation_raster.remove_selected"))
        self.clear_inputs_button.setText(tr("tools.elevation_raster.clear_inputs"))
        self.show_extent_button.setText(tr("tools.elevation_raster.show_extent"))
        self.clear_extent_button.setText(tr("tools.elevation_raster.clear_extent"))
        self.auto_extent_check.setText(tr("tools.elevation_raster.auto_extent"))
        self.output_group.setTitle(tr("tools.elevation_raster.output_group"))
        self.output_browse_button.setText(tr("tools.elevation_raster.output_browse"))
        self.resolution_label.setText(tr("tools.elevation_raster.resolution"))
        self.output_type_label.setText(tr("tools.elevation_raster.output_type"))
        self.tin_edge_label.setText(tr("tools.elevation_raster.tin_edge"))
        self.tin_edge_distance_label.setText(tr("tools.elevation_raster.tin_edge_distance"))
        self.fill_method_label.setText(tr("tools.elevation_raster.fill_method"))
        self.fill_distance_label.setText(tr("tools.elevation_raster.fill_distance"))
        self.fill_distance_spin.setSpecialValueText(tr("tools.elevation_raster.fill_distance_auto"))
        self.apply_selected_style_button.setText(tr("tools.elevation_raster.apply_selected_style"))
        self.apply_selected_style_button.setToolTip(tr("tools.elevation_raster.apply_selected_style_tooltip"))
        tin_edge_tooltip = tr("tools.elevation_raster.tin_edge_tooltip")
        self.tin_edge_label.setToolTip(tin_edge_tooltip)
        self.tin_edge_combo.setToolTip(tin_edge_tooltip)
        tin_edge_distance_tooltip = tr("tools.elevation_raster.tin_edge_distance_tooltip")
        self.tin_edge_distance_label.setToolTip(tin_edge_distance_tooltip)
        self.tin_edge_distance_spin.setToolTip(tin_edge_distance_tooltip)
        labels = {
            "tin": tr("tools.elevation_raster.output_type_tin"),
            "max": tr("tools.elevation_raster.output_type_max"),
            "min": tr("tools.elevation_raster.output_type_min"),
            "mean": tr("tools.elevation_raster.output_type_mean"),
        }
        for index in range(self.output_type_combo.count()):
            value = self.output_type_combo.itemData(index)
            self.output_type_combo.setItemText(index, labels.get(value, str(value)))
        tin_edge_labels = {
            "unlimited": tr("tools.elevation_raster.tin_edge_unlimited"),
            "auto": tr("tools.elevation_raster.tin_edge_auto"),
            "manual": tr("tools.elevation_raster.tin_edge_manual"),
        }
        tin_edge_tooltips = {
            "unlimited": tr("tools.elevation_raster.tin_edge_unlimited_tooltip"),
            "auto": tr("tools.elevation_raster.tin_edge_auto_tooltip"),
            "manual": tr("tools.elevation_raster.tin_edge_manual_tooltip"),
        }
        for index in range(self.tin_edge_combo.count()):
            value = self.tin_edge_combo.itemData(index)
            self.tin_edge_combo.setItemText(index, tin_edge_labels.get(value, str(value)))
            self.tin_edge_combo.setItemData(index, tin_edge_tooltips.get(value, ""), Qt.ItemDataRole.ToolTipRole)
        fill_labels = {
            "none": tr("tools.elevation_raster.fill_method_none"),
            "nearest": tr("tools.elevation_raster.fill_method_nearest"),
        }
        for index in range(self.fill_method_combo.count()):
            value = self.fill_method_combo.itemData(index)
            self.fill_method_combo.setItemText(index, fill_labels.get(value, str(value)))
        self.auto_load_check.setText(tr("tools.elevation_raster.auto_load"))
        self.run_button.setText(tr("tools.elevation_raster.run"))
        self.cancel_button.setText(tr("tools.elevation_raster.cancel"))
        self._update_method_controls()
        if not self.status_label.text():
            self.status_label.setText(tr("tools.elevation_raster.input_count").format(count=self.input_list.count()))

    def _update_method_controls(self):
        self.tin_edge_label.setVisible(True)
        self.tin_edge_combo.setVisible(True)
        use_tin_manual_distance = self.tin_edge_combo.currentData() == "manual"
        self.tin_edge_distance_label.setVisible(use_tin_manual_distance)
        self.tin_edge_distance_spin.setVisible(use_tin_manual_distance)
        self.fill_method_label.setVisible(False)
        self.fill_method_combo.setVisible(False)
        self.fill_distance_label.setVisible(False)
        self.fill_distance_spin.setVisible(False)
