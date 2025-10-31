#!/usr/bin/env python3
"""
调试字段趋势分析功能
"""

import os
import sys
import requests
import traceback

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dynamic_waterlevel_manager import get_waterlevel_manager

def test_waterlevel_manager():
    """测试水位管理器"""
    print("=== 测试水位管理器 ===")
    
    try:
        wl_manager = get_waterlevel_manager()
        print("✅ 水位管理器创建成功")
        
        # 检查田块历史数据
        print(f"📊 田块历史数据: {list(wl_manager.field_histories.keys())}")
        
        # 测试字段趋势分析
        field_id = "1"
        print(f"\n🔍 测试田块 {field_id} 的趋势分析:")
        
        analysis = wl_manager.get_field_trend_analysis(field_id, hours=48)
        if analysis:
            print(f"✅ 趋势分析成功:")
            for key, value in analysis.items():
                print(f"   {key}: {value}")
        else:
            print(f"❌ 田块 {field_id} 没有足够的历史数据")
            
        # 尝试其他田块ID
        for test_field_id in ["field_1", "gzp_field_1", "0", "2"]:
            print(f"\n🔍 测试田块 {test_field_id} 的趋势分析:")
            analysis = wl_manager.get_field_trend_analysis(test_field_id, hours=48)
            if analysis:
                print(f"✅ 趋势分析成功: {len(analysis)} 个字段")
            else:
                print(f"❌ 田块 {test_field_id} 没有足够的历史数据")
                
    except Exception as e:
        print(f"❌ 水位管理器测试失败: {e}")
        traceback.print_exc()

def test_api_directly():
    """直接测试API"""
    print("\n=== 直接测试API ===")
    
    base_url = "http://127.0.0.1:8000"
    
    for field_id in ["1", "field_1", "gzp_field_1"]:
        try:
            url = f"{base_url}/api/irrigation/dynamic-execution/field-trend/{field_id}"
            print(f"\n🌐 测试API: {url}")
            
            response = requests.get(url, timeout=10)
            print(f"📊 状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ 响应成功: {len(data)} 个字段")
                for key, value in data.items():
                    print(f"   {key}: {value}")
            else:
                print(f"❌ 响应失败: {response.text}")
                
        except Exception as e:
            print(f"❌ API测试失败: {e}")

if __name__ == "__main__":
    test_waterlevel_manager()
    test_api_directly()