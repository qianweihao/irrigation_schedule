#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备自检工具
调用设备自检接口和状态查询接口
"""
import requests
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# 设备自检网关地址
DEVICE_CHECK_GATEWAY = "http://101.201.78.54:8100"


def trigger_device_self_check(unique_no_list: List[str], timeout: int = 30) -> Dict[str, Any]:
    """
    触发设备自检
    
    Args:
        unique_no_list: 设备唯一标识列表
        timeout: 请求超时时间（秒）
        
    Returns:
        dict: {
            "success": bool,
            "accepted_no_list": List[int],
            "message": str,
            "error": Optional[str]
        }
    """
    try:
        url = f"{DEVICE_CHECK_GATEWAY}/device_self_check"
        params = [("unique_no_list", no) for no in unique_no_list]
        
        logger.info(f"触发设备自检，设备数量: {len(unique_no_list)}")
        logger.info(f"📋 请求URL: {url}")
        logger.info(f"📋 前5个设备示例: {unique_no_list[:5]}")
        
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("code") == 200:
            logger.info(f"✅ 设备自检触发成功: {data.get('message')}")
            accepted_list = data.get("accepted_no_list", [])
            logger.info(f"📋 硬件API返回的完整数据: {data}")
            logger.info(f"📋 接受的设备列表: {accepted_list}, 数量: {len(accepted_list)}")
            return {
                "success": True,
                "accepted_no_list": accepted_list,
                "message": data.get("message", ""),
                "error": None
            }
        else:
            logger.error(f"❌ 设备自检触发失败: code={data.get('code')}, message={data.get('message')}")
            return {
                "success": False,
                "accepted_no_list": [],
                "message": data.get("message", ""),
                "error": f"API返回错误码: {data.get('code')}"
            }
            
    except requests.exceptions.Timeout:
        error_msg = f"请求超时（>{timeout}秒）"
        logger.error(f"❌ {error_msg}")
        return {"success": False, "accepted_no_list": [], "message": "", "error": error_msg}
    except Exception as e:
        error_msg = f"触发设备自检失败: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"success": False, "accepted_no_list": [], "message": "", "error": error_msg}


def query_device_status(unique_no_list: List[str], timeout: int = 30) -> Dict[str, Any]:
    """
    查询设备状态
    
    Args:
        unique_no_list: 设备唯一标识列表
        timeout: 请求超时时间（秒）
        
    Returns:
        dict: {
            "success": bool,
            "devices": List[{"no": str, "status": str}],
            "message": str,
            "error": Optional[str]
        }
    """
    try:
        url = f"{DEVICE_CHECK_GATEWAY}/devices_status"
        params = [("unique_no_list", no) for no in unique_no_list]
        
        logger.info(f"查询设备状态，设备数量: {len(unique_no_list)}")
        logger.info(f"📋 请求URL: {url}")
        logger.info(f"📋 前5个设备示例: {unique_no_list[:5]}")
        
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("code") == 200:
            devices = data.get("data", [])
            logger.info(f"✅ 设备状态查询成功，共 {len(devices)} 个设备")
            logger.info(f"📋 硬件API返回的完整数据: {data}")
            if devices and len(devices) > 0:
                logger.info(f"📋 设备状态示例: {devices[0]}")
            return {
                "success": True,
                "devices": devices,
                "message": data.get("message", ""),
                "error": None
            }
        else:
            logger.error(f"❌ 设备状态查询失败: code={data.get('code')}, message={data.get('message')}")
            return {
                "success": False,
                "devices": [],
                "message": data.get("message", ""),
                "error": f"API返回错误码: {data.get('code')}"
            }
            
    except requests.exceptions.Timeout:
        error_msg = f"请求超时（>{timeout}秒）"
        logger.error(f"❌ {error_msg}")
        return {"success": False, "devices": [], "message": "", "error": error_msg}
    except Exception as e:
        error_msg = f"查询设备状态失败: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"success": False, "devices": [], "message": "", "error": error_msg}


def get_device_status_summary(devices_status: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    获取设备状态统计摘要
    
    Args:
        devices_status: 设备状态列表 [{"no": str, "status": str}, ...]
        
    Returns:
        dict: {
            "successful": List[str],
            "checking": List[str],
            "failed": List[str],
            "other": List[str]
        }
    """
    summary = {
        "successful": [],
        "checking": [],
        "failed": [],
        "other": []
    }
    
    for device in devices_status:
        status = device.get("status")
        device_no = device.get("no")
        
        if status == "check_success":
            summary["successful"].append(device_no)
        elif status == "checking":
            summary["checking"].append(device_no)
        elif status == "check_failed":
            summary["failed"].append(device_no)
        else:
            summary["other"].append(device_no)
    
    return summary


def filter_successful_devices(devices_status: List[Dict[str, Any]]) -> List[str]:
    """
    过滤自检成功的设备
    
    Args:
        devices_status: 设备状态列表 [{"no": str, "status": str}, ...]
        
    Returns:
        List[str]: 自检成功的设备unique_no列表
    """
    successful = []
    checking = []
    failed = []
    
    for device in devices_status:
        status = device.get("status")
        device_no = device.get("no")
        
        if status == "check_success":
            successful.append(device_no)
        elif status == "checking":
            checking.append(device_no)
        elif status == "check_failed":
            failed.append(device_no)
    
    logger.info(f"设备状态统计: 成功={len(successful)}, 自检中={len(checking)}, 失败={len(failed)}, 总数={len(devices_status)}")
    
    if checking:
        logger.warning(f"⚠️ 有 {len(checking)} 个设备还在自检中，建议增加等待时间或启用轮询模式")
    
    return successful

