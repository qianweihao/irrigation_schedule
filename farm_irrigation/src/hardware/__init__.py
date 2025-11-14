# -*- coding: utf-8 -*-
"""硬件控制模块"""

from .hw_iot_client import IoTClient
from .hw_control_onoff import set_gate_degree, close_gate, open_gate
from .hw_check_openness import get_device_properties, get_gate_degree
from .hw_get_deviceids_by_field import get_device_codes_by_section, extract_device_codes
from .hw_get_info_by_deviceids import get_device_info_by_code, extract_unique_no, extract_device_info
from .hw_field_device_mapper import get_field_devices_mapping, get_field_devices_unique_nos
from .hw_batch_field_status import get_all_fields_device_status

__all__ = [
    # 核心客户端
    "IoTClient",
    # 设备控制
    "set_gate_degree",
    "close_gate",
    "open_gate",
    # 设备查询
    "get_device_properties",
    "get_gate_degree",
    # 设备编码查询
    "get_device_codes_by_section",
    "extract_device_codes",
    # 设备信息查询
    "get_device_info_by_code",
    "extract_unique_no",
    "extract_device_info",
    # 田块设备映射
    "get_field_devices_mapping",
    "get_field_devices_unique_nos",
    # 批量查询
    "get_all_fields_device_status",
]

