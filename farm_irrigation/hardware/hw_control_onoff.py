import hmac
import hashlib
import time
import json
import requests
import urllib.parse
from collections.abc import Iterable

# 物联网平台控制设备的接口
url = "http://ziot-web.zvos.zoomlion.com/api/app/openApi/device/deviceMsg/thingProperty.sync.invoke"


def is_simple_data_type(obj):
    """判断对象是否为基本数据类型"""
    return isinstance(obj, (int, float, str, bool)) or obj is None


def map_to_query_params(param):
    """
    将字典转换为查询参数字符串
    
    :param param: 输入的字典参数
    :return: 查询参数字符串
    """
    if not param:
        return ""
        
    def build_value(val):
        if val is None:
            return None
        elif isinstance(val, dict):
            nested_result = map_to_query_params(val)
            return '{' + nested_result + '}' if nested_result else None
        elif isinstance(val, (list, tuple)):
            items = []
            for item in val:
                if is_simple_data_type(item):
                    items.append(str(item))
                else:
                    nested_result = map_to_query_params(item if isinstance(item, dict) else vars(item))
                    items.append('{' + nested_result + '}')
            return '[' + ','.join(items) + ']'
        elif not is_simple_data_type(val):
            # 对象转字典后再处理
            return '{' + map_to_query_params(vars(val)) + '}'
        else:
            return str(val)
    # 排除特定key并排序
    filtered_items = [(k, v) for k, v in param.items() if k not in ('sign', 'signType') and v is not None]
    sorted_items = sorted(filtered_items, key=lambda x: x[0])

    parts = []
    for key, value in sorted_items:
        formatted_value = build_value(value)
        if formatted_value is not None and formatted_value.strip():
            parts.append(f"{key}={formatted_value}")
    
    return '&'.join(parts)

def generate_signature(app_id, secret, timestamp, payload_query_str):

    sign_content = payload_query_str + "\n" + secret + "\n" + str(timestamp)
    
    secret_bytes = secret.encode('utf-8')
    content_bytes = sign_content.encode('utf-8')
    
    signature = hmac.new(
        secret_bytes,
        content_bytes,
        hashlib.sha256
    ).hexdigest().upper()
    
    return signature, sign_content

def send_request(app_id, secret, unique_no, target_gate_degree):
    timestamp = int(time.time() * 1000)
    
    payload_dict = {"uniqueNo": unique_no,"identifier":"gateDegree","params":{"gateDegree": target_gate_degree}}
    
    # 将payload转换为QueryParam格式的字符串
    payload_query_str = map_to_query_params(payload_dict)
    
    if payload_query_str is None:
        payload_query_str = ""
    else:
        payload_query_str = payload_query_str.strip()

    if payload_query_str is not None and len(payload_query_str) > 1000:
        payload_query_str = payload_query_str[:1000]
    
    signature, signed_content = generate_signature(app_id, secret, timestamp, payload_query_str)
    
    headers = {
        "AppId": app_id,
        "timestamp": str(timestamp),
        "AppSign": signature,
        "Content-Type": "application/json"
    }
    
    print("=== 请求详情 ===")
    print(f"URL: {url}")
    print(f"Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
    print(f"Payload (JSON): {json.dumps(payload_dict, ensure_ascii=False)}")
    print(f"Payload (QueryParam): {payload_query_str}")
    print(f"签名字符串: {signed_content}")
    print(f"签名: {signature}")
    print("================\n")
    
    try:
        response = requests.post(
            url=url,
            json=payload_dict,  # 使用JSON格式的payload
            headers=headers,
            timeout=30
        )
        
        print("=== 响应详情 ===")
        print(f"状态码: {response.status_code}")
        
        try:
            response_json = response.json()
            print("响应体 (JSON):")
            print(json.dumps(response_json, indent=2, ensure_ascii=False))
            return response_json
        except json.JSONDecodeError:
            print("响应体 (文本):")
            print(response.text)
            return response.text
            
    except requests.exceptions.Timeout:
        print("请求超时 (30秒)")
        return None
    except requests.exceptions.ConnectionError:
        print("连接错误 - 请检查URL和网络连接")
        return None
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None

# 使用示例
if __name__ == "__main__":
    # 使用指定的参数值
    app_id = "siotextend"
    secret = "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
    unique_no = "477379421064159253"
    
    print("使用指定参数发送请求:")
    print(f"AppId: {app_id}")
    print(f"unique_no: {unique_no}")
    print(f"secret: {secret[:5]}...{secret[-5:]}")
    
    # -------- 发送关闭设备请求 --------
    result = send_request(app_id, secret, unique_no, 0)
    if result is None:
        print("\n❌ 发送关闭设备请求失败")
    else:
        print("\n✅ 发送关闭设备请求完成")

    # -------- 发送打开设备请求 --------
    # result = send_request(app_id, secret, unique_no, 100)
    # if result is None:
    #     print("\n❌ 发送打开设备请求失败")
    # else:
    #     print("\n✅ 发送打开设备请求完成")