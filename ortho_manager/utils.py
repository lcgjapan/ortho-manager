import os
import json
from qgis.core import (
    QgsMessageLog, Qgis, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtGui import QColor

try:
    from osgeo import gdal
    gdal.UseExceptions()
    GDAL_OK = True
except ImportError:
    GDAL_OK = False

PROJECT_KEY = "OrthoManager"
PROJECT_ENTRY = "vrt_registry_v2"
DEFAULT_MIN_SCALE = 500
DEFAULT_OVERLAY_COLOR = QColor(0x76, 0xa3, 0x2a, 255)
NODATA_VALUE = 0

def get_bounds_safe(tif_path):
    """直列スレッド/並列スレッドから呼ばれるTIF座標読み取り関数（安全版）"""
    try:
        ds = gdal.OpenEx(tif_path, gdal.OF_READONLY | gdal.OF_RASTER)
        if not ds: return None
        gt = ds.GetGeoTransform()
        x_size = ds.RasterXSize
        y_size = ds.RasterYSize
        
        # 回転なしの標準的なオルソ画像の場合（高速化）
        if gt[2] == 0 and gt[4] == 0:
            minx = gt[0]
            maxy = gt[3]
            maxx = minx + gt[1] * x_size
            miny = maxy + gt[5] * y_size
            wkt = f"POLYGON (({minx} {maxy}, {maxx} {maxy}, {maxx} {miny}, {minx} {miny}, {minx} {maxy}))"
        else:
            x1 = gt[0]
            y1 = gt[3]
            x2 = gt[0] + x_size*gt[1]
            y2 = gt[3] + x_size*gt[4]
            x3 = gt[0] + x_size*gt[1] + y_size*gt[2]
            y3 = gt[3] + x_size*gt[4] + y_size*gt[5]
            x4 = gt[0] + y_size*gt[2]
            y4 = gt[3] + y_size*gt[5]
            wkt = f"POLYGON (({x1} {y1}, {x2} {y2}, {x3} {y3}, {x4} {y4}, {x1} {y1}))"
        
        ds = None
        return {"path": tif_path, "wkt": wkt}
    except Exception as e:
        QgsMessageLog.logMessage(f"座標抽出失敗 ({os.path.basename(tif_path)}): {e}", "OrthoManager", Qgis.Warning)
        return None