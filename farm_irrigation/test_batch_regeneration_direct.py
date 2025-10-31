#!/usr/bin/env python3
"""
直接测试批次重新生成逻辑
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from dynamic_plan_regenerator import DynamicPlanRegenerator
from dynamic_waterlevel_manager import WaterLevelReading, WaterLevelSource, WaterLevelQuality

async def test_batch_regeneration_logic():
    """直接测试批次重新生成逻辑"""
    print("=== 直接测试批次重新生成逻辑 ===")
    
    # 1. 创建测试计划
    print("1. 创建测试计划...")
    test_plan = {
        "plan_id": "test_plan_001",
        "farm_id": "farm_001",
        "created_at": datetime.now().isoformat(),
        "commands": [
            {
                "batch": 1,
                "sectionID": "1",
                "waterlevel_mm": 100.0,
                "duration_minutes": 30,
                "flow_rate": 2.5,
                "start_time": 0.5,
                "pump_id": "pump_001"
            },
            {
                "batch": 1,
                "sectionID": "2", 
                "waterlevel_mm": 95.0,
                "duration_minutes": 25,
                "flow_rate": 2.0,
                "start_time": 0.5,
                "pump_id": "pump_001"
            },
            {
                "batch": 2,
                "sectionID": "3",
                "waterlevel_mm": 105.0,
                "duration_minutes": 35,
                "flow_rate": 3.0,
                "start_time": 1.0,
                "pump_id": "pump_002"
            }
        ]
    }
    
    # 2. 创建新的水位数据（更合理的测试场景）
    print("2. 创建新的水位数据...")
    new_water_levels = {
        "1": WaterLevelReading(
            field_id="1",
            water_level_mm=85.0,  # 从100.0下降到85.0，需要补水
            timestamp=datetime.now(),
            source=WaterLevelSource.MANUAL,
            quality=WaterLevelQuality.GOOD
        ),
        "2": WaterLevelReading(
            field_id="2", 
            water_level_mm=80.0,  # 从95.0下降到80.0，需要补水
            timestamp=datetime.now(),
            source=WaterLevelSource.MANUAL,
            quality=WaterLevelQuality.GOOD
        ),
        "3": WaterLevelReading(
            field_id="3",
            water_level_mm=120.0,  # 从105.0上升到120.0，水位充足，可能取消灌溉
            timestamp=datetime.now(),
            source=WaterLevelSource.MANUAL,
            quality=WaterLevelQuality.GOOD
        )
    }
    
    # 3. 初始化重新生成器（使用更合理的目标水位）
    print("3. 初始化重新生成器...")
    try:
        # 使用更合理的重新生成规则
        regeneration_rules = {
            "water_level_threshold_mm": 5,        # 水位变化阈值
            "water_level_target_mm": 100,         # 目标水位100mm
            "water_level_tolerance_mm": 10,       # 水位容差10mm
            "min_irrigation_duration_minutes": 5,
            "max_irrigation_duration_minutes": 60
        }
        
        regenerator = DynamicPlanRegenerator(regeneration_rules=regeneration_rules)
        print("✅ 重新生成器初始化成功")
        print(f"目标水位: {regeneration_rules['water_level_target_mm']}mm")
        print(f"水位容差: {regeneration_rules['water_level_tolerance_mm']}mm")
    except Exception as e:
        print(f"❌ 重新生成器初始化失败: {e}")
        return
    
    # 4. 测试批次1的重新生成
    print("4. 测试批次1的重新生成...")
    try:
        result = await regenerator.regenerate_batch(
            batch_index=1,
            original_plan=test_plan,
            new_water_levels=new_water_levels
        )
        
        print(f"重新生成结果:")
        print(f"  成功: {result.success}")
        print(f"  批次索引: {result.batch_index}")
        print(f"  原始命令数: {len(result.original_commands)}")
        print(f"  重新生成命令数: {len(result.regenerated_commands)}")
        print(f"  变更数: {len(result.changes)}")
        print(f"  水位变化: {result.water_level_changes}")
        
        if result.error_message:
            print(f"  错误信息: {result.error_message}")
        
        if result.changes:
            print("  变更详情:")
            for i, change in enumerate(result.changes):
                print(f"    {i+1}. {change.change_type.value}: {change.field_id} - {change.old_value} -> {change.new_value}")
                print(f"       原因: {change.reason}")
        
        # 5. 测试变更摘要生成
        print("5. 测试变更摘要生成...")
        if result.changes:
            summary = regenerator.generate_change_summary(result.changes)
            print(f"变更摘要: {summary}")
        
    except Exception as e:
        print(f"❌ 批次重新生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 6. 测试不存在的批次
    print("6. 测试不存在的批次...")
    try:
        result = await regenerator.regenerate_batch(
            batch_index=99,  # 不存在的批次
            original_plan=test_plan,
            new_water_levels=new_water_levels
        )
        
        print(f"不存在批次的结果:")
        print(f"  成功: {result.success}")
        print(f"  错误信息: {result.error_message}")
        
    except Exception as e:
        print(f"❌ 测试不存在批次失败: {e}")

if __name__ == "__main__":
    asyncio.run(test_batch_regeneration_logic())