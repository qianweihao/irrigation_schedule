#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量查询田块设备状态
根据农场ID查询所有田块对应的设备状态
"""
import json
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path

from .hw_field_device_mapper import get_field_devices_mapping


def _load_farm_id_mapping() -> Dict[str, str]:
    """
    加载农场ID到农场名称的映射
    
    Returns:
        dict: {farm_id: farm_name}
    """
    # 从当前文件位置向上找到项目根目录
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    mapping_file = project_root / "data" / "gzp_farm" / "farm_id_mapping.json"
    
    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 加载农场ID映射失败: {e}")
        return {}


def _get_farm_name(farm_id: str) -> Optional[str]:
    """
    根据农场ID获取农场名称
    
    Args:
        farm_id: 农场ID
        
    Returns:
        str: 农场名称，如果未找到则返回 None
    """
    mapping = _load_farm_id_mapping()
    return mapping.get(str(farm_id))


def _get_field_ids_from_csv(farm_name: str) -> List[Dict[str, str]]:
    """
    根据农场名称从CSV文件中提取田块ID列表
    
    Args:
        farm_name: 农场名称（如"港中坪"）
        
    Returns:
        List[Dict]: 田块信息列表，格式：[{"id": "田块ID", "name": "田块名称"}, ...]
    """
    # 从当前文件位置向上找到项目根目录
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    gzp_farm_dir = project_root / "data" / "gzp_farm"
    
    # 查找对应的CSV文件
    csv_file = gzp_farm_dir / f"{farm_name}地块id.csv"
    
    if not csv_file.exists():
        print(f"⚠️ 未找到CSV文件: {csv_file}")
        return []
    
    try:
        # 读取CSV文件
        df = pd.read_csv(csv_file, encoding="utf-8-sig")
        
        # 提取id和name列
        if "id" not in df.columns or "name" not in df.columns:
            print(f"⚠️ CSV文件缺少必要的列: id 或 name")
            return []
        
        # 过滤掉id或name为空的行
        df_filtered = df[["id", "name"]].dropna()
        
        # 转换为字典列表
        fields = []
        for _, row in df_filtered.iterrows():
            fields.append({
                "id": str(row["id"]).strip(),
                "name": str(row["name"]).strip()
            })
        
        return fields
        
    except Exception as e:
        print(f"⚠️ 读取CSV文件失败: {e}")
        return []




def get_all_fields_device_status(
    app_id: str,
    secret: str,
    farm_id: str,
    timeout: int = 30,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    根据农场ID获取所有田块对应的设备信息
    
    完整流程：
    1. 根据农场ID获取农场名称
    2. 根据农场名称查找CSV文件，提取田块ID列表
    3. 对每个田块ID，获取其设备映射（田块ID -> 设备编码 -> 设备信息 -> uniqueNo）
    4. 返回所有设备的基本信息（不查询开度和控制状态）
    
    Args:
        app_id: 应用ID
        secret: 密钥
        farm_id: 农场ID
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 所有田块设备信息，格式：
        {
            "farm_id": "农场ID",
            "farm_name": "农场名称",
            "total_fields": 田块总数,
            "fields": [
                {
                    "field_id": "田块ID",
                    "field_name": "田块名称",
                    "device_count": 设备数量,
                    "devices": [
                        {
                            "device_code": "设备编码",
                            "unique_no": "设备唯一编号",
                            "device_info": {
                                ...完整设备信息...
                            }
                        },
                        ...
                    ]
                },
                ...
            ],
            "success": True/False,
            "error": "错误信息（如果有）"
        }
    """
    result = {
        "farm_id": str(farm_id),
        "farm_name": None,
        "total_fields": 0,
        "fields": [],
        "success": False,
        "error": None
    }
    
    try:
        # 步骤1: 根据农场ID获取农场名称
        farm_name = _get_farm_name(farm_id)
        if not farm_name:
            result["error"] = f"未找到农场ID {farm_id} 对应的农场名称"
            return result
        
        result["farm_name"] = farm_name
        
        if verbose:
            print(f"步骤1: 农场ID {farm_id} -> 农场名称: {farm_name}")
        
        # 步骤2: 从CSV文件提取田块ID列表
        fields = _get_field_ids_from_csv(farm_name)
        if not fields:
            result["error"] = f"未找到农场 {farm_name} 的田块数据"
            return result
        
        result["total_fields"] = len(fields)
        
        if verbose:
            print(f"步骤2: 找到 {len(fields)} 个田块")
        
        # 步骤3: 对每个田块获取设备状态
        field_results = []
        for i, field in enumerate(fields, 1):
            field_id = field["id"]
            field_name = field["name"]
            
            if verbose:
                print(f"\n步骤3.{i}: 处理田块 {field_name} (ID: {field_id})")
            
            # 获取田块的设备映射
            device_mapping = get_field_devices_mapping(
                app_id=app_id,
                secret=secret,
                section_id=field_id,
                timeout=timeout,
                verbose=verbose
            )
            
            if not device_mapping.get("success"):
                if verbose:
                    print(f"⚠️ 田块 {field_name} 未找到设备")
                field_results.append({
                    "field_id": field_id,
                    "field_name": field_name,
                    "device_count": 0,
                    "devices": [],
                    "error": device_mapping.get("error", "未找到设备")
                })
                continue
            
            # 直接返回设备信息（不查询开度和控制状态）
            devices = []
            for device in device_mapping.get("devices", []):
                unique_no = device.get("unique_no")
                if not unique_no:
                    continue
                
                if verbose:
                    print(f"  设备: {device.get('device_code')} -> uniqueNo: {unique_no}")
                
                devices.append({
                    "device_code": device.get("device_code"),
                    "unique_no": unique_no,
                    "device_info": device.get("device_info")
                })
            
            field_results.append({
                "field_id": field_id,
                "field_name": field_name,
                "device_count": len(devices),
                "devices": devices
            })
        
        result["fields"] = field_results
        result["success"] = True
        
        return result
        
    except Exception as e:
        result["error"] = f"处理过程中发生错误: {str(e)}"
        if verbose:
            print(f"❌ 错误: {result['error']}")
        return result


if __name__ == "__main__":
    # 测试数据
    APP_ID = "YJY"
    SECRET = "test005"
    FARM_ID = "13944136728576"  # 港中坪
    
    # 测试批量查询
    print(f"测试农场 {FARM_ID} 的所有田块设备状态...")
    result = get_all_fields_device_status(
        app_id=APP_ID,
        secret=SECRET,
        farm_id=FARM_ID,
        verbose=True
    )
    
    print("\n=== 最终结果 ===")
    print(f"农场ID: {result['farm_id']}")
    print(f"农场名称: {result['farm_name']}")
    print(f"田块总数: {result['total_fields']}")
    print(f"成功: {result['success']}")
    
    if result['success']:
        print("\n田块设备信息:")
        for field in result['fields']:
            print(f"\n  田块: {field['field_name']} (ID: {field['field_id']})")
            print(f"  设备数量: {field['device_count']}")
            for device in field['devices']:
                print(f"    - 设备编码: {device['device_code']}")
                print(f"      唯一编号: {device['unique_no']}")
                device_info = device.get('device_info', {})
                if device_info:
                    print(f"      设备类型: {device_info.get('deviceTypeName', 'N/A')}")
                    print(f"      设备名称: {device_info.get('deviceName', 'N/A')}")
    else:
        print(f"错误: {result.get('error', 'Unknown error')}")

