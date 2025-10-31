#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试API端点的脚本
"""

import requests
import json
import traceback

def test_endpoint(url, method='GET', data=None):
    """测试API端点"""
    try:
        print(f"\n测试: {method} {url}")
        
        if method == 'GET':
            response = requests.get(url)
        elif method == 'POST':
            response = requests.post(url, json=data)
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
            except:
                print(f"响应: {response.text}")
        else:
            print(f"错误响应: {response.text}")
            
    except Exception as e:
        print(f"请求失败: {e}")
        traceback.print_exc()

def main():
    base_url = "http://127.0.0.1:8000"
    
    # 测试健康检查
    test_endpoint(f"{base_url}/api/health")
    
    # 测试失败的端点
    print("\n" + "="*50)
    print("测试失败的端点")
    print("="*50)
    
    # 获取执行历史
    test_endpoint(f"{base_url}/api/irrigation/dynamic-execution/history")
    
    # 获取田块趋势
    test_endpoint(f"{base_url}/api/irrigation/dynamic-execution/field-trend/1")
    
    # 启动执行 - 提供正确的请求体
    start_request = {
        "plan_file_path": "export/20250820_151007/plan.json",
        "farm_id": "test_farm"
    }
    test_endpoint(f"{base_url}/api/irrigation/dynamic-execution/start", method='POST', data=start_request)
    
    # 重新生成批次 - 提供正确的请求体
    regen_request = {
        "batch_index": 1
    }
    test_endpoint(f"{base_url}/api/irrigation/dynamic-execution/regenerate-batch", method='POST', data=regen_request)

if __name__ == "__main__":
    main()