import hmac
import hashlib
import time
import json
import requests
import urllib.parse
import pprint

# 物联网平台查看设备属性的接口
url = "http://ziot-web.zvos.zoomlion.com/api/app/openApi/device/properties.newest"


def generate_signature(app_id, secret, timestamp, payload_query_str):

    sign_content = payload_query_str + "\n" + secret + "\n" + str(timestamp)
    
    # 生成HMAC-SHA256签名
    secret_bytes = secret.encode('utf-8')
    content_bytes = sign_content.encode('utf-8')
    
    signature = hmac.new(
        secret_bytes,
        content_bytes,
        hashlib.sha256
    ).hexdigest().upper()
    
    return signature, sign_content

def send_request(app_id, secret, unique_no):
    # 生成时间戳
    timestamp = int(time.time() * 1000)
    
    # 组装payload
    payload_dict = {"uniqueNo": unique_no}
    
    # 将payload转换为QueryParam格式的字符串
    payload_query_str = urllib.parse.urlencode(payload_dict)
    
    if payload_query_str is None:
        payload_query_str = ""
    else:
        payload_query_str = payload_query_str.strip()

    if payload_query_str is not None and len(payload_query_str) > 1000:
        payload_query_str = payload_query_str[:1000]
    
    # 生成签名
    signature, signed_content = generate_signature(app_id, secret, timestamp, payload_query_str)
        
    headers = {
        "AppId": app_id,
        "timestamp": str(timestamp),
        "AppSign": signature,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            url=url,
            json=payload_dict,  # 使用JSON格式的payload
            headers=headers,
            timeout=30
        )
        
        try:
            response_json = response.json()
            return response_json
        except json.JSONDecodeError:
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

if __name__ == "__main__":
    # 使用指定的参数值
    app_id = "siotextend"
    secret = "!iWu$fyUgOSH+mc_nSirKpL%+zZ%)%cL"
    unique_no = "477379421064159253"
    
    result = send_request(app_id, secret, unique_no)
    # print(result)
    print('-----------result------------')
    for d in result['data']:
        for p in d['properties']:
            if p['name'] == '水闸闸门开度':
                print(f"设备的开合度为：{p['value']}")
    print('-----------------------------')

    if result is None:
        print("\n❌ 请求失败")
    else:
        print("\n✅ 请求完成")
