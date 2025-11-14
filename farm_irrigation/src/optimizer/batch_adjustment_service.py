#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次间田块调整服务
支持在不改变批次数量的情况下，调整田块在批次间的分配
重新计算灌溉顺序和时间
"""

import json
import logging
import copy
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class BatchAdjustmentService:
    """批次间田块调整服务"""
    
    def __init__(self):
        # 从当前文件位置（src/optimizer/）向上两级到项目根目录，然后指向 data/output
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # src/optimizer -> src -> 项目根目录
        self.output_dir = project_root / "data" / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def load_plan(self, plan_id: str) -> Dict[str, Any]:
        """加载灌溉计划"""
        try:
            # 尝试直接作为文件路径
            plan_path = Path(plan_id)
            if not plan_path.exists():
                # 尝试在output目录查找
                plan_path = self.output_dir / plan_id
            
            if not plan_path.exists():
                raise FileNotFoundError(f"未找到计划文件: {plan_id}")
            
            with open(plan_path, 'r', encoding='utf-8') as f:
                plan_data = json.load(f)
            
            logger.info(f"成功加载计划: {plan_path}")
            return plan_data
        
        except Exception as e:
            logger.error(f"加载计划失败: {e}")
            raise
    
    def adjust_fields_between_batches(
        self,
        plan_id: str,
        field_adjustments: List[Dict[str, Any]],
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        在批次间调整田块
        
        Args:
            plan_id: 计划ID或文件路径
            field_adjustments: 田块调整列表 [{"field_id": "S1-G2-F03", "from_batch": 1, "to_batch": 2}]
            options: 优化选项
        
        Returns:
            调整结果字典
        """
        try:
            # 加载原始计划
            original_plan = self.load_plan(plan_id)
            
            # 深拷贝计划以避免修改原始数据
            adjusted_plan = copy.deepcopy(original_plan)
            
            # 验证调整请求（只需验证第一个场景）
            validation_result = self._validate_adjustments(adjusted_plan, field_adjustments)
            if not validation_result["is_valid"]:
                raise ValueError(f"调整验证失败: {validation_result['errors']}")
            
            # 获取受影响的批次
            affected_batches = self._get_affected_batches(field_adjustments)
            
            # 处理多场景计划：对每个场景执行相同的调整
            if "scenarios" in adjusted_plan and isinstance(adjusted_plan["scenarios"], list):
                all_move_results = []
                all_recalc_results = []
                
                for scenario_idx, scenario in enumerate(adjusted_plan["scenarios"]):
                    if "plan" not in scenario:
                        continue
                    
                    logger.info(f"处理场景 {scenario_idx + 1}: {scenario.get('scenario_name', 'Unknown')}")
                    
                    # 为这个场景执行田块移动
                    move_results = self._move_fields_in_scenario(scenario["plan"], field_adjustments)
                    all_move_results.extend(move_results)
                    
                    # 重新计算受影响的批次
                    for batch_idx in affected_batches:
                        if options.get("recalculate_sequence", True):
                            self._reorder_fields_in_scenario(scenario["plan"], batch_idx)
                        
                        if options.get("recalculate_timing", True):
                            time_result = self._recalculate_batch_timing_in_scenario(scenario["plan"], batch_idx)
                            all_recalc_results.append(time_result)
                
                # 使用第一个场景的结果作为代表
                move_results = all_move_results[:len(field_adjustments)] if all_move_results else []
                recalc_results = all_recalc_results[:len(affected_batches)] if all_recalc_results else []
            else:
                # 单场景计划
                move_results = self._move_fields_in_scenario(adjusted_plan, field_adjustments)
                
                recalc_results = []
                for batch_idx in affected_batches:
                    if options.get("recalculate_sequence", True):
                        self._reorder_fields_in_scenario(adjusted_plan, batch_idx)
                    
                    if options.get("recalculate_timing", True):
                        time_result = self._recalculate_batch_timing_in_scenario(adjusted_plan, batch_idx)
                        recalc_results.append(time_result)
            
            # 重新生成命令（如果需要）
            if options.get("regenerate_commands", True):
                self._regenerate_commands(adjusted_plan, affected_batches)
            
            # 生成变更摘要
            changes_summary = self._generate_changes_summary(
                original_plan, 
                adjusted_plan, 
                field_adjustments,
                move_results,
                recalc_results
            )
            
            # 保存调整后的计划
            output_file = self._save_adjusted_plan(adjusted_plan, plan_id)
            
            return {
                "success": True,
                "message": f"成功调整 {len(field_adjustments)} 个田块",
                "original_plan": original_plan,
                "adjusted_plan": adjusted_plan,
                "changes_summary": changes_summary,
                "output_file": str(output_file),
                "validation": {"is_valid": True, "warnings": [], "constraints_met": True}
            }
        
        except Exception as e:
            logger.error(f"批次调整失败: {e}")
            raise
    
    def _validate_adjustments(
        self, 
        plan: Dict[str, Any], 
        field_adjustments: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """验证田块调整请求"""
        errors = []
        warnings = []
        
        # 获取批次数据
        batches = self._get_batches_from_plan(plan)
        total_batches = len(batches)
        
        for adj in field_adjustments:
            field_id = adj.get("field_id")
            from_batch = adj.get("from_batch")
            to_batch = adj.get("to_batch")
            
            # 验证批次索引
            if from_batch < 1 or from_batch > total_batches:
                errors.append(f"源批次 {from_batch} 超出范围 (1-{total_batches})")
            
            if to_batch < 1 or to_batch > total_batches:
                errors.append(f"目标批次 {to_batch} 超出范围 (1-{total_batches})")
            
            # 验证田块是否存在于源批次
            if from_batch >= 1 and from_batch <= total_batches:
                source_batch = batches[from_batch - 1]
                field_found = False
                for field in source_batch.get("fields", []):
                    if field.get("id") == field_id:
                        field_found = True
                        break
                
                if not field_found:
                    errors.append(f"田块 {field_id} 不存在于批次 {from_batch}")
            
            # 相同批次警告
            if from_batch == to_batch:
                warnings.append(f"田块 {field_id} 的源批次和目标批次相同")
        
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def _move_fields_in_scenario(
        self, 
        plan_data: Dict[str, Any], 
        field_adjustments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """在单个场景中执行田块移动操作"""
        results = []
        
        if "batches" not in plan_data:
            return results
        
        batches = plan_data["batches"]
        
        for adj in field_adjustments:
            field_id = adj["field_id"]
            from_batch_idx = adj["from_batch"] - 1  # 转为0基索引
            to_batch_idx = adj["to_batch"] - 1
            
            # 从源批次移除田块
            source_batch = batches[from_batch_idx]
            field_data = None
            
            for i, field in enumerate(source_batch.get("fields", [])):
                if field.get("id") == field_id:
                    field_data = source_batch["fields"].pop(i)
                    break
            
            if field_data:
                # 添加到目标批次
                target_batch = batches[to_batch_idx]
                if "fields" not in target_batch:
                    target_batch["fields"] = []
                target_batch["fields"].append(field_data)
                
                # 更新批次面积
                self._update_batch_area(source_batch)
                self._update_batch_area(target_batch)
                
                results.append({
                    "field_id": field_id,
                    "from_batch": adj["from_batch"],
                    "to_batch": adj["to_batch"],
                    "status": "success"
                })
                
                logger.info(f"成功移动田块 {field_id}: 批次{adj['from_batch']} -> 批次{adj['to_batch']}")
            else:
                results.append({
                    "field_id": field_id,
                    "from_batch": adj["from_batch"],
                    "to_batch": adj["to_batch"],
                    "status": "failed",
                    "error": "田块未找到"
                })
        
        return results
    
    def _get_affected_batches(self, field_adjustments: List[Dict[str, Any]]) -> List[int]:
        """获取受影响的批次索引列表（0基）"""
        affected = set()
        for adj in field_adjustments:
            affected.add(adj["from_batch"] - 1)
            affected.add(adj["to_batch"] - 1)
        return sorted(list(affected))
    
    def _reorder_fields_in_scenario(self, plan_data: Dict[str, Any], batch_idx: int):
        """在单个场景中重新排序批次内的田块（按距离等级）"""
        if "batches" not in plan_data:
            return
        
        batches = plan_data["batches"]
        if batch_idx < 0 or batch_idx >= len(batches):
            return
        
        batch = batches[batch_idx]
        fields = batch.get("fields", [])
        
        # 按距离等级排序
        fields.sort(key=lambda f: (
            f.get("distance_rank", 999),
            f.get("segment_id", ""),
            f.get("id", "")
        ))
        
        batch["fields"] = fields
        logger.info(f"批次 {batch_idx + 1} 内田块已重新排序，共 {len(fields)} 个田块")
    
    def _recalculate_batch_timing_in_scenario(
        self, 
        plan_data: Dict[str, Any], 
        batch_idx: int
    ) -> Dict[str, Any]:
        """在单个场景中重新计算批次时间"""
        if "batches" not in plan_data:
            return {}
        
        batches = plan_data["batches"]
        if batch_idx < 0 or batch_idx >= len(batches):
            return {}
        
        batch = batches[batch_idx]
        
        # 计算批次总面积
        total_area = sum(f.get("area_mu", 0) for f in batch.get("fields", []))
        
        # 从 calc 中获取水泵信息
        pump_info = plan_data.get("calc", {}).get("pump", {})
        pump_flow_rate = pump_info.get("q_rated_m3ph", 240.0)
        
        # 估算灌溉时间（简化计算）
        # 假设每亩需要 80mm 水深，转换为 m3
        water_per_mu = 0.08 * 666.67  # 666.67 m2/亩
        total_water_m3 = total_area * water_per_mu
        duration_h = total_water_m3 / pump_flow_rate if pump_flow_rate > 0 else 0
        
        # 更新批次时间信息
        old_duration = batch.get("duration_h", 0)
        batch["area_mu"] = total_area
        batch["duration_h"] = round(duration_h, 2)
        
        logger.info(f"批次 {batch_idx + 1} 时间已重新计算: {old_duration}h -> {duration_h}h")
        
        return {
            "batch_index": batch_idx + 1,
            "old_duration_h": old_duration,
            "new_duration_h": round(duration_h, 2),
            "time_diff_h": round(duration_h - old_duration, 2)
        }
    
    def _regenerate_commands(self, plan: Dict[str, Any], affected_batches: List[int]):
        """重新生成受影响批次的命令"""
        logger.info(f"重新生成受影响批次的命令: {[b+1 for b in affected_batches]}")
        
        # 处理多场景计划
        if "scenarios" in plan and isinstance(plan["scenarios"], list):
            for scenario in plan["scenarios"]:
                if "plan" in scenario:
                    scenario_plan = scenario["plan"]
                    self._regenerate_steps_for_plan(scenario_plan, affected_batches)
        else:
            # 单场景计划
            self._regenerate_steps_for_plan(plan, affected_batches)
    
    def _regenerate_steps_for_plan(self, plan_data: Dict[str, Any], affected_batches: List[int]):
        """为单个场景重新生成步骤"""
        if "batches" not in plan_data or "steps" not in plan_data:
            return
        
        batches = plan_data["batches"]
        steps = plan_data["steps"]
        
        # 确保批次数和步骤数匹配
        if len(batches) != len(steps):
            logger.warning(f"批次数({len(batches)})与步骤数({len(steps)})不匹配")
            return
        
        # 为每个受影响的批次重新生成步骤
        for batch_idx in affected_batches:
            if batch_idx < 0 or batch_idx >= len(batches):
                continue
            
            batch = batches[batch_idx]
            step = steps[batch_idx]
            
            # 获取当前批次的田块ID列表
            new_field_ids = [f["id"] for f in batch.get("fields", [])]
            
            # 更新步骤中的 sequence.fields 列表
            if "sequence" in step and isinstance(step["sequence"], dict):
                step["sequence"]["fields"] = new_field_ids
                logger.info(f"已更新批次 {batch_idx + 1} 的 sequence.fields，共 {len(new_field_ids)} 个田块")
            
            # 更新步骤中的 full_order 列表
            if "full_order" in step and isinstance(step["full_order"], list):
                new_full_order = []
                fields_inserted = False
                
                for i, item in enumerate(step["full_order"]):
                    item_type = item.get("type", "")
                    
                    # 跳过旧的田块条目
                    if item_type == "field":
                        continue
                    
                    # 在第一个 pump_off 前插入新田块列表
                    if item_type == "pump_off" and not fields_inserted:
                        for field_id in new_field_ids:
                            field_data = next((f for f in batch.get("fields", []) if f["id"] == field_id), None)
                            inlet_g_id = field_data.get("inlet_G_id", "") if field_data else ""
                            new_full_order.append({
                                "type": "field",
                                "id": field_id,
                                "inlet_G_id": inlet_g_id
                            })
                        fields_inserted = True
                    
                    new_full_order.append(item)
                
                step["full_order"] = new_full_order
                logger.info(f"已更新批次 {batch_idx + 1} 的 full_order，共 {len(new_field_ids)} 个田块")
    
    def _generate_changes_summary(
        self,
        original_plan: Dict[str, Any],
        adjusted_plan: Dict[str, Any],
        field_adjustments: List[Dict[str, Any]],
        move_results: List[Dict[str, Any]],
        recalc_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """生成变更摘要"""
        successful_moves = [r for r in move_results if r.get("status") == "success"]
        
        return {
            "total_fields_moved": len(successful_moves),
            "affected_batches": list(set([adj["from_batch"] for adj in field_adjustments] + 
                                        [adj["to_batch"] for adj in field_adjustments])),
            "field_movements": successful_moves,
            "batch_time_changes": recalc_results,
            "timestamp": datetime.now().isoformat()
        }
    
    def _update_batch_area(self, batch: Dict[str, Any]):
        """更新批次总面积"""
        total_area = sum(f.get("area_mu", 0) for f in batch.get("fields", []))
        batch["area_mu"] = round(total_area, 2)
    
    def _get_batches_from_plan(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从计划中提取批次列表"""
        # 支持多种计划格式
        if "scenarios" in plan and isinstance(plan["scenarios"], list) and len(plan["scenarios"]) > 0:
            first_scenario = plan["scenarios"][0]
            if "plan" in first_scenario and "batches" in first_scenario["plan"]:
                return first_scenario["plan"]["batches"]
        
        if "batches" in plan:
            return plan["batches"]
        
        return []
    
    def _get_pumps_from_plan(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从计划中提取水泵信息"""
        if "scenarios" in plan and isinstance(plan["scenarios"], list) and len(plan["scenarios"]) > 0:
            first_scenario = plan["scenarios"][0]
            if "plan" in first_scenario and "pumps" in first_scenario["plan"]:
                return first_scenario["plan"]["pumps"]
        
        if "pumps" in plan:
            return plan["pumps"]
        
        return []
    
    def _save_adjusted_plan(self, plan: Dict[str, Any], original_plan_id: str) -> Path:
        """保存调整后的计划"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name = Path(original_plan_id).stem
        output_file = self.output_dir / f"{original_name}_adjusted_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        
        logger.info(f"调整后的计划已保存: {output_file}")
        return output_file
    
    def reorder_batches(
        self,
        plan_id: str,
        new_order: Optional[List[int]] = None,
        scenario_name: Optional[str] = None,
        reorder_configs: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        调整批次执行顺序（支持多scenario）
        
        Args:
            plan_id: 计划ID或文件路径
            new_order: 新的批次顺序列表（兼容旧版，与scenario_name配合使用）
            scenario_name: 指定要调整的scenario名称（兼容旧版）
            reorder_configs: 多scenario调整配置列表（新功能）
                格式：[
                    {"scenario_name": "P1单独使用", "new_order": [2, 1, 3, ...]},
                    {"scenario_name": "P2单独使用", "new_order": [3, 1, 2, ...]},
                    {"scenario_name": None, "new_order": [2, 1, 3, ...]}  # None表示所有scenario
                ]
        
        Returns:
            调整结果字典
        """
        try:
            # 加载原始计划
            original_plan = self.load_plan(plan_id)
            
            # 深拷贝计划以避免修改原始数据
            reordered_plan = copy.deepcopy(original_plan)
            
            # 新版：使用reorder_configs进行多scenario调整
            if reorder_configs:
                return self._reorder_multiple_scenarios(
                    original_plan, reordered_plan, plan_id, reorder_configs
                )
            
            # 兼容旧版：使用new_order和scenario_name
            if new_order is None:
                raise ValueError("必须提供new_order或reorder_configs参数")
            
            # 如果指定了scenario_name，只处理该scenario
            if scenario_name:
                target_scenario = self._find_scenario_by_name(original_plan, scenario_name)
                if not target_scenario:
                    raise ValueError(f"未找到scenario: {scenario_name}")
                
                # 从目标scenario获取批次数量
                batches = target_scenario.get("plan", {}).get("batches", [])
                total_batches = len(batches)
            else:
                # 未指定scenario，获取第一个scenario的批次数量，并验证所有scenario批次数量一致
                batches = self._get_batches_from_plan(original_plan)
                total_batches = len(batches)
                
                # 验证所有scenario的批次数量是否一致
                if "scenarios" in original_plan:
                    for scenario in original_plan["scenarios"]:
                        scenario_batches = scenario.get("plan", {}).get("batches", [])
                        if len(scenario_batches) != total_batches:
                            raise ValueError(
                                f"不同scenario的批次数量不一致。"
                                f"请使用scenario_name参数指定要调整的scenario。"
                                f"可选值：{', '.join([s.get('scenario_name', '') for s in original_plan['scenarios']])}"
                            )
            
            # 验证新顺序
            if len(new_order) != total_batches:
                scenario_info = f"（scenario: {scenario_name}）" if scenario_name else ""
                raise ValueError(
                    f"新顺序长度({len(new_order)})与批次数量({total_batches})不匹配{scenario_info}"
                )
            
            if sorted(new_order) != list(range(1, total_batches + 1)):
                raise ValueError(f"新顺序必须包含1到{total_batches}的所有批次索引")
            
            # 检查是否有实际变化
            original_order = list(range(1, total_batches + 1))
            if new_order == original_order:
                logger.info("批次顺序未改变，无需调整")
                return {
                    "success": True,
                    "message": "批次顺序未改变",
                    "original_plan": original_plan,
                    "reordered_plan": original_plan,
                    "changes_summary": {
                        "order_changed": False,
                        "original_order": original_order,
                        "new_order": new_order
                    },
                    "output_file": None
                }
            
            # 处理多场景计划或单场景计划
            if scenario_name:
                # 只调整指定的scenario
                target_scenario = self._find_scenario_by_name(reordered_plan, scenario_name)
                if target_scenario and "plan" in target_scenario:
                    self._reorder_batches_in_scenario(target_scenario["plan"], new_order)
                    logger.info(f"已调整scenario '{scenario_name}' 的批次顺序")
            elif "scenarios" in reordered_plan and isinstance(reordered_plan["scenarios"], list):
                # 调整所有scenario
                for scenario in reordered_plan["scenarios"]:
                    if "plan" in scenario:
                        self._reorder_batches_in_scenario(scenario["plan"], new_order)
                logger.info(f"已调整所有{len(reordered_plan['scenarios'])}个scenario的批次顺序")
            else:
                # 单场景计划
                self._reorder_batches_in_scenario(reordered_plan, new_order)
            
            # 生成变更摘要
            changes_summary = self._generate_reorder_summary(original_plan, reordered_plan, original_order, new_order)
            
            # 保存调整后的计划
            output_file = self._save_reordered_plan(reordered_plan, plan_id)
            
            return {
                "success": True,
                "message": f"成功调整批次顺序，共{total_batches}个批次",
                "original_plan": original_plan,
                "reordered_plan": reordered_plan,
                "changes_summary": changes_summary,
                "output_file": str(output_file),
                "validation": {"is_valid": True}
            }
        
        except Exception as e:
            logger.error(f"批次顺序调整失败: {e}")
            raise
    
    def _reorder_batches_in_scenario(self, plan: Dict[str, Any], new_order: List[int]):
        """
        在单个场景中重新排序批次
        通过调整时间来实现顺序变化
        """
        if "batches" not in plan:
            return
        
        batches = plan["batches"]
        
        # 收集每个批次的持续时间
        batch_durations = {}
        for batch in batches:
            batch_idx = batch.get("index")
            # 从stats中获取持续时间，如果没有则根据田块计算
            if "stats" in batch and "eta_hours" in batch["stats"]:
                duration = batch["stats"]["eta_hours"]
            else:
                # 默认持续时间（如果无法获取）
                duration = 10.0
            batch_durations[batch_idx] = duration
        
        # 根据新顺序重新分配时间
        current_time = 0.0
        new_batch_times = {}
        
        for batch_idx in new_order:
            duration = batch_durations.get(batch_idx, 10.0)
            new_batch_times[batch_idx] = {
                "start_time": current_time,
                "end_time": current_time + duration,
                "duration": duration
            }
            current_time += duration
        
        # 更新steps中的时间
        if "steps" in plan:
            for step in plan["steps"]:
                # 找到这个step对应的批次
                label = step.get("label", "")
                if "批次" in label or "Batch" in label.lower():
                    # 提取批次索引
                    import re
                    match = re.search(r'(\d+)', label)
                    if match:
                        batch_idx = int(match.group(1))
                        if batch_idx in new_batch_times:
                            times = new_batch_times[batch_idx]
                            step["t_start_h"] = times["start_time"]
                            step["t_end_h"] = times["end_time"]
                            
                            # 更新step中所有commands的时间
                            if "commands" in step:
                                for cmd in step["commands"]:
                                    cmd["t_start_h"] = times["start_time"]
                                    cmd["t_end_h"] = times["end_time"]
        
        # 更新sequence（如果存在）
        if "sequence" in plan:
            for seq_item in plan["sequence"]:
                batch_idx = seq_item.get("batch_index")
                if batch_idx in new_batch_times:
                    times = new_batch_times[batch_idx]
                    seq_item["t_start_h"] = times["start_time"]
                    seq_item["t_end_h"] = times["end_time"]
        
        logger.info(f"成功重新排序批次: {new_order}")
    
    def _generate_reorder_summary(
        self,
        original_plan: Dict[str, Any],
        reordered_plan: Dict[str, Any],
        original_order: List[int],
        new_order: List[int]
    ) -> Dict[str, Any]:
        """生成批次重排序的变更摘要"""
        
        # 获取批次信息
        original_batches = self._get_batches_from_plan(original_plan)
        reordered_batches = self._get_batches_from_plan(reordered_plan)
        
        # 构建批次变化列表
        batch_changes = []
        for new_position, batch_idx in enumerate(new_order, 1):
            old_position = original_order.index(batch_idx) + 1
            
            # 获取批次名称（如果有）
            batch_name = f"批次{batch_idx}"
            
            # 获取时间变化
            original_batch = next((b for b in original_batches if b.get("index") == batch_idx), None)
            reordered_batch = next((b for b in reordered_batches if b.get("index") == batch_idx), None)
            
            time_change = {}
            if original_batch and reordered_batch:
                # 从steps获取时间信息
                orig_step = self._get_step_for_batch(original_plan, batch_idx)
                new_step = self._get_step_for_batch(reordered_plan, batch_idx)
                
                if orig_step and new_step:
                    time_change = {
                        "original_start": orig_step.get("t_start_h", 0),
                        "new_start": new_step.get("t_start_h", 0),
                        "original_end": orig_step.get("t_end_h", 0),
                        "new_end": new_step.get("t_end_h", 0)
                    }
            
            batch_changes.append({
                "batch_index": batch_idx,
                "batch_name": batch_name,
                "original_position": old_position,
                "new_position": new_position,
                "position_change": new_position - old_position,
                "time_change": time_change
            })
        
        return {
            "order_changed": True,
            "original_order": original_order,
            "new_order": new_order,
            "total_batches": len(original_order),
            "batch_changes": batch_changes,
            "timestamp": datetime.now().isoformat()
        }
    
    def _get_step_for_batch(self, plan: Dict[str, Any], batch_idx: int) -> Optional[Dict[str, Any]]:
        """获取指定批次的step信息"""
        # 从第一个场景或主计划获取steps
        steps = None
        if "scenarios" in plan and isinstance(plan["scenarios"], list) and len(plan["scenarios"]) > 0:
            first_scenario = plan["scenarios"][0]
            if "plan" in first_scenario and "steps" in first_scenario["plan"]:
                steps = first_scenario["plan"]["steps"]
        elif "steps" in plan:
            steps = plan["steps"]
        
        if not steps:
            return None
        
        # 查找对应批次的step
        for step in steps:
            label = step.get("label", "")
            if f"批次 {batch_idx}" in label or f"批次{batch_idx}" in label or f"Batch {batch_idx}" in label.lower():
                return step
        
        return None
    
    def _save_reordered_plan(self, plan: Dict[str, Any], original_plan_id: str) -> Path:
        """保存重新排序后的计划"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name = Path(original_plan_id).stem
        output_file = self.output_dir / f"{original_name}_reordered_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        
        logger.info(f"重新排序后的计划已保存: {output_file}")
        return output_file
    
    def _find_scenario_by_name(self, plan: Dict[str, Any], scenario_name: str) -> Optional[Dict[str, Any]]:
        """根据名称查找scenario"""
        if "scenarios" in plan and isinstance(plan["scenarios"], list):
            for scenario in plan["scenarios"]:
                if scenario.get("scenario_name") == scenario_name:
                    return scenario
        return None
    
    def _reorder_multiple_scenarios(
        self,
        original_plan: Dict[str, Any],
        reordered_plan: Dict[str, Any],
        plan_id: str,
        reorder_configs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        同时调整多个scenarios的批次顺序
        
        Args:
            original_plan: 原始计划
            reordered_plan: 要修改的计划副本
            plan_id: 计划ID
            reorder_configs: 调整配置列表
        
        Returns:
            调整结果字典
        """
        scenarios_modified = []
        scenarios_unchanged = []
        scenario_changes = {}
        
        for config in reorder_configs:
            scenario_name = config.get("scenario_name")
            new_order = config.get("new_order")
            
            if not new_order:
                raise ValueError(f"配置缺少new_order: {config}")
            
            # scenario_name为None表示调整所有scenarios
            if scenario_name is None:
                logger.info("调整所有scenarios使用相同顺序")
                
                if "scenarios" not in reordered_plan:
                    raise ValueError("计划中没有scenarios字段")
                
                for scenario in reordered_plan["scenarios"]:
                    s_name = scenario.get("scenario_name", "Unknown")
                    
                    # 验证批次数量
                    batches = scenario.get("plan", {}).get("batches", [])
                    if len(batches) != len(new_order):
                        raise ValueError(
                            f"Scenario '{s_name}' 的批次数量({len(batches)})与new_order长度({len(new_order)})不匹配"
                        )
                    
                    # 检查是否有变化
                    original_order = list(range(1, len(batches) + 1))
                    if new_order != original_order:
                        # 执行调整
                        if "plan" in scenario:
                            self._reorder_batches_in_scenario(scenario["plan"], new_order)
                        
                        scenarios_modified.append(s_name)
                        scenario_changes[s_name] = self._get_batch_changes(
                            original_order, new_order, len(batches)
                        )
                    else:
                        scenarios_unchanged.append(s_name)
                
                logger.info(f"已调整所有scenarios，修改了{len(scenarios_modified)}个")
            else:
                # 调整指定的scenario
                target_scenario = self._find_scenario_by_name(reordered_plan, scenario_name)
                if not target_scenario:
                    raise ValueError(f"未找到scenario: {scenario_name}")
                
                # 验证批次数量
                batches = target_scenario.get("plan", {}).get("batches", [])
                if len(batches) != len(new_order):
                    raise ValueError(
                        f"Scenario '{scenario_name}' 的批次数量({len(batches)})与new_order长度({len(new_order)})不匹配"
                    )
                
                # 验证new_order有效性
                if sorted(new_order) != list(range(1, len(batches) + 1)):
                    raise ValueError(
                        f"Scenario '{scenario_name}' 的new_order必须包含1到{len(batches)}的所有批次索引"
                    )
                
                # 检查是否有变化
                original_order = list(range(1, len(batches) + 1))
                if new_order != original_order:
                    # 执行调整
                    if "plan" in target_scenario:
                        self._reorder_batches_in_scenario(target_scenario["plan"], new_order)
                    
                    scenarios_modified.append(scenario_name)
                    scenario_changes[scenario_name] = self._get_batch_changes(
                        original_order, new_order, len(batches)
                    )
                    logger.info(f"已调整scenario '{scenario_name}' 的批次顺序")
                else:
                    scenarios_unchanged.append(scenario_name)
                    logger.info(f"Scenario '{scenario_name}' 的批次顺序未改变")
        
        # 如果没有任何修改
        if not scenarios_modified:
            return {
                "success": True,
                "message": "所有scenarios的批次顺序均未改变",
                "original_plan": original_plan,
                "reordered_plan": original_plan,
                "changes_summary": {
                    "total_scenarios_modified": 0,
                    "scenarios_modified": [],
                    "scenarios_unchanged": scenarios_unchanged,
                    "scenario_changes": {}
                },
                "output_file": None
            }
        
        # 生成变更摘要
        changes_summary = {
            "total_scenarios_modified": len(scenarios_modified),
            "scenarios_modified": scenarios_modified,
            "scenarios_unchanged": scenarios_unchanged,
            "scenario_changes": scenario_changes,
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存调整后的计划
        output_file = self._save_reordered_plan(reordered_plan, plan_id)
        
        return {
            "success": True,
            "message": f"成功调整{len(scenarios_modified)}个scenario的批次顺序",
            "original_plan": original_plan,
            "reordered_plan": reordered_plan,
            "changes_summary": changes_summary,
            "output_file": str(output_file),
            "validation": {"is_valid": True}
        }
    
    def _get_batch_changes(
        self,
        original_order: List[int],
        new_order: List[int],
        total_batches: int
    ) -> Dict[str, Any]:
        """生成单个scenario的批次变化详情"""
        batch_movements = []
        
        for new_position, batch_idx in enumerate(new_order, 1):
            old_position = original_order.index(batch_idx) + 1
            if old_position != new_position:
                batch_movements.append({
                    "batch_index": batch_idx,
                    "from_position": old_position,
                    "to_position": new_position,
                    "position_change": new_position - old_position
                })
        
        return {
            "order_changed": True,
            "original_order": original_order,
            "new_order": new_order,
            "total_batches": total_batches,
            "batch_movements": batch_movements
        }
    
    def _reorder_multiple_scenarios(
        self,
        original_plan: Dict[str, Any],
        reordered_plan: Dict[str, Any],
        plan_id: str,
        reorder_configs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        同时调整多个scenarios的批次顺序
        
        Args:
            original_plan: 原始计划
            reordered_plan: 要修改的计划副本
            plan_id: 计划ID
            reorder_configs: 调整配置列表
        
        Returns:
            调整结果字典
        """
        scenarios_modified = []
        scenarios_unchanged = []
        scenario_changes = {}
        
        for config in reorder_configs:
            scenario_name = config.get("scenario_name")
            new_order = config.get("new_order")
            
            if not new_order:
                raise ValueError(f"配置缺少new_order: {config}")
            
            # scenario_name为None表示调整所有scenarios
            if scenario_name is None:
                logger.info("调整所有scenarios使用相同顺序")
                
                if "scenarios" not in reordered_plan:
                    raise ValueError("计划中没有scenarios字段")
                
                for scenario in reordered_plan["scenarios"]:
                    s_name = scenario.get("scenario_name", "Unknown")
                    
                    # 验证批次数量
                    batches = scenario.get("plan", {}).get("batches", [])
                    if len(batches) != len(new_order):
                        raise ValueError(
                            f"Scenario '{s_name}' 的批次数量({len(batches)})与new_order长度({len(new_order)})不匹配"
                        )
                    
                    # 检查是否有变化
                    original_order = list(range(1, len(batches) + 1))
                    if new_order != original_order:
                        # 执行调整
                        if "plan" in scenario:
                            self._reorder_batches_in_scenario(scenario["plan"], new_order)
                        
                        scenarios_modified.append(s_name)
                        scenario_changes[s_name] = self._get_batch_changes(
                            original_order, new_order, len(batches)
                        )
                    else:
                        scenarios_unchanged.append(s_name)
                
                logger.info(f"已调整所有scenarios，修改了{len(scenarios_modified)}个")
            else:
                # 调整指定的scenario
                target_scenario = self._find_scenario_by_name(reordered_plan, scenario_name)
                if not target_scenario:
                    raise ValueError(f"未找到scenario: {scenario_name}")
                
                # 验证批次数量
                batches = target_scenario.get("plan", {}).get("batches", [])
                if len(batches) != len(new_order):
                    raise ValueError(
                        f"Scenario '{scenario_name}' 的批次数量({len(batches)})与new_order长度({len(new_order)})不匹配"
                    )
                
                # 验证new_order有效性
                if sorted(new_order) != list(range(1, len(batches) + 1)):
                    raise ValueError(
                        f"Scenario '{scenario_name}' 的new_order必须包含1到{len(batches)}的所有批次索引"
                    )
                
                # 检查是否有变化
                original_order = list(range(1, len(batches) + 1))
                if new_order != original_order:
                    # 执行调整
                    if "plan" in target_scenario:
                        self._reorder_batches_in_scenario(target_scenario["plan"], new_order)
                    
                    scenarios_modified.append(scenario_name)
                    scenario_changes[scenario_name] = self._get_batch_changes(
                        original_order, new_order, len(batches)
                    )
                    logger.info(f"已调整scenario '{scenario_name}' 的批次顺序")
                else:
                    scenarios_unchanged.append(scenario_name)
                    logger.info(f"Scenario '{scenario_name}' 的批次顺序未改变")
        
        # 如果没有任何修改
        if not scenarios_modified:
            return {
                "success": True,
                "message": "所有scenarios的批次顺序均未改变",
                "original_plan": original_plan,
                "reordered_plan": original_plan,
                "changes_summary": {
                    "total_scenarios_modified": 0,
                    "scenarios_modified": [],
                    "scenarios_unchanged": scenarios_unchanged,
                    "scenario_changes": {}
                },
                "output_file": None
            }
        
        # 生成变更摘要
        changes_summary = {
            "total_scenarios_modified": len(scenarios_modified),
            "scenarios_modified": scenarios_modified,
            "scenarios_unchanged": scenarios_unchanged,
            "scenario_changes": scenario_changes,
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存调整后的计划
        output_file = self._save_reordered_plan(reordered_plan, plan_id)
        
        return {
            "success": True,
            "message": f"成功调整{len(scenarios_modified)}个scenario的批次顺序",
            "original_plan": original_plan,
            "reordered_plan": reordered_plan,
            "changes_summary": changes_summary,
            "output_file": str(output_file),
            "validation": {"is_valid": True}
        }
    
    def _get_batch_changes(
        self,
        original_order: List[int],
        new_order: List[int],
        total_batches: int
    ) -> Dict[str, Any]:
        """生成单个scenario的批次变化详情"""
        batch_movements = []
        
        for new_position, batch_idx in enumerate(new_order, 1):
            old_position = original_order.index(batch_idx) + 1
            if old_position != new_position:
                batch_movements.append({
                    "batch_index": batch_idx,
                    "from_position": old_position,
                    "to_position": new_position,
                    "position_change": new_position - old_position
                })
        
        return {
            "order_changed": True,
            "original_order": original_order,
            "new_order": new_order,
            "total_batches": total_batches,
            "batch_movements": batch_movements
        }

