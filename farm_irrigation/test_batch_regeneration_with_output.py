#!/usr/bin/env python3
"""
使用output文件夹中真实执行计划测试批次重新生成功能
"""

import json
import os
import asyncio
from datetime import datetime
from pathlib import Path
from dynamic_plan_regenerator import DynamicPlanRegenerator, BatchRegenerationResult
from dynamic_waterlevel_manager import WaterLevelReading, WaterLevelSource, WaterLevelQuality

def load_latest_execution_plan():
    """加载最新的执行计划文件"""
    output_dir = Path("output")
    if not output_dir.exists():
        print("❌ output文件夹不存在")
        return None
    
    # 获取所有执行计划文件
    plan_files = list(output_dir.glob("irrigation_plan_*.json"))
    if not plan_files:
        print("❌ 没有找到执行计划文件")
        return None
    
    # 按修改时间排序，获取最新的
    latest_file = max(plan_files, key=lambda f: f.stat().st_mtime)
    print(f"📁 使用最新执行计划: {latest_file.name}")
    
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            plan_data = json.load(f)
        return plan_data, latest_file
    except Exception as e:
        print(f"❌ 加载执行计划失败: {e}")
        return None

def analyze_plan_structure(plan_data):
    """分析计划结构"""
    print("\n=== 计划结构分析 ===")
    
    batches = plan_data.get('batches', [])
    steps = plan_data.get('steps', [])
    
    print(f"批次数量: {len(batches)}")
    print(f"执行步骤数量: {len(steps)}")
    
    # 分析每个批次
    for i, batch in enumerate(batches):
        batch_index = batch.get('index', i+1)
        fields = batch.get('fields', [])
        print(f"  批次 {batch_index}: {len(fields)} 个田块")
        
        # 显示前几个田块的信息
        for j, field in enumerate(fields[:3]):
            field_id = field.get('id')
            water_level = field.get('wl_mm', 0)
            area = field.get('area_mu', 0)
            print(f"    田块 {field_id}: 水位 {water_level}mm, 面积 {area}亩")
        
        if len(fields) > 3:
            print(f"    ... 还有 {len(fields) - 3} 个田块")
    
    # 分析执行步骤
    if steps:
        step = steps[0]  # 查看第一个步骤
        commands = step.get('commands', [])
        print(f"\n第一个执行步骤包含 {len(commands)} 个命令")
        print(f"执行时间: {step.get('t_start_h', 0)}h - {step.get('t_end_h', 0)}h")
    
    return batches, steps

def create_test_water_levels(batch_data):
    """基于批次数据创建测试水位"""
    print("\n=== 创建测试水位数据 ===")
    
    fields = batch_data.get('fields', [])
    if len(fields) < 3:
        print("❌ 批次田块数量不足，无法创建测试数据")
        return None
    
    # 选择前3个田块进行测试
    test_fields = fields[:3]
    water_levels = {}
    
    for field in test_fields:
        field_id = field.get('id')
        original_wl = field.get('wl_mm', 0)
        
        # 创建不同的水位变化场景
        if field_id == test_fields[0]['id']:
            # 第一个田块：水位下降，需要补水
            new_wl = max(0, original_wl - 20)
            scenario = "水位下降，需要补水"
        elif field_id == test_fields[1]['id']:
            # 第二个田块：水位大幅下降，需要更多补水
            new_wl = max(0, original_wl - 30)
            scenario = "水位大幅下降，需要更多补水"
        else:
            # 第三个田块：水位上升，可能减少灌溉
            new_wl = original_wl + 25
            scenario = "水位上升，可能减少灌溉"
        
        water_levels[field_id] = WaterLevelReading(
            field_id=field_id,
            water_level_mm=new_wl,
            timestamp=datetime.now(),
            source=WaterLevelSource.MANUAL,
            quality=WaterLevelQuality.GOOD
        )
        
        print(f"  田块 {field_id}: {original_wl}mm → {new_wl}mm ({scenario})")
    
    return water_levels

async def test_batch_regeneration_with_real_data():
    """使用真实数据测试批次重新生成"""
    print("=== 使用真实执行计划测试批次重新生成 ===")
    
    # 1. 加载最新执行计划
    plan_result = load_latest_execution_plan()
    if not plan_result:
        return
    
    plan_data, plan_file = plan_result
    
    # 2. 分析计划结构
    batches, steps = analyze_plan_structure(plan_data)
    if not batches:
        print("❌ 没有找到批次数据")
        return
    
    # 3. 选择第一个批次进行测试
    test_batch = batches[0]
    batch_index = test_batch.get('index', 1)
    print(f"\n=== 测试批次 {batch_index} 的重新生成 ===")
    
    # 4. 创建测试水位数据
    test_water_levels = create_test_water_levels(test_batch)
    if not test_water_levels:
        return
    
    # 5. 初始化重新生成器
    print("\n=== 初始化重新生成器 ===")
    try:
        # 使用合理的重新生成规则
        regeneration_rules = {
            "water_level_threshold_mm": 5,        # 水位变化阈值
            "water_level_target_mm": 50,          # 目标水位50mm（适合实际数据）
            "water_level_tolerance_mm": 10,       # 水位容差10mm
            "min_irrigation_duration_minutes": 5,
            "max_irrigation_duration_minutes": 120,
            "max_flow_rate_adjustment_ratio": 0.5,
            "enable_smart_scheduling": True
        }
        
        regenerator = DynamicPlanRegenerator(regeneration_rules=regeneration_rules)
        print("✅ 重新生成器初始化成功")
        print(f"目标水位: {regeneration_rules['water_level_target_mm']}mm")
        print(f"水位容差: {regeneration_rules['water_level_tolerance_mm']}mm")
    except Exception as e:
        print(f"❌ 重新生成器初始化失败: {e}")
        return
    
    # 6. 执行批次重新生成
    print(f"\n=== 执行批次 {batch_index} 重新生成 ===")
    
    # 添加调试信息
    print("调试信息:")
    print(f"  阈值设置: {regeneration_rules['water_level_threshold_mm']}mm")
    for field_id, reading in test_water_levels.items():
        print(f"  测试水位 {field_id}: {reading.water_level_mm}mm")
    
    try:
        result = await regenerator.regenerate_batch(
            batch_index,
            plan_data, 
            test_water_levels
        )
        
        print(f"重新生成结果:")
        print(f"  成功: {result.success}")
        print(f"  批次索引: {result.batch_index}")
        print(f"  原始命令数: {len(result.original_commands)}")
        print(f"  重新生成命令数: {len(result.regenerated_commands)}")
        print(f"  变更数: {len(result.changes)}")
        print(f"  执行时间调整: {result.execution_time_adjustment}秒")
        print(f"  总用水量调整: {result.total_water_adjustment}立方米")
        
        # 显示水位变化
        if result.water_level_changes:
            print(f"  水位变化: {result.water_level_changes}")
        
        # 显示变更详情
        if result.changes:
            print("  变更详情:")
            for i, change in enumerate(result.changes, 1):
                print(f"    {i}. {change.change_type.value}: 田块{change.field_id} - {change.old_value} → {change.new_value}")
                print(f"       原因: {change.reason}")
                print(f"       影响级别: {change.impact_level.value}")
        
        # 显示错误信息
        if result.error_message:
            print(f"  错误信息: {result.error_message}")
        
        return result
        
    except Exception as e:
        print(f"❌ 批次重新生成失败: {e}")
        return None

async def main():
    """主函数"""
    result = await test_batch_regeneration_with_real_data()
    
    if result and result.success:
        print("\n✅ 测试成功完成")
    else:
        print("\n❌ 测试失败")

if __name__ == "__main__":
    asyncio.run(main())