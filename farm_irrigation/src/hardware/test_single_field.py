#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试根据sectionId获取设备编码列表
专注于第一步：sectionId → 设备编码列表
"""
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
current_file = Path(__file__)
project_root = current_file.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.hardware.hw_get_deviceids_by_field import get_device_codes_by_section, extract_device_codes
from src.hardware.hw_get_info_by_deviceids import get_device_info_by_code, extract_unique_no, extract_device_info

# 测试配置
APP_ID = "YJY"
SECRET = "test005"
TEST_FIELD_ID = "1891820536309653504"  # 田块31

print("=" * 70)
print("测试：根据sectionId获取设备编码列表")
print("=" * 70)
print(f"田块ID (sectionId): {TEST_FIELD_ID}")
print(f"应用ID: {APP_ID}")
print(f"API接口: equipment.listCodeBySection")
print("=" * 70)
print()

# 调用API查询设备编码列表
print("【API调用】")
print("-" * 70)
response = get_device_codes_by_section(
    app_id=APP_ID,
    secret=SECRET,
    section_id=TEST_FIELD_ID,
    timeout=30,
    verbose=True
)

print()
print("=" * 70)
print("【响应分析】")
print("=" * 70)

if response:
    print("✅ HTTP请求成功")
    print()
    
    # 显示完整响应
    print("完整API响应:")
    print("-" * 70)
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print("-" * 70)
    print()
    
    # 分析响应结构
    code = response.get("code")
    message = response.get("message", "")
    data = response.get("data")
    
    print("响应字段分析:")
    print(f"  code (响应码): {code} (类型: {type(code).__name__})")
    print(f"  message (消息): {message if message else '(空字符串)'}")
    print(f"  data (数据): {data}")
    print(f"  data类型: {type(data).__name__}")
    
    if isinstance(data, list):
        print(f"  data长度: {len(data)}")
        if len(data) > 0:
            print(f"  data内容示例: {data[:3]}...")  # 只显示前3个
    elif isinstance(data, dict):
        print(f"  data键: {list(data.keys())}")
    print()
    
    # 判断是否为成功码
    code_str = str(code) if code is not None else ""
    is_success = (code == 200) or (code_str == "0000") or (code_str == "0")
    print(f"是否为成功码: {is_success}")
    print(f"  (200 或 '0000' 或 '0' 都视为成功)")
    print()
    
    # 提取设备编码
    print("=" * 70)
    print("【提取设备编码】")
    print("=" * 70)
    device_codes = extract_device_codes(response, verbose=True)
    print()
    
    print(f"提取结果: {device_codes}")
    print(f"设备编码数量: {len(device_codes)}")
    print()
    
    if device_codes:
        print("✅ 成功！找到以下设备编码:")
        for i, code in enumerate(device_codes, 1):
            print(f"  {i}. {code}")
        print()
        print("=" * 70)
        print("【总结 - 步骤1】")
        print("=" * 70)
        print(f"✅ sectionId '{TEST_FIELD_ID}' 对应 {len(device_codes)} 个设备编码")
        print(f"设备编码列表: {device_codes}")
        print()
        
        # 步骤2: 根据设备编码查询设备信息
        print("=" * 70)
        print("【步骤2】根据设备编码查询设备信息")
        print("=" * 70)
        print(f"将对 {len(device_codes)} 个设备编码逐一查询设备信息...")
        print()
        
        device_info_list = []
        for i, device_code in enumerate(device_codes, 1):
            print("-" * 70)
            print(f"设备 {i}/{len(device_codes)}: {device_code}")
            print("-" * 70)
            
            # 调用API查询设备信息
            device_response = get_device_info_by_code(
                app_id=APP_ID,
                secret=SECRET,
                device_code=device_code,
                timeout=30,
                verbose=True
            )
            
            print()
            if device_response:
                print("✅ API请求成功")
                print()
                print("完整API响应:")
                print("-" * 70)
                print(json.dumps(device_response, indent=2, ensure_ascii=False))
                print("-" * 70)
                print()
                
                # 分析响应
                api_code = device_response.get("code")
                api_message = device_response.get("message", "")
                api_data = device_response.get("data")
                
                print("响应分析:")
                print(f"  code: {api_code} (类型: {type(api_code).__name__})")
                print(f"  message: {api_message if api_message else '(空)'}")
                print(f"  data类型: {type(api_data).__name__}")
                print()
                
                # 判断是否为成功码
                code_str = str(api_code) if api_code is not None else ""
                is_success = (api_code == 200) or (code_str == "0000") or (code_str == "0")
                print(f"  是否为成功码: {is_success}")
                print()
                
                # 提取设备信息
                unique_no = extract_unique_no(device_response)
                device_info = extract_device_info(device_response)
                
                print("提取结果:")
                print(f"  uniqueNo: {unique_no if unique_no else '(未找到)'}")
                print(f"  设备信息: {'已提取' if device_info else '(未找到)'}")
                print()
                
                if unique_no and device_info:
                    device_info_list.append({
                        "device_code": device_code,
                        "unique_no": unique_no,
                        "device_info": device_info
                    })
                    print(f"✅ 设备编码 {device_code} -> uniqueNo: {unique_no}")
                    print(f"   设备信息键: {list(device_info.keys()) if isinstance(device_info, dict) else 'N/A'}")
                else:
                    print(f"⚠️ 设备编码 {device_code} 信息不完整")
                    if not unique_no:
                        print("   缺少: uniqueNo")
                    if not device_info:
                        print("   缺少: device_info")
            else:
                print("❌ API请求失败（响应为空）")
            
            print()
        
        # 总结步骤2
        print("=" * 70)
        print("【总结 - 步骤2】")
        print("=" * 70)
        print(f"成功查询设备信息: {len(device_info_list)}/{len(device_codes)}")
        print()
        
        if device_info_list:
            print("设备信息列表:")
            for i, info in enumerate(device_info_list, 1):
                print(f"\n设备 {i}:")
                print(f"  设备编码: {info['device_code']}")
                print(f"  唯一编号: {info['unique_no']}")
                print(f"  设备信息: {json.dumps(info['device_info'], indent=4, ensure_ascii=False)}")
        else:
            print("❌ 未能获取任何设备的完整信息")
    else:
        print("❌ 未获取到设备编码")
        print()
        print("=" * 70)
        print("【问题分析】")
        print("=" * 70)
        
        # 详细分析原因
        if is_success:
            if isinstance(data, list) and len(data) == 0:
                print("原因: API返回成功，但data为空列表 []")
                print("结论: 该sectionId在API系统中没有关联任何设备编码")
            elif data is None:
                print("原因: API返回成功，但data字段为None")
                print("结论: API响应格式异常")
            else:
                print(f"原因: API返回成功，但data格式不符合预期")
                print(f"实际data类型: {type(data).__name__}")
                print(f"实际data内容: {data}")
        else:
            print(f"原因: API返回错误码 {code}")
            print(f"错误消息: {message if message else '(空)'}")
            print("结论: API调用失败，需要检查认证信息或sectionId是否正确")
        
        print()
        print("建议:")
        print("1. 确认该sectionId在API系统中是否存在")
        print("2. 确认该sectionId是否已关联设备")
        print("3. 检查API认证信息是否正确")
        print("4. 查看API文档确认响应格式")
else:
    print("❌ HTTP请求失败（响应为空）")
    print()
    print("=" * 70)
    print("【问题分析】")
    print("=" * 70)
    print("可能的原因：")
    print("1. 网络连接问题")
    print("2. 请求超时（默认30秒）")
    print("3. API服务不可用")
    print("4. URL或请求格式错误")
    print()
    print("建议:")
    print("1. 检查网络连接")
    print("2. 增加timeout时间重试")
    print("3. 检查API URL是否正确")
    print("4. 查看详细错误日志")

print()
print("=" * 70)

