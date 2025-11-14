#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据设备编码查询设备信息
"""
import json
import requests
from typing import Dict, Any, Optional
from .hw_signature_helper import SignatureHelper

# API 接口地址
API_URL = "https://iland.zoomlion.com/fieldEquipment/openApi/v1/equipment.getByDeviceCode"


def get_device_info_by_code(
    app_id: str,
    secret: str,
    device_code: str,
    timeout: int = 30,
    verbose: bool = False
) -> Optional[Dict[str, Any]]:
    """
    根据设备编码查询设备信息
    
    Args:
        app_id: 应用ID
        secret: 密钥
        device_code: 设备编码
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 响应数据，包含设备信息。格式：
        {
            "code": 200,
            "message": "success",
            "data": {
                "uniqueNo": "设备唯一编号",
                "deviceCode": "设备编码",
                ...其他设备信息
            }
        }
        失败返回 None
    """
    payload = {
        "deviceCode": str(device_code)
    }
    
    # 生成签名和请求头
    _, _, headers = SignatureHelper.generate_signature_for_iland(
        app_id=app_id,
        secret=secret,
        payload=payload,
        verbose=verbose
    )
    
    if verbose:
        print("=== 请求详情 ===")
        print(f"URL: {API_URL}")
        print(f"Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
        print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        print("================\n")
    
    try:
        response = requests.get(
            url=API_URL,
            params=payload,
            headers=headers,
            timeout=timeout
        )
        
        if verbose:
            print("=== 响应详情 ===")
            print(f"状态码: {response.status_code}")
        
        response.raise_for_status()
        response_json = response.json()
        
        if verbose:
            print(f"响应: {json.dumps(response_json, indent=2, ensure_ascii=False)}")
            print("================\n")
        
        return response_json
        
    except requests.exceptions.Timeout:
        print(f"❌ 请求超时 ({timeout}秒)")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ 连接错误 - 请检查URL和网络连接")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ 响应解析失败: {response.text if 'response' in locals() else 'No response'}")
        return None


def extract_unique_no(response: Dict[str, Any]) -> Optional[str]:
    """
    从响应中提取设备唯一编号 (uniqueNo)
    
    Args:
        response: API响应数据
        
    Returns:
        str: 设备唯一编号，如果响应格式不正确则返回 None
    """
    if not response:
        return None
    
    # 检查响应格式 - 支持 200、"0000"、"0" 作为成功码
    code = response.get("code")
    code_str = str(code) if code is not None else ""
    is_success = (code == 200) or (code_str == "0000") or (code_str == "0")
    
    if not is_success:
        message = response.get("message") or response.get("msg", "Unknown error")
        print(f"⚠️ API返回错误: {message}")
        return None
    
    data = response.get("data")
    if isinstance(data, dict):
        unique_no = data.get("uniqueNo")
        return str(unique_no) if unique_no else None
    else:
        print(f"⚠️ 响应数据格式不正确，期望字典，实际: {type(data)}")
        return None


def extract_device_info(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从响应中提取完整的设备信息
    
    Args:
        response: API响应数据
        
    Returns:
        dict: 设备信息字典，如果响应格式不正确则返回 None
    """
    if not response:
        return None
    
    # 检查响应格式 - 支持 200、"0000"、"0" 作为成功码
    code = response.get("code")
    code_str = str(code) if code is not None else ""
    is_success = (code == 200) or (code_str == "0000") or (code_str == "0")
    
    if not is_success:
        message = response.get("message") or response.get("msg", "Unknown error")
        print(f"⚠️ API返回错误: {message}")
        return None
    
    data = response.get("data")
    if isinstance(data, dict):
        return data
    else:
        print(f"⚠️ 响应数据格式不正确，期望字典，实际: {type(data)}")
        return None


if __name__ == "__main__":
    # 测试数据
    APP_ID = "YJY"
    SECRET = "test005"
    DEVICE_CODE = "70fe0d98e8cc"
    
    # 查询设备信息
    print(f"查询设备编码 {DEVICE_CODE} 的设备信息...")
    response = get_device_info_by_code(
        app_id=APP_ID,
        secret=SECRET,
        device_code=DEVICE_CODE,
        verbose=True
    )
    
    if response:
        unique_no = extract_unique_no(response)
        device_info = extract_device_info(response)
        
        if unique_no:
            print(f"✅ 设备唯一编号: {unique_no}")
        if device_info:
            print(f"✅ 设备信息: {json.dumps(device_info, indent=2, ensure_ascii=False)}")
    else:
        print("❌ 查询失败")