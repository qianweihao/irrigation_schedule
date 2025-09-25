# clean_geojsons.py
import os
import json
import math
import glob
import sys
import io
from copy import deepcopy

# 设置输出编码以解决Windows命令行中文显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ========== 配置 ==========
DIR = "gzp_farm"

# 动态获取所有 *_code.geojson 文件
FILES = [os.path.basename(f) for f in glob.glob(os.path.join(DIR, "*_code.geojson"))]

if not FILES:
    print(f"在 {DIR} 文件夹中未找到任何 *_code.geojson 文件")
    print("请先运行 farmgis_convert.py 生成 geojson 文件")
else:
    print(f"找到 {len(FILES)} 个 geojson 文件: {FILES}")

# 若安装了 shapely，则可尝试自动修复面几何
try:
    from shapely.geometry import shape, mapping
    from shapely.validation import make_valid  # shapely>=2
    SHAPELY_OK = True
except Exception:
    SHAPELY_OK = False

# ========== 工具函数 ==========
def is_num(x):
    return isinstance(x, (int, float))

def is_valid_lonlat(lon, lat):
    if not (is_num(lon) and is_num(lat)):
        return False
    # 拒绝 NaN/Inf
    if any([math.isnan(lon), math.isnan(lat), math.isinf(lon), math.isinf(lat)]):
        return False
    # 拒绝极端哨兵值
    if abs(lon) > 1e6 or abs(lat) > 1e6:
        return False
    # 合法经纬度范围
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return False
    return True

def traverse_coords(geom_type, coords):
    """
    生成器：依几何类型遍历所有坐标点 (lon, lat)
    支持 Point/LineString/Polygon/MultiPoint/MultiLineString/MultiPolygon/GeometryCollection(部分)
    """
    if geom_type == "Point":
        yield coords
    elif geom_type == "MultiPoint" or geom_type == "LineString":
        for pt in coords:
            yield pt
    elif geom_type == "MultiLineString" or geom_type == "Polygon":
        # Polygon: [ [ring1...], [ring2...] ], ring = [ [x,y], ... ]
        # MultiLineString: [ [line1...], [line2...] ]
        for part in coords:
            for pt in part:
                yield pt
    elif geom_type == "MultiPolygon":
        # [[[ring1...],[ring2...]], [[...]], ...]
        for poly in coords:
            for ring in poly:
                for pt in ring:
                    yield pt
    elif geom_type == "GeometryCollection":
        # 递归遍历子几何
        for g in coords or []:
            gtype = g.get("type")
            gcoords = g.get("coordinates")
            if gtype and gcoords is not None:
                for pt in traverse_coords(gtype, gcoords):
                    yield pt
    else:
        # 未知类型：不产生坐标
        return

def geometry_has_valid_lonlat(geom):
    """检查几何中所有坐标是否都是有效经纬度"""
    if not geom or "type" not in geom:
        return False
    gtype = geom["type"]
    if gtype == "GeometryCollection":
        geoms = geom.get("geometries", [])
        for sub in geoms:
            if not geometry_has_valid_lonlat(sub):
                return False
        return True if geoms else False
    coords = geom.get("coordinates", None)
    if coords is None:
        return False
    for pt in traverse_coords(gtype, coords):
        if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
            return False
        lon, lat = pt[0], pt[1]
        if not is_valid_lonlat(lon, lat):
            return False
    return True

def ensure_code_property(props, fallback):
    """确保存在 code 字段；若存在候选则重命名为 code，否则用 fallback"""
    if props is None:
        props = {}
    candidates = ["code", "编码", "编号", "name", "NAME", "id", "ID"]
    for c in candidates:
        if c in props:
            # 若原本就有 code，直接返回
            if c == "code":
                return props
            # 否则重命名为 code（不覆盖现有 code）
            if "code" not in props:
                props["code"] = props[c]
                # 可选：删除原字段
                # del props[c]
            return props
    # 都没有就用回退
    props["code"] = str(fallback)
    return props

def try_make_valid_polygon(geom):
    """
    使用 shapely 尝试修复面几何（自交/重叠等）。
    仅当 SHAPELY_OK 时启用。
    """
    if not SHAPELY_OK:
        return geom  # 不做修改
    try:
        g = shape(geom)
        if g.is_valid:
            return geom
        fixed = make_valid(g)  # shapely>=2，返回有效几何
        # 仅接受面类型修复结果
        if fixed.geom_type in ("Polygon", "MultiPolygon"):
            return mapping(fixed)
        else:
            # 修复后变成别的类型，放弃修复以免语义错乱
            return geom
    except Exception:
        return geom

# ========== 主清洗逻辑 ==========
def clean_file(path):
    if not os.path.isfile(path):
        print(f"[跳过] 找不到文件: {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        print(f"[跳过] 不是 FeatureCollection: {path}")
        return

    feats = data.get("features", [])
    before = len(feats)

    good, bad = [], []
    for i, feat in enumerate(feats):
        geom = feat.get("geometry")
        props = feat.get("properties", {})
        gtype = geom.get("type") if geom else None

        if not geom or not gtype:
            bad.append((i, "no geometry"))
            continue

        # 对 Polygon/MultiPolygon 可选修复（shapely 可用时）
        if gtype in ("Polygon", "MultiPolygon"):
            geom = try_make_valid_polygon(geom)

        # 坐标合法性检查
        if not geometry_has_valid_lonlat(geom):
            # 记录部分信息便于定位
            preview = {"type": gtype, "props": {k: props.get(k) for k in list(props)[:3]}}
            bad.append((i, f"invalid coords", preview))
            continue

        # 确保 code 字段
        props = ensure_code_property(props, fallback=i)

        # 写回
        new_feat = {
            "type": "Feature",
            "properties": props,
            "geometry": geom
        }
        good.append(new_feat)

    after = len(good)
    print(f"\n[处理] {path}")
    print(f"  总要素: {before}  =>  保留: {after}  删除: {before - after}")
    if bad:
        print("  删除示例（最多3条）：")
        for row in bad[:3]:
            print("   -", row)

    # 备份
    bak = path + ".bak"
    if os.path.exists(bak):
        os.remove(bak)
    os.replace(path, bak)
    print(f"  已备份 -> {bak}")

    # 回写清洗后的文件
    out = deepcopy(data)
    out["features"] = good
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"  已写回清洗后的文件 -> {path}")

def main():
    abs_dir = os.path.abspath(DIR)
    print(f"工作目录: {abs_dir}")
    for fname in FILES:
        clean_file(os.path.join(DIR, fname))
    print("\n完成。请刷新前端页面验证。")

if __name__ == "__main__":
    main()
