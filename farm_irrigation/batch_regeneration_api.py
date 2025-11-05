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
    field_modifications: Optional[List[FieldModification]] = Field(default_factory=list, description="田块修改列表")
    pump_assignments: Optional[List[PumpAssignment]] = Field(default_factory=list, description="批次水泵分配修改列表")
    time_modifications: Optional[List[TimeModification]] = Field(default_factory=list, description="批次时间修改列表")
    regeneration_params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="重新生成参数")
    
class BatchRegenerationResponse(BaseModel):
    """批次重新生成响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    original_plan: Optional[Dict[str, Any]] = Field(None, description="原始计划数据")
    modified_plan: Optional[Dict[str, Any]] = Field(None, description="修改后的计划数据")
    modifications_summary: Dict[str, Any] = Field(default_factory=dict, description="修改摘要")
    
# ===== 核心业务逻辑 =====

class BatchRegenerationService:
    """批次重新生成服务"""
    
    def __init__(self):
        # 确保使用正确的output目录路径
        current_dir = Path(__file__).parent
        self.output_dir = current_dir / "output"
        
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
                plan_path = self.output_dir / plan_id
                if plan_path.exists():
                    with open(plan_path, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
        
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
                                modifications: List[FieldModification]) -> Dict[str, Any]:
        """应用田块修改"""
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 获取所有可用田块（从原始数据或配置中）
        available_fields = self._get_available_fields()
        
        # 统计修改信息
        added_fields = []
        removed_fields = []
        
        for mod in modifications:
            if mod.action == "add":
                # 添加田块到需要灌溉的列表
                field_info = self._find_field_info(available_fields, mod.field_id)
                if field_info:
                    # 如果指定了自定义水位，更新水位信息
                    if mod.custom_water_level is not None:
                        field_info['wl_mm'] = mod.custom_water_level
                    
                    # 检查是否已经在计划中
                    if not self._is_field_in_plan(modified_plan, mod.field_id):
                        self._add_field_to_plan(modified_plan, field_info)
                        added_fields.append(mod.field_id)
                        
            elif mod.action == "remove":
                # 从计划中移除田块
                if self._remove_field_from_plan(modified_plan, mod.field_id):
                    removed_fields.append(mod.field_id)
        
        # 重新生成批次
        modified_plan = self._regenerate_batches(modified_plan)
        
        # 更新修改摘要
        modified_plan['modifications_summary'] = {
            'added_fields': added_fields,
            'removed_fields': removed_fields,
            'total_modifications': len(modifications),
            'regeneration_timestamp': time.time()
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
    
    def apply_pump_modifications(self, plan_data: Dict[str, Any], 
                               pump_assignments: List[PumpAssignment]) -> Dict[str, Any]:
        """应用批次水泵分配修改"""
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 统计修改信息
        modified_batches = []
        
        for assignment in pump_assignments:
            batch_index = assignment.batch_index
            pump_ids = assignment.pump_ids
            
            # 验证批次是否存在（从scenarios中查找）
            batch_found = False
            scenarios = modified_plan.get('scenarios', [])
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
            
            # 更新所有scenarios中的水泵配置
            for scenario in modified_plan.get('scenarios', []):
                scenario['pumps_used'] = pump_ids
                modified_batches.append(batch_index)
        
        return modified_plan
    
    def apply_time_modifications(self, plan_data: Dict[str, Any], 
                               time_modifications: List[TimeModification]) -> Dict[str, Any]:
        """应用批次时间修改（完整实现）"""
        modified_plan = json.loads(json.dumps(plan_data))  # 深拷贝
        
        # 统计修改信息
        modified_batches = []
        
        # 按批次索引排序，确保按顺序处理
        sorted_time_mods = sorted(time_modifications, key=lambda x: x.batch_index)
        
        for scenario in modified_plan.get('scenarios', []):
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
                
                # 更新对应batch的统计信息中的时间
                for batch in batches:
                    if batch.get('index') == batch_index:
                        if 'stats' in batch:
                            batch['stats']['eta_hours'] = new_duration
                
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
                            
                            cumulative_time = new_end
            
            # 重新计算scenario的总时长
            if steps:
                total_duration = 0.0
                for step in steps:
                    step_duration = step.get('t_end_h', 0.0) - step.get('t_start_h', 0.0)
                    total_duration += step_duration
                
                # 更新scenario的total_eta_h
                scenario['total_eta_h'] = total_duration
                
                # 更新plan中的total_eta_h
                if scenario_plan:
                    scenario_plan['total_eta_h'] = total_duration
                
                # 重新计算电费（基于新的总时长）
                if 'total_pump_runtime_hours' in scenario:
                    pump_runtime = scenario['total_pump_runtime_hours']
                    # 获取水泵功率和电价
                    calc_info = scenario_plan.get('calc', {})
                    pump_info = calc_info.get('pump', {})
                    power_kw = pump_info.get('power_kw', 60.0)
                    electricity_price = pump_info.get('electricity_price', 0.6)
                    
                    # 重新计算电费
                    total_electricity_cost = 0.0
                    for pump_name, runtime_h in pump_runtime.items():
                        # 如果修改了时长，按比例调整运行时间
                        if modified_batches:
                            # 简化处理：使用总时长的比例
                            adjusted_runtime = total_duration if total_duration > 0 else runtime_h
                            total_electricity_cost += adjusted_runtime * power_kw * electricity_price
                            pump_runtime[pump_name] = adjusted_runtime
                        else:
                            total_electricity_cost += runtime_h * power_kw * electricity_price
                    
                    scenario['total_electricity_cost'] = total_electricity_cost
        
        return modified_plan
    
    def _save_modified_plan(self, modified_plan: Dict[str, Any], original_plan_id: str = None) -> str:
        """保存修改后的计划并返回文件路径"""
        timestamp = int(time.time())
        output_file = self.output_dir / f"irrigation_plan_modified_{timestamp}.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(modified_plan, f, ensure_ascii=False, indent=2)
        
        return str(output_file)
    
    def get_batch_info(self, plan_id: str) -> Dict[str, Any]:
        """获取现有计划的批次详细信息"""
        plan_data = self.load_original_plan(plan_id)
        
        # 从scenarios中提取批次信息
        all_batches = []
        scenarios = plan_data.get('scenarios', [])
        
        if scenarios:
            # 使用第一个scenario的批次数据（通常所有scenario的批次结构相同）
            first_scenario = scenarios[0]
            scenario_name = first_scenario.get('name', 'Unknown')
            scenario_plan = first_scenario.get('plan', {})
            batches = scenario_plan.get('batches', [])
            
            for batch in batches:
                batch_detail = {
                    'scenario_name': scenario_name,
                    'index': batch.get('index'),
                    'area_mu': batch.get('area_mu', 0),
                    'pumps_used': first_scenario.get('pumps_used', []),
                    'total_electricity_cost': first_scenario.get('total_electricity_cost', 0),
                    'total_eta_h': first_scenario.get('total_eta_h', 0),
                    'calc_info': scenario_plan.get('calc', {})
                }
                all_batches.append(batch_detail)
        
        batch_info = {
            'plan_id': plan_id,
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