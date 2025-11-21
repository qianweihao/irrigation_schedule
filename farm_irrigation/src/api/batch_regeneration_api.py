"""
批次重新生成API端点设计和实现

基于现有API架构，设计用于根据前端修改重新生成灌溉批次计划的新端点
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import HTTPException
import json
import hashlib
import time
import logging
from pathlib import Path

# ===== 数据模型定义 =====

class FieldModification(BaseModel):
    """田块修改信息"""
    field_id: str = Field(..., description="田块ID")
    action: str = Field(..., description="操作类型: 'add' 或 'remove'")
    custom_water_level: Optional[float] = Field(None, description="自定义水位(mm)")

class PumpAssignment(BaseModel):
    """批次水泵分配信息"""
    batch_index: int = Field(..., description="批次索引（从1开始）")
    pump_ids: List[str] = Field(..., description="分配给该批次的水泵ID列表")

class TimeModification(BaseModel):
    """批次时间修改信息"""
    batch_index: int = Field(..., description="批次索引（从1开始）")
    start_time_h: Optional[float] = Field(None, description="新的开始时间（小时）")
    duration_h: Optional[float] = Field(None, description="新的持续时间（小时）")
    
class BatchModificationRequest(BaseModel):
    """批次修改请求"""
    original_plan_id: str = Field(..., description="原始计划ID或文件路径")
    scenario_name: Optional[str] = Field(
        None, 
        description="""指定要修改的scenario名称。可选值：
        - 多泵方案: "P1单独使用" / "P2单独使用" / "全部水泵(P1+P2)组合使用" 等
        - 优化方案: "省电方案" / "省时方案" / "均衡方案" / "避峰方案" / "节水方案"
        - null 或不传: 修改所有scenario"""
    )
    field_modifications: Optional[List[FieldModification]] = Field(default_factory=list, description="田块修改列表")
    pump_assignments: Optional[List[PumpAssignment]] = Field(default_factory=list, description="批次水泵分配修改列表")
    time_modifications: Optional[List[TimeModification]] = Field(default_factory=list, description="批次时间修改列表")
    regeneration_params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="重新生成参数")
    
class BatchRegenerationResponse(BaseModel):
    """批次重新生成响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    modified_plan_path: Optional[str] = Field(None, description="修改后的计划文件路径")
    original_plan: Optional[Dict[str, Any]] = Field(None, description="原始计划数据")
    modified_plan: Optional[Dict[str, Any]] = Field(None, description="修改后的计划数据")
    modifications_summary: Dict[str, Any] = Field(default_factory=dict, description="修改摘要")
    
# ===== 核心业务逻辑 =====

class BatchRegenerationService:
    """批次重新生成服务"""
    
    def __init__(self):
        # 确保使用正确的output目录路径
        # 从当前文件位置（src/api/）向上两级到项目根目录，然后指向 data/output
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
        self.output_dir = project_root / "data" / "output"
        
        # 初始化logger
        self.logger = logging.getLogger(__name__)
        
    def _find_latest_plan_file(self) -> Optional[str]:
        """查找output目录中最新的计划文件"""
        try:
            import glob
            # 查找所有irrigation_plan开头的json文件
            pattern = str(self.output_dir / "irrigation_plan_*.json")
            plan_files = glob.glob(pattern)
            
            if plan_files:
                # 返回最新的文件路径
                latest_file = max(plan_files, key=lambda x: Path(x).stat().st_mtime)
                return latest_file
            
            return None
        except Exception:
            return None
        
    def load_original_plan(self, plan_id: str) -> Dict[str, Any]:
        """加载原始计划数据"""
        # 尝试多种方式加载计划
        plan_data = None
        
        # 1. 如果是文件路径
        if plan_id.endswith('.json'):
            plan_path = Path(plan_id)
            if plan_path.exists():
                with open(plan_path, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
            else:
                # 尝试在output目录中查找
                plan_path = self.output_dir / Path(plan_id).name
                if plan_path.exists():
                    with open(plan_path, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                else:
                    # 如果指定的文件不存在，尝试使用最新的文件
                    latest_file = self._find_latest_plan_file()
                    if latest_file:
                        with open(latest_file, 'r', encoding='utf-8') as f:
                            plan_data = json.load(f)
                        self.logger.warning(f"指定的文件 {plan_id} 不存在，使用最新文件: {latest_file}")
        
        # 2. 如果是计划ID，在output目录中查找匹配的文件
        else:
            import glob
            pattern = str(self.output_dir / f"*{plan_id}*.json")
            matching_files = glob.glob(pattern)
            if matching_files:
                # 选择最新的文件
                latest_file = max(matching_files, key=lambda x: Path(x).stat().st_mtime)
                with open(latest_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
        
        if not plan_data:
            raise HTTPException(status_code=404, detail=f"未找到计划: {plan_id}")
            
        return plan_data
    
    def apply_field_modifications(self, plan_data: Dict[str, Any], 
                                modifications: List[FieldModification],
                                target_scenario_name: Optional[str] = None) -> Dict[str, Any]:
        """
        应用田块修改（完整实现）
        
        Args:
            plan_data: 计划数据
            modifications: 田块修改列表
            target_scenario_name: 目标scenario名称，None表示修改所有scenario
            
        Returns:
            修改后的计划数据
        """
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 统计修改信息
        modified_scenarios = []
        unchanged_scenarios = []
        added_fields = []
        removed_fields = []
        
        scenarios = modified_plan.get('scenarios', [])
        
        # 如果指定了target_scenario_name，验证其是否存在
        if target_scenario_name:
            scenario_exists = any(s.get('scenario_name') == target_scenario_name for s in scenarios)
            if not scenario_exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"未找到指定的scenario: {target_scenario_name}"
                )
        
        # 获取所有可用田块（从config.json或现有计划中）
        available_fields = self._get_available_fields_from_config()
        
        for scenario in scenarios:
            scenario_name = scenario.get('scenario_name', '')
            
            # 如果指定了target_scenario_name，只修改匹配的scenario
            if target_scenario_name and scenario_name != target_scenario_name:
                if scenario_name not in unchanged_scenarios:
                    unchanged_scenarios.append(scenario_name)
                continue
            
            if scenario_name not in modified_scenarios:
                modified_scenarios.append(scenario_name)
            
            scenario_plan = scenario.get('plan', {})
            batches = scenario_plan.get('batches', [])
            
            # 应用田块修改
            for mod in modifications:
                if mod.action == "add":
                    # 查找田块信息
                    field_info = self._find_field_info(available_fields, mod.field_id)
                    if field_info:
                        # 如果指定了自定义水位，更新水位信息
                        if mod.custom_water_level is not None:
                            field_info['wl_mm'] = mod.custom_water_level
                        
                        # 检查是否已在计划中
                        if not self._is_field_in_batches(batches, mod.field_id):
                            # 添加到合适的批次（根据segment_id）
                            self._add_field_to_batches(batches, field_info)
                            if mod.field_id not in added_fields:
                                added_fields.append(mod.field_id)
                
                elif mod.action == "remove":
                    # 从批次中移除田块
                    if self._remove_field_from_batches(batches, mod.field_id):
                        if mod.field_id not in removed_fields:
                            removed_fields.append(mod.field_id)
            
            # 重新生成steps和commands
            self._regenerate_scenario_execution(scenario)
            
            # 重新计算统计数据
            self._recalculate_scenario_statistics(scenario)
        
        # 将修改统计信息附加到计划中
        if 'modification_tracking' not in modified_plan:
            modified_plan['modification_tracking'] = {}
        
        modified_plan['modification_tracking']['field_modifications'] = {
            'modified_scenarios': modified_scenarios,
            'unchanged_scenarios': unchanged_scenarios,
            'added_fields': added_fields,
            'removed_fields': removed_fields
        }
        
        return modified_plan
    
    def _get_available_fields(self) -> List[Dict[str, Any]]:
        """获取所有可用田块信息"""
        # 从配置文件或数据库中获取所有田块信息
        # 这里需要根据实际的数据源进行实现
        try:
            # 尝试从最新的计划文件中获取田块信息
            import glob
            plan_files = glob.glob(str(self.output_dir / "irrigation_plan_*.json"))
            if plan_files:
                latest_file = max(plan_files, key=lambda x: Path(x).stat().st_mtime)
                with open(latest_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
                    
                # 从批次中提取所有田块信息
                all_fields = []
                for batch in plan_data.get('batches', []):
                    all_fields.extend(batch.get('fields', []))
                return all_fields
        except Exception:
            pass
            
        # 如果无法从计划文件获取，返回空列表
        return []
    
    def _find_field_info(self, available_fields: List[Dict[str, Any]], field_id: str) -> Optional[Dict[str, Any]]:
        """查找田块信息"""
        for field in available_fields:
            if field.get('id') == field_id:
                return field.copy()
        return None
    
    def _is_field_in_plan(self, plan_data: Dict[str, Any], field_id: str) -> bool:
        """检查田块是否已在计划中"""
        for batch in plan_data.get('batches', []):
            for field in batch.get('fields', []):
                if field.get('id') == field_id:
                    return True
        return False
    
    def _add_field_to_plan(self, plan_data: Dict[str, Any], field_info: Dict[str, Any]):
        """将田块添加到计划中"""
        # 简单策略：添加到第一个批次，实际应用中可能需要更复杂的逻辑
        batches = plan_data.get('batches', [])
        if batches:
            batches[0]['fields'].append(field_info)
        else:
            # 如果没有批次，创建新批次
            new_batch = {
                'index': 1,
                'fields': [field_info]
            }
            plan_data['batches'] = [new_batch]
    
    def _remove_field_from_plan(self, plan_data: Dict[str, Any], field_id: str) -> bool:
        """从计划中移除田块"""
        removed = False
        for batch in plan_data.get('batches', []):
            fields = batch.get('fields', [])
            original_count = len(fields)
            batch['fields'] = [f for f in fields if f.get('id') != field_id]
            if len(batch['fields']) < original_count:
                removed = True
        return removed
    
    def _regenerate_batches(self, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """重新生成批次"""
        # 收集所有需要灌溉的田块
        all_fields = []
        for batch in plan_data.get('batches', []):
            all_fields.extend(batch.get('fields', []))
        
        if not all_fields:
            plan_data['batches'] = []
            return plan_data
        
        # 按段ID和距离排序田块（模拟原有的批次生成逻辑）
        sorted_fields = sorted(all_fields, key=lambda f: (
            f.get('segment_id', ''),
            f.get('distance_rank', 0)
        ))
        
        # 重新分配批次（简化版本，实际可能需要更复杂的算法）
        batch_size = 10  # 每批次最多10个田块
        new_batches = []
        
        for i in range(0, len(sorted_fields), batch_size):
            batch_fields = sorted_fields[i:i + batch_size]
            new_batch = {
                'index': len(new_batches) + 1,
                'fields': batch_fields
            }
            new_batches.append(new_batch)
        
        plan_data['batches'] = new_batches
        
        # 更新统计信息
        self._update_plan_statistics(plan_data)
        
        return plan_data
    
    def _update_plan_statistics(self, plan_data: Dict[str, Any]):
        """更新计划统计信息"""
        total_area = 0
        total_deficit = 0
        
        for batch in plan_data.get('batches', []):
            for field in batch.get('fields', []):
                total_area += field.get('area_mu', 0)
                # 计算缺水量（简化计算）
                wl_mm = field.get('wl_mm', 0)
                wl_low = field.get('wl_low', 80)  # 默认低水位阈值
                if wl_mm < wl_low:
                    deficit_mm = wl_low - wl_mm
                    total_deficit += deficit_mm * field.get('area_mu', 0) * 0.667  # 转换为m³
        
        # 更新计划的统计信息
        if 'calc' not in plan_data:
            plan_data['calc'] = {}
        
        plan_data['calc'].update({
            'total_area_mu': total_area,
            'total_deficit_m3': total_deficit,
            'batch_count': len(plan_data.get('batches', [])),
            'field_count': sum(len(b.get('fields', [])) for b in plan_data.get('batches', []))
        })
    
    def _get_available_fields_from_config(self) -> List[Dict[str, Any]]:
        """从config.json或最新计划中获取所有可用田块"""
        try:
            # 先尝试从config.json获取（config.json在项目根目录）
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
            config_path = project_root / 'config.json'
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if 'fields' in config:
                return config['fields']
        except Exception:
            pass
        
        # 如果config.json没有，从最新计划文件获取
        try:
            import glob
            plan_files = glob.glob(str(self.output_dir / "irrigation_plan_*.json"))
            if plan_files:
                latest_file = max(plan_files, key=lambda x: Path(x).stat().st_mtime)
                with open(latest_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
                
                # 从第一个scenario的批次中提取所有田块信息
                scenarios = plan_data.get('scenarios', [])
                if scenarios:
                    scenario_plan = scenarios[0].get('plan', {})
                    all_fields = []
                    for batch in scenario_plan.get('batches', []):
                        all_fields.extend(batch.get('fields', []))
                    return all_fields
        except Exception:
            pass
        
        return []
    
    def _is_field_in_batches(self, batches: List[Dict[str, Any]], field_id: str) -> bool:
        """检查田块是否已在批次列表中"""
        for batch in batches:
            for field in batch.get('fields', []):
                if field.get('id') == field_id:
                    return True
        return False
    
    def _add_field_to_batches(self, batches: List[Dict[str, Any]], field_info: Dict[str, Any]):
        """
        将田块添加到合适的批次
        策略：找到相同segment_id的批次，或添加到最后一个批次
        """
        field_segment = field_info.get('segment_id', '')
        
        # 查找相同segment的批次
        target_batch = None
        for batch in batches:
            batch_segments = set(f.get('segment_id', '') for f in batch.get('fields', []))
            if field_segment in batch_segments:
                target_batch = batch
                break
        
        # 如果没有找到相同segment的批次，添加到最后一个批次
        if not target_batch and batches:
            target_batch = batches[-1]
        
        # 如果有批次，添加田块
        if target_batch:
            target_batch['fields'].append(field_info)
            # 重新排序田块
            target_batch['fields'].sort(key=lambda f: (
                f.get('segment_id', ''),
                f.get('distance_rank', 0)
            ))
        else:
            # 如果没有批次，创建新批次
            batches.append({
                'index': 1,
                'fields': [field_info],
                'area_mu': field_info.get('area_mu', 0)
            })
    
    def _remove_field_from_batches(self, batches: List[Dict[str, Any]], field_id: str) -> bool:
        """从批次列表中移除田块"""
        removed = False
        for batch in batches:
            fields = batch.get('fields', [])
            original_count = len(fields)
            batch['fields'] = [f for f in fields if f.get('id') != field_id]
            if len(batch['fields']) < original_count:
                removed = True
        return removed
    
    def _regenerate_scenario_execution(self, scenario: Dict[str, Any]):
        """
        重新生成scenario的执行计划（steps和commands）
        基于当前的批次和田块列表
        """
        scenario_plan = scenario.get('plan', {})
        batches = scenario_plan.get('batches', [])
        
        if not batches:
            scenario_plan['steps'] = []
            return
        
        # 重新生成steps
        new_steps = []
        cumulative_time = 0.0
        
        for batch_idx, batch in enumerate(batches, 1):
            fields = batch.get('fields', [])
            if not fields:
                continue
            
            # 计算批次时长
            batch_area = sum(f.get('area_mu', 0) for f in fields)
            calc_info = scenario_plan.get('calc', {})
            q_avail = calc_info.get('q_avail_m3ph', 480.0)
            d_target = calc_info.get('d_target_mm', 90.0)
            
            # 计算缺水量
            total_deficit = 0.0
            for field in fields:
                wl_mm = field.get('wl_mm', 0)
                wl_opt = 90.0  # 默认最优水位
                if wl_mm < wl_opt:
                    deficit_mm = d_target
                    total_deficit += deficit_mm * field.get('area_mu', 0) * 0.667  # 转换为m³
            
            # 计算时长
            if total_deficit > 0:
                duration_h = total_deficit / q_avail
            else:
                duration_h = batch_area * d_target * 0.667 / q_avail
            
            # 更新batch统计信息
            batch['area_mu'] = batch_area
            if 'stats' not in batch:
                batch['stats'] = {}
            batch['stats']['deficit_vol_m3'] = total_deficit
            batch['stats']['eta_hours'] = duration_h
            batch['stats']['cap_vol_m3'] = q_avail * duration_h
            
            # 创建step
            start_time = cumulative_time
            end_time = cumulative_time + duration_h
            
            # 获取水泵信息
            pumps_on = scenario_plan.get('calc', {}).get('active_pumps', ['P1', 'P2'])
            
            # 生成commands（简化版本）
            commands = []
            
            # 添加启动水泵指令
            for pump_id in pumps_on:
                commands.append({
                    'action': 'start',
                    'target': pump_id,
                    'value': None,
                    't_start_h': start_time,
                    't_end_h': end_time
                })
            
            # 添加阀门控制指令（从现有田块信息推断）
            segments_in_batch = set(f.get('segment_id', '') for f in fields)
            for field in fields:
                inlet_g_id = field.get('inlet_G_id', '')
                if inlet_g_id:
                    commands.append({
                        'action': 'set',
                        'target': inlet_g_id,
                        'value': 100.0,
                        't_start_h': start_time,
                        't_end_h': end_time
                    })
            
            # 添加停止水泵指令
            for pump_id in pumps_on:
                commands.append({
                    'action': 'stop',
                    'target': pump_id,
                    'value': None,
                    't_start_h': start_time,
                    't_end_h': end_time
                })
            
            # 生成sequence
            field_ids = [f.get('id') for f in fields]
            gates_open = list(set(f.get('inlet_G_id') for f in fields if f.get('inlet_G_id')))
            
            sequence = {
                'pumps_on': pumps_on.copy(),
                'gates_open': gates_open,
                'gates_close': [],
                'fields': field_ids,
                'pumps_off': pumps_on.copy()
            }
            
            # 生成full_order
            full_order = []
            for pump_id in pumps_on:
                full_order.append({'type': 'pump_on', 'id': pump_id})
            for gate_id in gates_open:
                full_order.append({'type': 'regulator_set', 'id': gate_id, 'open_pct': 100})
            for field in fields:
                full_order.append({
                    'type': 'field',
                    'id': field.get('id'),
                    'inlet_G_id': field.get('inlet_G_id')
                })
            for pump_id in pumps_on:
                full_order.append({'type': 'pump_off', 'id': pump_id})
            
            step = {
                't_start_h': start_time,
                't_end_h': end_time,
                'label': f'批次 {batch_idx}',
                'commands': commands,
                'sequence': sequence,
                'full_order': full_order
            }
            
            new_steps.append(step)
            cumulative_time = end_time
        
        scenario_plan['steps'] = new_steps
    
    def _recalculate_scenario_statistics(self, scenario: Dict[str, Any]):
        """重新计算scenario的统计数据"""
        scenario_plan = scenario.get('plan', {})
        batches = scenario_plan.get('batches', [])
        steps = scenario_plan.get('steps', [])
        
        # 计算总时长
        total_duration = 0.0
        for step in steps:
            step_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
            total_duration += step_duration
        
        # 计算总缺水量
        total_deficit = 0.0
        for batch in batches:
            total_deficit += batch.get('stats', {}).get('deficit_vol_m3', 0.0)
        
        # 更新scenario级别的统计数据
        scenario['total_eta_h'] = total_duration
        if scenario_plan:
            scenario_plan['total_eta_h'] = total_duration
            scenario_plan['total_deficit_m3'] = total_deficit
        
        # 计算水泵运行时间
        pump_runtime_dict = {}
        for step in steps:
            step_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
            sequence = step.get('sequence', {})
            step_pumps = sequence.get('pumps_on', [])
            
            for pump in step_pumps:
                if pump not in pump_runtime_dict:
                    pump_runtime_dict[pump] = 0.0
                pump_runtime_dict[pump] += step_duration
        
        scenario['total_pump_runtime_hours'] = pump_runtime_dict.copy()
        if scenario_plan:
            scenario_plan['total_pump_runtime_hours'] = pump_runtime_dict.copy()
        
        # 计算总电费
        calc_info = scenario_plan.get('calc', {})
        pump_info = calc_info.get('pump', {})
        combined_power_kw = pump_info.get('power_kw', 120.0)
        electricity_price = pump_info.get('electricity_price', 0.6)
        
        active_pumps = calc_info.get('active_pumps', ['P1', 'P2'])
        num_pumps = len(active_pumps)
        single_pump_power_kw = combined_power_kw / num_pumps if num_pumps > 0 else 60.0
        
        total_electricity_cost = 0.0
        for pump, runtime_h in pump_runtime_dict.items():
            total_electricity_cost += runtime_h * single_pump_power_kw * electricity_price
        
        scenario['total_electricity_cost'] = total_electricity_cost
        if scenario_plan:
            scenario_plan['total_electricity_cost'] = total_electricity_cost
    
    def _get_valid_pump_ids(self) -> List[str]:
        """从配置文件获取有效的水泵ID列表"""
        try:
            # config.json在项目根目录
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # src/api -> src -> 项目根目录
            config_path = project_root / 'config.json'
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            valid_pump_ids = []
            if 'pumps' in config:
                for pump in config['pumps']:
                    pump_name = pump.get('name')
                    if pump_name:
                        valid_pump_ids.append(pump_name)
            
            return valid_pump_ids
        except Exception as e:
            # 如果无法读取配置，返回默认值
            return ['P1', 'P2']
    
    def apply_pump_modifications(self, plan_data: Dict[str, Any], 
                               pump_assignments: List[PumpAssignment],
                               target_scenario_name: Optional[str] = None) -> Dict[str, Any]:
        """
        应用批次水泵分配修改
        
        Args:
            plan_data: 计划数据
            pump_assignments: 水泵分配列表
            target_scenario_name: 目标scenario名称，None表示修改所有scenario
            
        Returns:
            修改后的计划数据
        """
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 获取有效的水泵ID列表
        valid_pump_ids = self._get_valid_pump_ids()
        
        # 验证水泵ID的有效性
        for assignment in pump_assignments:
            invalid_pumps = [pid for pid in assignment.pump_ids if pid not in valid_pump_ids]
            if invalid_pumps:
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的水泵ID: {', '.join(invalid_pumps)}。有效的水泵ID为: {', '.join(valid_pump_ids)}"
                )
        
        # 统计修改信息
        modified_scenarios = []
        unchanged_scenarios = []
        
        scenarios = modified_plan.get('scenarios', [])
        
        # 如果指定了target_scenario_name，验证其是否存在
        if target_scenario_name:
            scenario_exists = any(s.get('scenario_name') == target_scenario_name for s in scenarios)
            if not scenario_exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"未找到指定的scenario: {target_scenario_name}"
                )
        
        for assignment in pump_assignments:
            batch_index = assignment.batch_index
            pump_ids = assignment.pump_ids
            
            # 验证批次是否存在（从scenarios中查找）
            batch_found = False
            for scenario in scenarios:
                scenario_plan = scenario.get('plan', {})
                batches = scenario_plan.get('batches', [])
                for batch in batches:
                    if batch.get('index') == batch_index:
                        batch_found = True
                        break
                if batch_found:
                    break
            
            if not batch_found:
                raise HTTPException(
                    status_code=400, 
                    detail=f"未找到批次 {batch_index}"
                )
            
            # 更新符合条件的scenarios中的水泵配置
            for scenario in scenarios:
                scenario_name = scenario.get('scenario_name', '')
                
                # 如果指定了target_scenario_name，只修改匹配的scenario
                if target_scenario_name and scenario_name != target_scenario_name:
                    if scenario_name not in unchanged_scenarios:
                        unchanged_scenarios.append(scenario_name)
                    continue
                
                # ⚠️ 不要修改 scenario['pumps_used']，因为这是scenario级别的配置
                # 我们只修改特定批次的水泵分配
                if scenario_name not in modified_scenarios:
                    modified_scenarios.append(scenario_name)
                
                # 🔴 修复1: 更新指定批次的 commands 中的水泵指令
                scenario_plan = scenario.get('plan', {})
                steps = scenario_plan.get('steps', [])
                
                # 找到对应批次的step
                for step in steps:
                    # 从label中提取批次索引
                    label = step.get('label', '')
                    if '批次' in label:
                        try:
                            step_batch_index = int(label.split('批次')[1].strip().split()[0])
                            if step_batch_index == batch_index:
                                # 更新这个step的commands
                                commands = step.get('commands', [])
                                
                                # 移除所有旧的水泵start/stop命令
                                commands_to_keep = [cmd for cmd in commands 
                                                   if cmd.get('action') not in ['start', 'stop'] 
                                                   or cmd.get('target') not in valid_pump_ids]
                                
                                # 获取时间信息
                                t_start = step.get('t_start_h', 0.0)
                                t_end = step.get('t_end_h', 0.0)
                                
                                # 重建命令列表：start命令在前，stop命令在后
                                new_commands = []
                                
                                # 添加新的start命令（在最前面）
                                for pump_id in pump_ids:
                                    new_commands.append({
                                        "action": "start",
                                        "target": pump_id,
                                        "value": None,
                                        "t_start_h": t_start,
                                        "t_end_h": t_end
                                    })
                                
                                # 添加中间的非水泵命令
                                new_commands.extend(commands_to_keep)
                                
                                # 添加新的stop命令（在最后面）
                                for pump_id in pump_ids:
                                    new_commands.append({
                                        "action": "stop",
                                        "target": pump_id,
                                        "value": None,
                                        "t_start_h": t_start,
                                        "t_end_h": t_end
                                    })
                                
                                step['commands'] = new_commands
                                
                                # 同时更新 sequence 中的 pumps_on 和 pumps_off
                                if 'sequence' in step:
                                    step['sequence']['pumps_on'] = pump_ids.copy()
                                    step['sequence']['pumps_off'] = pump_ids.copy()
                                
                                # 同时更新 full_order 中的水泵指令
                                if 'full_order' in step:
                                    full_order = step['full_order']
                                    # 移除旧的水泵指令
                                    full_order_filtered = [item for item in full_order 
                                                          if item.get('type') not in ['pump_on', 'pump_off']]
                                    
                                    # 重建 full_order：pump_on在前，pump_off在后
                                    new_full_order = []
                                    
                                    # 添加 pump_on
                                    for pump_id in pump_ids:
                                        new_full_order.append({
                                            "type": "pump_on",
                                            "id": pump_id
                                        })
                                    
                                    # 添加中间的指令
                                    new_full_order.extend(full_order_filtered)
                                    
                                    # 添加 pump_off
                                    for pump_id in pump_ids:
                                        new_full_order.append({
                                            "type": "pump_off",
                                            "id": pump_id
                                        })
                                    
                                    step['full_order'] = new_full_order
                                
                        except (IndexError, ValueError):
                            pass
                
                # 🟡 修复2: 重新计算整个scenario的统计数据
                # 收集每个水泵在所有批次中的运行时间
                pump_runtime_dict = {}
                total_duration = 0.0
                
                self.logger.info(f"开始重新计算scenario统计数据，共有 {len(steps)} 个批次")
                
                for step_idx, step in enumerate(steps):
                    step_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
                    total_duration += step_duration
                    
                    # 从该step的sequence获取使用的水泵
                    sequence = step.get('sequence', {})
                    step_pumps = sequence.get('pumps_on', [])
                    
                    step_label = step.get('label', f'批次 {step_idx+1}')
                    self.logger.info(f"  {step_label}: 时长={step_duration:.2f}h, 水泵={step_pumps}")
                    
                    # 累计每个水泵的运行时间
                    for pump in step_pumps:
                        if pump not in pump_runtime_dict:
                            pump_runtime_dict[pump] = 0.0
                        pump_runtime_dict[pump] += step_duration
                
                self.logger.info(f"计算完成 - total_duration={total_duration:.2f}h, pump_runtime={pump_runtime_dict}")
                
                # 更新scenario的total_eta_h
                scenario['total_eta_h'] = total_duration
                if scenario_plan:
                    scenario_plan['total_eta_h'] = total_duration
                
                # 更新total_pump_runtime_hours
                scenario['total_pump_runtime_hours'] = pump_runtime_dict.copy()
                if scenario_plan:
                    scenario_plan['total_pump_runtime_hours'] = pump_runtime_dict.copy()
                
                # 重新计算总电费
                calc_info = scenario_plan.get('calc', {}) if scenario_plan else {}
                pump_info = calc_info.get('pump', {})
                combined_power_kw = pump_info.get('power_kw', 120.0)  # 组合水泵的总功率
                electricity_price = pump_info.get('electricity_price', 0.6)
                
                # 获取单个水泵的功率（假设每个水泵功率相同）
                # 从active_pumps数量推断
                active_pumps = calc_info.get('active_pumps', ['P1', 'P2'])
                num_pumps = len(active_pumps)
                single_pump_power_kw = combined_power_kw / num_pumps if num_pumps > 0 else 60.0
                
                # 计算总电费（考虑每个水泵的实际运行时间）
                total_electricity_cost = 0.0
                for pump, runtime_h in pump_runtime_dict.items():
                    # 每个水泵使用单泵功率计算
                    total_electricity_cost += runtime_h * single_pump_power_kw * electricity_price
                
                scenario['total_electricity_cost'] = total_electricity_cost
                if scenario_plan:
                    scenario_plan['total_electricity_cost'] = total_electricity_cost
                
                # 更新scenario的pumps_used（使用所有批次中用到的水泵的并集）
                all_pumps_used = set()
                for step in steps:
                    sequence = step.get('sequence', {})
                    step_pumps = sequence.get('pumps_on', [])
                    all_pumps_used.update(step_pumps)
                
                scenario['pumps_used'] = sorted(list(all_pumps_used))
        
        # 将修改统计信息附加到计划中
        if 'modification_tracking' not in modified_plan:
            modified_plan['modification_tracking'] = {}
        
        modified_plan['modification_tracking']['pump_modifications'] = {
            'modified_scenarios': modified_scenarios,
            'unchanged_scenarios': unchanged_scenarios
        }
        
        return modified_plan
    
    def apply_time_modifications(self, plan_data: Dict[str, Any], 
                               time_modifications: List[TimeModification],
                               target_scenario_name: Optional[str] = None) -> Dict[str, Any]:
        """
        应用批次时间修改（完整实现）
        
        Args:
            plan_data: 计划数据
            time_modifications: 时间修改列表
            target_scenario_name: 目标scenario名称，None表示修改所有scenario
            
        Returns:
            修改后的计划数据
        """
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 统计修改信息
        modified_scenarios = []
        unchanged_scenarios = []
        
        scenarios = modified_plan.get('scenarios', [])
        
        # 如果指定了target_scenario_name，验证其是否存在
        if target_scenario_name:
            scenario_exists = any(s.get('scenario_name') == target_scenario_name for s in scenarios)
            if not scenario_exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"未找到指定的scenario: {target_scenario_name}"
                )
        
        # 按批次索引排序，确保按顺序处理
        sorted_time_mods = sorted(time_modifications, key=lambda x: x.batch_index)
        
        for scenario in scenarios:
            scenario_name = scenario.get('scenario_name', '')
            
            # 如果指定了target_scenario_name，只修改匹配的scenario
            if target_scenario_name and scenario_name != target_scenario_name:
                if scenario_name not in unchanged_scenarios:
                    unchanged_scenarios.append(scenario_name)
                continue
            
            if scenario_name not in modified_scenarios:
                modified_scenarios.append(scenario_name)
            
            scenario_plan = scenario.get('plan', {})
            batches = scenario_plan.get('batches', [])
            steps = scenario_plan.get('steps', [])
            
            # 创建批次索引到steps索引的映射
            batch_to_step_map = {}
            for i, step in enumerate(steps):
                # 从label中提取批次索引，格式如 "批次 1"
                label = step.get('label', '')
                if '批次' in label:
                    try:
                        batch_idx = int(label.split('批次')[1].strip().split()[0])
                        batch_to_step_map[batch_idx] = i
                    except (IndexError, ValueError):
                        pass
            
            # 应用时间修改
            time_offset = 0.0  # 累计时间偏移
            modified_batches = []  # 记录被修改的批次索引
            
            for time_mod in sorted_time_mods:
                batch_index = time_mod.batch_index
                
                # 验证批次是否存在
                batch_exists = any(b.get('index') == batch_index for b in batches)
                if not batch_exists:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"未找到批次 {batch_index}"
                    )
                
                # 找到对应的step索引
                step_idx = batch_to_step_map.get(batch_index)
                if step_idx is None:
                    # 如果没有找到映射，尝试直接使用 batch_index - 1
                    step_idx = batch_index - 1
                    if step_idx < 0 or step_idx >= len(steps):
                        continue
                
                step = steps[step_idx]
                
                # 获取原始时间
                original_start = step.get('t_start_h', 0.0)
                original_end = step.get('t_end_h', 0.0)
                original_duration = original_end - original_start
                
                # 计算新的时间
                new_start = time_mod.start_time_h if time_mod.start_time_h is not None else (original_start + time_offset)
                new_duration = time_mod.duration_h if time_mod.duration_h is not None else original_duration
                new_end = new_start + new_duration
                
                # 更新step的时间
                step['t_start_h'] = new_start
                step['t_end_h'] = new_end
                
                # 更新step中所有commands的时间
                if 'commands' in step:
                    for cmd in step['commands']:
                        cmd['t_start_h'] = new_start
                        cmd['t_end_h'] = new_end
                
                # 更新label以反映新的时间
                step['label'] = f"批次 {batch_index}"
                
                # 计算时间偏移，用于后续批次
                actual_duration_change = new_duration - original_duration
                actual_start_change = new_start - original_start
                time_offset = max(actual_duration_change, actual_start_change)
                
                # 更新对应batch的统计信息（时间、水量等）
                for batch in batches:
                    if batch.get('index') == batch_index:
                        if 'stats' in batch:
                            # 更新时长
                            batch['stats']['eta_hours'] = new_duration
                            
                            # 获取流量信息（从scenario_plan.calc中获取）
                            calc_info = scenario_plan.get('calc', {})
                            flow_rate = calc_info.get('q_avail_m3ph', 240.0)  # 默认240 m³/h
                            
                            # 重新计算该批次能供应的最大水量
                            max_water_volume = flow_rate * new_duration
                            
                            # 更新cap_vol_m3和deficit_vol_m3
                            # 强制时长模式：能供多少算多少
                            batch['stats']['cap_vol_m3'] = max_water_volume
                            batch['stats']['deficit_vol_m3'] = max_water_volume
                            
                            self.logger.info(
                                f"[时间修改] 批次 {batch_index} 时长调整: "
                                f"{original_duration:.2f}h -> {new_duration:.2f}h, "
                                f"供水量: {max_water_volume:.2f} m³"
                            )
                
                modified_batches.append(batch_index)
            
            # 级联更新后续批次的时间
            if modified_batches and time_offset != 0:
                last_modified_batch = max(modified_batches)
                
                # 找到最后一个修改批次的结束时间
                last_modified_step_idx = batch_to_step_map.get(last_modified_batch, last_modified_batch - 1)
                if 0 <= last_modified_step_idx < len(steps):
                    cumulative_time = steps[last_modified_step_idx].get('t_end_h', 0.0)
                    
                    # 更新后续所有批次
                    for batch_idx in range(last_modified_batch + 1, len(batches) + 1):
                        step_idx = batch_to_step_map.get(batch_idx, batch_idx - 1)
                        if 0 <= step_idx < len(steps):
                            step = steps[step_idx]
                            
                            # 计算原始持续时间
                            original_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
                            
                            # 设置新的开始时间为前一批次的结束时间
                            new_start = cumulative_time
                            new_end = new_start + original_duration
                            
                            # 更新step时间
                            step['t_start_h'] = new_start
                            step['t_end_h'] = new_end
                            
                            # 更新commands时间
                            if 'commands' in step:
                                for cmd in step['commands']:
                                    cmd['t_start_h'] = new_start
                                    cmd['t_end_h'] = new_end
                            
                            # 同时更新对应batch的stats中的cap_vol_m3和deficit_vol_m3
                            for batch in batches:
                                if batch.get('index') == batch_idx:
                                    if 'stats' in batch:
                                        # 获取流量信息
                                        calc_info = scenario_plan.get('calc', {})
                                        flow_rate = calc_info.get('q_avail_m3ph', 240.0)
                                        
                                        # 根据持续时间重新计算水量
                                        max_water_volume = flow_rate * original_duration
                                        
                                        # 更新cap_vol_m3和deficit_vol_m3
                                        batch['stats']['cap_vol_m3'] = max_water_volume
                                        batch['stats']['deficit_vol_m3'] = max_water_volume
                                    break
                            
                            cumulative_time = new_end
            
            # 重新计算scenario的总时长和水泵运行时间
            if steps:
                # 重新计算每个水泵的运行时间
                pump_runtime_dict = {}
                total_duration = 0.0
                total_deficit = 0.0  # 重新计算总缺水量
                
                self.logger.info(f"[时间修改] 重新计算scenario统计数据，共有 {len(steps)} 个批次")
                
                for step_idx, step in enumerate(steps):
                    step_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
                    total_duration += step_duration
                    
                    # 从该step的sequence获取使用的水泵
                    sequence = step.get('sequence', {})
                    step_pumps = sequence.get('pumps_on', [])
                    
                    step_label = step.get('label', f'批次 {step_idx+1}')
                    self.logger.info(f"[时间修改]   {step_label}: 时长={step_duration:.2f}h, 水泵={step_pumps}")
                    
                    # 累计每个水泵的运行时间
                    for pump in step_pumps:
                        if pump not in pump_runtime_dict:
                            pump_runtime_dict[pump] = 0.0
                        pump_runtime_dict[pump] += step_duration
                    
                    # 累计总缺水量（从对应的batch中获取）
                    if step_idx < len(batches):
                        batch_deficit = batches[step_idx].get('stats', {}).get('deficit_vol_m3', 0.0)
                        total_deficit += batch_deficit
                
                self.logger.info(f"[时间修改] 计算完成 - total_duration={total_duration:.2f}h, total_deficit={total_deficit:.2f}m³, pump_runtime={pump_runtime_dict}")
                
                # 更新scenario的total_eta_h
                scenario['total_eta_h'] = total_duration
                if scenario_plan:
                    scenario_plan['total_eta_h'] = total_duration
                    scenario_plan['total_deficit_m3'] = total_deficit
                
                # 更新total_pump_runtime_hours
                scenario['total_pump_runtime_hours'] = pump_runtime_dict.copy()
                if scenario_plan:
                    scenario_plan['total_pump_runtime_hours'] = pump_runtime_dict.copy()
                
                # 重新计算总电费
                calc_info = scenario_plan.get('calc', {}) if scenario_plan else {}
                pump_info = calc_info.get('pump', {})
                combined_power_kw = pump_info.get('power_kw', 120.0)  # 组合水泵的总功率
                electricity_price = pump_info.get('electricity_price', 0.6)
                
                # 获取单个水泵的功率
                active_pumps = calc_info.get('active_pumps', ['P1', 'P2'])
                num_pumps = len(active_pumps)
                single_pump_power_kw = combined_power_kw / num_pumps if num_pumps > 0 else 60.0
                
                # 计算总电费（考虑每个水泵的实际运行时间）
                total_electricity_cost = 0.0
                for pump, runtime_h in pump_runtime_dict.items():
                    # 每个水泵使用单泵功率计算
                    total_electricity_cost += runtime_h * single_pump_power_kw * electricity_price
                
                scenario['total_electricity_cost'] = total_electricity_cost
                if scenario_plan:
                    scenario_plan['total_electricity_cost'] = total_electricity_cost
                
                # 更新scenario的pumps_used（使用所有批次中用到的水泵的并集）
                all_pumps_used = set()
                for step in steps:
                    sequence = step.get('sequence', {})
                    step_pumps = sequence.get('pumps_on', [])
                    all_pumps_used.update(step_pumps)
                
                scenario['pumps_used'] = sorted(list(all_pumps_used))
        
        # 将修改统计信息附加到计划中
        if 'modification_tracking' not in modified_plan:
            modified_plan['modification_tracking'] = {}
        
        modified_plan['modification_tracking']['time_modifications'] = {
            'modified_scenarios': modified_scenarios,
            'unchanged_scenarios': unchanged_scenarios
        }
        
        return modified_plan
    
    def _save_modified_plan(self, modified_plan: Dict[str, Any], original_plan_id: str = None) -> str:
        """保存修改后的计划并返回文件路径"""
        timestamp = int(time.time())
        output_file = self.output_dir / f"irrigation_plan_modified_{timestamp}.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(modified_plan, f, ensure_ascii=False, indent=2)
        
        return str(output_file)
    
    def get_available_scenarios(self, plan_id: str) -> Dict[str, Any]:
        """
        获取计划中所有可用的scenarios
        
        Args:
            plan_id: 计划ID或文件路径
            
        Returns:
            包含所有scenario信息的字典
        """
        plan_data = self.load_original_plan(plan_id)
        scenarios = plan_data.get('scenarios', [])
        
        available_scenarios = []
        for scenario in scenarios:
            scenario_plan = scenario.get('plan', {})
            batches = scenario_plan.get('batches', [])
            
            scenario_info = {
                'scenario_name': scenario.get('scenario_name', 'Unknown'),
                'pumps_used': scenario.get('pumps_used', []),
                'total_batches': len(batches),
                'total_eta_h': scenario.get('total_eta_h', 0),
                'total_electricity_cost': scenario.get('total_electricity_cost', 0),
                'total_pump_runtime_hours': scenario.get('total_pump_runtime_hours', {}),
                'coverage_info': scenario.get('coverage_info', {}),
                'optimization_goal': scenario.get('optimization_goal', None)
            }
            available_scenarios.append(scenario_info)
        
        return {
            'plan_id': plan_id,
            'total_scenarios': len(available_scenarios),
            'available_scenarios': available_scenarios
        }
    
    def get_batch_info(self, plan_id: str, scenario_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取现有计划的批次详细信息
        
        Args:
            plan_id: 计划ID或文件路径
            scenario_name: 指定scenario名称，不指定则返回第一个scenario的批次信息
            
        Returns:
            批次详细信息
        """
        plan_data = self.load_original_plan(plan_id)
        
        # 从scenarios中提取批次信息
        all_batches = []
        scenarios = plan_data.get('scenarios', [])
        
        if scenarios:
            # 如果指定了scenario_name，查找匹配的scenario
            target_scenario = None
            if scenario_name:
                for scenario in scenarios:
                    if scenario.get('scenario_name') == scenario_name:
                        target_scenario = scenario
                        break
                if not target_scenario:
                    raise HTTPException(
                        status_code=404,
                        detail=f"未找到指定的scenario: {scenario_name}"
                    )
            else:
                # 使用第一个scenario
                target_scenario = scenarios[0]
            
            scenario_name_used = target_scenario.get('scenario_name', 'Unknown')
            scenario_plan = target_scenario.get('plan', {})
            batches = scenario_plan.get('batches', [])
            
            for batch in batches:
                batch_detail = {
                    'scenario_name': scenario_name_used,
                    'index': batch.get('index'),
                    'area_mu': batch.get('area_mu', 0),
                    'fields': batch.get('fields', []),
                    'pumps_used': target_scenario.get('pumps_used', []),
                    'total_electricity_cost': target_scenario.get('total_electricity_cost', 0),
                    'total_eta_h': target_scenario.get('total_eta_h', 0),
                    'calc_info': scenario_plan.get('calc', {})
                }
                all_batches.append(batch_detail)
        
        batch_info = {
            'plan_id': plan_id,
            'scenario_name': scenario_name_used if 'scenario_name_used' in locals() else None,
            'total_batches': len(all_batches),
            'batches': all_batches
        }
        
        return batch_info

# ===== API端点实现 =====

def create_batch_regeneration_endpoint():
    """创建批次重新生成端点的工厂函数"""
    
    service = BatchRegenerationService()
    
    async def regenerate_batch_plan(request: BatchModificationRequest) -> BatchRegenerationResponse:
        """
        批次重新生成端点
        
        根据前端的田块修改、水泵分配和时间修改请求，重新生成灌溉批次计划
        """
        try:
            # 1. 加载原始计划
            original_plan = service.load_original_plan(request.original_plan_id)
            modified_plan = original_plan.copy()
            
            # 2. 应用田块修改
            if request.field_modifications:
                modified_plan = service.apply_field_modifications(
                    modified_plan, 
                    request.field_modifications
                )
            
            # 3. 应用水泵分配修改
            if request.pump_assignments:
                modified_plan = service.apply_pump_modifications(
                    modified_plan,
                    request.pump_assignments
                )
            
            # 4. 应用时间修改
            if request.time_modifications:
                modified_plan = service.apply_time_modifications(
                    modified_plan,
                    request.time_modifications
                )
            
            # 5. 保存修改后的计划
            timestamp = int(time.time())
            output_file = service.output_dir / f"irrigation_plan_modified_{timestamp}.json"
            service.output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(modified_plan, f, ensure_ascii=False, indent=2)
            
            # 6. 准备响应
            modifications_summary = modified_plan.get('modifications_summary', {})
            modifications_summary.update({
                'pump_modifications': len(request.pump_assignments or []),
                'time_modifications': len(request.time_modifications or []),
                'field_modifications': len(request.field_modifications or [])
            })
            
            return BatchRegenerationResponse(
                success=True,
                message=f"批次计划重新生成成功，已保存到 {output_file.name}",
                original_plan=original_plan,
                modified_plan=modified_plan,
                modifications_summary=modifications_summary
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"批次重新生成失败: {str(e)}"
            )
    
    return regenerate_batch_plan

def create_batch_info_endpoint():
    """创建批次信息查询端点的工厂函数"""
    
    service = BatchRegenerationService()
    
    async def get_batch_info(plan_id: str) -> Dict[str, Any]:
        """
        批次信息查询端点
        
        获取现有计划的批次详细信息，用于前端编辑界面
        """
        try:
            batch_info = service.get_batch_info(plan_id)
            return {
                "success": True,
                "message": "批次信息获取成功",
                "data": batch_info
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"获取批次信息失败: {str(e)}"
            )
    
    return get_batch_info

# ===== 缓存支持 =====

def generate_batch_cache_key(request: BatchModificationRequest) -> str:
    """生成批次重新生成的缓存键"""
    key_data = f"{request.original_plan_id}_{len(request.field_modifications)}"
    
    # 包含田块修改
    for mod in request.field_modifications:
        key_data += f"_{mod.field_id}_{mod.action}_{mod.custom_water_level}"
    
    # 包含水泵分配修改
    key_data += f"_pumps_{len(request.pump_assignments)}"
    for pump_mod in request.pump_assignments:
        key_data += f"_{pump_mod.batch_index}_{'_'.join(pump_mod.pump_ids)}"
    
    # 包含时间修改
    key_data += f"_time_{len(request.time_modifications)}"
    for time_mod in request.time_modifications:
        key_data += f"_{time_mod.batch_index}_{time_mod.start_time_h}_{time_mod.duration_h}"
    
    # 包含重新生成参数（简化处理）
    if request.regeneration_params:
        key_data += f"_params_{len(request.regeneration_params)}"
        for k, v in request.regeneration_params.items():
            key_data += f"_{k}_{v}"
    
    return hashlib.md5(key_data.encode()).hexdigest()