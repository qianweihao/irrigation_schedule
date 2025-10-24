# -*- coding: utf-8 -*-
"""
auto_to_config.py —— 三个(Geo)JSON → 生成 config.json

对齐你的约定（关键点）：
1) gates[].id = 闸门要素 properties.code
2) gates[].type = 闸门要素 properties.type（原样保留；后端用时可自行 .lower()）
3) segments[].regulator_gate_ids = 该段所有“节制类”闸门的 properties.code（按 Gy 数字升序；无法解析时按里程兜底）
4) fields[].sectionID = 田块要素 properties.id   ←← 这是你刚提出的强约束
   （严格等于源字段，不做其它兜底）
5) 同步输出 labeled_output 便于核查

还包含：
- 不重编号；保持源数据 id/code
- inlet_G_id 优先用源字段；若缺从 F_id 的 “Sx-Gy-Fzz” 提取；再缺用近邻闸门兜底（逐行赋值，避免长度不匹配）
- wl_mm 可选用外部 waterlevels.json 注入
- 顶层 farm_id：形参 → 环境变量 → DEFAULT_FARM_ID
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path
import json, os, re, math, glob
import yaml

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import nearest_points

# 加载配置文件
def _load_config(config_path: str = "auto_config_params.yaml") -> Dict[str, Any]:
    """加载配置文件，返回配置字典"""
    config_file = Path(config_path)
    if not config_file.exists():
        # 如果配置文件不存在，返回默认配置
        return {
            "default_farm_id": "13944136728576",
            "default_time_window_h": 20.0,
            "default_target_depth_mm": 90.0,
            "default_canal_id": "C_A",
            "default_water_levels": {"wl_low": 80.0, "wl_opt": 100.0, "wl_high": 140.0},
            "default_field_config": {"has_drain_gate": True, "rel_to_regulator": "downstream"},
            "default_pump": {"name": "AUTO", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6},
            "default_pumps": [{"name": "P1", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6}, {"name": "P2", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6}],
            "crs_config": {"geographic_crs": ["EPSG:4326", "EPSG:4490", "WGS84"], "sqm_to_mu_factor": 666.6667},
            "file_search_paths": {"data_paths": ["gzp_farm", "/mnt/data"], "waterlevels_paths": ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"]},
            "default_filenames": {"segments": "港中坪水路_code.geojson", "gates": "港中坪阀门与节制闸_code.geojson", "fields": "港中坪田块_code.geojson"},
            "output_config": {"config_file": "config.json", "labeled_dir": "labeled_output"},
            "env_vars": {"farm_id": ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"]},
            "default_distance_rank": 9999
        }
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
            if config_data is None:
                # 如果配置文件为空，返回默认配置
                return {
                    "default_farm_id": "13944136728576",
                    "default_time_window_h": 20.0,
                    "default_target_depth_mm": 90.0,
                    "default_canal_id": "C_A",
                    "default_water_levels": {"wl_low": 80.0, "wl_opt": 100.0, "wl_high": 140.0},
                    "default_field_config": {"has_drain_gate": True, "rel_to_regulator": "downstream"},
                    "default_pump": {"name": "AUTO", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6},
                "default_pumps": [{"name": "P1", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6}, {"name": "P2", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6}],
                    "crs_config": {"geographic_crs": ["EPSG:4326", "EPSG:4490", "WGS84"], "sqm_to_mu_factor": 666.6667},
                    "file_search_paths": {"data_paths": ["gzp_farm", "/mnt/data"], "waterlevels_paths": ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"]},
                    "default_filenames": {"segments": "港中坪水路_code.geojson", "gates": "港中坪阀门与节制闸_code.geojson", "fields": "港中坪田块_code.geojson"},
                    "output_config": {"config_file": "config.json", "labeled_dir": "labeled_output"},
                    "env_vars": {"farm_id": ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"]},
                    "default_distance_rank": 9999
                }
            return config_data
    except Exception as e:
        print(f"配置文件读取失败: {e}，使用默认配置")
        # 如果读取失败，返回默认配置
        return {
            "default_farm_id": "13944136728576",
            "default_time_window_h": 20.0,
            "default_target_depth_mm": 90.0,
            "default_canal_id": "C_A",
            "default_water_levels": {"wl_low": 80.0, "wl_opt": 100.0, "wl_high": 140.0},
            "default_field_config": {"has_drain_gate": True, "rel_to_regulator": "downstream"},
            "default_pump": {"name": "AUTO", "q_rated_m3ph": 300.0, "efficiency": 0.8},
            "default_pumps": [{"name": "P1", "q_rated_m3ph": 300.0, "efficiency": 0.8}],
            "crs_config": {"geographic_crs": ["EPSG:4326", "EPSG:4490", "WGS84"], "sqm_to_mu_factor": 666.6667},
            "file_search_paths": {"data_paths": ["gzp_farm", "/mnt/data"], "waterlevels_paths": ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"]},
            "default_filenames": {"segments": "港中坪水路_code.geojson", "gates": "港中坪阀门与节制闸_code.geojson", "fields": "港中坪田块_code.geojson"},
            "output_config": {"config_file": "config.json", "labeled_dir": "labeled_output"},
            "env_vars": {"farm_id": ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"]},
            "default_distance_rank": 9999
        }

# 全局配置对象
CONFIG = _load_config()

# ============== 基础工具 ==============

def _read_any(path: str) -> gpd.GeoDataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    gdf = gpd.read_file(str(p))
    if "geometry" not in gdf.columns:
        raise ValueError(f"{path} 缺少 geometry 列")
    if gdf.empty:
        raise ValueError(f"{path} 为空")
    return gdf

def _utm_crs_for(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    south = lat < 0
    epsg = 32700 + zone if south else 32600 + zone
    return f"EPSG:{epsg}"

def _ensure_crs_metric(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    geographic_crs = CONFIG.get("crs_config", {}).get("geographic_crs", ["EPSG:4326", "EPSG:4490", "WGS84"])
    if str(gdf.crs).upper() in geographic_crs:
        c = gdf.unary_union.centroid
        crs = _utm_crs_for(c.x, c.y)
        try:
            return gdf.to_crs(crs)
        except Exception:
            return gdf
    return gdf

def _mu_from_area(poly: Polygon) -> float:
    factor = CONFIG.get("crs_config", {}).get("sqm_to_mu_factor", 666.6667)
    return float(poly.area / factor)

def _try_float(x, default=None):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)): return default
        return float(x)
    except Exception:
        return default

def _num_tail(x, default=None):
    if default is None:
        default = CONFIG.get("default_distance_rank", 9999)
    if x is None: return default
    m = re.search(r"(\d+)$", str(x).strip())
    return int(m.group(1)) if m else default

def _get_gate_seq(code: Optional[str]) -> Optional[int]:
    """S4-G24 -> 24"""
    if not code: return None
    s = str(code)
    if "-G" not in s: return None
    part = s.split("-G", 1)[1]
    digits = "".join(ch for ch in part if ch.isdigit())
    return int(digits) if digits else None

def _sid_from_code(code: Optional[str]) -> Optional[str]:
    """S4-G24 -> S4"""
    if not code: return None
    s = str(code)
    if "-G" in s:
        return s.split("-G", 1)[0]
    m = re.search(r"(S\d+)", s)
    return m.group(1) if m else None

def _is_nanlike(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v.strip().lower() in {"nan","none","null",""})

def _first_non_empty(row: dict, keys: List[str]) -> Optional[str]:
    for k in keys:
        if k in row and not _is_nanlike(row.get(k)):
            s = str(row.get(k)).strip()
            if s: return s
    return None

def _norm_seg_type(v: Any) -> str:
    s = str(v).strip().lower()
    if s in {"main-s", "main", "主渠", "主干"}: return "main-S"
    return "branch-S"

def _is_regulator_type(v: Any) -> bool:
    """哪些 gate.type 视为 '节制类'：main-g / branch-g / regulator / 中文'节制'/'主闸' 等"""
    s = str(v).strip().lower()
    return any(t in s for t in ["main-g", "branch-g", "regulator", "节制", "主闸", "支闸"])

def _line_chainage(pt: Point, line: LineString) -> float:
    try:
        return float(line.project(pt))
    except Exception:
        p0 = Point(list(line.coords)[0])
        return float(p0.distance(nearest_points(pt, line)[1]))

def _attach_gates_to_segments(segments: gpd.GeoDataFrame, gates: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """为 gates 计算最近段索引与沿线里程，用于兜底排序/归属。"""
    seg_geom = segments.geometry.values
    seg_idx, chainages = [], []
    for p in gates.geometry.values:
        dists = [p.distance(g) for g in seg_geom]
        i = int(np.argmin(dists))
        seg_idx.append(i)
        chainages.append(_line_chainage(p, seg_geom[i]))
    out = gates.copy()
    out["__seg_idx__"] = seg_idx
    out["__chainage__"] = chainages
    return out

def _nearest_gate_index(points: List[Point], gates: gpd.GeoDataFrame) -> List[int]:
    gate_pts = gates.geometry.values
    out = []
    for p in points:
        d = [p.distance(q) for q in gate_pts]
        out.append(int(np.argmin(d)))
    return out

def _load_waterlevels(path: Optional[str]) -> Dict[str, float]:
    if not path: 
        # 如果没有指定路径，尝试从配置的搜索路径中查找
        waterlevels_paths = CONFIG.get("file_search_paths", {}).get("waterlevels_paths", 
                                       ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"])
        for wl_path in waterlevels_paths:
            if Path(wl_path).exists():
                path = wl_path
                break
        if not path:
            return {}
    
    p = Path(path)
    if not p.exists(): return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                fv = _try_float(v, None)
                if fv is not None: out[str(k)] = fv
        return out
    except Exception:
        return {}

# ============== 主转换 ==============

def convert(
    segments_path: str,
    gates_path: str,
    fields_path: str,
    cfg_out: Optional[str] = None,
    labeled_dir: Optional[str] = None,
    default_pumps: Optional[List[Dict[str, Any]]] = None,
    t_win_h: Optional[float] = None,
    d_target_mm: Optional[float] = None,
    farm_id: Optional[str] = None,
    waterlevels_json: Optional[str] = None
) -> Dict[str, Any]:
    
    # 从配置文件获取默认值
    if cfg_out is None:
        cfg_out = CONFIG.get("output_config", {}).get("config_file", "config.json")
    if labeled_dir is None:
        labeled_dir = CONFIG.get("output_config", {}).get("labeled_dir", "labeled_output")
    if t_win_h is None:
        t_win_h = CONFIG.get("default_time_window_h", 20.0)
    if d_target_mm is None:
        d_target_mm = CONFIG.get("default_target_depth_mm", 90.0)
    if default_pumps is None:
        default_pumps = CONFIG.get("default_pumps", [{"name":"P1","q_rated_m3ph":300.0,"efficiency":0.8}])

    # 读取
    seg_raw = _read_any(segments_path)
    gat_raw = _read_any(gates_path)
    fld_raw = _read_any(fields_path)

    # 投影到米制
    seg = _ensure_crs_metric(seg_raw)
    gat = _ensure_crs_metric(gat_raw)
    fld = _ensure_crs_metric(fld_raw)

    # -------- 段标准化 --------
    seg2 = seg.copy()
    # 段ID（优先 S_id/code/id）
    if "S_id" in seg2.columns:
        seg2["S_id"] = seg2["S_id"].astype(str).str.strip()
    elif "code" in seg2.columns:
        seg2["S_id"] = seg2["code"].astype(str).str.strip()
    elif "id" in seg2.columns:
        seg2["S_id"] = ("S" + seg2["id"].astype(str).str.strip())
    else:
        seg2["S_id"] = [f"S{i+1}" for i in range(len(seg2))]
    # 段类型
    if "type" in seg2.columns:
        seg2["S_type"] = seg2["type"].apply(_norm_seg_type)
    elif "类型" in seg2.columns:
        seg2["S_type"] = seg2["类型"].apply(_norm_seg_type)
    else:
        seg2["S_type"] = "branch-S"
    # 距离序
    seg2["distance_rank"] = seg2["S_id"].apply(_num_tail)

    # -------- 闸门标准化 --------
    gat2 = gat.copy()
    # 直接保留 properties.code / properties.type
    gat2["code"] = gat2.apply(lambda r: _first_non_empty(r, ["code","Code","gate_code","G_code","name","id"]), axis=1)
    # gate.type：优先 properties.type；若无，兼容中文“类型”；再无则留空
    if "type" in gat2.columns:
        pass
    elif "类型" in gat2.columns:
        gat2["type"] = gat2["类型"]
    else:
        gat2["type"] = None

    # 归属段：优先从 code 前缀解析；否则最近段兜底
    sid_from_code = gat2["code"].apply(_sid_from_code)
    # 计算最近段与里程
    gat2 = _attach_gates_to_segments(seg2, gat2)
    sid_from_near = gat2["__seg_idx__"].map(seg2["S_id"])
    gat2["S_id"] = sid_from_code.fillna(sid_from_near)

    # __g_seq__：同段内按 G 号升序；无 G 号时按 __chainage__ 升序
    gat2["__Gy__"] = gat2["code"].apply(_get_gate_seq)
    gat2["__Gy_isna__"] = gat2["__Gy__"].isna()
    gat2 = gat2.sort_values(by=["S_id", "__Gy_isna__", "__Gy__", "__chainage__"]).copy()
    gat2["__g_seq__"] = gat2.groupby("S_id").cumcount() + 1

    # -------- 田块标准化 --------
    fld2 = fld.copy()
    # F_id：优先 F_id/code/name/id；否则 F1..Fn
    if "F_id" in fld2.columns:
        fld2["F_id"] = fld2["F_id"].astype(str).str.strip()
    else:
        fid = fld2.apply(lambda r: _first_non_empty(r, ["code","name","id","field_code"]), axis=1)
        if fid.isnull().any():
            fid = fid.fillna(pd.Series([f"F{i+1}" for i in range(len(fld2))], index=fld2.index))
        fld2["F_id"] = fid

    # segment_S_id：优先源字段；其次从 F_id 的 "Sx-" 前缀推断；否则“最近闸门所属段”兜底
    seg_from_src = fld2.apply(lambda r: _first_non_empty(r, ["segment_id","segment","S_id","水路","所属水路"]), axis=1)
    seg_from_fid = fld2["F_id"].apply(_sid_from_code)

    # 最近闸门及其所属段（为后续兜底用）
    fld2["_centroid_"] = [geom.centroid if geom is not None else None for geom in fld2.geometry.values]
    gat_attached = _attach_gates_to_segments(seg2, gat2)
    nearest_gate_idx = _nearest_gate_index([c for c in fld2["_centroid_"]], gat_attached)
    nearest_seg_idx = [int(gat_attached["__seg_idx__"].iloc[i]) for i in nearest_gate_idx]
    near_sid_series = pd.Series([seg2["S_id"].iloc[j] for j in nearest_seg_idx], index=fld2.index)

    fld2["segment_S_id"] = seg_from_src.fillna(seg_from_fid).fillna(near_sid_series)

    # inlet_G_id：优先源字段；其次从 F_id 的 "Sx-Gy-Fzz" 截取；最后近邻（逐行赋值，避免长度不匹配）
    def _pick_inlet(r):
        v = _first_non_empty(r, ["inlet_G_id","inlet","进水闸","入水闸","G_code"])
        if v: return v
        fid = str(r["F_id"])
        if "-F" in fid and "-G" in fid:
            return fid.split("-F")[0]
        return None
    fld2["inlet_G_id"] = fld2.apply(_pick_inlet, axis=1)

    # —— 近邻兜底：只给缺失行逐行赋值（避免长度不匹配）
    mask_inlet_nan = fld2["inlet_G_id"].isnull()
    if mask_inlet_nan.any() and not gat_attached.empty and len(nearest_gate_idx) > 0:
        for ridx in fld2.index[mask_inlet_nan]:
            try:
                gate_i = nearest_gate_idx[int(fld2.index.get_loc(ridx))]
                if gate_i < len(gat_attached) and "code" in gat_attached.columns:
                    fld2.at[ridx, "inlet_G_id"] = str(gat_attached["code"].iloc[gate_i])
            except (IndexError, KeyError) as e:
                # 如果索引超出范围或缺少字段，跳过该行
                continue

    # 面积（亩）
    fld2["area_mu"] = fld2.geometry.apply(lambda g: _mu_from_area(g) if g is not None else 0.0)

    # 可选 wl（外部 json）
    wl_map_ext = _load_waterlevels(waterlevels_json)
    name_cols = [c for c in ["name","code","section_code","field_code","id"] if c in fld2.columns]

    def _field_row_wl(row) -> Optional[float]:
        for c in ["wl_mm","liquidLevel_clean","water_level","waterlevel"]:
            if c in fld2.columns:
                v = _try_float(row.get(c), None)
                if v is not None: return v
        v = wl_map_ext.get(str(row["F_id"])) if isinstance(wl_map_ext, dict) else None
        if v is not None: return _try_float(v, None)
        for c in name_cols:
            key = row.get(c)
            if key is not None and str(key) in wl_map_ext:
                return _try_float(wl_map_ext[str(key)], None)
        return None

    # -------- 生成 config 结构 --------

    # 泵：若 gates.type 含 pump，则自动识别；否则使用默认泵清单
    def _detect_pumps_from_gates(gdf: gpd.GeoDataFrame) -> List[Dict[str, Any]]:
        if "type" not in gdf.columns: return []
        g = gdf[gdf["type"].astype(str).str.lower().str.contains("pump")]
        if g.empty: return []
        def pick_name(row, fallback):
            for c in ["name","label","title","code","id"]:
                if c in row and isinstance(row[c], str) and row[c].strip():
                    return str(row[c]).strip()
            return fallback
        def pick_flow(row, default=300.0):
            for c in ["q_rated","q","flow","flow_m3ph","q_m3ph"]:
                if c in row:
                    v = _try_float(row[c])
                    if v is not None: return v
            return default
        pumps, idx = [], 1
        for _, r in g.iterrows():
            nm = pick_name(r, f"P{idx}")
            flow = pick_flow(r, 300.0)
            pumps.append({"name": nm if nm.startswith("P") else f"P{idx}", "q_rated_m3ph": float(flow), "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6})
            idx += 1
        uniq = {}
        for p in pumps: uniq[p["name"]] = p
        return list(uniq.values())

    pumps_detail = _detect_pumps_from_gates(gat2)
    if not pumps_detail:
        pumps_detail = default_pumps or [{"name":"P1","q_rated_m3ph":300.0,"efficiency":0.8,"power_kw":60.0,"electricity_price":0.6}]

    # 段输出：把该段所有“节制类”闸门的 properties.code 收集到 regulator_gate_ids
    seg_rows: List[Dict[str, Any]] = []
    for _, sr in seg2.iterrows():
        sid = sr["S_id"]
        g_in = gat2[(gat2["S_id"] == sid) & (gat2["type"].apply(_is_regulator_type))]
        # 排序：优先按 Gy；Gy 缺失的放后并按 __chainage__ 兜底
        g_in = g_in.sort_values(by=["__Gy_isna__", "__Gy__", "__chainage__"])
        reg_ids = [str(x) for x in g_in["code"].tolist()]
        # feed_by 透传（可选）
        def _parse_feed_by(s):
            if s is None: return []
            s = str(s).strip()
            try:
                arr = json.loads(s.replace("(", "[").replace(")", "]"))
                return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                pass
            for sep in [",",";","|","/","&","+","，","；","、"," "]:
                if sep in s:
                    return [t.strip() for t in s.split(sep) if t.strip()]
            return [s] if s else []
        feed_raw = _first_non_empty(sr, ["feed_by","FEED_BY","feedBy","Feed_By","feedBY"])
        canal_id = CONFIG.get("default_canal_id", "C_A")
        seg_rows.append({
            "id": sid,
            "canal_id": canal_id,
            "distance_rank": int(_num_tail(sid, 9999)),
            "regulator_gate_ids": reg_ids,
            "regulator_gate_id": (reg_ids[0] if reg_ids else None),
            "feed_by": _parse_feed_by(feed_raw)
        })

    # gate 输出：id=code；type=properties.type（原样），q_max_m3ph 默认
    gate_rows: List[Dict[str, Any]] = []
    for _, r in gat2.iterrows():
        gate_rows.append({
            "id": str(r["code"]),
            "type": (None if _is_nanlike(r.get("type")) else str(r.get("type"))),
            "q_max_m3ph": 9999.0
        })

    # field 输出（这里落实你的强约束：sectionID = properties.id）
    fld_rows: List[Dict[str, Any]] = []
    for _, r in fld2.iterrows():
        # 1) sectionID = 源 properties.id（严格按你的要求）
        section_id = str(r["id"]) if "id" in fld2.columns and not _is_nanlike(r.get("id")) else None

        # 2) sectionCode 原样从常见字段取（不强制）
        section_code = _first_non_empty(r, ["sectionCode","section_code","code","field_code","name"])

        # 3) 其它显示字段
        name = _first_non_empty(r, ["name","Name","地块名称","田块名称"])

        # 4) wl_mm（若有）
        wl = _field_row_wl(r)

        # 5) 距离 rank：优先 F_id 的数字尾；否则段 id 的数字尾
        default_rank = CONFIG.get("default_distance_rank", 9999)
        dist_rank = int(_num_tail(r.get("F_id"), _num_tail(r.get("segment_S_id"), default_rank)))
        
        # 从配置获取默认值
        canal_id = CONFIG.get("default_canal_id", "C_A")
        water_levels = CONFIG.get("default_water_levels", {"wl_low": 80.0, "wl_opt": 100.0, "wl_high": 140.0})
        field_config = CONFIG.get("default_field_config", {"has_drain_gate": True, "rel_to_regulator": "downstream"})

        fld_rows.append({
            "id": str(r["F_id"]),
            "sectionID": (section_id if section_id else None),      # ←← 只用 properties.id
            "sectionCode": (str(section_code) if section_code else None),
            "name": (str(name) if name else None),
            "area_mu": float(round(_mu_from_area(r.geometry) if r.geometry is not None else 0.0, 3)),
            "canal_id": canal_id,
            "segment_id": str(r["segment_S_id"]),
            "distance_rank": dist_rank,
            "wl_mm": wl,
            "wl_low": water_levels.get("wl_low", 80.0),
            "wl_opt": water_levels.get("wl_opt", 100.0),
            "wl_high": water_levels.get("wl_high", 140.0),
            "has_drain_gate": field_config.get("has_drain_gate", True),
            "rel_to_regulator": field_config.get("rel_to_regulator", "downstream"),
            "inlet_G_id": (str(r["inlet_G_id"]) if not _is_nanlike(r.get("inlet_G_id")) else None)
        })

    # 顶层 farm_id（形参 → 环境 → 默认）
    env_vars = CONFIG.get("env_vars", {}).get("farm_id", ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"])
    default_farm_id = CONFIG.get("default_farm_id", "13944136728576")
    
    if not farm_id:
        for env_var in env_vars:
            farm_id = os.environ.get(env_var)
            if farm_id:
                break
        if not farm_id:
            farm_id = default_farm_id
    
    # 默认泵配置
    default_pump_config = CONFIG.get("default_pump", {"name": "AUTO", "q_rated_m3ph": 300.0, "efficiency": 0.8, "power_kw": 60.0, "electricity_price": 0.6})

    # 默认泵时间约束配置
    default_pump_time_constraints = CONFIG.get("default_pump_time_constraints", [
        {"pump_name": "P1", "start_hour": 0, "end_hour": 8},
        {"pump_name": "P2", "start_hour": 8, "end_hour": 16}
    ])

    data = {
        "farm_id": farm_id,
        "t_win_h": float(t_win_h),
        "d_target_mm": float(d_target_mm),
        "pump": default_pump_config,
        "pumps": pumps_detail,
        "pump_time_constraints": default_pump_time_constraints,
        "segments": seg_rows,
        "gates": gate_rows,
        "fields": fld_rows
    }

    Path(cfg_out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ============== labeled_output ==============
    out_dir = Path(labeled_dir); out_dir.mkdir(parents=True, exist_ok=True)
    # 段
    (seg2[["S_id","S_type","distance_rank","geometry"]]).to_file(out_dir / "segments_labeled.geojson", driver="GeoJSON")
    # 闸门（按口径：code/type/S_id）
    (gat2[["code","type","S_id","geometry"]]).to_file(out_dir / "gates_labeled.geojson", driver="GeoJSON")
    # 田块（便于核查：F_id, properties.id → sectionID, inlet_G_id, segment_S_id）
    cols = ["F_id","id","inlet_G_id","segment_S_id","geometry"]
    cols = [c for c in cols if c in fld2.columns] + [c for c in ["F_id","inlet_G_id","segment_S_id","geometry"] if c not in cols]
    (fld2[cols]).to_file(out_dir / "fields_labeled.geojson", driver="GeoJSON")

    return data

# ============== 便捷入口 ==============

def _pick_path(name: str, file_type: str = None) -> str:
    # 如果包含通配符，使用glob匹配
    if '*' in name or '?' in name:
        # 首先检查当前目录
        matches = glob.glob(name)
        if matches:
            # 如果有多个匹配，尝试根据文件类型选择最合适的
            if file_type and len(matches) > 1:
                type_keywords = {
                    'segments': ['水路', '渠道', 'canal', 'segment'],
                    'gates': ['阀门', '闸门', 'gate', 'valve'],
                    'fields': ['田块', '地块', 'field', 'plot']
                }
                keywords = type_keywords.get(file_type, [])
                for keyword in keywords:
                    for match in matches:
                        if keyword in Path(match).stem:
                            return str(Path(match))
            return str(Path(matches[0]))
        
        # 然后检查配置的搜索路径
        search_paths = CONFIG.get("file_search_paths", {}).get("data_paths", ["gzp_farm", "/mnt/data"])
        for search_path in search_paths:
            pattern = str(Path(search_path) / name)
            matches = glob.glob(pattern)
            if matches:
                # 同样的类型匹配逻辑
                if file_type and len(matches) > 1:
                    type_keywords = {
                        'segments': ['水路', '渠道', 'canal', 'segment'],
                        'gates': ['阀门', '闸门', 'gate', 'valve'],
                        'fields': ['田块', '地块', 'field', 'plot']
                    }
                    keywords = type_keywords.get(file_type, [])
                    for keyword in keywords:
                        for match in matches:
                            if keyword in Path(match).stem:
                                return str(Path(match))
                return str(Path(matches[0]))
    else:
        # 精确匹配逻辑（原有逻辑）
        if Path(name).exists():
            return str(Path(name))
        
        search_paths = CONFIG.get("file_search_paths", {}).get("data_paths", ["gzp_farm", "/mnt/data"])
        for search_path in search_paths:
            p = Path(search_path) / name
            if p.exists():
                return str(p)
    
    # 如果都找不到，返回原始路径
    return str(Path(name))

if __name__ == "__main__":
    # 从配置获取默认文件名
    default_filenames = CONFIG.get("default_filenames", {
        "segments": "港中坪水路_code.geojson",
        "gates": "港中坪阀门与节制闸_code.geojson",
        "fields": "港中坪田块_code.geojson"
    })
    
    segments_path = _pick_path(default_filenames["segments"], "segments")
    gates_path    = _pick_path(default_filenames["gates"], "gates")
    fields_path   = _pick_path(default_filenames["fields"], "fields")
    
    # 可选水位文件搜索
    wl_json = None
    waterlevels_paths = CONFIG.get("file_search_paths", {}).get("waterlevels_paths", 
                                   ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"])
    for p in waterlevels_paths:
        if Path(p).exists(): 
            wl_json = p
            break
    
    # 农场ID：优先环境，其次默认
    env_vars = CONFIG.get("env_vars", {}).get("farm_id", ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"])
    default_farm_id = CONFIG.get("default_farm_id", "13944136728576")
    
    farm_id = None
    for env_var in env_vars:
        farm_id = os.environ.get(env_var)
        if farm_id:
            break
    if not farm_id:
        farm_id = default_farm_id
    
    convert(
        segments_path, gates_path, fields_path,
        farm_id=farm_id, waterlevels_json=wl_json
    )
