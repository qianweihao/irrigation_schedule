#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物联网平台设备属性查询
查询设备当前状态（如闸门开度）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def get_gate_degree(app_id: str, secret: str, unique_no: str) -> float:
    """
    获取闸门开度
    
    Args:
        app_id: 应用ID
        secret: 密钥
        unique_no: 设备唯一编号
        
    Returns:
        float: 闸门开度（0-100）
    """
    result = get_device_properties(app_id, secret, unique_no)
    
    if not result or 'data' not in result:
        return None
    
    for device in result['data']:
        for prop in device.get('properties', []):
            if prop.get('name') == '水闸闸门开度':
                return float(prop.get('value', 0))
    
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
