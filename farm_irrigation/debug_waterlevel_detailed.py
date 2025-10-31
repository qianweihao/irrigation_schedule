#!/usr/bin/env python3
"""
详细的水位管理器调试脚本
"""

import sys
import os
import traceback
from datetime import datetime, timedelta

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynamic_waterlevel_manager import DynamicWaterLevelManager

def debug_waterlevel_manager():
    """调试水位管理器"""
    print("=== 调试水位管理器 ===")
    
    try:
        # 创建水位管理器实例
        wl_manager = DynamicWaterLevelManager()
        print("✓ 水位管理器创建成功")
        
        # 检查field_histories
        print(f"field_histories 数量: {len(wl_manager.field_histories)}")
        print(f"field_histories 内容: {list(wl_manager.field_histories.keys())}")
        
        # 检查配置数据
        print(f"config_data: {wl_manager.config_data}")
        
        # 检查缓存文件
        cache_file = wl_manager.cache_file
        print(f"缓存文件路径: {cache_file}")
        print(f"缓存文件存在: {cache_file.exists()}")
        
        if cache_file.exists():
            import json
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            print(f"缓存文件内容: {cache_data}")
        
        # 尝试获取水位数据
        print("\n=== 尝试获取水位数据 ===")
        field_id = "1"
        
        # 检查是否有获取水位的方法
        if hasattr(wl_manager, 'get_current_waterlevels'):
            print("尝试获取当前水位...")
            current_levels = wl_manager.get_current_waterlevels([field_id])
            print(f"当前水位: {current_levels}")
        else:
            print("没有找到 get_current_waterlevels 方法")
        
        # 手动添加一些测试数据
        print("\n=== 添加测试数据 ===")
        from dynamic_waterlevel_manager import FieldWaterLevelHistory, WaterLevelReading, WaterLevelSource, WaterLevelQuality
        
        # 创建测试历史数据
        history = FieldWaterLevelHistory(field_id=field_id)
        
        # 添加一些测试读数
        now = datetime.now()
        for i in range(5):
            reading = WaterLevelReading(
                field_id=field_id,
                water_level_mm=100.0 + i * 5,  # 递增的水位
                timestamp=now - timedelta(hours=i*6),
                source=WaterLevelSource.API,
                quality=WaterLevelQuality.GOOD
            )
            history.add_reading(reading)
        
        wl_manager.field_histories[field_id] = history
        print(f"添加了 {len(history.readings)} 条测试数据")
        
        # 现在测试趋势分析
        print("\n=== 测试趋势分析 ===")
        result = wl_manager.get_field_trend_analysis(field_id, 24)
        print(f"趋势分析结果: {result}")
        
        return True
        
    except Exception as e:
        print(f"✗ 调试失败: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    print("开始详细调试水位管理器...")
    debug_waterlevel_manager()
    print("\n调试完成")