#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rice_smart_irrigation → farm_irrigation 桥接脚本
零修改方案：不修改任何现有项目代码

作者：AI Assistant
版本：1.0
"""

import json
import subprocess
import sys
import requests
from pathlib import Path
from datetime import datetime
import argparse


def print_header(title):
    """打印标题"""
    print("\n" + "="*70)
    print(title)
    print("="*70)


def print_success(message):
    """打印成功信息"""
    print(f"✓ {message}")


def print_error(message):
    """打印错误信息"""
    print(f"✗ {message}")


def print_info(message):
    """打印信息"""
    print(f"  {message}")


def get_rice_decisions(farm_id, rice_api_url="http://localhost:5000/v1/rice_irrigation"):
    """
    从 rice API 获取灌溉决策
    
    Args:
        farm_id: 农场ID
        rice_api_url: rice API 地址
    
    Returns:
        dict: 决策数据，失败返回 None
    """
    print(f"\n正在获取农场 {farm_id} 的智能决策...")
    
    try:
        response = requests.get(
            rice_api_url, 
            params={'farm_id': farm_id}, 
            timeout=30
        )
        response.raise_for_status()
        decisions = response.json()
        
        # 统计决策
        stats = {'irrigate': 0, 'drain': 0, 'none': 0}
        for section_id, decision in decisions.items():
            if section_id != 'log':
                action = decision.get('action', 'none')
                stats[action] = stats.get(action, 0) + 1
        
        print_success(f"决策获取成功")
        print_info(f"需要灌溉: {stats['irrigate']} 个田块")
        print_info(f"需要排水: {stats['drain']} 个田块")
        print_info(f"无需操作: {stats['none']} 个田块")
        
        return decisions
        
    except requests.exceptions.ConnectionError:
        print_error("无法连接到 rice 后端服务")
        print_info("请确保 rice 后端正在运行: python app.py")
        return None
    except requests.exceptions.Timeout:
        print_error("请求超时")
        return None
    except Exception as e:
        print_error(f"获取决策失败: {str(e)}")
        return None


def load_farm_config(farm_dir):
    """
    加载 farm_irrigation 配置
    
    Args:
        farm_dir: farm_irrigation 项目目录
    
    Returns:
        tuple: (映射字典, 配置字典)
    """
    config_path = farm_dir / "config.json"
    
    if not config_path.exists():
        print_error(f"配置文件不存在: {config_path}")
        return None, None
    
    print("\n正在加载 farm_irrigation 配置...")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 建立 section_id → field_id 映射
        mapping = {}
        for field in config.get('fields', []):
            section_id = str(field.get('sectionID'))
            if section_id:
                mapping[section_id] = {
                    'field_id': field.get('id'),
                    'area_mu': field.get('area_mu')
                }
        
        print_success(f"配置加载成功，找到 {len(mapping)} 个田块映射")
        return mapping, config
        
    except Exception as e:
        print_error(f"加载配置失败: {str(e)}")
        return None, None


def convert_decisions(decisions, mapping):
    """
    转换 rice 决策为 farm 格式
    
    Args:
        decisions: rice 的决策数据
        mapping: section_id 到 field_id 的映射
    
    Returns:
        tuple: (custom_waterlevels字典, field_targets字典)
    """
    print("\n正在转换决策格式...")
    
    custom_wl = {}
    field_targets = {}
    skipped = []
    
    for section_id, decision in decisions.items():
        if section_id == 'log':
            continue
        
        # 只处理需要灌溉的田块
        if decision.get('action') != 'irrigate':
            continue
        
        # 查找映射
        if section_id not in mapping:
            skipped.append(section_id)
            continue
        
        field_id = mapping[section_id]['field_id']
        current_wl = decision.get('current_waterlevel')
        target_wl = decision.get('target')
        
        # 验证数据完整性
        if current_wl is None or target_wl is None:
            print_info(f"⚠ {section_id} 缺少水位数据，跳过")
            continue
        
        if target_wl <= current_wl:
            print_info(f"⚠ {section_id} 目标水位不高于当前水位，跳过")
            continue
        
        custom_wl[field_id] = current_wl
        field_targets[field_id] = target_wl
    
    print_success(f"转换完成: {len(custom_wl)} 个灌溉任务")
    
    if skipped:
        print_info(f"⚠ {len(skipped)} 个田块未找到映射，已跳过")
    
    return custom_wl, field_targets


def create_temp_config(config, field_targets, custom_wl, farm_dir):
    """
    创建临时配置文件
    
    策略：
    1. 需要灌溉的田块：wl_low = current + 1, wl_opt = rice_target
    2. 不需要灌溉的田块：wl_low = 999（高阈值）
    
    Args:
        config: 原始配置
        field_targets: 需要灌溉的田块目标水位
        custom_wl: 当前水位
        farm_dir: farm 项目目录
    
    Returns:
        Path: 临时配置文件路径
    """
    print("\n正在创建临时配置...")
    
    temp_config = config.copy()
    updated_count = 0
    
    for field in temp_config.get('fields', []):
        field_id = field.get('id')
        
        if field_id in field_targets:
            # 需要灌溉的田块
            current_wl = custom_wl[field_id]
            target_wl = field_targets[field_id]
            
            field['wl_mm'] = current_wl
            field['wl_low'] = current_wl + 1  # 关键：确保触发灌溉
            field['wl_opt'] = target_wl       # 关键：rice 的目标
            
            updated_count += 1
        else:
            # 不需要灌溉的田块：设置高阈值
            if field.get('wl_mm') is not None:
                field['wl_low'] = 999
    
    # 保存临时配置
    temp_config_path = farm_dir / "config_temp_rice.json"
    
    try:
        with open(temp_config_path, 'w', encoding='utf-8') as f:
            json.dump(temp_config, f, ensure_ascii=False, indent=2)
        
        print_success(f"临时配置已创建: {temp_config_path}")
        print_info(f"已更新 {updated_count} 个田块的配置")
        
        return temp_config_path
        
    except Exception as e:
        print_error(f"创建临时配置失败: {str(e)}")
        return None


def call_farm_irrigation(farm_dir, temp_config, custom_wl, pumps, time_constraints):
    """
    调用 farm_irrigation 生成计划
    
    Args:
        farm_dir: farm 项目目录
        temp_config: 临时配置路径
        custom_wl: 自定义水位字典
        pumps: 启用的水泵
        time_constraints: 是否启用时间约束
    
    Returns:
        tuple: (是否成功, 输出文件名)
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"plan_from_rice_{timestamp}.json"
    
    print_header("调用 farm_irrigation 生成灌溉计划")
    
    cmd = [
        sys.executable,
        "-m", "src.core.run_irrigation_plan",
        "--config", str(temp_config),
        "--out", output_file,
        "--pumps", pumps,
        "--custom-waterlevels", json.dumps(custom_wl),
        "--summary"
    ]
    
    if time_constraints:
        cmd.append("--time-constraints")
    
    print_info(f"配置文件: {temp_config}")
    print_info(f"启用水泵: {pumps}")
    print_info(f"输出文件: {output_file}")
    print_info(f"时间约束: {'是' if time_constraints else '否'}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=farm_dir,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=120
        )
        
        if result.returncode == 0:
            print_success("灌溉计划生成成功！")
            print("\n" + "="*70)
            print(result.stdout)
            print("="*70)
            return True, output_file
        else:
            print_error("生成失败")
            print(result.stderr)
            return False, None
            
    except subprocess.TimeoutExpired:
        print_error("执行超时（120秒）")
        return False, None
    except Exception as e:
        print_error(f"执行出错: {str(e)}")
        return False, None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="rice → farm 智能灌溉桥接（零修改方案）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  # 基本用法
  python rice_to_farm_bridge.py --farm-id 13944136728576
  
  # 指定水泵
  python rice_to_farm_bridge.py --farm-id 13944136728576 --pumps P1
  
  # 启用时间约束
  python rice_to_farm_bridge.py --farm-id 13944136728576 --time-constraints
  
  # 保留临时配置（调试用）
  python rice_to_farm_bridge.py --farm-id 13944136728576 --keep-temp

注意事项：
  1. 确保 rice_smart_irrigation 后端正在运行
  2. 确保 farm_irrigation 配置文件存在
  3. 生成的计划会保存在 farm_irrigation 目录
        """
    )
    
    parser.add_argument("--farm-id", required=True, help="农场ID")
    parser.add_argument("--pumps", default="P1,P2", help="启用的水泵（逗号分隔）")
    parser.add_argument("--time-constraints", action="store_true", help="启用泵时间约束")
    parser.add_argument("--keep-temp", action="store_true", help="保留临时配置文件（调试用）")
    parser.add_argument("--rice-api", 
                        default="http://localhost:5000/v1/rice_irrigation",
                        help="rice API 地址")
    parser.add_argument("--farm-dir", 
                        default="e:/irrigation_schedule/farm_irrigation",
                        help="farm_irrigation 项目目录")
    
    args = parser.parse_args()
    
    print_header("rice → farm 智能灌溉桥接")
    print("零修改方案：不修改任何项目代码")
    print(f"农场ID: {args.farm_id}")
    print(f"水泵: {args.pumps}")
    
    farm_dir = Path(args.farm_dir)
    
    # 步骤1：获取 rice 决策
    decisions = get_rice_decisions(args.farm_id, args.rice_api)
    if not decisions:
        print_error("\n流程终止：无法获取决策")
        sys.exit(1)
    
    # 步骤2：加载 farm 配置
    mapping, config = load_farm_config(farm_dir)
    if not mapping or not config:
        print_error("\n流程终止：无法加载配置")
        sys.exit(1)
    
    # 步骤3：转换格式
    custom_wl, field_targets = convert_decisions(decisions, mapping)
    
    if not custom_wl:
        print_success("\n没有需要灌溉的田块")
        sys.exit(0)
    
    # 步骤4：创建临时配置
    temp_config = create_temp_config(config, field_targets, custom_wl, farm_dir)
    if not temp_config:
        print_error("\n流程终止：无法创建临时配置")
        sys.exit(1)
    
    # 步骤5：调用 farm_irrigation
    success, output_file = call_farm_irrigation(
        farm_dir=farm_dir,
        temp_config=temp_config,
        custom_wl=custom_wl,
        pumps=args.pumps,
        time_constraints=args.time_constraints
    )
    
    # 步骤6：清理临时文件
    if not args.keep_temp:
        try:
            temp_config.unlink()
            print_success("\n已删除临时配置")
        except Exception as e:
            print_info(f"⚠ 删除临时配置失败: {str(e)}")
    else:
        print_info(f"\n临时配置已保留: {temp_config}")
    
    # 输出结果
    if success:
        print_header("✓ 集成完成")
        print_info(f"灌溉计划: {farm_dir / output_file}")
        print_info("基于 rice_smart_irrigation 的智能决策")
        print_info("farm_irrigation 完全信任并执行决策")
        print("="*70 + "\n")
        sys.exit(0)
    else:
        print_error("\n流程失败")
        sys.exit(1)


if __name__ == "__main__":
    main()

