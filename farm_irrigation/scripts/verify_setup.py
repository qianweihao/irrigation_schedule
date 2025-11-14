#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证项目设置是否正确
注意：此脚本需要从项目根目录运行
"""
import os
import sys
import io
from pathlib import Path

# 设置输出编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 切换到项目根目录（脚本在scripts目录下）
script_dir = Path(__file__).parent
project_root = script_dir.parent
os.chdir(project_root)

# 添加项目根目录到Python路径
sys.path.insert(0, str(project_root))

def check_directories():
    """检查必要的目录是否存在"""
    print("检查目录结构...")
    required_dirs = [
        "data",
        "data/gzp_farm",
        "data/output",
        "data/execution_logs",
        "data/labeled_output",
        "src",
        "src/core",
        "src/api",
        "src/scheduler",
        "src/optimizer",
        "src/converter",
        "src/hardware",
        "docs",
        "tests"
    ]
    
    missing = []
    for dir_path in required_dirs:
        if not os.path.exists(dir_path):
            missing.append(dir_path)
            print(f"  ✗ {dir_path} - 不存在")
        else:
            print(f"  ✓ {dir_path}")
    
    return len(missing) == 0

def check_files():
    """检查关键文件是否存在"""
    print("\n检查关键文件...")
    required_files = [
        "main_dynamic_execution_api.py",
        "api_server.py",
        "requirements.txt",
        "config.json",
        "deployment/Dockerfile",
        "deployment/docker-compose.yml"
    ]
    
    missing = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing.append(file_path)
            print(f"  ✗ {file_path} - 不存在")
        else:
            print(f"  ✓ {file_path}")
    
    return len(missing) == 0

def check_imports():
    """检查模块导入"""
    print("\n检查模块导入...")
    try:
        # 添加当前目录到Python路径
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # 测试核心模块
        from src.core import pipeline
        print("  ✓ src.core.pipeline")
        
        from src.core import farm_irr_full_device_modified
        print("  ✓ src.core.farm_irr_full_device_modified")
        
        # 测试API模块
        from src.api import dynamic_execution_api
        print("  ✓ src.api.dynamic_execution_api")
        
        from src.api import batch_regeneration_api
        print("  ✓ src.api.batch_regeneration_api")
        
        # 测试调度器模块
        from src.scheduler import batch_execution_scheduler
        print("  ✓ src.scheduler.batch_execution_scheduler")
        
        from src.scheduler import execution_status_manager
        print("  ✓ src.scheduler.execution_status_manager")
        
        print("\n  所有模块导入成功！")
        return True
    except Exception as e:
        print(f"\n  ✗ 模块导入失败: {e}")
        return False

def check_data_files():
    """检查数据文件"""
    print("\n检查数据文件...")
    
    # 检查GIS数据
    gis_files = list(Path("data/gzp_farm").glob("*.geojson"))
    if gis_files:
        print(f"  ✓ 找到 {len(gis_files)} 个GeoJSON文件")
    else:
        print(f"  ⚠ 未找到GeoJSON文件（如需使用请添加）")
    
    # 检查labeled数据
    labeled_files = list(Path("data/labeled_output").glob("*.geojson"))
    if labeled_files:
        print(f"  ✓ 找到 {len(labeled_files)} 个标注文件")
    else:
        print(f"  ⚠ 未找到标注文件（可选）")
    
    return True

def main():
    """主函数"""
    print("=" * 60)
    print("项目设置验证")
    print("=" * 60)
    
    checks = [
        ("目录结构", check_directories),
        ("关键文件", check_files),
        ("数据文件", check_data_files),
        ("模块导入", check_imports)
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n{name}检查失败: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")
        if not result:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✓ 所有检查通过！系统可以正常启动。")
        print("\n启动命令:")
        print("  python main_dynamic_execution_api.py")
        print("  或")
        print("  docker-compose up -d")
    else:
        print("✗ 部分检查未通过，请修复上述问题后再启动。")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

