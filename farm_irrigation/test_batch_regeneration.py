#!/usr/bin/env python3
"""
测试批次重新生成接口
"""

import requests
import json

def test_batch_regeneration():
    """测试批次重新生成接口"""
    
    # API端点
    url = "http://localhost:8000/api/regeneration/batch"
    
    # 测试数据
    test_data = {
        "original_plan_id": "e:/irrigation_schedule/farm_irrigation/output/irrigation_plan_modified_1761982575.json",
        "field_modifications": [
            {
                "field_id": "S3-G5-F1",
                "action": "add",
                "custom_water_level": 95.0
            },
            {
                "field_id": "S3-G5-F2",
                "action": "remove"
            }
        ],
        "pump_assignments": [
            {
                "batch_index": 1,
                "pump_ids": ["P001", "P002"]
            }
        ],
        "time_modifications": [
            {
                "batch_index": 1,
                "start_time_h": 6.0,
                "duration_h": 4.0
            }
        ],
        "regeneration_params": {
            "force_regeneration": True,
            "optimize_schedule": True
        }
    }
    
    # 发送请求
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        print("发送批次重新生成请求...")
        print(f"URL: {url}")
        print(f"数据: {json.dumps(test_data, indent=2, ensure_ascii=False)}")
        
        response = requests.post(url, json=test_data, headers=headers, timeout=30)
        
        print(f"\n响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"响应成功: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"响应失败: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"JSON解析异常: {e}")
        print(f"原始响应: {response.text}")
        return False

if __name__ == "__main__":
    print("开始测试批次重新生成接口...")
    success = test_batch_regeneration()
    
    if success:
        print("\n✅ 测试成功！接口修复完成。")
    else:
        print("\n❌ 测试失败！需要进一步检查。")