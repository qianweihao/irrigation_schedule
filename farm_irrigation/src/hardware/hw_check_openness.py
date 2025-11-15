#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物联网平台设备属性查询
查询设备当前状态（如闸门开度）
"""
from .hw_iot_client import IoTClient

# 物联网平台查看设备属性的接口
API_URL = "https://ziot-web.zoomlion.com/api/app/openApi/device/properties.newest"


def get_device_properties(app_id: str, secret: str, unique_no: str) -> dict:
    """
    获取设备属性
    
    Args:
        app_id: 应用ID
        secret: 密钥
        unique_no: 设备唯一编号
        
    Returns:
        dict: 设备属性数据
    """
    client = IoTClient(app_id, secret)
    payload = {"uniqueNo": unique_no}
    return client.send_request(API_URL, payload)


def get_gate_degree(app_id: str, secret: str, unique_no: str, verbose: bool = False) -> float:
    """
    获取闸门开度
    
    Args:
        app_id: 应用ID
        secret: 密钥
        unique_no: 设备唯一编号（从 hw_get_info_by_deviceids 获取）
        verbose: 是否打印详细信息
        
    Returns:
        float: 闸门开度（0-100），失败返回 None
    """
    result = get_device_properties(app_id, secret, unique_no)
    
    if verbose:
        print(f"\n=== 设备属性查询结果 (uniqueNo: {unique_no}) ===")
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("=" * 50)
    
    if not result:
        if verbose:
            print(f"[WARNING] API returned empty")
        return None
    
    if 'data' not in result:
        if verbose:
            print(f"[WARNING] No 'data' field in response")
            print(f"Response keys: {list(result.keys())}")
            if 'code' in result:
                print(f"Response code: {result.get('code')}")
                print(f"Response msg: {result.get('msg')}")
        return None
    
    # 可能的开度属性名称
    degree_names = [
        '水闸闸门开度',
        '闸门开度',
        '开度',
        'gate_degree',
        'openness',
        '阀门开度'
    ]
    
    for device in result['data']:
        properties = device.get('properties', [])
        if verbose:
            print(f"设备属性列表:")
            for prop in properties:
                print(f"  - {prop.get('name')}: {prop.get('value')}")
        
        for prop in properties:
            prop_name = prop.get('name', '')
            # 尝试匹配多种可能的属性名
            for degree_name in degree_names:
                if degree_name in prop_name or prop_name in degree_name:
                    try:
                        value = float(prop.get('value', 0))
                        if verbose:
                            print(f"[SUCCESS] Found degree property: {prop_name} = {value}")
                        return value
                    except (ValueError, TypeError) as e:
                        if verbose:
                            print(f"[WARNING] Failed to convert degree value: {prop.get('value')} - {e}")
                        continue
    
    if verbose:
        print(f"[WARNING] No matching degree property found")
    return None


if __name__ == "__main__":
    # 配置参数
    APP_ID = "siotextend"
    SECRET = "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
    UNIQUE_NO = "477379421064159253"
    
    # 获取闸门开度
    degree = get_gate_degree(APP_ID, SECRET, UNIQUE_NO)
    
    if degree is not None:
        print(f"✅ 设备闸门开度: {degree}%")
    else:
        print("❌ 获取闸门开度失败")
