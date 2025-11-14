#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据地块查询设备编码列表
"""
import json
import requests
from typing import List, Dict, Any, Optional
from .hw_signature_helper import SignatureHelper

# API 接口地址
API_URL = "https://iland.zoomlion.com/fieldEquipment/openApi/v1/equipment.listCodeBySection"


def get_device_codes_by_section(
    app_id: str,
    secret: str,
    section_id: str,
    timeout: int = 30,
    verbose: bool = False
) -> Optional[Dict[str, Any]]:
    """
    根据地块ID查询设备编码列表
    
    Args:
        app_id: 应用ID
        secret: 密钥
        section_id: 地块ID
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 响应数据，包含设备编码列表。格式：
        {
            "code": 200,
            "message": "success",
            "data": ["deviceCode1", "deviceCode2", ...]
        }
        失败返回 None
    """
    payload = {
        "sectionId": str(section_id)
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
        response = requests.post(
            url=API_URL,
            json=payload,
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


def extract_device_codes(response: Dict[str, Any], verbose: bool = False) -> List[str]:
    """
    从响应中提取设备编码列表
    
    Args:
        response: API响应数据
        verbose: 是否打印详细信息
        
    Returns:
        List[str]: 设备编码列表，如果响应格式不正确则返回空列表
    """
    if not response:
        if verbose:
            print("⚠️ 响应为空")
        return []
    
    # 检查响应格式
    # 注意：有些API可能使用 "0000" 表示成功，200 也可能表示成功
    code = response.get("code")
    code_str = str(code) if code is not None else ""
    
    # 判断是否为成功码：200 或 "0000" 都视为成功
    is_success = (code == 200) or (code_str == "0000") or (code_str == "0")
    
    if not is_success:
        error_msg = response.get('message', 'Unknown error')
        if verbose:
            print(f"⚠️ API返回错误码 {code}: {error_msg}")
            print(f"完整响应: {response}")
        return []
    
    # 如果是成功码，继续处理数据
    if verbose and code != 200:
        print(f"ℹ️ API返回码 {code}（视为成功）")
    
    data = response.get("data", [])
    if isinstance(data, list):
        device_codes = [str(code) for code in data if code]
        if verbose:
            if len(device_codes) == 0:
                print(f"⚠️ API返回成功，但设备编码列表为空（该田块可能没有关联设备）")
                print(f"完整响应: {response}")
            else:
                print(f"✅ 成功提取 {len(device_codes)} 个设备编码")
        return device_codes
    else:
        if verbose:
            print(f"⚠️ 响应数据格式不正确，期望列表，实际: {type(data)}")
            print(f"完整响应: {response}")
        return []


if __name__ == "__main__":
    # 测试数据
    APP_ID = "YJY"
    SECRET = "test005"
    SECTION_ID = "62703309342730"
    
    # 查询设备编码
    print(f"查询地块 {SECTION_ID} 的设备编码...")
    response = get_device_codes_by_section(
        app_id=APP_ID,
        secret=SECRET,
        section_id=SECTION_ID,
        verbose=True
    )
    
    if response:
        device_codes = extract_device_codes(response)
        print(f"✅ 找到 {len(device_codes)} 个设备编码:")
        for code in device_codes:
            print(f"  - {code}")
    else:
        print("❌ 查询失败")
