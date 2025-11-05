# -*- coding: utf-8 -*-
"""
web_farm_irrigation_modified.py
前端可视化（Leaflet + 原生JS） + 后端计划计算接口
修复要点：
- 去除“选择文件”入口，仅从后端 /v1/plan 生成与加载计划；
- btnLoadPlan 增加错误处理与加载状态提示；
- 修复 JS 中误用 “#” 注释导致脚本不执行的问题（改为 //）；
- 无 step.label 时按批次索引回退绑定时间窗（保证时间轴/水位动画工作）。
"""

import os
import json
from typing import Optional, Tuple

from flask import Flask, make_response, jsonify, abort, request
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString

# ====== 工程内路径 / 文件名 ======
ROOT = os.path.abspath(os.path.dirname(__file__))

# 原始三件套（用于回退）
GEOJSON_DIR   = os.path.join(ROOT, "gzp_farm")
VALVE_FILE    = "港中坪阀门与节制闸_code.geojson"
FIELD_FILE    = "港中坪田块_code.geojson"
WATERWAY_FILE = "港中坪水路_code.geojson"

# 标注后的（优先使用，内含 F_id / G_id / S_id）
LABELED_DIR     = os.path.join(ROOT, "labeled_output")
LABELED_FIELDS  = os.path.join(LABELED_DIR, "fields_labeled.geojson")
LABELED_GATES   = os.path.join(LABELED_DIR, "gates_labeled.geojson")
LABELED_SEGMENT = os.path.join(LABELED_DIR, "segments_labeled.geojson")

# 配置文件（由 auto_to_config.py 生成）
CONFIG_JSON = os.path.join(ROOT, "config.json")

# 计划计算：使用你提供的"多节制闸"版本
from farm_irr_full_device_modified import (
    farmcfg_from_json_select,
    build_concurrent_plan,
    plan_to_json,
    generate_multi_pump_scenarios,
)

# ====== Geo 工具 ======
def _looks_like_lonlat(bounds):
    try:
        minx, miny, maxx, maxy = bounds
        return -180 <= minx <= 180 and -90 <= miny <= 90 and -180 <= maxx <= 180 and -90 <= maxy <= 90
    except Exception:
        return False

def read_geo_ensure_wgs84(path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty:
        return gdf
    if gdf.crs is None:
        # 如果像经纬度，强设 WGS84；否则抛错提示重投影
        if _looks_like_lonlat(gdf.total_bounds):
            gdf = gdf.set_crs(epsg=4326)
        else:
            raise RuntimeError(f"{os.path.basename(path)} 无 CRS 且不像 WGS84，经纬度范围={gdf.total_bounds}")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    return gdf

def _first_existing(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None

def _ensure_dir(pth: str):
    os.makedirs(os.path.dirname(pth), exist_ok=True)


# ====== Flask App ======
app = Flask(__name__, static_folder=None)

# ---------------- GeoJSON API ----------------
@app.route("/geojson/fields")
def api_fields():
    p = _first_existing(LABELED_FIELDS, os.path.join(GEOJSON_DIR, FIELD_FILE))
    if not p:
        abort(404, description="未找到田块图层")
    gdf = read_geo_ensure_wgs84(p)
    return make_response(jsonify(json.loads(gdf.to_json())))

@app.route("/geojson/gates")
def api_gates():
    p = _first_existing(LABELED_GATES, os.path.join(GEOJSON_DIR, VALVE_FILE))
    if not p:
        abort(404, description="未找到闸门图层")
    gdf = read_geo_ensure_wgs84(p)
    return make_response(jsonify(json.loads(gdf.to_json())))

@app.route("/geojson")
def api_geojson():
    """兼容旧接口：/geojson?type=waterway|fields|gates"""
    typ = (request.args.get("type") or "").lower().strip()
    if typ in ("fields", "field"):
        return api_fields()
    if typ in ("gates", "gate", "valves", "valve"):
        return api_gates()
    if typ in ("waterway", "segments", "lines"):
        p = _first_existing(LABELED_SEGMENT, os.path.join(GEOJSON_DIR, WATERWAY_FILE))
        if not p:
            abort(404, description="未找到水路图层")
        gdf = read_geo_ensure_wgs84(p)
        return make_response(jsonify(json.loads(gdf.to_json())))
    abort(400, description="type 参数必须为 waterway/fields/gates 之一")

# ---------------- 计划计算 API ----------------
@app.route("/v1/plan")
def api_plan():
    """
    生成 plan.json（内存返回，不落盘）
    可选 Query:
      - pumps=P1,P2  仅启用指定泵
      - zones=A,B    仅启用指定供区（如果 config 里配置了 supply_zone）
      - no_realtime=1  不拉实时水位（默认融合）
    """
    if not os.path.isfile(CONFIG_JSON):
        abort(404, description="缺少 config.json，请先运行 auto_to_config.py 生成。")

    data = json.loads(open(CONFIG_JSON, "r", encoding="utf-8").read())
    pumps = request.args.get("pumps", "").strip()
    zones = request.args.get("zones", "").strip()
    active = [s.strip() for s in pumps.split(",") if s.strip()] or None
    zone_ids = [s.strip() for s in zones.split(",") if s.strip()] or None
    use_realtime = not (request.args.get("no_realtime") in ("1", "true", "True"))

    cfg = farmcfg_from_json_select(
        data,
        active_pumps=active,
        zone_ids=zone_ids,
        use_realtime_wl=use_realtime
    )
    plan = build_concurrent_plan(cfg)
    return make_response(jsonify(plan_to_json(plan)))

@app.route("/v1/multi-pump-scenarios")
def api_multi_pump_scenarios():
    """
    生成多水泵方案对比（内存返回，不落盘）
    可选 Query:
      - zones=A,B    仅启用指定供区（如果 config 里配置了 supply_zone）
      - no_realtime=1  不拉实时水位（默认融合）
    
    返回格式：
    {
        "scenarios": [
            {
                "pump_combination": ["P1"],
                "coverage": {"covered_segments": [...], "total_segments": N},
                "plan": {...},
                "electricity_cost": 123.45,
                "pump_runtime_hours": 8.5
            },
            ...
        ],
        "analysis": {
            "total_segments_requiring_irrigation": N,
            "pump_combinations_tested": [["P1"], ["P2"], ["P1", "P2"]],
            "optimal_scenario": {...}
        }
    }
    """
    if not os.path.isfile(CONFIG_JSON):
        abort(404, description="缺少 config.json，请先运行 auto_to_config.py 生成。")

    data = json.loads(open(CONFIG_JSON, "r", encoding="utf-8").read())
    zones = request.args.get("zones", "").strip()
    zone_ids = [s.strip() for s in zones.split(",") if s.strip()] or None
    use_realtime = not (request.args.get("no_realtime") in ("1", "true", "True"))

    # 创建基础配置（不指定 active_pumps，让 generate_multi_pump_scenarios 动态决定）
    cfg = farmcfg_from_json_select(
        data,
        active_pumps=None,  # 不限制水泵，让函数自动分析
        zone_ids=zone_ids,
        use_realtime_wl=use_realtime
    )
    
    # 从配置中获取触发条件
    min_fields_trigger = data.get('irrigation_trigger_config', {}).get('min_fields_trigger', 1)
    
    # 生成多水泵方案
    scenarios_result = generate_multi_pump_scenarios(cfg, min_fields_trigger=min_fields_trigger)
    return make_response(jsonify(scenarios_result))

@app.route("/config.json")
def api_config_json():
    """把 config.json 暴露给前端（用于读取 wl_opt / 每块田阈值、regulator 列表等元信息）"""
    if not os.path.isfile(CONFIG_JSON):
        abort(404, description="缺少 config.json，请先运行 auto_to_config.py 生成。")
    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return make_response(jsonify(data))

# ---------------- 重置到初始数据 API ----------------
@app.post("/v1/reset")
def api_reset():
    """
    还原到“初始三件套”生成的状态：
      - 重新运行 auto_to_config.convert(...) 生成干净的 config.json
      - 覆盖 labeled_output/segments_labeled.geojson / gates_labeled.geojson / fields_labeled.geojson
    前端再点击“生成并加载计划”即可得到最初的计划。
    """
    try:
        # 用你的转换脚本；它会把三件套 → config.json，并同步输出 labeled_output/**
        from auto_to_config import convert as _convert, _pick_path as _pick
    except Exception as e:
        abort(500, description=f"缺少 auto_to_config.py 或导入失败：{e}")

    # 用项目里已有的文件名常量，回到“原始三件套”（gzp_farm 下的源文件）
    seg_path = _pick(WATERWAY_FILE)   # 例如 港中坪水路_code.geojson
    gat_path = _pick(VALVE_FILE)      # 例如 港中坪阀门与节制闸_code.geojson
    fld_path = _pick(FIELD_FILE)      # 例如 港中坪田块_code.geojson

    # 尽量复用现有的泵配置（若当前 config 存在）
    default_pumps = None
    try:
        if os.path.isfile(CONFIG_JSON):
            _cfg = json.loads(open(CONFIG_JSON, "r", encoding="utf-8").read())
            default_pumps = _cfg.get("pumps") or None
    except Exception:
        pass

    # 兜底：如没有，则给一个双泵示例（和你之前常用的一致）
    if not default_pumps:
        default_pumps = [
            {"name": "P1", "q_rated_m3ph": 300.0, "efficiency": 0.8},
            {"name": "P2", "q_rated_m3ph": 180.0, "efficiency": 0.8},
        ]

    try:
        _convert(
            segments_path=seg_path,
            gates_path=gat_path,
            fields_path=fld_path,
            cfg_out=CONFIG_JSON,
            labeled_dir=LABELED_DIR,
            default_pumps=default_pumps,
            t_win_h=20.0,
            d_target_mm=90.0,
            farm_id=os.environ.get("FARM_ID", "13944136728576"),
            waterlevels_json=None
        )
    except Exception as e:
        abort(500, description=f"重置失败：{e}")

    return make_response(jsonify({"ok": True, "message": "已恢复到初始数据；请重新点击“生成并加载计划”。"}))


# ---------------- 新增：闸门编辑 API ----------------
def _load_labeled_segments() -> gpd.GeoDataFrame:
    p = _first_existing(LABELED_SEGMENT, os.path.join(GEOJSON_DIR, WATERWAY_FILE))
    if not p:
        abort(404, description="缺少 segments 图层（labeled 或原始水路）。")
    gdf = read_geo_ensure_wgs84(p)
    # 期望 labeled 文件内含 S_id；若回退到原始文件，S_id 可能缺失
    if "S_id" not in gdf.columns:
        abort(400, description="segments 文件缺少 S_id，请先用 auto_to_config.py 生成 labeled_output/segments_labeled.geojson")
    return gdf

def _load_labeled_gates() -> gpd.GeoDataFrame:
    p = _first_existing(LABELED_GATES)
    if not p:
        return gpd.GeoDataFrame({"G_id": [], "S_id": [], "type": []}, geometry=[], crs="EPSG:4326")
    gdf = read_geo_ensure_wgs84(p)
    # 统一列名：code -> G_id， 类型中文 -> type
    if "G_id" not in gdf.columns and "code" in gdf.columns:
        gdf = gdf.rename(columns={"code": "G_id"})
    if "type" not in gdf.columns and "类型" in gdf.columns:
        gdf = gdf.rename(columns={"类型": "type"})
    # S_id 兜底：从 G_id 里截取 S 段号
    if "S_id" not in gdf.columns and "G_id" in gdf.columns:
        gdf["S_id"] = gdf["G_id"].astype(str).str.split("-G").str[0]
    # 只保留需要的列
    keep = [c for c in ["G_id", "S_id", "type", "geometry"] if c in gdf.columns]
    return gdf[keep].copy()

def _load_labeled_fields() -> gpd.GeoDataFrame:
    p = _first_existing(LABELED_FIELDS, os.path.join(GEOJSON_DIR, FIELD_FILE))
    if not p:
        abort(404, description="缺少田块图层")
    gdf = read_geo_ensure_wgs84(p)
    if "F_id" not in gdf.columns:
        abort(400, description="fields 文件缺少 F_id，请先用 auto_to_config.py 生成 labeled_output/fields_labeled.geojson")
    return gdf

def _nearest_segment(lat: float, lng: float) -> Tuple[str, LineString, Point]:
    seg = _load_labeled_segments()
    pt = Point(float(lng), float(lat))
    # 计算最近的线段
    dists = seg.geometry.distance(pt)
    idx = int(dists.idxmin())
    line: LineString = seg.geometry.loc[idx]
    s_id = str(seg.loc[idx].get("S_id"))
    # 最近点（投影点）
    nearest_on_line = line.interpolate(line.project(pt))
    return s_id, line, nearest_on_line

def _parse_g_seq(gid: str) -> Optional[int]:
    try:
        return int(str(gid).split("-G")[1])
    except Exception:
        return None

def _next_gate_id_for_segment(gates_df: gpd.GeoDataFrame, s_id: str) -> str:
    g_in = gates_df[gates_df["S_id"].astype(str) == str(s_id)]
    if g_in.empty:
        return f"{s_id}-G1"
    # 兼容：有 G_id 用 G_id；否则用 code
    col = "G_id" if "G_id" in g_in.columns else ("code" if "code" in g_in.columns else None)
    if not col:
        return f"{s_id}-G1"
    mx = 0
    for gid in g_in[col].astype(str):
        n = _parse_g_seq(gid) or 0
        if n > mx: mx = n
    return f"{s_id}-G{mx+1}"

def _update_config_add_gate(gate_id: str, s_id: str, gtype: str, qmax: float = 9999.0):
    """把新闸门写入 config.json，并把节制闸加入对应 segment 的 regulator_gate_ids（按序号排好）"""
    if not os.path.isfile(CONFIG_JSON):
        abort(404, description="缺少 config.json，请先用 auto_to_config.py 生成。")
    data = json.loads(open(CONFIG_JSON, "r", encoding="utf-8").read())

    # 1) gates[] 追加/去重
    gates = data.get("gates") or []
    if not any(str(x.get("id")) == gate_id for x in gates):
        gates.append({"id": gate_id, "type": gtype, "q_max_m3ph": float(qmax)})
        data["gates"] = gates

    # 2) segments[] regulator_gate_ids 维护（仅 main-g/branch-g 才作为节制闸）
    if gtype in ("main-g", "branch-g"):
        segs = data.get("segments") or []
        found = False
        for s in segs:
            if str(s.get("id")) == s_id:
                found = True
                reg_ids = list(s.get("regulator_gate_ids") or [])
                if gate_id not in reg_ids:
                    reg_ids.append(gate_id)
                # 按 G 序号排序
                reg_ids.sort(key=lambda x: _parse_g_seq(x) or 0)
                s["regulator_gate_ids"] = reg_ids
                if reg_ids and (s.get("regulator_gate_id") not in reg_ids):
                    s["regulator_gate_id"] = reg_ids[0]  # 兼容字段
                break
        if not found:
            # 若 segments 中没有该 S_id，则新建一个最小条目
            try:
                distance_rank = int(str(s_id)[1:]) if str(s_id).startswith("S") else 1
            except Exception:
                distance_rank = 1
            seg_obj = {
                "id": s_id, "canal_id": "C_A", "distance_rank": distance_rank,
                "regulator_gate_ids": [gate_id], "regulator_gate_id": gate_id
            }
            segs.append(seg_obj)
            data["segments"] = segs

    # 3) 写回
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.post("/v1/gates/add")
def api_add_gate():
    """
    请求体 JSON:
      {
        "lat": 29.123, "lng": 121.456,
        "type": "main-g" | "branch-g" | "inlet-g" | "inout-g" | "drain-g",
        "q_max_m3ph": 9999   (可选)
      }
    流程：
      - 根据点找到最近的 S 段、计算最近点坐标（作为闸门安装位置）
      - 为该段分配下一个 G 序号，生成 G_id = S_id-Gk
      - 写入 labeled_output/gates_labeled.geojson
      - 写入/更新 config.json（gates[]；如是节制闸则更新 segments[].regulator_gate_ids）
    """
    try:
        body = request.get_json(force=True)
    except Exception:
        abort(400, description="无效 JSON")
    lat = body.get("lat"); lng = body.get("lng"); gtype = (body.get("type") or "").lower().strip()
    qmax = float(body.get("q_max_m3ph", 9999.0))
    if lat is None or lng is None or not gtype:
        abort(400, description="参数缺失：lat/lng/type 均必填")

    # 1) 定位最近段、最近点
    s_id, line, proj_pt = _nearest_segment(float(lat), float(lng))

    # 2) 读取/创建 gates 文件 & 生成 G_id
    gates_df = _load_labeled_gates()
    gid = _next_gate_id_for_segment(gates_df, s_id)

    # 3) 追加行并写回
    new_row = gpd.GeoDataFrame(
        {"G_id": [gid], "S_id": [s_id], "type": [gtype]},
        geometry=[proj_pt], crs="EPSG:4326"
    )
    gates_df = gpd.GeoDataFrame(pd.concat([gates_df, new_row], ignore_index=True), crs="EPSG:4326")
    _ensure_dir(LABELED_GATES)
    gates_df.to_file(LABELED_GATES, driver="GeoJSON")

    # 4) 更新 config.json
    _update_config_add_gate(gate_id=gid, s_id=s_id, gtype=gtype, qmax=qmax)

    return make_response(jsonify({"ok": True, "gate": {"id": gid, "S_id": s_id, "type": gtype}, "lat": proj_pt.y, "lng": proj_pt.x}))

@app.post("/v1/gates/install_for_field")
def api_install_gate_for_field():
    """
    请求体 JSON:
      {
        "field_id": "F001",
        "type": "inlet-g" | "inout-g",
        "q_max_m3ph": 9999  (可选)
      }
    流程：
      - 定位该 F_id 的质心
      - 在最近水路段的最近点安装该类型闸门（同 /v1/gates/add）
    """
    try:
        body = request.get_json(force=True)
    except Exception:
        abort(400, description="无效 JSON")
    fid = body.get("field_id")
    gtype = (body.get("type") or "inlet-g").lower().strip()
    qmax = float(body.get("q_max_m3ph", 9999.0))
    if not fid:
        abort(400, description="field_id 必填")

    fld = _load_labeled_fields()
    hit = fld[fld["F_id"].astype(str) == str(fid)]
    if hit.empty:
        abort(404, description=f"未找到田块 {fid}")
    centroid: Point = hit.geometry.iloc[0].centroid

    # 交给 add_gate：用 centroid 作为点击点
    s_id, line, proj_pt = _nearest_segment(float(centroid.y), float(centroid.x))
    gates_df = _load_labeled_gates()
    gid = _next_gate_id_for_segment(gates_df, s_id)
    new_row = gpd.GeoDataFrame(
        {"G_id": [gid], "S_id": [s_id], "type": [gtype]},
        geometry=[proj_pt], crs="EPSG:4326"
    )
    gates_df = gpd.GeoDataFrame(pd.concat([gates_df, new_row], ignore_index=True), crs="EPSG:4326")
    _ensure_dir(LABELED_GATES)
    gates_df.to_file(LABELED_GATES, driver="GeoJSON")
    _update_config_add_gate(gate_id=gid, s_id=s_id, gtype=gtype, qmax=qmax)

    return make_response(jsonify({"ok": True, "gate": {"id": gid, "S_id": s_id, "type": gtype},
                                  "lat": proj_pt.y, "lng": proj_pt.x, "field_id": fid}))

# ---------------- 页面 ----------------
HTML_TEMPLATE = r"""
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8"/>
  <title>农场级灌溉计划 | 地图与时间轴 + 添加闸门 + 水位动画</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    html, body {height:100%; margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;}
    #app {display:grid; grid-template-columns: 1fr 380px; height:100%;}
    #map {height:100%; width:100%;}
    .panel {padding:12px; border-left:1px solid #e5e7eb; overflow:auto;}
    .toolbar {display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:8px;}
    .toolbar input, .toolbar select {padding:6px 8px; border:1px solid #d1d5db; border-radius:6px;}
    .toolbar button {padding:6px 10px; border:1px solid #6366f1; background:#6366f1; color:white; border-radius:6px; cursor:pointer;}
    .list {font-size:14px;}
    .legend {display:flex; gap:6px; flex-wrap:wrap; margin-top:8px;}
    .dot {width:10px; height:10px; border-radius:50%;}
    .subtle {color:#6b7280;}
    .muted {color:#9ca3af;}
    .card {border:1px solid #e5e7eb; border-radius:8px; padding:8px; margin-top:8px;}
    canvas.leaflet-zoom-animated { position:absolute; left:0; top:0; pointer-events:none; }
    .leaflet-container.picking-cursor { cursor: crosshair !important; }
    .err {color:#b91c1c;}
  </style>
</head>
<body>
<div id="app">
  <div id="map"></div>
  <div class="panel">
    <div class="toolbar">
      <button id="btnLoadLayers">加载图层</button>
      <button id="btnLoadPlan">生成并加载计划</button>
      <button id="btnReset" class="btn">重置（还原初始）</button>
      <!-- 移除了本地文件选择入口 -->
    </div>
    <div class="toolbar" style="margin-top:-4px;">
      <input id="inpPumps" placeholder="启用泵（如 P1,P2）"/>
      <input id="inpZones" placeholder="供区（可选）"/>
      <label><input type="checkbox" id="chkRealtime" checked/> 融合实时水位</label>
    </div>

    <div class="list card">
      <div><strong>计划摘要</strong></div>
      <div id="planSummary" class="subtle" style="margin:4px 0 6px;">（未加载）</div>
      <div id="legend" class="legend"></div>

      <!-- 简易时间轴 -->
      <div id="timeline" style="height:8px; background:#eee; position:relative; border-radius:6px;">
        <div id="timelineFill" style="height:8px; width:0%; background:#4f46e5; border-radius:6px;"></div>
        <div id="timelineCursor" style="position:absolute; top:-4px; left:0%; width:2px; height:16px; background:#111;"></div>
      </div>
      <div style="display:flex; gap:6px; align-items:center; margin-top:6px;">
        <button id="btnPlay">▶ 播放</button>
        <button id="btnPause">⏸ 暂停</button>
        <label style="margin-left:6px;"><input type="checkbox" id="chkWave" checked/> 水位动画</label>
        <span id="timeText" class="muted">0.00 h</span>
      </div>
      <div id="errBox" class="err" style="margin-top:6px;"></div>
    </div>

    <div class="list card">
      <div><strong>步骤 / 指令</strong></div>
      <div id="stepList" style="max-height:240px; overflow:auto; margin-top:6px;"></div>
    </div>

    <div class="list card">
      <div><strong>添加闸门</strong>（写入 labeled_output + config.json）</div>
      <div style="display:flex; flex-direction:column; gap:8px; margin-top:6px;">

        <div>
          <label><input type="radio" name="addmode" value="click" checked/> 地图点选添加闸门</label>
          <label style="margin-left:8px;"><input type="radio" name="addmode" value="field"/> 为田块安装进水闸</label>
        </div>

        <!-- 地图点选添加闸门（带开始/取消选点按钮） -->
        <div id="boxClick" style="display:block;">
          <div class="muted">点击“开始地图选点”后，再在地图上点选安装位置。</div>
          <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
            <select id="selGateType">
              <option value="main-g">节制闸（主干） main-g</option>
              <option value="branch-g">节制闸（支渠） branch-g</option>
              <option value="inlet-g">进水闸 inlet-g</option>
              <option value="inout-g">进排合一 inout-g</option>
              <option value="drain-g">排水闸 drain-g</option>
            </select>
            <input id="inpQmax" type="number" step="1" min="0" style="width:140px;" placeholder="q_max_m3ph (可选)"/>
            <button id="btnPickOnMap" type="button">开始地图选点</button>
            <button id="btnSubmitPoint" type="button">提交</button>
          </div>
          <div id="clickHint" class="muted" style="margin-top:4px;">未启用选点</div>
        </div>

        <!-- 为田块安装进水闸 -->
        <div id="boxField" style="display:none;">
          <div class="muted">点击一个田块以选中，然后提交安装进水闸（自动贴近最近水路）。</div>
          <div style="display:flex; gap:6px; align-items:center;">
            <select id="selGateTypeField">
              <option value="inlet-g">进水闸 inlet-g</option>
              <option value="inout-g">进排合一 inout-g</option>
            </select>
            <input id="inpQmaxField" type="number" step="1" min="0" style="width:140px;" placeholder="q_max_m3ph (可选)"/>
            <button id="btnSubmitField" disabled>提交</button>
          </div>
          <div id="fieldHint" class="muted" style="margin-top:4px;">未选择田块</div>
        </div>

        <div id="addResult" class="muted"></div>
      </div>
    </div>
  </div>
</div>

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
'use strict';

// CDN 加载失败时的提示
if (typeof L === 'undefined') {
  const box = document.getElementById('errBox');
  if (box) box.textContent = 'Leaflet 脚本未加载（可能被网络拦截）。请检查网络或更换 CDN。';
}

// 初始化地图
const map = (typeof L !== 'undefined') ? L.map('map') : null;
if (map) {
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19}).addTo(map);
  map.setView([29.8, 121.6], 12); // 兜底中心；加载图层时会 fitBounds
}

let fieldLayer = (map ? L.geoJSON(null, {
  style: {color:'#1e3a8a', weight:1, fillColor:'#93c5fd', fillOpacity:0.35},
  onEachFeature: (feat, ly) => {
    const p = feat.properties || {};
    const fid = p.F_id || p.fid || p.id || p.code;
    const display = p.name || p.section_code || p.sectionCode || p.code || fid;

    if (display){
      ly.bindTooltip(`${display}${fid ? ` (${fid})` : ''}`, {direction:'center', sticky:true});
    }

    ly.on('click', ()=>{
      if (document.querySelector('input[name=addmode]:checked').value === 'field'){
        selectedFieldId = fid;
        document.getElementById('fieldHint').textContent = `已选择田块：${display} (${fid})`;
        document.getElementById('btnSubmitField').disabled = !selectedFieldId;
      }
    });
  }
}).addTo(map) : null);

// —— 形状与着色工具 ——（不要包 <script>）
function _normType(t){ return String(t||'').toLowerCase(); }
function gateKindFromProps(p){
  const t = _normType(p.type || p.gate_type || p.kind);
  if (t.includes('pump')) return 'pump';      // 泵
  if (t.includes('main-')) return 'main-g';   // 主干节制闸
  if (t.includes('branch-')) return 'branch-g'; // 支渠节制闸
  if (t.includes('inout')) return 'inout-g';  // 进排合一
  if (t.includes('inlet')) return 'inlet-g';  // 进水闸
  return 'branch-g';
}
function makeGateIcon(kind, color='#ffd43b', stroke='#333'){
  const sz=18, s2=sz/2;
  let shape='';
  if (kind==='pump'){
    shape=`<rect x="3" y="3" width="12" height="12" rx="2" ry="2" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;
  } else if (kind==='main-g'){
    shape=`<path d="M${s2} 3 L15 15 L3 15 Z" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;
  } else if (kind==='inout-g'){
    shape=`<path d="M${s2} 3 L15 ${s2} L${s2} 15 L3 ${s2} Z" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;
  } else if (kind==='inlet-g'){
    shape=`<path d="M3 6 L${s2} 15 L15 6 Z" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;
  } else {
    shape=`<circle cx="${s2}" cy="${s2}" r="6" fill="${color}" stroke="${stroke}" stroke-width="1.5"/>`;
  }
  return L.divIcon({
    className: 'gate-icon',
    html: `<svg viewBox="0 0 ${sz} ${sz}" xmlns="http://www.w3.org/2000/svg">${shape}</svg>`,
    iconSize: [sz, sz],
    iconAnchor: [s2, s2],
  });
}
// 通用着色：兼容 circleMarker & marker(divIcon)
function setGateLayerColor(ly, color){
  if (ly && ly.setStyle){
    ly.setStyle({color:'#111', fillColor:color});
  } else if (ly && ly.setIcon){
    const k = ly._gateKind || 'branch-g';
    ly.setIcon(makeGateIcon(k, color));
  }
}


let valveLayer = (map ? L.geoJSON(null, {
  pointToLayer: (feat, latlng)=>{
    const p = feat.properties || {};
    const kind = gateKindFromProps(p);
    const name = p.G_id || p.id || p.code || p.name || '';
    const mk = L.marker(latlng, { icon: makeGateIcon(kind, '#ffd43b') });
    mk._gateKind = kind; // 记录形状，供变色使用
    if (name) mk.bindTooltip(String(name), {direction:'top', offset:[0,-8]});
    return mk;
  }
}).addTo(map) : null);



let waterwayLayer = (map ? L.geoJSON(null, {style:{color:'#64748b', weight:2, opacity:0.7}}).addTo(map) : null);

// ===== Canvas 水位动画层 ========================
class WaterAnim {
  constructor(map){
    this.map = map;
    this.enabled = true;
    if (!map) return;
    this.phase = 0;
    this.canvas = L.DomUtil.create('canvas', 'leaflet-zoom-animated');
    this.ctx = this.canvas.getContext('2d');
    this.pane = map.getPanes().overlayPane;
    this.pane.appendChild(this.canvas);
    map.on('move zoom resize', ()=>this.reset());
    this.reset();
    this.features = [];      // [{fid, geom}]
    this.fieldWindows = {};  // fid -> {start,end,wl_mm}
    this.fieldMeta = {};     // fid -> {wl_opt}
    this.plan = null;
  }
  reset(){
    if (!this.map) return;
    const size = this.map.getSize();
    this.canvas.width = size.x;
    this.canvas.height = size.y;
    this.canvas.style.width = size.x + 'px';
    this.canvas.style.height = size.y + 'px';
    this.redraw(0);
  }
  bind(fieldLayer){
    if (!this.map) return;
    this.fieldLayer = fieldLayer;
    this.features = [];
    fieldLayer.eachLayer(ly=>{
      const geom = ly.feature && ly.feature.geometry;
      const p = ly.feature && ly.feature.properties || {};
      const fid = p.F_id || p.fid || p.id || p.code;
      if (!geom || !fid) return;
      this.features.push({fid: String(fid), geom});
    });
  }
  setPlan(plan, fieldMeta){
    if (!this.map) return;
    this.plan = plan;
    this.fieldMeta = fieldMeta || {};
    this.fieldWindows = {};
    const batches = plan.batches || [];
    const steps = plan.steps || [];
    batches.forEach((b, i)=>{
      let step = steps.find(s => s.label === `批次 ${b.index}`);
      if (!step && steps[i]) step = steps[i];
      if (!step) return;
      (b.fields||[]).forEach(f=>{
        this.fieldWindows[f.id] = {start: step.t_start_h, end: step.t_end_h, wl_mm: f.wl_mm};
      });
    });
    this.total = plan.total_eta_h || 0;
  }
  getRatio(fid, tHour){
    const win = this.fieldWindows[fid];
    if (!win || !isFinite(tHour)) return 0;
    const meta = this.fieldMeta[fid] || {};
    const wl_opt = (meta.wl_opt != null) ? meta.wl_opt : 80.0;
    const d_target = (this.plan && this.plan.calc && this.plan.calc.d_target_mm) || 90.0;

    const start = win.start, end = win.end;
    if (start == null || end == null || end <= start) return 0;
    const prog = (tHour<=start) ? 0 : (tHour>=end ? 1 : (tHour-start)/(end-start));

    const wl0 = (win.wl_mm != null ? win.wl_mm : 0);
    const wl1 = Math.min(wl_opt, wl0 + d_target);
    const r0 = Math.max(0, Math.min(1, wl0 / wl_opt));
    const r1 = Math.max(0, Math.min(1, wl1 / wl_opt));
    return r0 + prog * (r1 - r0);
  }
  redraw(tHour=0){
    if (!this.map) return;
    const ctx = this.ctx;
    ctx.clearRect(0,0,this.canvas.width, this.canvas.height);
    if (!this.enabled || !this.plan || !this.features) return;

    const amp = 6;
    const dens = 0.02;
    this.phase += 0.12;

    this.features.forEach(fe=>{
      const ratio = this.getRatio(fe.fid, tHour);
      if (ratio <= 0) return;

      const bbox = this._geomBounds(fe.geom);
      if (!bbox) return;
      const [minx, miny, maxx, maxy] = bbox;
      const width = maxx - minx, height = maxy - miny;
      const waterH = Math.max(2, height * ratio);
      const yBase = maxy - waterH;

      ctx.save();
      ctx.beginPath();
      this._traceGeom(fe.geom, ctx);
      ctx.clip();

      ctx.fillStyle = 'rgba(59,130,246,0.35)';
      ctx.fillRect(minx, yBase, width, waterH);

      ctx.beginPath();
      ctx.moveTo(minx, yBase);
      const step = 4;
      for (let x = minx; x <= maxx; x += step){
        const y = yBase + amp * Math.sin(x*dens + this.phase);
        ctx.lineTo(x, y);
      }
      ctx.lineTo(maxx, yBase + amp + 8);
      ctx.lineTo(minx, yBase + amp + 8);
      ctx.closePath();
      ctx.fillStyle = 'rgba(59,130,246,0.65)';
      ctx.fill();

      ctx.restore();
    });
  }
  _traceGeom(geom, ctx){
    const toPt = (ll)=> this.map.latLngToLayerPoint([ll[1], ll[0]]);
    const poly = (coords)=>{
      coords.forEach((ring, i)=>{
        ring.forEach((ll, j)=>{
          const p = toPt(ll);
          if (j===0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
        });
      });
    };
    if (geom.type === 'Polygon'){
      ctx.beginPath(); poly(geom.coordinates);
    } else if (geom.type === 'MultiPolygon'){
      geom.coordinates.forEach(co=> { ctx.beginPath(); poly(co); });
    }
  }
  _geomBounds(geom){
    const toPt = (ll)=> this.map.latLngToLayerPoint([ll[1], ll[0]]);
    let minx=Infinity,miny=Infinity,maxx=-Infinity,maxy=-Infinity;
    const accum = (p)=>{ if(p.x<minx)minx=p.x; if(p.y<miny)miny=p.y; if(p.x>maxx)maxx=p.x; if(p.y>maxy)maxy=p.y; };
    if (geom.type === 'Polygon'){
      geom.coordinates.forEach(r=> r.forEach(ll=> accum(toPt(ll))));
    } else if (geom.type === 'MultiPolygon'){
      geom.coordinates.forEach(co=> co.forEach(r=> r.forEach(ll=> accum(toPt(ll)))));
    } else return null;
    return [minx,miny,maxx,maxy];
  }
}

let waterAnim = new WaterAnim(map);

// 调色板（批次）
const batchColors = ['#fde68a','#fca5a5','#a7f3d0','#bfdbfe','#d8b4fe','#fecaca','#c7d2fe','#86efac'];
function renderLegend(n){
  const box = document.getElementById('legend');
  box.innerHTML = '';
  for(let i=0;i<n;i++){
    const c = batchColors[i % batchColors.length];
    const span = document.createElement('span');
    span.style.display = 'inline-flex'; span.style.alignItems='center'; span.style.gap='6px';
    span.innerHTML = `<span class="dot" style="background:${c}; border:1px solid #999;"></span> 批次${i+1}`;
    box.appendChild(span);
  }
}

// 简易 fetch（集中错误处理）
async function fetchJson(url, opt){
  const r = await fetch(url, opt);
  const txt = await r.text();
  if(!r.ok){
    let msg = txt || r.statusText || '请求失败';
    try { const j = JSON.parse(txt); msg = (j.message || j.detail || j.error || msg); } catch(e){}
    throw new Error(msg);
  }
  return txt ? JSON.parse(txt) : {};
}

function setBusy(btn, busy, labelLoading='处理中…', labelNormal='生成并加载计划'){
  if (!btn) return;
  btn.disabled = !!busy;
  btn.textContent = busy ? labelLoading : labelNormal;
  btn.style.opacity = busy ? 0.7 : 1;
}

function setSummary(text, isError=false){
  const box = document.getElementById('planSummary');
  const err = document.getElementById('errBox');
  if (isError){
    if (box) box.textContent = '（加载失败）';
    if (err) err.textContent = text;
  } else {
    if (box) box.textContent = text;
    if (err) err.textContent = '';
  }
}

// 加图层
async function loadLayers(){
  if (!map){ setSummary('Leaflet 未就绪，无法加载图层', true); return; }
  setSummary('加载图层中…');
  const [fieldData, valveData, waterwayData] = await Promise.all([
    fetchJson('/geojson/fields'),
    fetchJson('/geojson/gates'),
    fetchJson('/geojson?type=waterway'),
  ]);
  fieldLayer.clearLayers().addData(fieldData);
  valveLayer.clearLayers().addData(valveData);
  waterwayLayer.clearLayers().addData(waterwayData);
  waterAnim.bind(fieldLayer);

  try {
    const g = L.featureGroup([fieldLayer, valveLayer, waterwayLayer]);
    map.fitBounds(g.getBounds(), {padding:[20,20]});
  } catch(e) {}
  setSummary('图层已加载');
}
document.getElementById('btnLoadLayers').onclick = ()=>loadLayers().catch(e=>setSummary(e.message||String(e), true));

// 索引：F_id / G_id -> layer
let fieldIndexByFid = {};
let gateIndexByGid = {};
function indexLayersForPlan(){
  fieldIndexByFid = {}; gateIndexByGid = {};
  fieldLayer.eachLayer(ly=>{
    const p = ly.feature && ly.feature.properties || {};
    const fid = p.F_id || p.fid || p.id || p.code;
    if (fid) fieldIndexByFid[String(fid)] = ly;
  });
  valveLayer.eachLayer(ly=>{
    const p = ly.feature && ly.feature.properties || {};
    const gid = p.G_id || p.id || p.code;
    if (gid) gateIndexByGid[String(gid)] = ly;
  });
}

/* ================== Gate 角色与排序辅助 ================== */
let gateTypeIdx = {};
let regulatorSet = new Set();
let segRankIdx = {};
function buildGateIndexes(cfg){
  gateTypeIdx = {};
  regulatorSet = new Set();
  segRankIdx = {};
  if (cfg && Array.isArray(cfg.gates)){
    cfg.gates.forEach(g => {
      if (g && g.id) gateTypeIdx[String(g.id)] = String(g.type || '').toLowerCase();
    });
  }
  if (cfg && Array.isArray(cfg.segments)){
    cfg.segments.forEach(s => {
      const sid = String(s.id);
      const rids = [];
      if (Array.isArray(s.regulator_gate_ids)) rids.push(...s.regulator_gate_ids);
      if (s.regulator_gate_id) rids.push(s.regulator_gate_id);
      rids.forEach(id => regulatorSet.add(String(id)));
      const mr = String(sid).match(/^S(\d+)/i);
      segRankIdx[sid] = parseInt(s.distance_rank ?? (mr ? mr[1] : 1e9), 10);
    });
  }
}
function gateSeq(gid){ const m = String(gid).match(/-G(\d+)/i); return m? parseInt(m[1],10): null; }
function segIdFromGate(gid){ const m = String(gid).match(/^(S\d+)-G\d+/i); return m? m[1]: null; }
function inletGateFromFieldId(fid){ const m = String(fid).match(/^(S\d+)-(G\d+)-F\d+/i); return m? `${m[1]}-${m[2]}`: null; }
function segRankOfGate(gid){
  const sid = segIdFromGate(gid);
  if (sid && segRankIdx[sid]!=null) return segRankIdx[sid];
  const m = String(sid||'').match(/^S(\d+)/i); return m? parseInt(m[1],10): 1e9;
}
/* ============================================================ */

// 渲染：按批次给田块上色
function colorFieldsByBatch(plan){
  fieldLayer.eachLayer(ly => ly.setStyle({fillOpacity:0.35, fillColor:'#93c5fd', color:'#1e3a8a', weight:1}));
  (plan.batches || []).forEach((b, bi)=>{
    const color = batchColors[bi % batchColors.length];
    (b.fields || []).forEach(f=>{
      const ly = fieldIndexByFid[f.id];
      if(ly){
        ly.setStyle({fillColor:color, fillOpacity:0.75, color:'#1e3a8a', weight:2});
        const w = (f.wl_mm!=null && !isNaN(f.wl_mm)) ? f.wl_mm.toFixed(1) : '-';
        ly.bindTooltip(`批次${b.index}｜田块 ${fieldLabel(f.id)}｜WL=${w}mm`);
      }
    });
  });
}

// ======= 步骤面板 =======
function renderSteps(plan){
  const box = document.getElementById('stepList');
  const rows = [];
  const icon = (t)=>{
    switch(String(t)){
      case 'pump_on': return '🟢 泵启动';
      case 'pump_off': return '🔴 泵停止';
      case 'regulator_open': return '🟩 开闸';
      case 'regulator_close': return '🟥 关闸';
      case 'regulator_set': return '🟩 设定';
      case 'field': return '🟦 田块';
      default: return '•';
    }
  };

  (plan.steps || []).forEach((s, i)=>{
    const title = s.label || `批次 ${i+1}`;
    rows.push(`<div style="margin:8px 0 4px; font-weight:700;">${title} <span class="muted">(${Number(s.t_start_h).toFixed(2)}→${Number(s.t_end_h).toFixed(2)} h)</span></div>`);

    // 1) 分块顺序
    const seq = s.sequence || {};
    const pumps_on  = (seq.pumps_on  || []).map(x=>`<code>${x}</code>`).join(' → ') || '（无）';
    const fields    = (seq.fields    || []).map(x=>`<code>${x}</code>`).join(' → ') || '（无）';
    const pumps_off = (seq.pumps_off || []).map(x=>`<code>${x}</code>`).join(' → ') || '（无）';
    rows.push(`<div class="muted">泵（启用顺序）：${pumps_on}</div>`);

    // 新：节制闸（设定开度，来自 sequence.gates_set）
    const gset = (seq.gates_set||[]).map(g=>`<code>${g.id}</code>→${Number(g.open_pct||0)}%`).join(' ， ') || '（无）';
    rows.push(`<div class="muted">节制闸（设定开度）：${gset}</div>`);

    rows.push(`<div class="muted">田块（灌溉顺序）：${fields}</div>`);
    rows.push(`<div class="muted">泵（停机顺序）：${pumps_off}</div>`);

    // 2) 完整流程：包含 regulator_set
    const full = s.full_order || [];
    if (full.length){
      rows.push(`<div style="margin-top:6px;"><b>完整流程</b></div>`);
      rows.push(`<ol style="margin:6px 0 8px 18px;">${
        full.map(step=>{
          const t = String(step.type||'');
          if (t === 'field'){
            const fid = String(step.id||''); const gid = step.inlet_G_id ? `（${step.inlet_G_id}）` : '';
            return `<li>${icon(t)}：田块 <code>${fid}</code> ${gid}</li>`;
          } else if (t === 'regulator_set'){
            return `<li>${icon(t)}：<code>${String(step.id||'')}</code> → ${Number(step.open_pct||0)}%</li>`;
          }
          return `<li>${icon(t)}：<code>${String(step.id||'')}</code></li>`;
        }).join('')
      }</ol>`);
    }

    // 3) 原始 commands（调试）
    const cmds = s.commands || [];
    if (cmds.length){
      rows.push(`<details style="margin:6px 0;"><summary class="muted">原始指令（调试）</summary>${
        cmds.map(c=>{
          const val = (c.value!=null?` = ${c.value}`:'');
          return `<div style="display:flex; justify-content:space-between; color:#555; font-family:monospace;">
            <span>${String(c.action||'').toUpperCase()} ${c.target}${val}</span>
            <span></span>
          </div>`;
        }).join('')
      }</details>`);
    }
  });

  box.innerHTML = rows.join('') || '<div style="color:#888;">无步骤</div>';
}



// 时间轴 & 闸门高亮
let currentPlan = null, playing = false, tCurrent = 0, tTotal = 0;
function setTimelineProgress(pct){
  document.getElementById('timelineFill').style.width = (pct*100).toFixed(1)+'%';
  document.getElementById('timelineCursor').style.left = (pct*100).toFixed(1)+'%';
}
function highlightGatesAtTime(plan, tHour){
  // 先重置底色
  Object.values(gateIndexByGid).forEach(ly => setGateLayerColor(ly, '#ffd43b'));

  // 在时间窗内点亮：开=绿，关=红
  (plan.steps || []).forEach(s=>{
    if (tHour >= s.t_start_h && tHour <= s.t_end_h){
      (s.commands || []).forEach(c=>{
        const ly = gateIndexByGid[c.target];
        if (!ly) return;
        const act = String(c.action||'').toLowerCase();
        let isOpen = false;
        if (act === 'open') isOpen = true;
        else if (act === 'set') isOpen = Number(c.value||0) > 0;
        else if (act === 'close') isOpen = false;
        setGateLayerColor(ly, isOpen ? '#16a34a' : '#ef4444');
      });
    }
  });
}



function loadPlanToUI(plan, cfgMetaIndex){
  currentPlan = plan;
  tTotal = Number(plan.total_eta_h || 0); tCurrent = 0;
  setSummary(`批次 ${plan.batches?.length||0}｜总ETA ${tTotal.toFixed(2)} h｜需水 ${Number(plan.total_deficit_m3||0).toFixed(0)} m³`);
  renderLegend(plan.batches?.length || 0);
  indexLayersForPlan();
  colorFieldsByBatch(plan);
  renderSteps(plan);
  setTimelineProgress(0);
  highlightGatesAtTime(plan, 0);

  waterAnim.setPlan(plan, cfgMetaIndex || {});
  waterAnim.enabled = document.getElementById('chkWave').checked;
  waterAnim.redraw(0);

  const group = (map ? L.featureGroup() : null);
  if (group){
    (plan.batches||[]).forEach(b => (b.fields||[]).forEach(f => { const ly = fieldIndexByFid[f.id]; if (ly) group.addLayer(ly); }));
    if (group.getLayers().length) map.fitBounds(group.getBounds(), {padding:[16,16]});
  }
}

function play(){
  if(!currentPlan || playing) return;
  playing = true;
  const loop = ()=>{
    if(!playing) return;
    tCurrent += 0.1;
    if (tCurrent > tTotal){ tCurrent = tTotal; playing = false; }
    const pct = (tTotal>0) ? Math.min(1, tCurrent/tTotal) : 0;
    setTimelineProgress(pct);
    highlightGatesAtTime(currentPlan, tCurrent);
    waterAnim.enabled = document.getElementById('chkWave').checked;
    waterAnim.redraw(tCurrent);
    document.getElementById('timeText').textContent = `${tCurrent.toFixed(2)} h`;
    if (playing) requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}
function pause(){ playing = false; }
document.getElementById('btnPlay').onclick = play;
document.getElementById('btnPause').onclick = pause;


// 纠正上一段里 True/False（若你复制时误把 True 粘进 JS，请改为小写 true/false）
document.getElementById('btnLoadPlan').onclick = async ()=>{
  const btn = document.getElementById('btnLoadPlan');
  try{
    setBusy(btn, true, '计划生成中…');
    // 若图层还没加载，先加载一次（修复：使用 // 注释）
    if (fieldLayer.getLayers().length === 0 || valveLayer.getLayers().length === 0){
      await loadLayers();
    }
    const pumps = document.getElementById('inpPumps').value.trim();
    const zones  = document.getElementById('inpZones').value.trim();
    const realtime = document.getElementById('chkRealtime').checked;
    const url = new URL(location.origin + '/v1/plan');
    if (pumps) url.searchParams.set('pumps', pumps);
    if (zones) url.searchParams.set('zones', zones);
    if (!realtime) url.searchParams.set('no_realtime', '1');

    const [plan, cfg] = await Promise.all([
      fetchJson(url.toString()),
      fetchJson('/config.json').catch(()=>null)
    ]);

    const metaIdx = {};
    if (cfg && Array.isArray(cfg.fields)) {
      cfg.fields.forEach(f => {
        if (!f || !f.id) return;
        metaIdx[String(f.id)] = {
          wl_opt: (f.wl_opt!=null ? f.wl_opt : 80.0),
          sectionCode: f.sectionCode || null,
          name: f.name || null,
          label: (f.sectionCode || f.name || null)
        };
      });
    }
    fieldMeta = metaIdx;
    buildGateIndexes(cfg);
    loadPlanToUI(plan, metaIdx);
  }catch(e){
    setSummary(e.message || String(e), true);
    alert('生成计划失败：' + (e.message || String(e)));
  }finally{
    setBusy(btn, false);
  }
};

document.getElementById('btnReset').onclick = async () => {
  const btn = document.getElementById('btnReset');
  try {
    setBusy(btn, true, "重置中…", "重置（还原初始）");
    // 1) 调后端重置
    await fetchJson("/v1/reset", { method: "POST" });

    // 2) 重新加载底图图层（会读取新的 labeled_output/**）
    await loadLayers();

    // 3) 清空前端的计划/步骤/播放状态
    window.__currentPlan = null;
    if (typeof setTimelineProgress === "function") setTimelineProgress(0);
    const stepUl = document.getElementById("stepList");
    if (stepUl) stepUl.innerHTML = "";
    const sumDiv = document.getElementById("planSummary");
    if (sumDiv) sumDiv.textContent = "（已重置，尚未生成计划）";

    setSummary("已恢复到初始数据；请点击“生成并加载计划”重新计算。", false);
  } catch (e) {
    setSummary("重置失败：" + (e?.message || String(e)), true);
  } finally {
    setBusy(btn, false, "重置中…", "重置（还原初始）");
  }
};


// ========= 添加闸门 UI =========
let addMode = 'click';
document.querySelectorAll('input[name=addmode]').forEach(r=>{
  r.onchange = ()=>{
    addMode = document.querySelector('input[name=addmode]:checked').value;
    document.getElementById('boxClick').style.display = (addMode==='click')?'block':'none';
    document.getElementById('boxField').style.display = (addMode==='field')?'block':'none';
    setPicking(false);
    document.getElementById('clickHint').textContent = '未启用选点';
    selectedFieldId = null;
    document.getElementById('btnSubmitField').disabled = true;
    document.getElementById('fieldHint').textContent = '未选择田块';
    if (previewMarker){ map.removeLayer(previewMarker); previewMarker = null; }
  };
});

let previewMarker = null;
let lastClickLatLng = null;
let isPicking = false;

function setPicking(on){
  isPicking = !!on;
  const btn = document.getElementById('btnPickOnMap');
  if (btn) btn.textContent = isPicking ? '取消选点' : '开始地图选点';
  const hint = document.getElementById('clickHint');
  if (hint) hint.textContent = isPicking ? '请在地图上点击一个位置作为安装点…（ESC 取消）' : '未启用选点';

  const cont = map && map.getContainer();
  if (cont){
    if (isPicking) cont.classList.add('picking-cursor');
    else cont.classList.remove('picking-cursor');
  }
  if (!isPicking){
    if (previewMarker){ map.removeLayer(previewMarker); previewMarker = null; }
    lastClickLatLng = null;
  }
}

document.getElementById('btnPickOnMap').onclick = ()=>{
  const mode = document.querySelector('input[name=addmode]:checked').value;
  if (mode !== 'click'){
    alert('当前为“为田块安装进水闸”模式，请切换到“地图点选添加闸门”。');
    return;
  }
  setPicking(!isPicking);
};

document.addEventListener('keydown', (e)=>{
  if (e.key === 'Escape' && isPicking) setPicking(false);
});

map && map.on('click', (e)=>{
  if (addMode !== 'click' || !isPicking) return;
  lastClickLatLng = e.latlng;
  if (previewMarker) map.removeLayer(previewMarker);
  previewMarker = L.circleMarker(e.latlng, {radius:7, color:'#111', fillColor:'#22c55e', fillOpacity:0.9, weight:2}).addTo(map);
  document.getElementById('clickHint').textContent = `已选点：${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`;
});

document.getElementById('btnSubmitPoint').onclick = async ()=>{
  if (!lastClickLatLng){
    alert('请先点击“开始地图选点”，然后在地图上选择一个位置');
    return;
  }
  const type = document.getElementById('selGateType').value;
  const qmax = document.getElementById('inpQmax').value;
  const payload = {lat: lastClickLatLng.lat, lng: lastClickLatLng.lng, type};
  if (qmax) payload.q_max_m3ph = Number(qmax);

  try{
    const res = await fetchJson('/v1/gates/add', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    document.getElementById('addResult').textContent = `已添加闸门：${res.gate.id}（段 ${res.gate.S_id}）`;
    setPicking(false);
    await loadLayers();
  }catch(e){
    alert('添加闸门失败：' + (e.message || String(e)));
  }
};

let selectedFieldId = null;
let fieldMeta = {};

function fieldLabel(fid){
  const m = fieldMeta && fieldMeta[String(fid)];
  return (m && (m.label || m.sectionCode || m.name)) ? (m.label || m.sectionCode || m.name) : String(fid);
}

document.getElementById('btnSubmitField').onclick = async ()=>{
  if (!selectedFieldId){ alert('请先点击一个田块'); return; }
  const type = document.getElementById('selGateTypeField').value;
  const qmax = document.getElementById('inpQmaxField').value;
  const payload = {field_id: selectedFieldId, type};
  if (qmax) payload.q_max_m3ph = Number(qmax);
  try{
    const res = await fetchJson('/v1/gates/install_for_field', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    document.getElementById('addResult').textContent = `已为田块 ${selectedFieldId} 安装闸门：${res.gate.id}（段 ${res.gate.S_id}）`;
    await loadLayers();
  }catch(e){
    alert('安装进水闸失败：' + (e.message || String(e)));
  }
};

// 首次自动加载底图层（可注释）
loadLayers().catch(e=>setSummary(e.message||String(e), true));
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return HTML_TEMPLATE

# ====== 主入口 ======
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
