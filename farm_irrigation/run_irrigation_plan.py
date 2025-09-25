#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_irrigation_plan.py —— 一键生成灌溉计划
- 读取 config.json(建议先由 auto_to_config.py 生成)
- 支持指定启用泵、供区；默认不拉实时水位（如需实时加 --realtime)
"""
from __future__ import annotations
import json, sys
import io
from pathlib import Path
from typing import Optional, Dict, Any

# 设置输出编码以解决Windows命令行中文显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from farm_irr_full_device_modified import (
    build_concurrent_plan, plan_to_json, farmcfg_from_json_select
)

def _auto_config_path(user_path: Optional[str]) -> Optional[Path]:
    if user_path:
        p = Path(user_path)
        if p.exists(): return p
    for cand in ["config.json", "/mnt/data/config.json"]:
        p = Path(cand)
        if p.exists(): return p
    return None

def _print_summary(plan_json: Dict[str, Any]) -> None:
    batches = plan_json.get("batches", []) or []
    drains  = plan_json.get("drainage_targets", []) or []
    total_eta = plan_json.get("total_eta_h")
    calc = plan_json.get("calc", {}) or {}
    print("====== 灌溉决策摘要 ======")
    if total_eta is not None:
        try: print(f"总 ETA: {float(total_eta):.2f} h")
        except Exception: print("总 ETA:", total_eta)
    if calc:
        t_win = calc.get("t_win_h"); d_tar = calc.get("d_target_mm"); q_av  = calc.get("q_avail_m3ph")
        if t_win is not None: print(f"并灌时窗: {t_win} h")
        if d_tar is not None: print(f"目标补水深: {d_tar} mm")
        if q_av  is not None: print(f"等效泵流量: {q_av} m3/h")
    if drains:
        print(f"并行排水目标: {len(drains)} 个")
        for d in drains[:6]: print(" -", d)
        if len(drains) > 6: print("   ...")
    print(f"灌溉批次: {len(batches)} 批")
    for b in batches:
        eta = ((b.get("stats",{}) or {}).get("eta_hours") or 0.0)
        try: print(f" - 批次{b.get('index')} ETA={float(eta):.2f}h  田块数={len(b.get('fields') or [])}")
        except Exception: print(f" - 批次{b.get('index')} ETA={eta}h  田块数={len(b.get('fields') or [])}")

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="一键生成灌溉计划")
    ap.add_argument("--config","-c", default=None, help="配置文件路径")
    ap.add_argument("--out","-o", default="plan.json", help="输出计划文件（默认 plan.json）")
    ap.add_argument("--pumps","-p", default="", help="启用的泵，逗号分隔，如 P1,P2")
    ap.add_argument("--zones","-z", default="", help="启用的供区，逗号分隔（可选）")
    ap.add_argument("--summary","-s", action="store_true", help="打印摘要到控制台")
    ap.add_argument("--realtime", action="store_true", help="融合实时水位（默认否）")
    
    # 过滤掉 Jupyter notebook 的内核参数
    if argv is None:
        argv = sys.argv[1:]
    filtered_argv = [arg for arg in argv if not arg.startswith('--f=') and not arg.startswith('-f=')]
    
    args = ap.parse_args(filtered_argv)

    cfg_path = _auto_config_path(args.config)
    if not cfg_path:
        sys.stderr.write("[fatal] 未找到 config.json；请先运行 auto_to_config.py 生成。\n")
        sys.exit(2)

    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    active = [s.strip() for s in args.pumps.split(",") if s.strip()] or None
    zones  = [s.strip() for s in args.zones.split(",") if s.strip()] or None

    cfg = farmcfg_from_json_select(
        data, active_pumps=active, zone_ids=zones, use_realtime_wl=args.realtime
    )

    plan = build_concurrent_plan(cfg)
    plan_json = plan_to_json(plan)  # 已递归清理 NaN/Inf
    Path(args.out).write_text(json.dumps(plan_json, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.summary:
        _print_summary(plan_json)

    print(f"[done] 计划已写入：{Path(args.out).resolve()}")

if __name__ == "__main__":
    main()
