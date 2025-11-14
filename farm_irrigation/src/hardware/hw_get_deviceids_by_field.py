"""
根据地块查询设备编码列表
"""
import hashlib
import hmac
import time
import json
import requests
from collections import OrderedDict

# Constants模拟
class Constants:
    SIGN_APP_ID = "app-id"
    SIGN_TIMESTAMP = "timestamp"
    SIGN_PAYLOAD = "payload"

# SignatureMethod枚举模拟
class SignatureMethod:
    HMAC_MD5 = "HmacMD5"
    HMAC_SHA1 = "HmacSHA1"
    HMAC_SHA256 = "HmacSHA256"

def bytes_to_hex(bytes_data):
    """
    将字节数组转换为十六进制字符串
    """
    hex_chars = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f']
    result = []
    for b in bytes_data:
        result.append(hex_chars[(b & 0xf0) >> 4])
        result.append(hex_chars[b & 0x0f])
    return ''.join(result)
    
def get_sign_content(params):
    """
    计算签名内容
    """
    content_parts = []
    # 使用OrderedDict模拟TreeMap的排序行为
    sorted_keys = sorted(params.keys())
    
    for key in sorted_keys:
        value = params[key]
        # 检查键值是否都不为空
        if key and value:
            content_parts.append(f"{key}={value}")
    
    return "&".join(content_parts)
    
def encrypt(method, secret, content):
    """
    Hmac加密 返回hex格式的结果
    """
    # 根据算法类型选择哈希函数
    hash_funcs = {
        "HmacMD5": hashlib.md5,
        "HmacSHA1": hashlib.sha1,
        "HmacSHA256": hashlib.sha256
    }
    
    if method not in hash_funcs:
        raise ValueError(f"Unsupported encryption method: {method}")
    
    # 执行HMAC加密
    key = secret.encode('utf-8')
    message = content.encode('utf-8')
    digestmod = hash_funcs[method]
    
    hmac_obj = hmac.new(key, message, digestmod)
    return bytes_to_hex(hmac_obj.digest())
    
def sign(method, secret, params):
    """
    计算签名
    """
    content = get_sign_content(params)
    print(f"签名内容:{content}")
    
    # 支持的签名方法
    supported_methods = [SignatureMethod.HMAC_MD5, SignatureMethod.HMAC_SHA1, SignatureMethod.HMAC_SHA256]
    
    if method in supported_methods:
        return encrypt(method, secret, content)
    else:
        raise ValueError("method is error")

def main():
    """
    主函数，演示签名过程
    """
    # --------------------- 测试数据 ------------------------
    app_id = "YJY"
    secret = "test005"
    time_stamp = 1678414388870
    payload = {
        "sectionId": "62703309342730"
    }
    # ------------------------------------------------------

    # 转换payload为JSON字符串
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    # 构建参数字典
    params = OrderedDict()
    params[Constants.SIGN_APP_ID] = app_id
    params[Constants.SIGN_TIMESTAMP] = time_stamp
    params[Constants.SIGN_PAYLOAD] = payload_str
    
    # 计算签名
    signature = sign(SignatureMethod.HMAC_SHA256, secret, params)
    
    print(signature)
    
    url = "https://iland.zoomlion.com/fieldEquipment/openApi/v1/equipment.listCodeBySection"

    # 请求头
    headers = {
        "x-auth-app-id": app_id,
        "x-auth-timestamp": str(time_stamp),
        "x-auth-sign": signature,
        "Content-Type": "application/json"
    }

    print('................payload..................')
    print(payload)

    response = requests.post(
        url=url,
        json=payload,  # 使用JSON格式的payload
        headers=headers,
        timeout=30
    )
    
    response_json = response.json()
    print("响应体 (JSON):")
    print(json.dumps(response_json, indent=2, ensure_ascii=False))
    return response_json
            

if __name__ == "__main__":
    main()
