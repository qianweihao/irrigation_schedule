#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
田块设备映射工具
打通完整流程：田块ID -> 设备编码 -> 设备信息 -> uniqueNo
"""
from typing import List, Dict, Any, Optional
from .hw_get_deviceids_by_field import get_device_codes_by_section, extract_device_codes
from .hw_get_info_by_deviceids import get_device_info_by_code, extract_unique_no, extract_device_info


def get_field_devices_mapping(
    app_id: str,
    secret: str,
    section_id: str,
    timeout: int = 30,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    获取田块对应的所有设备信息（包括uniqueNo）
    
    完整流程：
    1. 根据田块ID查询设备编码列表
    2. 根据每个设备编码查询设备详细信息
    3. 提取uniqueNo等关键信息
    
    Args:
        app_id: 应用ID
        secret: 密钥
        section_id: 田块ID
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 田块设备映射信息，格式：
        {
            "section_id": "田块ID",
            "device_count": 设备数量,
            "devices": [
                {
                    "device_code": "设备编码",
                    "unique_no": "设备唯一编号",
                    "device_info": {...完整设备信息...}
                },
                ...
            ],
            "success": True/False,
            "error": "错误信息（如果有）"
        }
    """
    result = {
        "section_id": str(section_id),
        "device_count": 0,
        "devices": [],
        "success": False,
        "error": None
    }
    
    try:
        # 步骤1: 根据田块ID查询设备编码列表
        if verbose:
            print(f"步骤1: 查询田块 {section_id} 的设备编码...")
        
        response = get_device_codes_by_section(
            app_id=app_id,
            secret=secret,
            section_id=section_id,
            timeout=timeout,
            verbose=verbose
        )
        
        if not response:
            result["error"] = "获取设备编码列表失败（API请求失败或超时）"
            if verbose:
                print(f"❌ API请求失败，响应为空")
            return result
        
        device_codes = extract_device_codes(response, verbose=verbose)
        
        if not device_codes:
            # 检查是否是API返回了错误码
            api_code = response.get("code")
            api_code_str = str(api_code) if api_code is not None else ""
            api_message = response.get("message", "")
            
            # 判断是否为成功码：200 或 "0000" 都视为成功
            is_success_code = (api_code == 200) or (api_code_str == "0000") or (api_code_str == "0")
            
            if api_code and not is_success_code:
                result["error"] = f"API返回错误: code={api_code}, message={api_message}"
            else:
                # 成功码但数据为空，说明该田块确实没有设备
                result["error"] = "未找到设备编码（该田块可能没有关联设备，或设备编码列表为空）"
            if verbose:
                print(f"❌ {result['error']}")
                print(f"完整API响应: {response}")
            return result
        
        if verbose:
            print(f"✅ 找到 {len(device_codes)} 个设备编码: {device_codes}")
        
        # 步骤2: 根据每个设备编码查询设备详细信息
        devices = []
        for device_code in device_codes:
            if verbose:
                print(f"\n步骤2: 查询设备编码 {device_code} 的详细信息...")
            
            device_response = get_device_info_by_code(
                app_id=app_id,
                secret=secret,
                device_code=device_code,
                timeout=timeout,
                verbose=verbose
            )
            
            if not device_response:
                if verbose:
                    print(f"⚠️ 设备编码 {device_code} 查询失败，跳过")
                continue
            
            unique_no = extract_unique_no(device_response)
            device_info = extract_device_info(device_response)
            
            if unique_no and device_info:
                devices.append({
                    "device_code": device_code,
                    "unique_no": unique_no,
                    "device_info": device_info
                })
                if verbose:
                    print(f"✅ 设备编码 {device_code} -> uniqueNo: {unique_no}")
            else:
                if verbose:
                    print(f"⚠️ 设备编码 {device_code} 信息不完整，跳过")
        
        result["devices"] = devices
        result["device_count"] = len(devices)
        result["success"] = len(devices) > 0
        
        if not result["success"]:
            result["error"] = "未找到有效的设备信息"
        
        return result
        
    except Exception as e:
        result["error"] = f"处理过程中发生错误: {str(e)}"
        if verbose:
            print(f"❌ 错误: {result['error']}")
        return result


def get_field_devices_unique_nos(
    app_id: str,
    secret: str,
    section_id: str,
    timeout: int = 30,
    verbose: bool = False
) -> List[str]:
    """
    获取田块对应的所有设备唯一编号列表（简化版）
    
    Args:
        app_id: 应用ID
        secret: 密钥
        section_id: 田块ID
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        List[str]: 设备唯一编号列表
    """
    mapping = get_field_devices_mapping(
        app_id=app_id,
        secret=secret,
        section_id=section_id,
        timeout=timeout,
        verbose=verbose
    )
    
    return [device["unique_no"] for device in mapping.get("devices", []) if device.get("unique_no")]


if __name__ == "__main__":
    # 测试数据
    APP_ID = "YJY"
    SECRET = "test005"
    SECTION_ID = "62703309342730"
    
    # 测试完整流程
    print(f"测试田块 {SECTION_ID} 的设备映射...")
    result = get_field_devices_mapping(
        app_id=APP_ID,
        secret=SECRET,
        section_id=SECTION_ID,
        verbose=True
    )
    
    print("\n=== 最终结果 ===")
    print(f"田块ID: {result['section_id']}")
    print(f"设备数量: {result['device_count']}")
    print(f"成功: {result['success']}")
    
    if result['success']:
        print("\n设备列表:")
        for device in result['devices']:
            print(f"  - 设备编码: {device['device_code']}")
            print(f"    uniqueNo: {device['unique_no']}")
    else:
        print(f"错误: {result.get('error', 'Unknown error')}")

