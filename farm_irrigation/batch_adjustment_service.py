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
        self.output_dir = Path(__file__).parent / "output"
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

