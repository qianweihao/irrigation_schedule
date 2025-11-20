#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境检查脚本 - 验证桥接方案的前置条件

使用：python check_environment.py
"""

import sys
import json
from pathlib import Path
import requests


def check_item(description, status, details=None):
    """打印检查项结果"""
    symbol = "[OK]" if status else "[FAIL]"
    print(f"{symbol} {description}")
    if details:
        print(f"  {details}")
    return status


def check_python_version():
    """检查 Python 版本"""
    version = sys.version_info
    required = (3, 7)
    
    status = version >= required
    details = f"当前版本: {version.major}.{version.minor}.{version.micro}"
    if not status:
        details += f" (需要 >= {required[0]}.{required[1]})"
    
    return check_item("Python 版本", status, details)


def check_packages():
    """检查必需的包"""
    packages = ['requests', 'pathlib']
    missing = []
    
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    status = len(missing) == 0
    details = "所有包已安装" if status else f"缺少: {', '.join(missing)}"
    
    return check_item("Python 依赖包", status, details)


def check_rice_backend():
    """检查 rice 后端是否运行"""
    try:
        response = requests.get(
            "http://localhost:5000/v1/rice_irrigation",
            params={'farm_id': '13944136728576'},
            timeout=5
        )
        status = response.status_code == 200
        details = "后端正在运行" if status else f"HTTP {response.status_code}"
    except requests.exceptions.ConnectionError:
        status = False
        details = "无法连接（请启动: python app.py）"
    except requests.exceptions.Timeout:
        status = False
        details = "连接超时"
    except Exception as e:
        status = False
        details = f"错误: {str(e)}"
    
    return check_item("rice_smart_irrigation 后端", status, details)


def check_farm_config():
    """检查 farm 配置文件"""
    config_path = Path("e:/irrigation_schedule/farm_irrigation/config.json")
    
    if not config_path.exists():
        return check_item("farm_irrigation 配置", False, f"文件不存在: {config_path}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        fields_count = len(config.get('fields', []))
        details = f"配置正常，包含 {fields_count} 个田块"
        return check_item("farm_irrigation 配置", True, details)
        
    except Exception as e:
        return check_item("farm_irrigation 配置", False, f"读取错误: {str(e)}")


def check_bridge_script():
    """检查桥接脚本"""
    script_path = Path("e:/irrigation_schedule/rice_to_farm_bridge.py")
    
    status = script_path.exists()
    details = "脚本已就绪" if status else f"文件不存在: {script_path}"
    
    return check_item("桥接脚本", status, details)


def check_mapping():
    """检查田块ID映射"""
    config_path = Path("e:/irrigation_schedule/farm_irrigation/config.json")
    
    if not config_path.exists():
        return check_item("田块ID映射", False, "配置文件不存在")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        fields_with_section = 0
        total_fields = len(config.get('fields', []))
        
        for field in config.get('fields', []):
            if field.get('sectionID'):
                fields_with_section += 1
        
        status = fields_with_section > 0
        details = f"{fields_with_section}/{total_fields} 个田块有 sectionID 映射"
        
        return check_item("田块ID映射", status, details)
        
    except Exception as e:
        return check_item("田块ID映射", False, f"检查错误: {str(e)}")


def main():
    """主函数"""
    print("="*70)
    print("环境检查 - rice → farm 桥接方案")
    print("="*70)
    print()
    
    results = []
    
    # 执行所有检查
    results.append(check_python_version())
    results.append(check_packages())
    results.append(check_bridge_script())
    results.append(check_farm_config())
    results.append(check_mapping())
    results.append(check_rice_backend())
    
    # 汇总结果
    print()
    print("="*70)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"[OK] All checks passed ({passed}/{total})")
        print()
        print("Environment ready! You can run:")
        print("  python rice_to_farm_bridge.py --farm-id 13944136728576")
    else:
        print(f"[WARNING] {passed}/{total} checks passed, {total - passed} need fixing")
        print()
        print("Please fix the issues above and try again")
    
    print("="*70)
    
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

