#!/usr/bin/env python3
"""
调试批次命令提取逻辑
"""

import json
from pathlib import Path

def debug_plan_structure():
    """调试计划结构"""
    print("=== 调试计划结构 ===")
    
    # 加载最新的执行计划
    output_dir = Path("output")
    plan_files = list(output_dir.glob("irrigation_plan_*.json"))
    latest_file = max(plan_files, key=lambda f: f.stat().st_mtime)
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    
    print(f"计划文件: {latest_file.name}")
    print(f"顶级键: {list(plan_data.keys())}")
    
    # 检查commands字段
    commands = plan_data.get("commands", [])
    print(f"直接commands字段: {len(commands)} 个命令")
    
    # 检查steps字段
    steps = plan_data.get("steps", [])
    print(f"steps字段: {len(steps)} 个步骤")
    
    if steps:
        for i, step in enumerate(steps):
            step_commands = step.get("commands", [])
            print(f"  步骤 {i+1}: {len(step_commands)} 个命令")
            print(f"    标签: {step.get('label', 'N/A')}")
            print(f"    时间: {step.get('t_start_h', 0)}h - {step.get('t_end_h', 0)}h")
            
            # 显示前几个命令
            for j, cmd in enumerate(step_commands[:3]):
                print(f"      命令 {j+1}: {cmd}")
    
    # 检查batches字段
    batches = plan_data.get("batches", [])
    print(f"batches字段: {len(batches)} 个批次")
    
    if batches:
        for batch in batches:
            batch_index = batch.get("index", "N/A")
            fields = batch.get("fields", [])
            print(f"  批次 {batch_index}: {len(fields)} 个田块")

def extract_commands_from_steps(plan_data, target_batch_index):
    """从steps中提取指定批次的命令"""
    print(f"\n=== 从steps中提取批次 {target_batch_index} 的命令 ===")
    
    steps = plan_data.get("steps", [])
    batch_commands = []
    
    for step in steps:
        step_label = step.get("label", "")
        if f"批次 {target_batch_index}" in step_label:
            commands = step.get("commands", [])
            batch_commands.extend(commands)
            print(f"找到匹配步骤: {step_label}")
            print(f"包含 {len(commands)} 个命令")
    
    print(f"总共提取到 {len(batch_commands)} 个命令")
    return batch_commands

def main():
    debug_plan_structure()
    
    # 尝试提取批次1的命令
    output_dir = Path("output")
    plan_files = list(output_dir.glob("irrigation_plan_*.json"))
    latest_file = max(plan_files, key=lambda f: f.stat().st_mtime)
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    
    batch_commands = extract_commands_from_steps(plan_data, 1)
    
    if batch_commands:
        print("\n前3个命令:")
        for i, cmd in enumerate(batch_commands[:3]):
            print(f"  {i+1}. {cmd}")

if __name__ == "__main__":
    main()