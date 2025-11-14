#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
农场灌溉调度系统 - 自动化执行流水线

功能：
1. 数据预处理:farmgis_convert.py 和 fix_farmgis_convert.py
2. 配置生成:auto_to_config.py
3. 计划生成:run_irrigation_plan.py

使用方法：
    python pipeline.py --input-dir ./gzp_farm --output-dir ./output
    python pipeline.py --config pipeline_config.yaml
"""

import os
import sys
import argparse
import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime
import yaml

# 配置日志
import os
# 基于项目根目录计算日志路径
_log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'execution_logs')
_log_dir = os.path.abspath(_log_dir)
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, 'pipeline.log'), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ],
    force = True,
)
logger = logging.getLogger(__name__)
# 设置控制台输出编码
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass  # Python < 3.7
logger = logging.getLogger(__name__)

class IrrigationPipeline:
    """农场灌溉调度系统自动化流水线"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.current_dir = Path(__file__).parent
        self.start_time = datetime.now()
        
    def check_dependencies(self):
        """检查依赖文件是否存在"""
        logger.info("检查依赖文件...")
        
        # 获取项目根目录
        project_root = self.current_dir.parent.parent if 'src' in str(self.current_dir) else self.current_dir
        
        required_modules = [
            ('src/converter/farmgis_convert.py', 'farmgis_convert'),
            ('src/converter/fix_farmgis_convert.py', 'fix_farmgis_convert'), 
            ('src/converter/auto_to_config.py', 'auto_to_config'),
            ('src/core/run_irrigation_plan.py', 'run_irrigation_plan')
        ]
        
        missing_files = []
        for file_path, module_name in required_modules:
            full_path = project_root / file_path
            if not full_path.exists():
                missing_files.append(module_name)
                
        if missing_files:
            logger.error(f"缺少必要模块: {missing_files}")
            return False
            
        logger.info("依赖文件检查通过")
        return True
        
    def check_input_files(self, input_dir):
        """检查输入文件是否存在"""
        logger.info(f"检查输入目录: {input_dir}")
        
        input_path = Path(input_dir)
        if not input_path.exists():
            logger.error(f"输入目录不存在: {input_dir}")
            return False
            
        # 检查是否有GIS数据文件（shapefile或geojson）
        gis_files = list(input_path.glob('*.shp')) + list(input_path.glob('*.geojson'))
        if not gis_files:
            logger.warning(f"在 {input_dir} 中未找到GIS数据文件(.shp或.geojson)")
            
        logger.info(f"找到 {len(gis_files)} 个GIS数据文件")
        return True
        
    def run_command(self, command, description, cwd=None, timeout=300):
        """执行命令并处理结果"""
        logger.info(f"开始执行: {description}")
        logger.info(f"命令: {' '.join(command)}")
        
        process = None
        try:
            # 获取项目根目录并设置PYTHONPATH
            project_root = self.current_dir.parent.parent if 'src' in str(self.current_dir) else self.current_dir
            env = os.environ.copy()
            env['PYTHONPATH'] = str(project_root)
            
            # 使用 Popen 以便更好地控制进程
            process = subprocess.Popen(
                command,
                cwd=project_root,  # 从项目根目录运行
                env=env,  # 传递环境变量
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # 等待进程完成，设置超时
            stdout, stderr = process.communicate(timeout=timeout)
            
            if process.returncode == 0:
                if stdout:
                    logger.info(f"输出: {stdout}")
                if stderr:
                    logger.warning(f"警告: {stderr}")
                logger.info(f"[OK] {description} 执行成功")
                return True
            else:
                logger.error(f"[FAIL] {description} 执行失败")
                logger.error(f"错误代码: {process.returncode}")
                logger.error(f"错误输出: {stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"[TIMEOUT] {description} 执行超时 ({timeout}秒)")
            if process:
                process.kill()
                process.wait()  # 确保进程完全终止
            return False
        except Exception as e:
            logger.error(f"[ERROR] {description} 执行异常: {str(e)}")
            if process:
                process.kill()
                process.wait()
            return False
        finally:
            # 确保进程资源被清理
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            
    def step1_data_preprocessing(self, input_dir):
        """步骤1: 数据预处理"""
        logger.info("=== 步骤1: 数据预处理 ===")
        
        # 检查是否需要运行farmgis_convert.py
        input_path = Path(input_dir)
        shp_files = list(input_path.glob('*.shp'))
        
        if shp_files:
            logger.info("发现Shapefile文件，运行格式转换...")
            
            # 运行farmgis_convert模块
            if not self.run_command(
                [sys.executable, '-m', 'src.converter.farmgis_convert'],
                "GIS数据格式转换"
            ):
                return False
                
            # 运行fix_farmgis_convert模块
            if not self.run_command(
                [sys.executable, '-m', 'src.converter.fix_farmgis_convert'],
                "GIS数据修复"
            ):
                return False
        else:
            logger.info("未发现Shapefile文件，跳过格式转换步骤")
            
        return True
        
    def step2_config_generation(self, input_dir, output_dir):
        """步骤2: 配置生成"""
        logger.info("=== 步骤2: 配置生成 ===")
        
        # 构建auto_to_config模块的参数
        cmd = [sys.executable, '-m', 'src.converter.auto_to_config']
        
        # 如果指定了输入目录，添加相关参数
        if input_dir != './gzp_farm':
            input_path = Path(input_dir)
            
            # 查找相关文件
            segments_file = None
            gates_file = None
            fields_file = None
            
            for file in input_path.glob('*'):
                name_lower = file.name.lower()
                if '水路' in name_lower or 'segment' in name_lower:
                    if file.suffix == '.geojson':
                        segments_file = str(file)
                elif '阀门' in name_lower or '节制闸' in name_lower or 'gate' in name_lower:
                    if file.suffix == '.geojson':
                        gates_file = str(file)
                elif '田块' in name_lower or 'field' in name_lower:
                    if file.suffix == '.geojson':
                        fields_file = str(file)
                        
            # 添加文件路径参数
            if segments_file:
                cmd.extend(['--segments', segments_file])
            if gates_file:
                cmd.extend(['--gates', gates_file])
            if fields_file:
                cmd.extend(['--fields', fields_file])
                
        return self.run_command(cmd, "生成系统配置")
        
    def step3_plan_generation(self, output_dir, **kwargs):
        """步骤3: 计划生成"""
        logger.info("=== 步骤3: 灌溉计划生成 ===")
        
        # 构建run_irrigation_plan模块的参数
        cmd = [sys.executable, '-m', 'src.core.run_irrigation_plan']
        
        # 添加输出文件
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        plan_file = output_path / f"irrigation_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        cmd.extend(['--out', str(plan_file)])
        
        # 添加可选参数
        if kwargs.get('pumps'):
            cmd.extend(['--pumps', kwargs['pumps']])
        if kwargs.get('zones'):
            cmd.extend(['--zones', kwargs['zones']])
        if kwargs.get('multi_pump_scenarios', False):
            cmd.append('--multi-pump')
        if kwargs.get('time_constraints', False):
            cmd.append('--time-constraints')
        if kwargs.get('print_summary', True):
            cmd.append('--summary')
        if kwargs.get('merge_waterlevels', True):
            cmd.append('--realtime')
        if kwargs.get('custom_waterlevels'):
            cmd.extend(['--custom-waterlevels', kwargs['custom_waterlevels']])
            
        return self.run_command(cmd, "生成灌溉计划")
        
    def run_pipeline(self, input_dir='./gzp_farm', output_dir='./output', **kwargs):
        """运行完整流水线"""
        logger.info("开始执行农场灌溉调度系统自动化流水线")
        logger.info(f"输入目录: {input_dir}")
        logger.info(f"输出目录: {output_dir}")
        
        # 检查依赖
        if not self.check_dependencies():
            return False
            
        # 检查输入文件
        if not self.check_input_files(input_dir):
            return False
            
        # 执行步骤
        steps = [
            (self.step1_data_preprocessing, [input_dir]),
            (self.step2_config_generation, [input_dir, output_dir]),
            (self.step3_plan_generation, [output_dir], kwargs)
        ]
        
        for i, step_info in enumerate(steps, 1):
            step_func = step_info[0]
            step_args = step_info[1]
            step_kwargs = step_info[2] if len(step_info) > 2 else {}
            
            try:
                if not step_func(*step_args, **step_kwargs):
                    logger.error(f"步骤{i}执行失败，流水线终止")
                    return False
            except Exception as e:
                logger.error(f"步骤{i}执行异常: {str(e)}")
                return False
                
        # 执行完成
        duration = datetime.now() - self.start_time
        logger.info(f"[SUCCESS] 流水线执行完成！总耗时: {duration}")
        
        # 显示输出文件
        output_path = Path(output_dir)
        if output_path.exists():
            output_files = list(output_path.glob('*'))
            if output_files:
                logger.info("生成的文件:")
                for file in output_files:
                    logger.info(f"  - {file}")
                    
        return True
        
    def load_config_file(self, config_file):
        """加载配置文件"""
        config_path = Path(config_file)
        if not config_path.exists():
            logger.error(f"配置文件不存在: {config_file}")
            return None
            
        try:
            if config_path.suffix.lower() in ['.yaml', '.yml']:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
            elif config_path.suffix.lower() == '.json':
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.error(f"不支持的配置文件格式: {config_path.suffix}")
                return None
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            return None

def main():
    # 过滤掉 Jupyter notebook 的内核参数
    import sys
    print(">>> pipeline starting...", flush=True)
    filtered_argv = [arg for arg in sys.argv[1:] if not arg.startswith('--f=') and not arg.startswith('-f=')]
    
    parser = argparse.ArgumentParser(
        description='农场灌溉调度系统自动化执行流水线',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python pipeline.py --input-dir ./gzp_farm --output-dir ./output
  python pipeline.py --config pipeline_config.yaml
  python pipeline.py --input-dir ./data --pumps 1,2 --zones A,B --no-waterlevels
  python pipeline.py --input-dir ./data --multi-pump --output-dir ./output
        """
    )
    
    parser.add_argument('--input-dir', default='./gzp_farm',
                       help='输入数据目录 (默认: ./gzp_farm)')
    parser.add_argument('--output-dir', default='./output',
                       help='输出目录 (默认: ./output)')
    parser.add_argument('--config', 
                       help='配置文件路径 (YAML或JSON格式)')
    parser.add_argument('--pumps',
                       help='启用的泵站列表，逗号分隔 (例如: 1,2,3)')
    parser.add_argument('--zones',
                       help='启用的供区列表，逗号分隔 (例如: A,B,C)')
    parser.add_argument('--multi-pump', action='store_true',
                       help='生成多水泵方案对比')
    parser.add_argument('--time-constraints', action='store_true',
                       help='启用泵时间约束模式')
    parser.add_argument('--no-waterlevels', action='store_true',
                       help='不融合实时水位数据')
    parser.add_argument('--no-summary', action='store_true',
                       help='不打印执行摘要')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='详细输出')
    
    args = parser.parse_args(filtered_argv)
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        
    # 创建流水线实例
    pipeline = IrrigationPipeline()
    
    # 准备参数
    kwargs = {
        'merge_waterlevels': not args.no_waterlevels,
        'print_summary': not args.no_summary,
        'multi_pump_scenarios': args.multi_pump,
        'time_constraints': args.time_constraints
    }
    
    if args.pumps:
        kwargs['pumps'] = args.pumps
    if args.zones:
        kwargs['zones'] = args.zones
        
    # 如果指定了配置文件，加载配置
    if args.config:
        config = pipeline.load_config_file(args.config)
        if config is None:
            return 1
            
        # 从配置文件中获取参数
        input_dir = config.get('input_dir', args.input_dir)
        output_dir = config.get('output_dir', args.output_dir)
        kwargs.update(config.get('options', {}))
    else:
        input_dir = args.input_dir
        output_dir = args.output_dir
        
    # 运行流水线
    success = pipeline.run_pipeline(input_dir, output_dir, **kwargs)
    
    if success:
        logger.info("[SUCCESS] 自动化流水线执行成功")
        return 0
    else:
        logger.error("[FAIL] 自动化流水线执行失败")
        return 1

if __name__ == '__main__':
    import sys
    exit_code = main()
    if exit_code != 0:
        sys.exit(exit_code)