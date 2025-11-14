#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
物联网平台通用客户端
提供签名生成和HTTP请求的公共功能
"""
import hmac
import hashlib
import time
import json
import requests
import urllib.parse


class IoTClient:
    """物联网平台客户端"""
    
    def __init__(self, app_id: str, secret: str, timeout: int = 30):
        """
        初始化客户端
        
        Args:
            app_id: 应用ID
            secret: 密钥
            timeout: 请求超时时间（秒）
        """
        self.app_id = app_id
        self.secret = secret
        self.timeout = timeout
    
    def _generate_signature(self, timestamp: int, payload_query_str: str) -> str:
        """
        生成HMAC-SHA256签名
        
        Args:
            timestamp: 时间戳（毫秒）
            payload_query_str: 查询参数字符串
            
        Returns:
            str: 签名字符串
        """
        sign_content = f"{payload_query_str}\n{self.secret}\n{timestamp}"
        signature = hmac.new(
            self.secret.encode('utf-8'),
            sign_content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().upper()
        return signature
    
    def _payload_to_query_string(self, payload: dict) -> str:
        """
        将payload转换为查询参数字符串
        
        Args:
            payload: 请求参数字典
            
        Returns:
            str: 查询参数字符串
        """
        def build_value(val):
            if val is None:
                return None
            elif isinstance(val, dict):
                nested = self._dict_to_query_params(val)
                return f"{{{nested}}}" if nested else None
            elif isinstance(val, (list, tuple)):
                items = [str(item) if isinstance(item, (int, float, str, bool)) or item is None 
                        else f"{{{self._dict_to_query_params(item if isinstance(item, dict) else vars(item))}}}"
                        for item in val]
                return f"[{','.join(items)}]"
            elif not isinstance(val, (int, float, str, bool)):
                return f"{{{self._dict_to_query_params(vars(val))}}}"
            return str(val)
        
        return self._dict_to_query_params(payload, build_value)
    
    def _dict_to_query_params(self, param: dict, value_builder=None) -> str:
        """
        将字典转换为查询参数字符串
        
        Args:
            param: 参数字典
            value_builder: 值构建函数
            
        Returns:
            str: 查询参数字符串
        """
        if not param:
            return ""
        
        if value_builder is None:
            value_builder = lambda v: str(v) if v is not None else None
        
        # 排除特定key并排序
        filtered = [(k, v) for k, v in param.items() 
                   if k not in ('sign', 'signType') and v is not None]
        sorted_items = sorted(filtered, key=lambda x: x[0])
        
        parts = []
        for key, value in sorted_items:
            formatted_value = value_builder(value)
            if formatted_value and formatted_value.strip():
                parts.append(f"{key}={formatted_value}")
        
        return '&'.join(parts)
    
    def send_request(self, url: str, payload: dict, verbose: bool = False) -> dict:
        """
        发送HTTP请求
        
        Args:
            url: 请求URL
            payload: 请求参数
            verbose: 是否打印详细信息
            
        Returns:
            dict: 响应数据，失败返回None
        """
        timestamp = int(time.time() * 1000)
        
        # 生成查询参数字符串
        if 'identifier' in payload:  # 控制接口需要特殊处理
            payload_query_str = self._payload_to_query_string(payload)
        else:  # 查询接口使用简单编码
            payload_query_str = urllib.parse.urlencode(payload)
        
        # 限制长度
        payload_query_str = (payload_query_str or "").strip()[:1000]
        
        # 生成签名
        signature = self._generate_signature(timestamp, payload_query_str)
        
        # 构建请求头
        headers = {
            "AppId": self.app_id,
            "timestamp": str(timestamp),
            "AppSign": signature,
            "Content-Type": "application/json"
        }
        
        # 打印详细信息
        if verbose:
            print("=== 请求详情 ===")
            print(f"URL: {url}")
            print(f"Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
            print(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
            print(f"Query String: {payload_query_str}")
            print(f"Signature: {signature}")
            print("================\n")
        
        # 发送请求
        try:
            response = requests.post(
                url=url.strip(),
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            if verbose:
                print("=== 响应详情 ===")
                print(f"状态码: {response.status_code}")
            
            response_data = response.json()
            
            if verbose:
                print(f"响应: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
                print("================\n")
            
            return response_data
            
        except requests.exceptions.Timeout:
            print(f"❌ 请求超时 ({self.timeout}秒)")
        except requests.exceptions.ConnectionError:
            print("❌ 连接错误 - 请检查URL和网络连接")
        except requests.exceptions.RequestException as e:
            print(f"❌ 请求失败: {e}")
        except json.JSONDecodeError:
            print(f"❌ 响应解析失败: {response.text if 'response' in locals() else 'No response'}")
        
        return None
