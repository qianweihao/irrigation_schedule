#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量查询田块设备状态
根据农场ID查询所有田块对应的设备状态
"""
import json
import re
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path

from .hw_field_device_mapper import get_field_devices_mapping
from .hw_check_openness import get_device_properties, get_gate_degree


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


def _get_gate_type_by_device_type(device_type_code: str) -> Optional[str]:
    """
    根据设备类型编码映射到闸门类型
    
    Args:
        device_type_code: 设备类型编码
        
    Returns:
        str: 闸门类型 (inout-G, branch-G) 或 None
    """
    type_mapping = {
        "101588": "inout-G",  # 智能技术-进水阀
        "101544": "inout-G",  # 其他进出水闸类型
        "101134": "branch-G"  # 节制闸类型
    }
    return type_mapping.get(device_type_code)


def _should_include_device(device_info: Dict[str, Any]) -> bool:
    """
    判断设备是否需要包含（根据设备类型筛选）
    
    Args:
        device_info: 设备信息
        
    Returns:
        bool: 是否包含该设备
    """
    device_type_code = device_info.get("deviceTypeCode")
    return device_type_code in ["101588", "101544", "101134"]


def _extract_gates_code_from_section_code(section_code: Optional[str]) -> Optional[str]:
    """
    从 section_code (S-G-F格式) 中提取 gates_code (S-G格式)
    
    Args:
        section_code: 田块编码，格式如 "S3-G10-F7"
        
    Returns:
        str: 闸门编码，格式如 "S3-G10"，如果无法解析则返回 None
    """
    if not section_code:
        return None
    
    # 使用正则表达式匹配 S-G-F 格式，提取 S-G 部分
    match = re.match(r'^(S\d+-G\d+)', section_code)
    if match:
        return match.group(1)
    
    return None


def _load_section_id_to_code_mapping() -> Dict[str, str]:
    """
    从 config.json 加载 sectionID 到 sectionCode 的映射
    
    Returns:
        dict: {sectionID: sectionCode} 映射
    """
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    config_file = project_root / "config.json"
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 从 fields 数组中提取 sectionID -> sectionCode 映射
        mapping = {}
        for field in config.get("fields", []):
            section_id = field.get("sectionID")
            section_code = field.get("sectionCode") or field.get("id")  # 优先使用 sectionCode，否则用 id
            if section_id and section_code:
                mapping[str(section_id)] = str(section_code)
        
        return mapping
    except Exception as e:
        print(f"⚠️ 加载 config.json 失败: {e}")
        return {}


def _get_field_ids_from_csv(farm_name: str) -> List[Dict[str, str]]:
    """
    根据农场名称从CSV文件中提取田块ID列表，并从 config.json 中补充 sectionCode
    
    Args:
        farm_name: 农场名称（如"港中坪"）
        
    Returns:
        List[Dict]: 田块信息列表，格式：[{"id": "田块ID", "name": "田块名称", "section_code": "S-G-F格式"}, ...]
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
        # 加载 sectionID -> sectionCode 映射
        section_mapping = _load_section_id_to_code_mapping()
        
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
            field_id = str(row["id"]).strip()
            field_name = str(row["name"]).strip()
            section_code = section_mapping.get(field_id)  # 从映射中获取 sectionCode
            
            field_info = {
                "id": field_id,
                "name": field_name
            }
            
            # 如果找到 sectionCode，添加到结果中
            if section_code:
                field_info["section_code"] = section_code
            
            fields.append(field_info)
        
        return fields
        
    except Exception as e:
        print(f"⚠️ 读取CSV文件失败: {e}")
        return []




def get_all_fields_device_status(
    app_id: str,
    secret: str,
    farm_id: str,
    iot_app_id: Optional[str] = None,
    iot_secret: Optional[str] = None,
    timeout: int = 30,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    根据农场ID获取所有田块对应的设备信息和状态
    
    完整流程：
    1. 根据农场ID获取农场名称
    2. 根据农场名称查找CSV文件，提取田块ID列表
    3. 对每个田块ID，获取其设备映射（田块ID -> 设备编码 -> 设备信息 -> uniqueNo）
    4. 筛选特定设备类型（101588、101544、101134）
    5. 根据设备类型标记为 inout-G 或 branch-G
    6. 查询每个设备的实时状态（闸门开度等）
    
    Args:
        app_id: 应用ID（用于iLand平台查询设备信息）
        secret: 密钥（用于iLand平台）
        farm_id: 农场ID
        iot_app_id: IoT平台应用ID（用于查询设备状态，默认使用siotextend）
        iot_secret: IoT平台密钥（用于查询设备状态）
        timeout: 请求超时时间（秒）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 所有田块设备信息和状态，格式：
        {
            "farm_id": "农场ID",
            "farm_name": "农场名称",
            "total_fields": 田块总数,
            "fields": [
                {
                    "field_id": "田块ID",
                    "field_name": "田块名称",
                    "section_code": "S-G-F格式编码（如S3-G2-F1）",
                    "gates_code": "S-G格式编码（如S3-G2）",
                    "device_count": 设备数量,
                    "devices": [
                        {
                            "device_code": "设备编码",
                            "unique_no": "设备唯一编号",
                            "gate_type": "inout-G" or "branch-G",
                            "device_info": {...完整设备信息...},
                            "status": {
                                "gate_degree": 闸门开度,
                                "online_status": 在线状态,
                                "success": True/False
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
    
    # 设置IoT平台认证信息（用于查询设备状态）
    if not iot_app_id:
        iot_app_id = "siotextend"
    if not iot_secret:
        iot_secret = "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
    
    if verbose:
        print(f"iLand平台认证: app_id={app_id[:4]}...")
        print(f"IoT平台认证: app_id={iot_app_id[:4]}...")
    
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
            section_code = field.get("section_code")  # 获取 S-G-F 格式的编码
            gates_code = _extract_gates_code_from_section_code(section_code)  # 提取 S-G 部分
            
            if verbose:
                print(f"\n步骤3.{i}: 处理田块 {field_name} (ID: {field_id}, Code: {section_code or 'N/A'}, Gate: {gates_code or 'N/A'})")
            
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
                field_result = {
                    "field_id": field_id,
                    "field_name": field_name,
                    "device_count": 0,
                    "devices": [],
                    "error": device_mapping.get("error", "未找到设备")
                }
                # 添加 section_code 和 gates_code（如果存在）
                if section_code:
                    field_result["section_code"] = section_code
                if gates_code:
                    field_result["gates_code"] = gates_code
                field_results.append(field_result)
                continue
            
            # 筛选特定类型的设备并查询状态
            devices = []
            for device in device_mapping.get("devices", []):
                device_info = device.get("device_info", {})
                unique_no = device.get("unique_no")
                
                if not unique_no or not device_info:
                    continue
                
                # 筛选：只包含指定设备类型
                if not _should_include_device(device_info):
                    if verbose:
                        print(f"  ⏭️ 跳过设备 {device.get('device_code')} (类型: {device_info.get('deviceTypeCode')})")
                    continue
                
                # 获取闸门类型标记
                gate_type = _get_gate_type_by_device_type(device_info.get("deviceTypeCode"))
                
                if verbose:
                    print(f"  ✅ 设备: {device.get('device_code')} -> uniqueNo: {unique_no}, 类型: {gate_type}")
                
                # 查询设备状态
                device_status = {
                    "gate_degree": None,
                    "online_status": device_info.get("onlineStatus"),
                    "success": False,
                    "error": None
                }
                
                try:
                    # 获取闸门开度（使用IoT平台认证）
                    gate_degree = get_gate_degree(iot_app_id, iot_secret, unique_no, verbose=verbose)
                    if gate_degree is not None:
                        device_status["gate_degree"] = gate_degree
                        device_status["success"] = True
                        if verbose:
                            print(f"    闸门开度: {gate_degree}%")
                    else:
                        device_status["error"] = "未获取到闸门开度（设备可能不支持或属性名称不匹配）"
                        if verbose:
                            print(f"    ⚠️ 未获取到闸门开度")
                            print(f"    建议：使用 verbose=true 参数查看详细的API响应")
                except Exception as e:
                    device_status["error"] = f"查询状态失败: {str(e)}"
                    if verbose:
                        print(f"    ⚠️ 查询状态失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                devices.append({
                    "device_code": device.get("device_code"),
                    "unique_no": unique_no,
                    "gate_type": gate_type,
                    "device_info": device_info,
                    "status": device_status
                })
            
            field_result = {
                "field_id": field_id,
                "field_name": field_name,
                "device_count": len(devices),
                "devices": devices
            }
            # 添加 section_code 和 gates_code（如果存在）
            if section_code:
                field_result["section_code"] = section_code
            if gates_code:
                field_result["gates_code"] = gates_code
            field_results.append(field_result)
        
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
        print("\n田块设备信息和状态:")
        for field in result['fields']:
            section_code = field.get('section_code', 'N/A')
            gates_code = field.get('gates_code', 'N/A')
            print(f"\n  田块: {field['field_name']} (ID: {field['field_id']}, Code: {section_code}, Gate: {gates_code})")
            print(f"  设备数量: {field['device_count']}")
            for device in field['devices']:
                print(f"    - 设备编码: {device['device_code']}")
                print(f"      唯一编号: {device['unique_no']}")
                print(f"      闸门类型: {device.get('gate_type', 'N/A')}")
                device_info = device.get('device_info', {})
                if device_info:
                    print(f"      设备类型: {device_info.get('deviceTypeName', 'N/A')}")
                    print(f"      设备名称: {device_info.get('deviceName', 'N/A')}")
                status = device.get('status', {})
                if status:
                    print(f"      闸门开度: {status.get('gate_degree', 'N/A')}%")
                    print(f"      在线状态: {status.get('online_status', 'N/A')}")
                    print(f"      状态查询: {'成功' if status.get('success') else '失败'}")
    else:
        print(f"错误: {result.get('error', 'Unknown error')}")

