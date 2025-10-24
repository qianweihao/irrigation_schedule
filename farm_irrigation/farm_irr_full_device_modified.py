# -*- coding: utf-8 -*-
"""
多节制闸计划生成核心（规则版，按主渠/支渠比较范围实现）：
- 节制闸开度按规则计算（主渠 vs 其它支渠；支渠 vs 本支渠），与田块闸门顺序解耦：
  * 主渠 main-g：若本批“其它支渠”的所有需灌溉田块闸号 Gy 都 > 该节制闸号 k → 开度 0%；否则 100%
  * 支渠 branch-g/regulator：若本支渠内的所有需灌溉田块闸号 Gy 都 < k → 开度 0%；否则 100%
- 在 steps[*].sequence.gates_set 写入 [{'id':..., 'open_pct':0|100, 'type':...}]；
  并在 steps[*].full_order 里追加 {type:'regulator_set', id, open_pct}
- 指令使用 action='set'（value=0/100）
- 其余：不重编号、跳过 wl_mm=null、NaN 清理、实时水位融合、farm_id 读取等
"""

from __future__ import annotations

import json, math, os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union

# 可选：实时水位
try:
    # 优先使用真实的实时水位API
    from waterlevel_api import fetch_waterlevels  # 期望签名：fetch_waterlevels(farm_id: str, unit: str = "mm")
    print("[DEBUG] 使用真实实时水位API")
except Exception:
    try:
        # 备选方案：使用模拟API
        from mock_waterlevel_api import fetch_waterlevels  # 期望签名：fetch_waterlevels(farm_id: str, unit: str = "mm")
        print("[DEBUG] 真实API不可用，使用模拟实时水位API")
    except Exception:
        fetch_waterlevels = None
        print("[DEBUG] 实时水位API不可用")

# ===================== 数据类 =====================

@dataclass
class Pump:
    name: str
    q_rated_m3ph: float
    efficiency: float = 0.8
    power_kw: float = 0.0
    electricity_price: float = 0.0

@dataclass
class Segment:
    id: str                 # Sx（基段）
    canal_id: str
    distance_rank: int = 1
    regulator_gate_ids: List[str] = field(default_factory=list)  # 建议填 Sx-Gy 的顺序
    regulator_gate_id: Optional[str] = None
    feed_by: List[str] = field(default_factory=list)
    supply_zone: Optional[str] = None

@dataclass
class Gate:
    id: str                 # 一般是 Sx-Gy
    type: str               # main-g / branch-g / regulator / inlet-g / ...
    q_max_m3ph: float = 9999.0

@dataclass
class FieldPlot:
    id: str                 # 形如 Sx-Gy-Fzz（原编号）
    area_mu: float
    canal_id: str
    segment_id: str         # 允许是 Sx（基段）
    distance_rank: int
    wl_mm: Optional[float] = None
    wl_low: float = 30.0
    wl_opt: float = 80.0
    wl_high: float = 140.0
    has_drain_gate: bool = True
    rel_to_regulator: str = "downstream"
    inlet_gid: Optional[str] = None   # 形如 Sx-Gy

@dataclass
class Batch:
    index: int
    fields: List[FieldPlot] = field(default_factory=list)
    @property
    def area_mu(self) -> float:
        return sum(f.area_mu for f in self.fields)

@dataclass
class BatchStat:
    deficit_vol_m3: float
    cap_vol_m3: float
    eta_hours: float

@dataclass
class Command:
    action: str               # open/close/start/stop/set
    target: str               # gate id / pump name / field id
    value: Optional[float] = None
    t_start_h: float = 0.0
    t_end_h: float = 0.0

@dataclass
class Step:
    t_start_h: float
    t_end_h: float
    commands: List[Command] = field(default_factory=list)
    label: str = ""   # 如 “批次 1”
    sequence: Dict[str, Any] = field(default_factory=dict)   # 含 gates_set
    full_order: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class Plan:
    calc: dict
    drainage_targets: List[str]
    batches: List[Batch]
    batch_stats: List[BatchStat]
    steps: List[Step]

@dataclass
class PumpTimeConstraint:
    """泵时间约束数据结构"""
    pump_name: str
    start_hour: float  # 开始时间（小时）
    end_hour: float    # 结束时间（小时）
    flow_rate: float   # 流量 m³/h

@dataclass
class FarmConfig:
    pump: Pump
    segments: Dict[str, Segment]
    gates: Dict[str, Gate]
    fields: Dict[str, FieldPlot]
    t_win_h: float = 20.0
    d_target_mm: float = 90.0
    active_pumps: List[str] = field(default_factory=list)
    allowed_zones: Optional[List[str]] = None
    original_config_data: Optional[Dict[str, Any]] = None
    pump_time_constraints: Optional[List[PumpTimeConstraint]] = None  # 泵时间约束（可选）

# ===================== 工具 =====================

def _as_float(x, default=None):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)): return default
        if isinstance(x, str) and x.strip().lower() == "nan": return default
        return float(x)
    except Exception:
        return default

def _norm_id(x) -> Optional[str]:
    if x is None: return None
    s = str(x).strip().lstrip("0")
    return s or None

def _norm_code(x) -> Optional[str]:
    if x is None: return None
    s = str(x).strip()
    return s or None

def _rows_to_wl_maps(rows: List[dict]) -> Tuple[Dict[str,float], Dict[str,float]]:
    by_sid, by_code = {}, {}
    for r in rows or []:
        sid  = _norm_id(r.get("sectionID"))
        code = _norm_code(r.get("sectionCode"))
        v = _as_float(r.get("waterlevel_mm"), None)
        if v is None: continue
        if sid:  by_sid[sid]  = v
        if code: by_code[code] = v
    return by_sid, by_code

def _get_gate_seq(gid: str) -> Optional[int]:
    """S4-G24 → 24；不符合格式返回 None"""
    try:
        if not gid: return None
        if "-G" in gid:
            part = gid.split("-G", 1)[1]
            num = "".join(ch for ch in part if ch.isdigit())
            return int(num) if num else None
        return None
    except Exception:
        return None

def _base_sid(segid: Optional[str]) -> Optional[str]:
    """把 Sx-Gy 取前缀 → Sx；否则原样返回"""
    if not segid: return segid
    return segid.split("-G")[0] if "-G" in segid else segid

def _list_intersects(a: List[str], b: List[str]) -> bool:
    if not a: return True
    if not b: return False
    sa = set(x.strip() for x in a if x.strip())
    sb = set(x.strip() for x in b if x.strip())
    return len(sa.intersection(sb)) > 0

# 递归把 NaN/Inf → None（保证 JSON 合法）
def _sanitize_json(o):
    if isinstance(o, dict):
        return {k: _sanitize_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sanitize_json(v) for v in o]
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o): return None
        return o
    return o

# ===================== 读取配置 =====================

def farmcfg_from_json_select(config: Union[str, Dict[str, Any]],
                             active_pumps: Optional[List[str]] = None,
                             zone_ids: Optional[List[str]] = None,
                             use_realtime_wl: bool = False,
                             realtime_rows: Optional[List[dict]] = None) -> FarmConfig:
    if isinstance(config, str):
        data = json.loads(open(config, "r", encoding="utf-8").read())
    else:
        data = dict(config)

    # 从 config 顶层读取 farm_id；允许环境变量覆盖
    farm_id = (os.environ.get("RICE_IRRIGATION_FARM_ID")
               or os.environ.get("FARM_ID")
               or os.environ.get("FARMID")
               or data.get("farm_id"))

    # 泵
    all_pumps = [p.get("name") for p in data.get("pumps") or [] if p.get("name")]
    if not all_pumps:
        all_pumps = [data.get("pump",{}).get("name") or "P1"]
    if not active_pumps:
        active_pumps = list(all_pumps)

    pump_objs = [p for p in (data.get("pumps") or []) if p.get("name") in active_pumps]
    if not pump_objs:
        pump_objs = [{
            "name": "+".join(active_pumps),
            "q_rated_m3ph": sum(_as_float(pp.get("q_rated_m3ph"), 0.0) or 0.0 for pp in (data.get("pumps") or [])),
            "efficiency": _as_float(data.get("pump", {}).get("efficiency"), 0.8) or 0.8,
            "power_kw": sum(_as_float(pp.get("power_kw"), 0.0) or 0.0 for pp in (data.get("pumps") or [])),
            "electricity_price": max(_as_float(pp.get("electricity_price"), 0.0) or 0.0 for pp in (data.get("pumps") or []))
        }]
    q_sum = sum((_as_float(p.get("q_rated_m3ph"), 0.0) or 0.0) * (_as_float(p.get("efficiency"), 0.8) or 0.8)
                for p in pump_objs)
    eff   = max(_as_float(p.get("efficiency"), 0.8) or 0.8 for p in pump_objs) if pump_objs else 0.8
    power_sum = sum(_as_float(p.get("power_kw"), 0.0) or 0.0 for p in pump_objs)
    price_avg = (sum(_as_float(p.get("electricity_price"), 0.0) or 0.0 for p in pump_objs) / len(pump_objs)) if pump_objs else 0.0
    pump  = Pump(name="+".join(active_pumps), q_rated_m3ph=q_sum, efficiency=eff, 
                 power_kw=power_sum, electricity_price=price_avg)

    # 闸门/段
    gates: Dict[str, Gate] = {}
    for g in data.get("gates", []) or []:
        gid = str(g["id"])
        gates[gid] = Gate(
            id=gid,
            type=str(g.get("type","")).lower() or "regulator",
            q_max_m3ph=_as_float(g.get("q_max_m3ph"), 9999.0) or 9999.0
        )

    def _parse_feed_by(s):
        if s is None: return []
        if isinstance(s, list): return [str(x).strip() for x in s if str(x).strip()]
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

    segments: Dict[str, Segment] = {}
    for s in data.get("segments", []) or []:
        regs = list(s.get("regulator_gate_ids") or [])
        if s.get("regulator_gate_id") and s["regulator_gate_id"] not in regs:
            regs.append(s["regulator_gate_id"])
        segments[str(s["id"])] = Segment(
            id=str(s["id"]),                                 # 这里是 Sx（基段）
            canal_id=str(s.get("canal_id","C_A")),
            distance_rank=int(s.get("distance_rank",1)),
            regulator_gate_ids=regs,
            regulator_gate_id=s.get("regulator_gate_id"),
            feed_by=_parse_feed_by(s.get("feed_by")),
            supply_zone=s.get("supply_zone")
        )

    # 实时水位
    wl_by_sid, wl_by_code = {}, {}
    if use_realtime_wl and realtime_rows is None and callable(fetch_waterlevels) and farm_id:
        try:
            realtime_rows = fetch_waterlevels(farm_id)  # 关键：传 farm_id
        except Exception:
            realtime_rows = None
    if realtime_rows:
        wl_by_sid, wl_by_code = _rows_to_wl_maps(realtime_rows)

    # 田块
    fields: Dict[str, FieldPlot] = {}
    for f in data.get("fields", []) or []:
        fid = str(f["id"])
        wl = _as_float(f.get("wl_mm"), None)   # 默认 None，不造 NaN
        if use_realtime_wl and (wl_by_sid or wl_by_code):
            sid = _norm_id(f.get("sectionID"))
            if (sid and (sid in wl_by_sid)):
                wl = wl_by_sid[sid]
            else:
                scode = _norm_code(f.get("sectionCode"))
                if scode and (scode in wl_by_code):
                    wl = wl_by_code[scode]
        fields[fid] = FieldPlot(
            id=fid,
            area_mu=_as_float(f.get("area_mu"), 1.0) or 1.0,
            canal_id=str(f.get("canal_id","C_A")),
            segment_id=str(f.get("segment_id")),                 # 这里预期是 Sx（基段）
            distance_rank=int(f.get("distance_rank",1)),
            wl_mm=wl,
            wl_opt=_as_float(f.get("wl_opt"), 100.0) or 100.0,
            wl_low=_as_float(f.get("wl_low"), 80.0) or 80.0,
            wl_high=_as_float(f.get("wl_high"), 140.0) or 140.0,
            has_drain_gate=bool(f.get("has_drain_gate", True)),
            rel_to_regulator=str(f.get("rel_to_regulator","downstream")),
            inlet_gid=(str(f["inlet_G_id"]) if f.get("inlet_G_id") else None)  # 这里预期是 Sx-Gy
        )

    return FarmConfig(
        pump=pump,
        segments=segments,
        gates=gates,
        fields=fields,
        t_win_h=_as_float(data.get("t_win_h"), 20.0) or 20.0,
        d_target_mm=_as_float(data.get("d_target_mm"), 90.0) or 90.0,
        active_pumps=list(active_pumps),
        allowed_zones=(list(zone_ids) if zone_ids else None),
        original_config_data=data
    )

# ===================== 规则与排序 =====================

def _regulators_for_segment(sid: str,
                            seg: Optional[Segment],
                            flist: List[FieldPlot],
                            cfg: FarmConfig) -> List[str]:
    """返回该段的节制闸候选（按 G 号升序）"""
    regs: List[str] = []

    # 1) segment 提供
    if seg:
        base = list(seg.regulator_gate_ids or [])
        if seg.regulator_gate_id and seg.regulator_gate_id not in base:
            base.append(seg.regulator_gate_id)
        regs.extend(base)

    # 2) gates[] 推断
    if not regs and cfg.gates:
        cand = []
        for gid, gobj in cfg.gates.items():
            gtype = (gobj.type or "").lower()
            if gtype in ("main-g", "branch-g", "regulator"):
                if str(gid).startswith(f"{sid}-G"):
                    cand.append(str(gid))
        if cand:
            regs.extend(sorted(set(cand), key=lambda x: (_get_gate_seq(x) or 999999, x)))

    # 3) 田块入口闸兜底
    if not regs and flist:
        guess = set()
        for f in flist:
            gid = f.inlet_gid
            if not gid and f.id and "-F" in str(f.id):
                parts = str(f.id).split("-F")[0]
                if parts and "-G" in parts:
                    gid = parts
            if gid and gid.startswith(f"{sid}-G"):
                guess.add(gid)
        regs.extend(sorted(guess, key=lambda x: (_get_gate_seq(x) or 999999, x)))

    # 去重并排序
    seen, uniq = set(), []
    for g in regs:
        if g not in seen:
            seen.add(g); uniq.append(g)
    uniq.sort(key=lambda x: (_get_gate_seq(x) or 999999, x))
    return uniq

def _open_pct_for_regulator(gid: str, gtype: str, flist: List[FieldPlot]) -> int:
    """
    计算开度（0 或 100）：
      - main-g：若比较集合（本批“其它支渠”）所有田块 Gy > k → 0；否则 100
      - branch-g/regulator：若比较集合（本支渠）所有田块 Gy < k → 0；否则 100
    说明：Gy 来自（优先）f.inlet_G_id 的 G 号，否则从 f.id 的 'Sx-Gy-Fzz' 提取。
    """
    k = _get_gate_seq(gid)
    if k is None:
        return 0
    gy_list: List[int] = []
    for f in flist:
        g = f.inlet_gid
        if not g and f.id and "-F" in f.id:
            g = f.id.split("-F")[0]
        gy = _get_gate_seq(g) if g else None
        if gy is not None:
            gy_list.append(gy)
    if not gy_list:
        return 0
    t = (gtype or "").lower()
    if t == "main-g":
        return 0 if all(gy > k for gy in gy_list) else 100
    else:  # branch-g / regulator
        return 0 if all(gy < k for gy in gy_list) else 100

# ===================== 计划计算 =====================

def _per_mu_volume_m3(d_target_mm: float) -> float:
    # 1 亩·mm ≈ 0.666667 m3
    return 0.666667 * float(d_target_mm)

def _q_avail(cfg: FarmConfig) -> float:
    return float(cfg.pump.q_rated_m3ph)

def _segment_reachable(seg: Segment, active_pumps: List[str]) -> bool:
    return _list_intersects(seg.feed_by, active_pumps)

@dataclass
class TimeSlot:
    """时间段数据结构"""
    start_hour: float
    end_hour: float
    active_pumps: List[str]
    total_flow_rate: float

def _build_time_constrained_plan(cfg: FarmConfig) -> Plan:
    """基于泵时间约束的批次生成算法"""
    if not cfg.pump_time_constraints:
        raise ValueError("pump_time_constraints is required for time-constrained planning")
    
    per_mu_m3 = _per_mu_volume_m3(cfg.d_target_mm)
    
    # 1) 解析泵时间窗口，生成时间段
    time_points = set()
    for constraint in cfg.pump_time_constraints:
        time_points.add(constraint.start_hour)
        time_points.add(constraint.end_hour)
    
    time_points = sorted(time_points)
    time_slots: List[TimeSlot] = []
    
    for i in range(len(time_points) - 1):
        start_h = time_points[i]
        end_h = time_points[i + 1]
        
        # 找出在此时间段内活跃的泵
        active_pumps = []
        total_flow = 0.0
        
        for constraint in cfg.pump_time_constraints:
            if constraint.start_hour <= start_h and end_h <= constraint.end_hour:
                active_pumps.append(constraint.pump_name)
                total_flow += constraint.flow_rate
        
        if active_pumps:  # 只有当有泵活跃时才创建时间段
            time_slots.append(TimeSlot(
                start_hour=start_h,
                end_hour=end_h,
                active_pumps=active_pumps,
                total_flow_rate=total_flow
            ))
    
    # 2) 可达段过滤（基于所有可能的活跃泵）
    all_possible_pumps = set()
    for constraint in cfg.pump_time_constraints:
        all_possible_pumps.add(constraint.pump_name)
    
    reachable_sids: List[str] = []
    filtered_by_feed_by = 0
    for sid, s in cfg.segments.items():
        if cfg.allowed_zones and s.supply_zone and (s.supply_zone not in cfg.allowed_zones):
            continue
        if _segment_reachable(s, list(all_possible_pumps)):
            reachable_sids.append(sid)
        else:
            filtered_by_feed_by += 1
    
    # 3) 田块过滤和排序
    eligible_fields: List[FieldPlot] = []
    skipped_null_wl: List[FieldPlot] = []
    for f in cfg.fields.values():
        base = _base_sid(f.segment_id)
        if base not in reachable_sids:
            continue
        if (f.wl_mm is None) or (isinstance(f.wl_mm, float) and math.isnan(f.wl_mm)):
            skipped_null_wl.append(f)
            continue
        eligible_fields.append(f)
    
    seg_rank = {sid: cfg.segments[sid].distance_rank for sid in reachable_sids}
    eligible_fields.sort(
        key=lambda f: (seg_rank.get(_base_sid(f.segment_id), 9999), f.distance_rank, f.id)
    )
    
    # 4) 按时间段分配田块
    batches: List[Batch] = []
    batch_stats: List[BatchStat] = []
    steps: List[Step] = []
    
    remaining_fields = list(eligible_fields)
    
    for slot_idx, slot in enumerate(time_slots):
        if not remaining_fields:
            break
            
        # 计算此时间段的灌溉能力
        slot_duration = slot.end_hour - slot.start_hour
        max_volume = slot.total_flow_rate * slot_duration
        max_area = max_volume / per_mu_m3 if per_mu_m3 > 0 else 0
        
        # 分配田块到此时间段
        batch_fields = []
        acc_area = 0.0
        
        fields_to_remove = []
        for f in remaining_fields:
            if acc_area + f.area_mu <= max_area:
                batch_fields.append(f)
                acc_area += f.area_mu
                fields_to_remove.append(f)
        
        # 从剩余田块中移除已分配的
        for f in fields_to_remove:
            remaining_fields.remove(f)
        
        if batch_fields:
            # 创建批次
            batch = Batch(index=len(batches) + 1, fields=batch_fields)
            batches.append(batch)
            
            # 计算批次统计
            need_m3 = batch.area_mu * per_mu_m3
            eta_h = slot_duration  # 使用时间段的持续时间
            batch_stats.append(BatchStat(
                deficit_vol_m3=need_m3,
                cap_vol_m3=max_volume,
                eta_hours=eta_h
            ))
            
            # 创建步骤
            step = _create_time_slot_step(cfg, batch, slot, slot_idx + 1)
            steps.append(step)
    
    # 5) 计算信息
    calc = {
        "time_constrained": True,
        "time_slots_count": len(time_slots),
        "total_pumps": len(all_possible_pumps),
        "d_target_mm": cfg.d_target_mm,
        "filtered_by_feed_by": filtered_by_feed_by,
        "allowed_zones": list(cfg.allowed_zones) if cfg.allowed_zones else None,
        "skipped_null_wl_count": len(skipped_null_wl),
        "skipped_null_wl_fields": [f.id for f in skipped_null_wl],
        "remaining_fields_count": len(remaining_fields),
        "pump": cfg.pump,
    }
    
    return Plan(calc=calc,
                drainage_targets=[],
                batches=batches,
                batch_stats=batch_stats,
                steps=steps)

def _create_time_slot_step(cfg: FarmConfig, batch: Batch, slot: TimeSlot, batch_index: int) -> Step:
    """为时间段创建执行步骤"""
    per_mu_m3 = _per_mu_volume_m3(cfg.d_target_mm)
    
    # 计算涉及的段
    seg_to_fields: Dict[str, List[FieldPlot]] = {}
    for f in batch.fields:
        seg_to_fields.setdefault(_base_sid(f.segment_id), []).append(f)
    sids_with_fields = set(seg_to_fields.keys())
    
    # 获取段排序
    seg_rank = {sid: cfg.segments[sid].distance_rank for sid in cfg.segments.keys()}
    
    # 额外纳入拥有main-g的段
    main_sids_with_gates: set[str] = set()
    for sid, seg in cfg.segments.items():
        regs = _regulators_for_segment(sid, seg, seg_to_fields.get(sid, []), cfg)
        if any(((cfg.gates.get(gid).type or "").lower() == "main-g") for gid in regs):
            main_sids_with_gates.add(sid)
    
    all_sids = sorted(sids_with_fields.union(main_sids_with_gates), key=lambda x: seg_rank.get(x, 9999))
    
    # 节制闸设定
    gates_set_all: List[Dict[str, Any]] = []
    regs_to_open: List[str] = []
    regs_to_close: List[str] = []
    
    for sid in all_sids:
        seg = cfg.segments.get(sid)
        flist_same = seg_to_fields.get(sid, [])
        regs_sorted = _regulators_for_segment(sid, seg, flist_same, cfg)
        
        for gid in regs_sorted:
            gtype = (cfg.gates.get(gid).type if gid in cfg.gates else "regulator") or "regulator"
            if gtype.lower() == "main-g":
                cmp_fields = [f for f in batch.fields if _base_sid(f.segment_id) != sid]
            else:
                cmp_fields = flist_same
            
            pct = _open_pct_for_regulator(gid, gtype, cmp_fields)
            gates_set_all.append({"id": gid, "open_pct": pct, "type": gtype})
            (regs_to_open if pct > 0 else regs_to_close).append(gid)
    
    # 田块顺序
    fields_order = [f.id for f in batch.fields]
    
    # 结构化顺序
    seq = {
        "pumps_on": slot.active_pumps,
        "gates_open": regs_to_open,
        "gates_close": regs_to_close,
        "gates_set": gates_set_all,
        "fields": fields_order,
        "pumps_off": list(reversed(slot.active_pumps))
    }
    
    # 完整流程
    full: List[Dict[str, Any]] = []
    for pnm in slot.active_pumps:
        full.append({"type": "pump_on", "id": pnm})
    for g in gates_set_all:
        full.append({"type": "regulator_set", "id": g["id"], "open_pct": g["open_pct"]})
    for f in batch.fields:
        full.append({"type": "field", "id": f.id, "inlet_G_id": (f.inlet_gid or None)})
    for pnm in reversed(slot.active_pumps):
        full.append({"type": "pump_off", "id": pnm})
    
    # 指令列表
    cmds: List[Command] = []
    for pnm in slot.active_pumps:
        cmds.append(Command(action="start", target=pnm, t_start_h=slot.start_hour, t_end_h=slot.end_hour))
    for g in gates_set_all:
        cmds.append(Command(action="set", target=g["id"], value=float(g["open_pct"]), 
                          t_start_h=slot.start_hour, t_end_h=slot.end_hour))
    for pnm in slot.active_pumps:
        cmds.append(Command(action="stop", target=pnm, t_start_h=slot.start_hour, t_end_h=slot.end_hour))
    
    return Step(
        t_start_h=slot.start_hour,
        t_end_h=slot.end_hour,
        commands=cmds,
        label=f"时间段 {batch_index} ({slot.start_hour:.1f}h-{slot.end_hour:.1f}h)",
        sequence=seq,
        full_order=full
    )

def build_concurrent_plan(cfg: FarmConfig) -> Plan:
    """
    构建灌溉计划
    - 如果cfg.pump_time_constraints存在，使用时间约束的并行批次逻辑
    - 否则使用传统的顺序批次逻辑
    """
    # 检查是否有泵时间约束
    if cfg.pump_time_constraints:
        return _build_time_constrained_plan(cfg)
    
    # 传统逻辑
    q_av = _q_avail(cfg)
    per_mu_m3 = _per_mu_volume_m3(cfg.d_target_mm)
    A_cover_mu = (q_av * cfg.t_win_h) / (per_mu_m3 if per_mu_m3 > 0 else 1e9)

    # 1) 可达段
    reachable_sids: List[str] = []
    filtered_by_feed_by = 0
    for sid, s in cfg.segments.items():
        if cfg.allowed_zones and s.supply_zone and (s.supply_zone not in cfg.allowed_zones):
            continue
        if _segment_reachable(s, cfg.active_pumps):
            reachable_sids.append(sid)
        else:
            filtered_by_feed_by += 1

    # 2) 田块过滤（wl_mm 为 None/NaN 的跳过）
    eligible_fields: List[FieldPlot] = []
    skipped_null_wl: List[FieldPlot] = []
    for f in cfg.fields.values():
        base = _base_sid(f.segment_id)
        if base not in reachable_sids:
            continue
        if (f.wl_mm is None) or (isinstance(f.wl_mm, float) and math.isnan(f.wl_mm)):
            skipped_null_wl.append(f)
            continue
        eligible_fields.append(f)

    # 3) 排序
    seg_rank = {sid: cfg.segments[sid].distance_rank for sid in reachable_sids}
    eligible_fields.sort(
        key=lambda f: (seg_rank.get(_base_sid(f.segment_id), 9999), f.distance_rank, f.id)
    )

    # 4) 分批（覆盖面积不超过泵能力 × 时窗）
    batches: List[Batch] = []
    cur, acc = [], 0.0
    for f in eligible_fields:
        if cur and (acc + f.area_mu > A_cover_mu):
            batches.append(Batch(index=len(batches)+1, fields=list(cur)))
            cur, acc = [], 0.0
        cur.append(f); acc += f.area_mu
    if cur:
        batches.append(Batch(index=len(batches)+1, fields=list(cur)))

    # 5) 批次统计与步骤（含主渠+支渠节制闸）
    batch_stats: List[BatchStat] = []
    steps: List[Step] = []
    t_cursor = 0.0

    pumps_on_order  = list(cfg.active_pumps)
    pumps_off_order = list(reversed(cfg.active_pumps))

    for b in batches:
        need_m3 = b.area_mu * per_mu_m3
        eta_h   = (need_m3 / q_av) if q_av > 0 else 0.0
        batch_stats.append(BatchStat(deficit_vol_m3=need_m3, cap_vol_m3=q_av * cfg.t_win_h, eta_hours=eta_h))

        st, ed = t_cursor, t_cursor + eta_h
        t_cursor = ed

        # —— 本批涉及的基段（有田块的段）
        seg_to_fields: Dict[str, List[FieldPlot]] = {}
        for f in b.fields:
            seg_to_fields.setdefault(_base_sid(f.segment_id), []).append(f)
        sids_with_fields = set(seg_to_fields.keys())

        # —— 额外纳入“所有拥有 main-g 的段”（即使该段本批没有田块）
        main_sids_with_gates: set[str] = set()
        for sid, seg in cfg.segments.items():
            regs = _regulators_for_segment(sid, seg, seg_to_fields.get(sid, []), cfg)
            if any(((cfg.gates.get(gid).type or "").lower() == "main-g") for gid in regs):
                main_sids_with_gates.add(sid)

        # —— 合并需要处理的段（主渠段 ∪ 有田块的段），按距离序
        all_sids = sorted(sids_with_fields.union(main_sids_with_gates), key=lambda x: seg_rank.get(x, 9999))

        # —— 节制闸设定（含顺序与开度；主渠按“其它支渠”比较，支渠按“本支渠”比较）
        gates_set_all: List[Dict[str, Any]] = []
        regs_to_open: List[str] = []
        regs_to_close: List[str] = []

        for sid in all_sids:
            seg = cfg.segments.get(sid)
            flist_same = seg_to_fields.get(sid, [])             # 本支渠田块（可能为空）
            regs_sorted = _regulators_for_segment(sid, seg, flist_same, cfg)

            for gid in regs_sorted:
                gtype = (cfg.gates.get(gid).type if gid in cfg.gates else "regulator") or "regulator"
                if gtype.lower() == "main-g":
                    # 主渠：与“其它支渠”的田块比较
                    cmp_fields = [f for f in b.fields if _base_sid(f.segment_id) != sid]
                else:
                    # 支渠：与“本支渠”的田块比较
                    cmp_fields = flist_same

                pct = _open_pct_for_regulator(gid, gtype, cmp_fields)
                gates_set_all.append({"id": gid, "open_pct": pct, "type": gtype})
                (regs_to_open if pct > 0 else regs_to_close).append(gid)

        # —— 田块顺序
        fields_order = [f.id for f in b.fields]

        # —— 结构化顺序（用于前端展示）
        seq = {
            "pumps_on":  pumps_on_order,
            "gates_open": regs_to_open,
            "gates_close": regs_to_close,
            "gates_set": gates_set_all,     # 前端可直接渲染“设定：Sx-Gy → xx%”
            "fields": fields_order,
            "pumps_off": pumps_off_order
        }

        # —— 完整流程（严格时间顺序）
        full: List[Dict[str, Any]] = []
        for pnm in pumps_on_order:
            full.append({"type": "pump_on", "id": pnm})
        for g in gates_set_all:
            full.append({"type": "regulator_set", "id": g["id"], "open_pct": g["open_pct"]})
        for f in b.fields:
            full.append({"type": "field", "id": f.id, "inlet_G_id": (f.inlet_gid or None)})
        for pnm in pumps_off_order:
            full.append({"type": "pump_off", "id": pnm})

        # —— 指令列表（泵启停 + 节制闸开度设定）
        cmds: List[Command] = []
        for pnm in pumps_on_order:
            cmds.append(Command(action="start", target=pnm, t_start_h=st, t_end_h=ed))
        for g in gates_set_all:
            cmds.append(Command(action="set", target=g["id"], value=float(g["open_pct"]), t_start_h=st, t_end_h=ed))
        for pnm in pumps_off_order:
            cmds.append(Command(action="stop", target=pnm, t_start_h=st, t_end_h=ed))

        steps.append(Step(
            t_start_h=st, t_end_h=ed,
            commands=cmds,
            label=f"批次 {b.index}",
            sequence=seq,
            full_order=full
        ))

    calc = {
        "A_cover_mu": A_cover_mu,
        "q_avail_m3ph": q_av,
        "t_win_h": cfg.t_win_h,
        "d_target_mm": cfg.d_target_mm,
        "active_pumps": sorted(list(cfg.active_pumps)),
        "filtered_by_feed_by": filtered_by_feed_by,
        "allowed_zones": list(cfg.allowed_zones) if cfg.allowed_zones else None,
        "skipped_null_wl_count": len(skipped_null_wl),
        "skipped_null_wl_fields": [f.id for f in skipped_null_wl],
        "pump": cfg.pump,  # 添加pump对象以支持电费计算
    }

    return Plan(calc=calc,
                drainage_targets=[],
                batches=batches,
                batch_stats=batch_stats,
                steps=steps)

# ===================== 序列化 =====================

def plan_to_json(plan: Plan) -> Dict[str, Any]:
    # 处理calc字典，确保pump对象可以序列化
    calc_serializable = dict(plan.calc)
    if "pump" in calc_serializable and hasattr(calc_serializable["pump"], "__dict__"):
        # 将Pump对象转换为字典
        pump_obj = calc_serializable["pump"]
        calc_serializable["pump"] = {
            "name": pump_obj.name,
            "q_rated_m3ph": pump_obj.q_rated_m3ph,
            "efficiency": pump_obj.efficiency,
            "power_kw": getattr(pump_obj, "power_kw", 0.0),
            "electricity_price": getattr(pump_obj, "electricity_price", 0.0)
        }
    
    out: Dict[str, Any] = {
        "calc": calc_serializable,
        "drainage_targets": plan.drainage_targets,
        "batches": [],
        "steps": [],
    }
    total_eta = 0.0
    total_deficit = 0.0
    for b, st in zip(plan.batches, plan.batch_stats):
        total_eta += float(st.eta_hours or 0.0)
        total_deficit += float(st.deficit_vol_m3 or 0.0)
        out["batches"].append({
            "index": b.index,
            "area_mu": b.area_mu,
            "fields": [
                {
                    "id": f.id,
                    "area_mu": f.area_mu,
                    "segment_id": f.segment_id,     # Sx
                    "distance_rank": f.distance_rank,
                    "wl_mm": (None if f.wl_mm is None else float(f.wl_mm)),
                    "inlet_G_id": f.inlet_gid       # Sx-Gy
                } for f in b.fields
            ],
            "stats": {
                "deficit_vol_m3": st.deficit_vol_m3,
                "cap_vol_m3": st.cap_vol_m3,
                "eta_hours": st.eta_hours
            }
        })
    for s in plan.steps:
        out["steps"].append({
            "t_start_h": s.t_start_h,
            "t_end_h": s.t_end_h,
            "label": s.label,
            "commands": [
                {"action": c.action, "target": c.target, "value": c.value,
                 "t_start_h": c.t_start_h, "t_end_h": c.t_end_h}
                for c in s.commands
            ],
            "sequence": s.sequence,      # 含 gates_set
            "full_order": s.full_order
        })
    out["total_eta_h"] = total_eta
    out["total_deficit_m3"] = total_deficit
    
    # 添加电费计算
    if "pump" in calc_serializable:
        pump = calc_serializable["pump"]
        if isinstance(pump, dict) and "power_kw" in pump and "electricity_price" in pump:
            power_kw = float(pump.get("power_kw", 0.0))
            electricity_price = float(pump.get("electricity_price", 0.0))
            total_electricity_cost = power_kw * total_eta * electricity_price
            out["total_electricity_cost"] = total_electricity_cost
            out["total_pump_runtime_hours"] = {pump.get("name", "unknown"): total_eta}
        else:
            out["total_electricity_cost"] = 0.0
            out["total_pump_runtime_hours"] = {}
    else:
        out["total_electricity_cost"] = 0.0
        out["total_pump_runtime_hours"] = {}
    
    return _sanitize_json(out)

# ===================== 多水泵方案生成 =====================

def _list_intersects(list1: List[str], list2: List[str]) -> bool:
    """检查两个字符串列表是否有交集"""
    return bool(set(list1) & set(list2))

def _segment_reachable(segment: Segment, active_pumps: List[str]) -> bool:
    """检查段是否可以被激活的水泵覆盖"""
    return _list_intersects(segment.feed_by, active_pumps)

def generate_multi_pump_scenarios(cfg: FarmConfig) -> Dict[str, Any]:
    """
    动态生成多水泵灌溉方案
    
    根据需要灌溉的地块，智能分析所需的水泵组合，
    并生成最优的灌溉方案供用户选择。
    
    Args:
        cfg: 农场配置对象
        
    Returns:
        包含多个方案的字典，每个方案包含成本分析和运行时间
    """
    try:
        # 1. 分析需要灌溉的地块
        fields_to_irrigate = []
        segments_needed = set()
        
        for field_id, field in cfg.fields.items():
            # 检查是否需要灌溉（wl_mm不为None且不为NaN，且水位低于低水位阈值）
            if (field.wl_mm is not None) and not (isinstance(field.wl_mm, float) and field.wl_mm != field.wl_mm):
                # 只有当前水位低于低水位阈值时才需要灌溉
                if field.wl_mm < field.wl_low:
                    fields_to_irrigate.append(field)
                    # 提取基础段ID（去掉子段后缀）
                    base_sid = field.segment_id.split('-')[0] if '-' in field.segment_id else field.segment_id
                    segments_needed.add(base_sid)
        
        if not fields_to_irrigate:
            return {
                "error": "没有找到需要灌溉的地块",
                "analysis": {
                    "total_fields_to_irrigate": 0,
                    "required_segments": [],
                    "segment_pump_requirements": {},
                    "valid_pump_combinations": []
                },
                "scenarios": []
            }
        
        # 2. 分析每个段的水泵需求
        segment_pump_requirements = {}
        for sid in segments_needed:
            segment = cfg.segments.get(sid)
            if segment:
                segment_pump_requirements[sid] = segment.feed_by
            else:
                segment_pump_requirements[sid] = []
        
        # 3. 找出能够覆盖所有段的水泵组合
        all_pumps = cfg.active_pumps
        valid_combinations = []
        
        # 首先尝试单个水泵
        for pump in all_pumps:
            can_cover_all = True
            for sid in segments_needed:
                required_pumps = segment_pump_requirements.get(sid, [])
                if required_pumps and pump not in required_pumps:
                    can_cover_all = False
                    break
            if can_cover_all:
                valid_combinations.append([pump])
        
        # 如果没有单个水泵能覆盖所有段，尝试多水泵组合
        if not valid_combinations:
            from itertools import combinations
            
            # 尝试2个水泵的组合
            for combo in combinations(all_pumps, 2):
                can_cover_all = True
                for sid in segments_needed:
                    required_pumps = segment_pump_requirements.get(sid, [])
                    if required_pumps and not _list_intersects(list(combo), required_pumps):
                        can_cover_all = False
                        break
                if can_cover_all:
                    valid_combinations.append(list(combo))
            
            # 如果还是没有，使用所有水泵
            if not valid_combinations:
                can_cover_all = True
                for sid in segments_needed:
                    required_pumps = segment_pump_requirements.get(sid, [])
                    if required_pumps and not _list_intersects(all_pumps, required_pumps):
                        can_cover_all = False
                        break
                if can_cover_all:
                    valid_combinations.append(all_pumps)
        
        if not valid_combinations:
            return {
                "error": "没有找到能够覆盖所有需要灌溉段的水泵组合",
                "analysis": {
                    "total_fields_to_irrigate": len(fields_to_irrigate),
                    "required_segments": sorted(segments_needed),
                    "segment_pump_requirements": segment_pump_requirements,
                    "valid_pump_combinations": []
                },
                "scenarios": []
            }
        
        # 4. 为每个有效的水泵组合生成灌溉方案
        scenarios = []
        
        for pump_combo in valid_combinations:
            try:
                # 创建该水泵组合的配置
                # 需要传递原始的JSON配置数据，而不是FarmConfig对象
                if cfg.original_config_data:
                    combo_cfg = farmcfg_from_json_select(
                        cfg.original_config_data,  # 使用原始JSON配置数据
                        active_pumps=pump_combo,
                        use_realtime_wl=True  # 修复：使用实时水位数据
                    )
                else:
                    # 如果没有原始配置数据，跳过这个组合
                    print(f"警告: 缺少原始配置数据，跳过水泵组合 {pump_combo}")
                    continue
                
                # 生成灌溉计划
                plan = build_concurrent_plan(combo_cfg)
                plan_json = plan_to_json(plan)
                
                # 计算覆盖的段
                covered_segments = []
                for sid in segments_needed:
                    segment = cfg.segments.get(sid)
                    if segment and _segment_reachable(segment, pump_combo):
                        covered_segments.append(sid)
                
                # 创建方案名称
                if len(pump_combo) == 1:
                    scenario_name = f"{pump_combo[0]}单独使用"
                else:
                    scenario_name = f"{'+'.join(sorted(pump_combo))}组合使用"
                
                # 添加方案信息
                scenario = {
                    "scenario_name": scenario_name,
                    "pumps_used": sorted(pump_combo),
                    "total_electricity_cost": plan_json.get("total_electricity_cost", 0),
                    "total_eta_h": plan_json.get("total_eta_h", 0),
                    "total_pump_runtime_hours": plan_json.get("total_pump_runtime_hours", {}),
                    "coverage_info": {
                        "covered_segments": sorted(covered_segments),
                        "total_covered_segments": len(covered_segments)
                    },
                    "plan": plan_json
                }
                
                scenarios.append(scenario)
                
            except Exception as e:
                # 如果某个组合生成失败，记录错误但继续处理其他组合
                print(f"警告: 水泵组合 {pump_combo} 生成方案失败: {e}")
                continue
        
        # 5. 按电费成本排序
        scenarios.sort(key=lambda x: x.get("total_electricity_cost", float('inf')))
        
        return {
            "analysis": {
                "total_fields_to_irrigate": len(fields_to_irrigate),
                "required_segments": sorted(segments_needed),
                "segment_pump_requirements": segment_pump_requirements,
                "valid_pump_combinations": [sorted(combo) for combo in valid_combinations]
            },
            "scenarios": scenarios,
            "total_scenarios": len(scenarios)
        }
        
    except Exception as e:
        return {
            "error": f"生成多水泵方案时发生错误: {str(e)}",
            "analysis": {
                "total_fields_to_irrigate": 0,
                "required_segments": [],
                "segment_pump_requirements": {},
                "valid_pump_combinations": []
            },
            "scenarios": []
        }
