#!/usr/bin/env python3
"""
调试批次结构和田块命令关系
"""

import json
from pathlib import Path

def analyze_batch_structure():
    """分析批次结构"""
    print("=== 分析批次结构 ===")
    
    # 加载最新的执行计划
    output_dir = Path("output")
    plan_files = list(output_dir.glob("irrigation_plan_*.json"))
    latest_file = max(plan_files, key=lambda f: f.stat().st_mtime)
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    
    print(f"计划文件: {latest_file.name}")
    
    # 分析批次数据
    batches = plan_data.get("batches", [])
    print(f"\n批次数据 ({len(batches)} 个批次):")
    
    for batch in batches:
        batch_index = batch.get("index", "N/A")
        fields = batch.get("fields", [])
        print(f"\n批次 {batch_index}: {len(fields)} 个田块")
        
        # 显示前几个田块的详细信息
        for i, field in enumerate(fields[:5]):
            field_id = field.get("id", "N/A")
            area = field.get("area_mu", 0)
            water_level = field.get("wl_mm", 0)
            inlet_id = field.get("inlet_id", "N/A")
            print(f"  田块 {field_id}: 水位 {water_level}mm, 面积 {area}亩, 进水口 {inlet_id}")
        
        if len(fields) > 5:
            print(f"  ... 还有 {len(fields) - 5} 个田块")
    
    # 分析步骤和命令
    steps = plan_data.get("steps", [])
    print(f"\n执行步骤 ({len(steps)} 个步骤):")
    
    for i, step in enumerate(steps):
        label = step.get("label", f"步骤 {i+1}")
        commands = step.get("commands", [])
        t_start = step.get("t_start_h", 0)
        t_end = step.get("t_end_h", 0)
        
        print(f"\n{label}: {len(commands)} 个命令 ({t_start:.1f}h - {t_end:.1f}h)")
        
        # 分析命令类型
        pump_commands = [cmd for cmd in commands if cmd.get("target", "").startswith("P")]
        valve_commands = [cmd for cmd in commands if cmd.get("target", "").startswith("S")]
        
        print(f"  泵控制命令: {len(pump_commands)}")
        print(f"  阀门控制命令: {len(valve_commands)}")
        
        # 显示前几个命令
        for j, cmd in enumerate(commands[:3]):
            action = cmd.get("action", "N/A")
            target = cmd.get("target", "N/A")
            value = cmd.get("value", "N/A")
            print(f"    命令 {j+1}: {action} {target} = {value}")

def analyze_field_to_command_mapping():
    """分析田块到命令的映射关系"""
    print("\n=== 分析田块到命令的映射关系 ===")
    
    # 加载最新的执行计划
    output_dir = Path("output")
    plan_files = list(output_dir.glob("irrigation_plan_*.json"))
    latest_file = max(plan_files, key=lambda f: f.stat().st_mtime)
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    
    # 获取批次1的田块和命令
    batches = plan_data.get("batches", [])
    batch_1_fields = []
    
    for batch in batches:
        if batch.get("index") == 1:
            batch_1_fields = batch.get("fields", [])
            break
    
    steps = plan_data.get("steps", [])
    batch_1_commands = []
    
    for step in steps:
        if "批次 1" in step.get("label", ""):
            batch_1_commands = step.get("commands", [])
            break
    
    print(f"批次 1 田块数: {len(batch_1_fields)}")
    print(f"批次 1 命令数: {len(batch_1_commands)}")
    
    # 分析田块的进水口
    inlet_ids = set()
    for field in batch_1_fields:
        inlet_id = field.get("inlet_id")
        if inlet_id:
            inlet_ids.add(inlet_id)
    
    print(f"涉及的进水口: {sorted(inlet_ids)}")
    
    # 分析命令的目标
    command_targets = set()
    for cmd in batch_1_commands:
        target = cmd.get("target")
        if target:
            command_targets.add(target)
    
    print(f"命令目标: {sorted(command_targets)}")
    
    # 尝试找到映射关系
    print("\n可能的映射关系:")
    for inlet_id in sorted(inlet_ids):
        # 查找相关的阀门命令
        related_commands = [cmd for cmd in batch_1_commands 
                          if inlet_id in cmd.get("target", "")]
        if related_commands:
            print(f"  进水口 {inlet_id} -> 命令目标: {[cmd.get('target') for cmd in related_commands]}")

def main():
    analyze_batch_structure()
    analyze_field_to_command_mapping()

if __name__ == "__main__":
    main()