#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
签名工具类
用于 iland 平台的 API 签名
"""
import hashlib
import hmac
import time
import json
from collections import OrderedDict
from typing import Dict, Any


class SignatureMethod:
    """签名方法枚举"""
    HMAC_MD5 = "HmacMD5"
    HMAC_SHA1 = "HmacSHA1"
    HMAC_SHA256 = "HmacSHA256"


class Constants:
    """签名常量"""
    SIGN_APP_ID = "app-id"
    SIGN_TIMESTAMP = "timestamp"
    SIGN_PAYLOAD = "payload"


class SignatureHelper:
    """签名工具类"""
    
    @staticmethod
    def bytes_to_hex(bytes_data: bytes) -> str:
        """
        将字节数组转换为十六进制字符串
        
        Args:
            bytes_data: 字节数组
            
        Returns:
            str: 十六进制字符串
        """
        hex_chars = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f']
        result = []
        for b in bytes_data:
            result.append(hex_chars[(b & 0xf0) >> 4])
            result.append(hex_chars[b & 0x0f])
        return ''.join(result)
    
    @staticmethod
    def get_sign_content(params: Dict[str, Any]) -> str:
        """
        计算签名内容
        
        Args:
            params: 参数字典
            
        Returns:
            str: 签名内容字符串
        """
        content_parts = []
        # 使用排序模拟TreeMap的排序行为
        sorted_keys = sorted(params.keys())
        
        for key in sorted_keys:
            value = params[key]
            # 检查键值是否都不为空
            if key and value:
                content_parts.append(f"{key}={value}")
        
        return "&".join(content_parts)
    
    @staticmethod
    def encrypt(method: str, secret: str, content: str) -> str:
        """
        Hmac加密，返回hex格式的结果
        
        Args:
            method: 加密方法 (HmacMD5, HmacSHA1, HmacSHA256)
            secret: 密钥
            content: 待加密内容
            
        Returns:
            str: 加密后的十六进制字符串
        """
        # 根据算法类型选择哈希函数
        hash_funcs = {
            SignatureMethod.HMAC_MD5: hashlib.md5,
            SignatureMethod.HMAC_SHA1: hashlib.sha1,
            SignatureMethod.HMAC_SHA256: hashlib.sha256
        }
        
        if method not in hash_funcs:
            raise ValueError(f"Unsupported encryption method: {method}")
        
        # 执行HMAC加密
        key = secret.encode('utf-8')
        message = content.encode('utf-8')
        digestmod = hash_funcs[method]
        
        hmac_obj = hmac.new(key, message, digestmod)
        return SignatureHelper.bytes_to_hex(hmac_obj.digest())
    
    @staticmethod
    def sign(method: str, secret: str, params: Dict[str, Any], verbose: bool = False) -> str:
        """
        计算签名
        
        Args:
            method: 签名方法
            secret: 密钥
            params: 参数字典
            verbose: 是否打印详细信息
            
        Returns:
            str: 签名字符串
        """
        content = SignatureHelper.get_sign_content(params)
        
        if verbose:
            print(f"签名内容: {content}")
        
        # 支持的签名方法
        supported_methods = [
            SignatureMethod.HMAC_MD5,
            SignatureMethod.HMAC_SHA1,
            SignatureMethod.HMAC_SHA256
        ]
        
        if method in supported_methods:
            return SignatureHelper.encrypt(method, secret, content)
        else:
            raise ValueError(f"Unsupported signature method: {method}")
    
    @staticmethod
    def generate_signature_for_iland(
        app_id: str,
        secret: str,
        payload: Dict[str, Any],
        timestamp: int = None,
        verbose: bool = False
    ) -> tuple:
        """
        为 iland 平台生成签名
        
        Args:
            app_id: 应用ID
            secret: 密钥
            payload: 请求负载
            timestamp: 时间戳（毫秒），如果为None则自动生成
            verbose: 是否打印详细信息
            
        Returns:
            tuple: (timestamp, signature, headers)
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        
        # 转换payload为JSON字符串
        payload_str = json.dumps(payload, separators=(',', ':'))
        
        # 构建参数字典
        params = OrderedDict()
        params[Constants.SIGN_APP_ID] = app_id
        params[Constants.SIGN_TIMESTAMP] = timestamp
        params[Constants.SIGN_PAYLOAD] = payload_str
        
        # 计算签名
        signature = SignatureHelper.sign(
            SignatureMethod.HMAC_SHA256,
            secret,
            params,
            verbose=verbose
        )
        
        # 构建请求头
        headers = {
            "x-auth-app-id": app_id,
            "x-auth-timestamp": str(timestamp),
            "x-auth-sign": signature,
            "Content-Type": "application/json"
        }
        
        return timestamp, signature, headers

