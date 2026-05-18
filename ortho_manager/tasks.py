import os
import datetime
import xml.etree.ElementTree as ET
import shutil
import time
import json
import subprocess
import sys
import tempfile
from qgis.core import QgsTask, QgsMessageLog, Qgis
from qgis.PyQt.QtCore import pyqtSignal, QObject

try:
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    ogr.UseExceptions()
except ImportError:
    pass

class TaskSignals(QObject):
    # シグナルに一時ファイルパスを追加
    completed = pyqtSignal(bool, str, str, str, object)


def find_external_vrt_engine_path():
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("ORTHO_MANAGER_VRT_ENGINE", ""),
        os.path.join(plugin_dir, "private_engine", "vrt_engine.exe"),
        os.path.join(plugin_dir, "private_engine", "vrt_engine_cli.py"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def find_qgis_python_runner():
    env_runner = os.environ.get("ORTHO_MANAGER_QGIS_PYTHON", "")
    if env_runner and os.path.exists(env_runner):
        return env_runner

    current_exe = sys.executable or ""
    if current_exe and os.path.exists(current_exe) and os.path.basename(current_exe).lower().startswith("python"):
        return current_exe

    candidates = [
        r"C:\Program Files\QGIS 4.0.2\bin\python-qgis.bat",
        r"C:\Program Files\QGIS 4.0.1\bin\python-qgis.bat",
        r"C:\Program Files\QGIS 3.44.9\bin\python-qgis.bat",
        r"C:\Program Files\QGIS 3.40.8\bin\python-qgis.bat",
        r"C:\Program Files\QGIS 3.32.3\bin\python-qgis.bat",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return ""

def build_external_vrt_engine_command(engine_path, input_path, result_path):
    ext = os.path.splitext(engine_path)[1].lower()
    if ext == ".py":
        runner = find_qgis_python_runner()
        if not runner:
            raise Exception("外部VRTエンジン用のQGIS Pythonが見つかりません")
        return [runner, engine_path, "--input", input_path, "--result", result_path]
    return [engine_path, "--input", input_path, "--result", result_path]


def run_external_vrt_engine_sync(tif_list, vrt_path, gpkg_path, rebuild_gpkg, engine_path):
    work_dir = tempfile.mkdtemp(prefix="ortho_manager_v3_sync_")
    input_path = os.path.join(work_dir, "input.json")
    result_path = os.path.join(work_dir, "result.json")
    temp_vrt = vrt_path + ".tmp.vrt"
    temp_gpkg = gpkg_path + ".tmp.gpkg"
    total_start = time.perf_counter()
    timing = {}

    try:
        request = {
            "version": "3.0",
            "action": "sync_vrt_gpkg",
            "vrt_path": vrt_path,
            "gpkg_path": gpkg_path,
            "temp_vrt": temp_vrt,
            "temp_gpkg": temp_gpkg,
            "tif_list": list(tif_list),
            "rebuild_gpkg": rebuild_gpkg,
        }
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(request, f, ensure_ascii=False, indent=2)

        cmd = build_external_vrt_engine_command(engine_path, input_path, result_path)
        QgsMessageLog.logMessage(
            f"VRT_ENGINE_EXTERNAL_START engine={engine_path}",
            "OrthoManager",
            Qgis.MessageLevel.Info,
        )

        creationflags = 0x08000000 if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        stdout, stderr = proc.communicate()

        if stdout.strip():
            QgsMessageLog.logMessage(stdout.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Info)
        if stderr.strip():
            QgsMessageLog.logMessage(stderr.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Warning)

        data = {}
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        success = bool(data.get("success")) and proc.returncode == 0
        error_msg = data.get("error") or (stderr.strip() if proc.returncode else "")
        temp_vrt = data.get("temp_vrt") or temp_vrt
        temp_gpkg = data.get("temp_gpkg") or temp_gpkg
        timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
        timing["engine"] = "external"
        timing["engine_path"] = engine_path
        timing.setdefault("task_total_sec", time.perf_counter() - total_start)
        return success, error_msg, temp_vrt, temp_gpkg, timing
    except Exception as e:
        timing["engine"] = "external"
        timing["engine_path"] = engine_path
        timing["task_total_sec"] = time.perf_counter() - total_start
        QgsMessageLog.logMessage(f"外部VRTエンジン実行エラー: {e}", "OrthoManager", Qgis.MessageLevel.Critical)
        return False, str(e), temp_vrt, temp_gpkg, timing
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

class ExternalVrtEngineTask(QgsTask):
    def __init__(self, tif_list, vrt_path, gpkg_path, rebuild_gpkg, engine_path):
        task_name = f"OrthoManager v3.3: 外部VRTエンジン ({datetime.datetime.now().strftime('%H:%M:%S')})"
        super().__init__(task_name, QgsTask.Flag.CanCancel)
        self.tif_list = list(tif_list)
        self.vrt_path = vrt_path
        self.gpkg_path = gpkg_path
        self.rebuild_gpkg = rebuild_gpkg
        self.engine_path = engine_path
        self.signals = TaskSignals()
        self.error_msg = ""
        self.success = False
        self.temp_vrt = self.vrt_path + ".tmp.vrt"
        self.temp_gpkg = self.gpkg_path + ".tmp.gpkg"
        self.timing = {}

    def _build_command(self, input_path, result_path):
        return build_external_vrt_engine_command(self.engine_path, input_path, result_path)

    def run(self):
        work_dir = tempfile.mkdtemp(prefix="ortho_manager_v3_")
        input_path = os.path.join(work_dir, "input.json")
        result_path = os.path.join(work_dir, "result.json")
        total_start = time.perf_counter()

        try:
            request = {
                "version": "3.0",
                "action": "sync_vrt_gpkg",
                "vrt_path": self.vrt_path,
                "gpkg_path": self.gpkg_path,
                "temp_vrt": self.temp_vrt,
                "temp_gpkg": self.temp_gpkg,
                "tif_list": self.tif_list,
                "rebuild_gpkg": self.rebuild_gpkg,
            }
            with open(input_path, "w", encoding="utf-8") as f:
                json.dump(request, f, ensure_ascii=False, indent=2)

            cmd = self._build_command(input_path, result_path)
            QgsMessageLog.logMessage(
                f"VRT_ENGINE_EXTERNAL_START engine={self.engine_path}",
                "OrthoManager",
                Qgis.MessageLevel.Info,
            )

            creationflags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            self.setProgress(5)
            while proc.poll() is None:
                if self.isCanceled():
                    proc.kill()
                    self.error_msg = "外部VRTエンジンをキャンセルしました"
                    return False
                elapsed = time.perf_counter() - total_start
                self.setProgress(min(90, 5 + int(elapsed) % 85))
                time.sleep(0.2)

            stdout, stderr = proc.communicate()
            if stdout.strip():
                QgsMessageLog.logMessage(stdout.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Info)
            if stderr.strip():
                QgsMessageLog.logMessage(stderr.strip()[-2000:], "OrthoManager", Qgis.MessageLevel.Warning)

            data = {}
            if os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            self.success = bool(data.get("success")) and proc.returncode == 0
            self.error_msg = data.get("error") or (stderr.strip() if proc.returncode else "")
            self.temp_vrt = data.get("temp_vrt") or self.temp_vrt
            self.temp_gpkg = data.get("temp_gpkg") or self.temp_gpkg
            self.timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
            self.timing["engine"] = "external"
            self.timing["engine_path"] = self.engine_path
            self.timing.setdefault("task_total_sec", time.perf_counter() - total_start)
            self.setProgress(100 if self.success else 0)
            return self.success

        except Exception as e:
            self.error_msg = str(e)
            self.success = False
            self.timing["engine"] = "external"
            self.timing["task_total_sec"] = time.perf_counter() - total_start
            QgsMessageLog.logMessage(f"外部VRTエンジン実行エラー: {e}", "OrthoManager", Qgis.MessageLevel.Critical)
            return False
        finally:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    def finished(self, result):
        self.signals.completed.emit(self.success, self.error_msg, self.temp_vrt, self.temp_gpkg, self.timing)


class BuildVrtAndGpkgTask(QgsTask):
    def __init__(self, tif_list, vrt_path, gpkg_path, rebuild_gpkg):
        task_name = f"OrthoManager: VRT生成 ({datetime.datetime.now().strftime('%H:%M:%S')})"
        super().__init__(task_name, QgsTask.Flag.CanCancel)
        self.tif_list = tif_list
        self.vrt_path = vrt_path
        self.gpkg_path = gpkg_path
        self.rebuild_gpkg = rebuild_gpkg
        self.signals = TaskSignals()
        self.error_msg = ""
        self.success = False
        self.timing = {}
        
        # ロックを回避するための一時ファイル
        self.temp_vrt = self.vrt_path + ".tmp.vrt"
        self.temp_gpkg = self.gpkg_path + ".tmp.gpkg"

    def _get_existing_tifs_from_vrt(self, vrt_path):
        """VRTのXMLから登録されているTIFリストを高速に抽出する"""
        tifs = set()
        try:
            tree = ET.parse(vrt_path)
            root = tree.getroot()
            for src in root.findall(".//SourceFilename"):
                if src.text:
                    path = src.text
                    if src.get("relativeToVRT") == "1":
                        path = os.path.join(os.path.dirname(vrt_path), path)
                    tifs.add(os.path.normpath(path))
        except Exception as e:
            QgsMessageLog.logMessage(f"既存VRTパースエラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
        return tifs

    def _fast_update_vrt(self, existing_vrt_path, target_vrt_path, tifs_to_add, tifs_to_delete):
        """GDALを迂回し、XMLマージでVRTを超高速に差分更新する"""
        tree = ET.parse(existing_vrt_path)
        root = tree.getroot()
        
        gt_elem = root.find("GeoTransform")
        if gt_elem is None:
            raise Exception("GeoTransformが見つかりません")
            
        vrt_gt = [float(x) for x in gt_elem.text.strip().split(',')]
        pixel_width = vrt_gt[1]
        pixel_height = vrt_gt[5]
        
        vrt_minx = vrt_gt[0]
        vrt_maxy = vrt_gt[3]
        vrt_maxx = vrt_minx + int(root.attrib.get('rasterXSize', 0)) * pixel_width
        vrt_miny = vrt_maxy + int(root.attrib.get('rasterYSize', 0)) * pixel_height

        # 1. 削除処理 (XMLタグを抜くだけ)
        if tifs_to_delete:
            tifs_to_delete_norm = {os.path.normpath(p) for p in tifs_to_delete}
            for band in root.findall("VRTRasterBand"):
                for src in band.findall("SimpleSource") + band.findall("ComplexSource"):
                    fname_elem = src.find("SourceFilename")
                    if fname_elem is not None:
                        src_path = fname_elem.text
                        if fname_elem.get("relativeToVRT") == "1":
                            src_path = os.path.join(os.path.dirname(existing_vrt_path), src_path)
                        if os.path.normpath(src_path) in tifs_to_delete_norm:
                            band.remove(src)

        # 2. 追加処理（追加分だけミニVRTを作り、XMLを合成する）
        if tifs_to_add:
            diff_vrt_path = target_vrt_path + ".diff.vrt"
            opts = gdal.BuildVRTOptions(resolution="highest", addAlpha=True, hideNodata=True)
            ds = gdal.BuildVRT(diff_vrt_path, list(tifs_to_add), options=opts)
            if ds is None:
                raise Exception("差分VRTの構築に失敗")
            ds.FlushCache()
            ds = None
            
            diff_tree = ET.parse(diff_vrt_path)
            diff_root = diff_tree.getroot()
            diff_gt_elem = diff_root.find("GeoTransform")
            diff_gt = [float(x) for x in diff_gt_elem.text.strip().split(',')]
            
            diff_minx = diff_gt[0]
            diff_maxy = diff_gt[3]
            diff_maxx = diff_minx + int(diff_root.attrib.get('rasterXSize', 0)) * pixel_width
            diff_miny = diff_maxy + int(diff_root.attrib.get('rasterYSize', 0)) * pixel_height
            
            # 全体の表示枠（Bounding Box）を拡張
            new_minx = min(vrt_minx, diff_minx)
            new_maxy = max(vrt_maxy, diff_maxy)
            new_maxx = max(vrt_maxx, diff_maxx)
            new_miny = min(vrt_miny, diff_miny)
            
            new_vrt_gt = [new_minx, pixel_width, 0, new_maxy, 0, pixel_height]
            new_raster_x_size = int(round((new_maxx - new_minx) / pixel_width))
            new_raster_y_size = int(round((new_miny - new_maxy) / pixel_height))
            
            # 座標オフセットのシフト量を計算
            shift_x = int(round((vrt_gt[0] - new_vrt_gt[0]) / pixel_width))
            shift_y = int(round((vrt_gt[3] - new_vrt_gt[3]) / pixel_height))
            
            diff_shift_x = int(round((diff_gt[0] - new_vrt_gt[0]) / pixel_width))
            diff_shift_y = int(round((diff_gt[3] - new_vrt_gt[3]) / pixel_height))
            
            root.set('rasterXSize', str(new_raster_x_size))
            root.set('rasterYSize', str(new_raster_y_size))
            gt_elem.text = ", ".join(map(str, new_vrt_gt))
            
            for band in root.findall("VRTRasterBand"):
                band_idx = band.get('band')
                
                # 既存ソースの位置をシフト
                if shift_x != 0 or shift_y != 0:
                    for src in band.findall("SimpleSource") + band.findall("ComplexSource"):
                        dst_rect = src.find("DstRect")
                        if dst_rect is not None:
                            dst_rect.set("xOff", str(float(dst_rect.get("xOff")) + shift_x))
                            dst_rect.set("yOff", str(float(dst_rect.get("yOff")) + shift_y))
                            
                # 差分VRTからタグをコピー
                diff_band = diff_root.find(f"VRTRasterBand[@band='{band_idx}']")
                if diff_band is not None:
                    for src in diff_band.findall("SimpleSource") + diff_band.findall("ComplexSource"):
                        dst_rect = src.find("DstRect")
                        if dst_rect is not None:
                            dst_rect.set("xOff", str(float(dst_rect.get("xOff")) + diff_shift_x))
                            dst_rect.set("yOff", str(float(dst_rect.get("yOff")) + diff_shift_y))
                            
                        fname_elem = src.find("SourceFilename")
                        if fname_elem is not None and fname_elem.get("relativeToVRT") == "1":
                            abs_path = os.path.join(os.path.dirname(diff_vrt_path), fname_elem.text)
                            fname_elem.text = os.path.normpath(abs_path)
                            fname_elem.set("relativeToVRT", "0")
                        band.append(src)
            try:
                os.remove(diff_vrt_path)
            except: pass

        # 更新されたXMLを保存
        tree.write(target_vrt_path, encoding="utf-8", xml_declaration=False)

    def run(self):
        total_start = time.perf_counter()
        old_pam_enabled = None
        try:
            QgsMessageLog.logMessage(f"タスク[{self.description()}] 開始...", "OrthoManager", Qgis.MessageLevel.Info)
            old_pam_enabled = gdal.GetConfigOption('GDAL_PAM_ENABLED')
            gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
            self.timing["pam_disabled"] = True
            QgsMessageLog.logMessage("VRT生成中はGDAL_PAM_ENABLED=NOでaux.xml生成を抑制します", "OrthoManager", Qgis.MessageLevel.Info)
            self.setProgress(2)
            if self.isCanceled(): return False

            target_tifs_norm = set(os.path.normpath(p) for p in self.tif_list)
            
            fast_update_success = False
            tifs_to_add = set()
            tifs_to_delete = set()
            
            # --- 1. 超高速差分更新のトライ ---
            vrt_update_start = time.perf_counter()
            update_mode = "変更なしコピー"
            if os.path.exists(self.vrt_path):
                existing_tifs = self._get_existing_tifs_from_vrt(self.vrt_path)
                if existing_tifs:
                    tifs_to_add = target_tifs_norm - existing_tifs
                    tifs_to_delete = existing_tifs - target_tifs_norm
                    
                    if tifs_to_add or tifs_to_delete:
                        QgsMessageLog.logMessage(f"XML差分更新を試行します (追加:{len(tifs_to_add)} 削除:{len(tifs_to_delete)})", "OrthoManager", Qgis.MessageLevel.Info)
                        try:
                            self._fast_update_vrt(self.vrt_path, self.temp_vrt, tifs_to_add, tifs_to_delete)
                            fast_update_success = True
                            update_mode = f"XML差分更新（追加:{len(tifs_to_add)} 削除:{len(tifs_to_delete)}）"
                            QgsMessageLog.logMessage("XML差分更新に成功しました (超高速化)", "OrthoManager", Qgis.MessageLevel.Success)
                        except Exception as e:
                            QgsMessageLog.logMessage(f"XML差分更新に失敗、フルビルドに移行します: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
                    elif not tifs_to_add and not tifs_to_delete:
                        # 変更がない場合は既存をコピーするだけ
                        shutil.copy2(self.vrt_path, self.temp_vrt)
                        fast_update_success = True

            # --- 2. 従来のフルビルド (フォールバック / 新規作成時) ---
            if not fast_update_success:
                update_mode = "フルビルド"
                QgsMessageLog.logMessage("VRTのフルビルドを実行します...", "OrthoManager", Qgis.MessageLevel.Info)
                def gdal_progress(complete, message, user_data):
                    if self.isCanceled(): return 0
                    self.setProgress(int(5 + (complete * 75))) 
                    return 1

                opts = gdal.BuildVRTOptions(resolution="highest", addAlpha=True, hideNodata=True, callback=gdal_progress)
                ds = gdal.BuildVRT(self.temp_vrt, self.tif_list, options=opts)
                if ds is None:
                    raise Exception("VRTの生成に失敗しました。")
                vrt_crs_wkt = ds.GetProjection()
                ds.FlushCache()
                ds = None
            else:
                self.setProgress(80)
                ds = gdal.Open(self.temp_vrt)
                vrt_crs_wkt = ds.GetProjection() if ds else ""
                ds = None
            self.timing["vrt_update_sec"] = time.perf_counter() - vrt_update_start
            self.timing["vrt_update_mode"] = update_mode
            self.timing["tif_count"] = len(self.tif_list)

            if self.isCanceled(): return False

            # --- 3. GPKG(タイル図郭)の同期 ---
            gpkg_start = time.perf_counter()
            if self.rebuild_gpkg:
                QgsMessageLog.logMessage("GPKG(図郭ポリゴン)の同期を開始します...", "OrthoManager", Qgis.MessageLevel.Info)
                
                gpkg_exists = os.path.exists(self.gpkg_path)
                existing_tifs_gpkg = set()

                if gpkg_exists:
                    try:
                        shutil.copy2(self.gpkg_path, self.temp_gpkg)
                        ds_gpkg = ogr.Open(self.temp_gpkg, 0)
                        if ds_gpkg:
                            layer = ds_gpkg.GetLayerByName("tiles")
                            if layer:
                                for feat in layer:
                                    loc = feat.GetField("location")
                                    if loc: existing_tifs_gpkg.add(os.path.normpath(loc))
                        ds_gpkg = None
                    except Exception as e:
                        QgsMessageLog.logMessage(f"GPKG読取エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
                        gpkg_exists = False
                        existing_tifs_gpkg = set()

                gpkg_tifs_to_add = target_tifs_norm - existing_tifs_gpkg
                gpkg_tifs_to_delete = existing_tifs_gpkg - target_tifs_norm

                features_data = []
                if gpkg_tifs_to_add:
                    features_data = self._parse_vrt_xml(self.temp_vrt, gpkg_tifs_to_add)
                    if self.isCanceled(): return False

                self.setProgress(90)

                if not gpkg_exists and features_data:
                    self._create_gpkg(features_data, vrt_crs_wkt)
                elif gpkg_exists and (gpkg_tifs_to_add or gpkg_tifs_to_delete):
                    self._update_gpkg(features_data, gpkg_tifs_to_delete)
            self.timing["gpkg_sec"] = time.perf_counter() - gpkg_start

            self.setProgress(100)
            self.success = True
            self.timing["task_total_sec"] = time.perf_counter() - total_start
            return True

        except Exception as e:
            self.error_msg = str(e)
            self.success = False
            self.timing["task_total_sec"] = time.perf_counter() - total_start
            if "vrt_update_sec" not in self.timing and "vrt_update_start" in locals():
                self.timing["vrt_update_sec"] = time.perf_counter() - vrt_update_start
            if "gpkg_sec" not in self.timing and "gpkg_start" in locals():
                self.timing["gpkg_sec"] = time.perf_counter() - gpkg_start
            QgsMessageLog.logMessage(f"タスク実行中エラー: {e}", "OrthoManager", Qgis.MessageLevel.Critical)
            return False
        finally:
            try:
                if old_pam_enabled is None:
                    gdal.SetConfigOption('GDAL_PAM_ENABLED', None)
                else:
                    gdal.SetConfigOption('GDAL_PAM_ENABLED', old_pam_enabled)
            except Exception:
                pass

    def _parse_vrt_xml(self, vrt_path, target_tifs_norm):
        features_data = []
        try:
            tree = ET.parse(vrt_path)
            root = tree.getroot()

            gt_elem = root.find("GeoTransform")
            if gt_elem is None or not gt_elem.text:
                raise Exception("VRTにGeoTransformが見つかりません。")
            
            vrt_gt = [float(x) for x in gt_elem.text.strip().split(',')]
            vrt_minx = vrt_gt[0]
            vrt_maxy = vrt_gt[3]
            pixel_width = vrt_gt[1]
            pixel_height = vrt_gt[5] 

            targets = set(target_tifs_norm)

            for band in root.findall("VRTRasterBand"):
                for source in band.findall("SimpleSource") + band.findall("ComplexSource"):
                    src_file_elem = source.find("SourceFilename")
                    if src_file_elem is None or not src_file_elem.text:
                        continue
                    
                    src_path = src_file_elem.text
                    if src_file_elem.get("relativeToVRT") == "1":
                        src_path = os.path.join(os.path.dirname(vrt_path), src_path)
                    src_path_norm = os.path.normpath(src_path)

                    if src_path_norm in targets:
                        dst_rect = source.find("DstRect")
                        if dst_rect is not None:
                            x_off = float(dst_rect.get("xOff"))
                            y_off = float(dst_rect.get("yOff"))
                            x_size = float(dst_rect.get("xSize"))
                            y_size = float(dst_rect.get("ySize"))

                            minx = vrt_minx + (x_off * pixel_width)
                            maxy = vrt_maxy + (y_off * pixel_height)
                            maxx = minx + (x_size * pixel_width)
                            miny = maxy + (y_size * pixel_height)

                            wkt = f"POLYGON (({minx} {maxy}, {maxx} {maxy}, {maxx} {miny}, {minx} {miny}, {minx} {maxy}))"
                            features_data.append({"path": src_path_norm, "wkt": wkt})
                            
                            targets.remove(src_path_norm)
                            if not targets:
                                return features_data
        except Exception as e:
            QgsMessageLog.logMessage(f"XML解析エラー: {e}", "OrthoManager", Qgis.MessageLevel.Warning)
        
        return features_data

    def _create_gpkg(self, features_data, crs_wkt):
        driver = ogr.GetDriverByName("GPKG")
        ds = driver.CreateDataSource(self.temp_gpkg)
        if not ds:
            raise Exception("GPKGの作成に失敗しました")
        
        srs = osr.SpatialReference()
        if crs_wkt:
            srs.ImportFromWkt(crs_wkt)
            
        layer = ds.CreateLayer("tiles", srs, ogr.wkbPolygon)
        fld_loc = ogr.FieldDefn("location", ogr.OFTString)
        fld_loc.SetWidth(255)
        layer.CreateField(fld_loc)
        fld_fname = ogr.FieldDefn("filename", ogr.OFTString)
        fld_fname.SetWidth(255)
        layer.CreateField(fld_fname)
        
        layer.StartTransaction()
        for fd in features_data:
            feat = ogr.Feature(layer.GetLayerDefn())
            feat.SetField("location", fd["path"])
            feat.SetField("filename", os.path.splitext(os.path.basename(fd["path"]))[0])
            geom = ogr.CreateGeometryFromWkt(fd["wkt"])
            if geom:
                feat.SetGeometry(geom)
                layer.CreateFeature(feat)
            feat = None
        layer.CommitTransaction()
        ds = None

    def _update_gpkg(self, features_data, tifs_to_delete):
        driver = ogr.GetDriverByName("GPKG")
        ds = driver.Open(self.temp_gpkg, 1)
        if not ds:
            raise Exception("一時GPKGの追記オープンに失敗しました")
        layer = ds.GetLayerByName("tiles")
        if not layer:
            raise Exception("GPKG内にtilesレイヤが見つかりません")
        
        layer.StartTransaction()
        
        if tifs_to_delete:
            feature_ids_to_delete = []
            layer.ResetReading()
            for feat in layer:
                loc = feat.GetField("location")
                if loc and os.path.normpath(loc) in tifs_to_delete:
                    feature_ids_to_delete.append(feat.GetFID())
            for fid in feature_ids_to_delete:
                layer.DeleteFeature(fid)

        for fd in features_data:
            feat = ogr.Feature(layer.GetLayerDefn())
            feat.SetField("location", fd["path"])
            feat.SetField("filename", os.path.splitext(os.path.basename(fd["path"]))[0])
            geom = ogr.CreateGeometryFromWkt(fd["wkt"])
            if geom:
                feat.SetGeometry(geom)
                layer.CreateFeature(feat)
            feat = None
            
        layer.CommitTransaction()
        ds = None

    def finished(self, result):
        self.signals.completed.emit(self.success, self.error_msg, self.temp_vrt, self.temp_gpkg, self.timing)
