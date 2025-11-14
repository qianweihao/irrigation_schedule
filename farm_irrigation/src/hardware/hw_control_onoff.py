"""
物联网平台设备控制
控制设备开关和闸门开度
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from .hw_iot_client import IoTClient

# 物联网平台控制设备的接口
API_URL = "https://ziot-web.zoomlion.com/api/app/openApi/device/deviceMsg/thingProperty.sync.invoke"


def set_gate_degree(app_id: str, secret: str, unique_no: str, degree: float, verbose: bool = False) -> dict:
    """
    设置闸门开度
    
    Args:
        app_id: 应用ID
        secret: 密钥
        unique_no: 设备唯一编号
        degree: 目标开度（0-100）
        verbose: 是否打印详细信息
        
    Returns:
        dict: 响应数据
    """
    client = IoTClient(app_id, secret)
    payload = {
        "uniqueNo": unique_no,
        "identifier": "gateDegree",
        "params": {"gateDegree": degree}
    }
    return client.send_request(API_URL, payload, verbose=verbose)


def close_gate(app_id: str, secret: str, unique_no: str, verbose: bool = False) -> dict:
    """关闭闸门（开度设为0）"""
    return set_gate_degree(app_id, secret, unique_no, 0, verbose)


def open_gate(app_id: str, secret: str, unique_no: str, verbose: bool = False) -> dict:
    """完全打开闸门（开度设为100）"""
    return set_gate_degree(app_id, secret, unique_no, 100, verbose)


if __name__ == "__main__":
    # 配置参数
    APP_ID = "siotextend"
    SECRET = "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
    UNIQUE_NO = "477379421064159253"
    
    # 关闭闸门
    print("关闭闸门...")
    result = close_gate(APP_ID, SECRET, UNIQUE_NO, verbose=True)
    print("✅ 关闭闸门完成\n" if result else "❌ 关闭闸门失败\n")
    
    # 打开闸门（取消注释以使用）
    # print("打开闸门...")
    # result = open_gate(APP_ID, SECRET, UNIQUE_NO, verbose=True)
    # print("✅ 打开闸门完成" if result else "❌ 打开闸门失败")
    
    # 设置特定开度（取消注释以使用）
    # print("设置闸门开度为50%...")
    # result = set_gate_degree(APP_ID, SECRET, UNIQUE_NO, 50, verbose=True)
    # print("✅ 设置开度完成" if result else "❌ 设置开度失败")