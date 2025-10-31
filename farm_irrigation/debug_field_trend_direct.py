#!/usr/bin/env python3
"""
直接测试字段趋势分析功能的调试脚本
"""

import sys
import os
import traceback
from datetime import datetime, timedelta

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynamic_waterlevel_manager import DynamicWaterLevelManager

def test_field_trend_analysis():
    """测试字段趋势分析功能"""
    print("=== 测试字段趋势分析功能 ===")
    
    try:
        # 创建水位管理器实例
        wl_manager = DynamicWaterLevelManager()
        print("✓ 水位管理器创建成功")
        
        # 测试字段趋势分析
        field_id = "1"
        hours = 24
        
        print(f"测试参数: field_id={field_id}, hours={hours}")
        
        result = wl_manager.get_field_trend_analysis(field_id, hours)
        
        print("✓ 字段趋势分析成功")
        print(f"结果: {result}")
        
        return True
        
    except Exception as e:
        print(f"✗ 字段趋势分析失败: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return False

def test_water_level_readings():
    """测试水位读取功能"""
    print("\n=== 测试水位读取功能 ===")
    
    try:
        wl_manager = DynamicWaterLevelManager()
        
        # 测试获取历史水位数据
        field_id = "1"
        hours = 24
        
        # 计算时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        print(f"查询时间范围: {start_time} 到 {end_time}")
        
        # 直接调用内部方法获取历史数据
        readings = wl_manager._get_historical_readings(field_id, start_time, end_time)
        
        print(f"✓ 获取到 {len(readings)} 条历史记录")
        
        if readings:
            print("最近几条记录:")
            for i, reading in enumerate(readings[-3:]):
                print(f"  {i+1}. 时间: {reading['timestamp']}, 水位: {reading['water_level']}")
        else:
            print("没有找到历史记录")
            
        return True
        
    except Exception as e:
        print(f"✗ 水位读取失败: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    print("开始直接测试字段趋势分析功能...")
    
    # 测试水位读取
    test_water_level_readings()
    
    # 测试字段趋势分析
    test_field_trend_analysis()
    
    print("\n测试完成")