#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能批次优化器
根据不同优化目标自动生成多个灌溉方案
"""

import json
import logging
import hashlib
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


# ==================== 优化配置常量 ====================
class OptimizationConfig:
    """优化配置常量，消除魔法数字"""
    
    # 时间调整因子
    COST_TIME_EXTENSION_FACTOR = 1.2   # 省电方案延长20%时间
    TIME_REDUCTION_FACTOR = 0.7        # 省时方案缩短30%时间
    WATER_SAVING_EXTENSION_FACTOR = 1.2  # 节水方案延长20%时间
    
    # 默认电价配置
    DEFAULT_PEAK_HOURS = list(range(8, 22))  # 8:00-21:00高峰期
    DEFAULT_VALLEY_HOURS = list(range(22, 24)) + list(range(0, 8))  # 22:00-7:00低谷期
    DEFAULT_PEAK_PRICE = 1.0      # 默认高峰电价（元/度）
    DEFAULT_VALLEY_PRICE = 0.4    # 默认低谷电价（元/度）
    
    # 默认时段开始时间
    DEFAULT_VALLEY_START = 22.0   # 低谷期开始时间
    
    # 水泵默认参数
    DEFAULT_PUMP_POWER_KW = 60.0  # 默认水泵功率（kW）
    DEFAULT_ELECTRICITY_PRICE = 0.6  # 默认电价（元/度）
    
    # 缓存配置
    CACHE_MAX_SIZE = 100  # 最大缓存数量
    CACHE_TTL_SECONDS = 3600  # 缓存过期时间（秒）


class IntelligentBatchOptimizer:
    """智能批次优化器"""
    
    def __init__(self):
        # 从当前文件位置（src/optimizer/）向上两级到项目根目录，然后指向 data/output
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # src/optimizer -> src -> 项目根目录
        self.output_dir = project_root / "data" / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化缓存
        self._optimization_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
    
    def _generate_cache_key(self, base_plan: Dict[str, Any], 
                           optimization_goals: List[str],
                           constraints: Dict[str, Any]) -> str:
        """生成缓存键"""
        # 提取关键信息生成缓存键
        plan_id = base_plan.get("plan_id", "")
        if not plan_id and "scenarios" in base_plan:
            # 尝试从第一个scenario提取plan_id
            first_scenario = base_plan["scenarios"][0] if base_plan["scenarios"] else {}
            plan_id = first_scenario.get("plan", {}).get("plan_id", "")
        
        # 生成唯一键
        key_parts = [
            plan_id,
            ",".join(sorted(optimization_goals)),
            json.dumps(constraints, sort_keys=True)
        ]
        key_str = "|".join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _check_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """检查缓存是否有效"""
        if cache_key not in self._optimization_cache:
            return None
        
        # 检查缓存是否过期
        timestamp = self._cache_timestamps.get(cache_key)
        if timestamp:
            age = (datetime.now() - timestamp).total_seconds()
            if age > OptimizationConfig.CACHE_TTL_SECONDS:
                # 缓存过期，删除
                del self._optimization_cache[cache_key]
                del self._cache_timestamps[cache_key]
                logger.info(f"缓存已过期: {cache_key}")
                return None
        
        logger.info(f"使用缓存结果: {cache_key}")
        return self._optimization_cache[cache_key]
    
    def _save_cache(self, cache_key: str, result: Dict[str, Any]):
        """保存到缓存"""
        # 如果缓存数量超过限制，清理最老的缓存
        if len(self._optimization_cache) >= OptimizationConfig.CACHE_MAX_SIZE:
            # 找到最老的缓存键
            oldest_key = min(self._cache_timestamps.keys(), 
                           key=lambda k: self._cache_timestamps[k])
            del self._optimization_cache[oldest_key]
            del self._cache_timestamps[oldest_key]
            logger.info(f"清理旧缓存: {oldest_key}")
        
        self._optimization_cache[cache_key] = result
        self._cache_timestamps[cache_key] = datetime.now()
        logger.info(f"保存缓存: {cache_key}")
    
    def generate_optimized_scenarios(
        self, 
        base_plan: Dict[str, Any],
        optimization_goals: List[str],
        constraints: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        根据优化目标生成多个方案
        
        Args:
            base_plan: 基础灌溉计划
            optimization_goals: 优化目标列表
            constraints: 约束条件
            
        Returns:
            包含多个优化方案的字典
        """
        if constraints is None:
            constraints = {}
        
        # 生成缓存键并检查缓存
        cache_key = self._generate_cache_key(base_plan, optimization_goals, constraints)
        cached_result = self._check_cache(cache_key)
        if cached_result:
            return cached_result
        
        scenarios = []
        
        # 提取基础计划信息
        base_scenario = self._extract_base_scenario(base_plan)
        if not base_scenario:
            raise ValueError("无法从计划中提取基础方案")
        
        # 根据不同目标生成方案
        for goal in optimization_goals:
            try:
                if goal == "cost_minimization":
                    scenario = self._optimize_for_cost(base_scenario, constraints)
                    scenario["optimization_goal"] = "cost_minimization"
                    scenario["name"] = "省电方案"
                    
                elif goal == "time_minimization":
                    scenario = self._optimize_for_time(base_scenario, constraints)
                    scenario["optimization_goal"] = "time_minimization"
                    scenario["name"] = "省时方案"
                    
                elif goal == "balanced":
                    scenario = self._optimize_balanced(base_scenario, constraints)
                    scenario["optimization_goal"] = "balanced"
                    scenario["name"] = "均衡方案"
                    
                elif goal == "off_peak":
                    scenario = self._optimize_off_peak(base_scenario, constraints)
                    scenario["optimization_goal"] = "off_peak"
                    scenario["name"] = "避峰方案"
                    
                elif goal == "water_saving":
                    scenario = self._optimize_water_saving(base_scenario, constraints)
                    scenario["optimization_goal"] = "water_saving"
                    scenario["name"] = "节水方案"
                else:
                    logger.warning(f"未知的优化目标: {goal}")
                    continue
                
                scenarios.append(scenario)
                
            except Exception as e:
                logger.error(f"生成优化方案失败 ({goal}): {e}")
                continue
        
        # 生成对比分析
        comparison = self._generate_comparison(scenarios)
        
        result = {
            "success": True,
            "total_scenarios": len(scenarios),
            "scenarios": scenarios,
            "comparison": comparison,
            "base_plan_summary": self._get_plan_summary(base_scenario)
        }
        
        # 保存到缓存
        self._save_cache(cache_key, result)
        
        return result
    
    def _calculate_valley_periods(self, valley_hours: set, peak_hours: set) -> List[tuple]:
        """
        根据低谷小时计算连续的低谷时段
        
        Args:
            valley_hours: 低谷小时集合
            peak_hours: 高峰小时集合
            
        Returns:
            连续低谷时段列表，例如 [(0.0, 8.0), (22.0, 24.0)]
        """
        # 确保valley_hours中的小时都不在peak_hours中
        valid_valley_hours = sorted([h for h in valley_hours if h not in peak_hours])
        
        if not valid_valley_hours:
            # 如果没有低谷时段，使用默认低谷期
            logger.warning("未找到低谷时段，使用默认配置")
            return [(OptimizationConfig.DEFAULT_VALLEY_START, 24.0), (0.0, 8.0)]
        
        # 将连续的小时合并为时段
        periods = []
        start_hour = valid_valley_hours[0]
        prev_hour = start_hour
        
        for hour in valid_valley_hours[1:]:
            # 如果不连续（考虑跨天情况）
            if hour != prev_hour + 1 and not (prev_hour == 23 and hour == 0):
                # 保存当前时段
                periods.append((float(start_hour), float(prev_hour + 1)))
                start_hour = hour
            prev_hour = hour
        
        # 添加最后一个时段
        periods.append((float(start_hour), float(prev_hour + 1)))
        
        # 按时段长度降序排序（优先使用长时段）
        periods.sort(key=lambda p: p[1] - p[0], reverse=True)
        
        logger.info(f"计算得到低谷时段: {periods}")
        return periods
    
    def _extract_base_scenario(self, plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从计划中提取基础方案"""
        # 尝试从scenarios中提取
        if "scenarios" in plan and isinstance(plan["scenarios"], list) and len(plan["scenarios"]) > 0:
            return plan["scenarios"][0]
        
        # 如果是顶层计划，包装为scenario格式
        if "batches" in plan:
            return {
                "scenario_name": "基础方案",
                "plan": plan
            }
        
        return None
    
    def _optimize_for_cost(self, base_scenario: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        """成本最小化优化"""
        scenario = copy.deepcopy(base_scenario)
        
        # 获取电价信息（使用配置常量作为默认值）
        electricity_prices = constraints.get("electricity_price_schedule", {
            "peak": {
                "hours": OptimizationConfig.DEFAULT_PEAK_HOURS, 
                "price": OptimizationConfig.DEFAULT_PEAK_PRICE
            },
            "valley": {
                "hours": OptimizationConfig.DEFAULT_VALLEY_HOURS, 
                "price": OptimizationConfig.DEFAULT_VALLEY_PRICE
            }
        })
        
        valley_start = OptimizationConfig.DEFAULT_VALLEY_START
        
        plan = scenario.get("plan", {})
        steps = plan.get("steps", [])
        batches = plan.get("batches", [])
        
        # 策略1：调整到电价低谷期
        current_time = valley_start
        for i, step in enumerate(steps):
            original_duration = step.get("t_end_h", 0) - step.get("t_start_h", 0)
            
            # 延长批次时间（使用配置常量）
            extended_duration = original_duration * OptimizationConfig.COST_TIME_EXTENSION_FACTOR
            
            step["t_start_h"] = current_time
            step["t_end_h"] = current_time + extended_duration
            
            # 更新commands时间
            for cmd in step.get("commands", []):
                cmd["t_start_h"] = current_time
                cmd["t_end_h"] = current_time + extended_duration
            
            current_time += extended_duration
        
        # 策略2：优先使用低功率水泵（如果有多个选择）
        available_pumps = constraints.get("available_pumps", [])
        if available_pumps and len(available_pumps) > 0:
            # 使用第一个水泵（假设按功率排序）
            scenario["pumps_used"] = [available_pumps[0]]
        
        # 重新计算总时长和成本
        total_duration = sum(step.get("t_end_h", 0) - step.get("t_start_h", 0) for step in steps)
        
        # 获取水泵参数（使用配置常量作为默认值）
        pump_info = plan.get("calc", {}).get("pump", {})
        power_kw = pump_info.get("power_kw", OptimizationConfig.DEFAULT_PUMP_POWER_KW)
        electricity_price = electricity_prices["valley"]["price"]  # 使用低谷电价
        
        total_cost = total_duration * power_kw * electricity_price
        
        scenario["total_eta_h"] = total_duration
        scenario["total_electricity_cost"] = total_cost
        scenario["description"] = f"通过延长作业时间并安排在电价低谷期（{valley_start}:00后），降低总电费"
        
        return scenario
    
    def _optimize_for_time(self, base_scenario: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        """时间最小化优化"""
        scenario = copy.deepcopy(base_scenario)
        
        plan = scenario.get("plan", {})
        steps = plan.get("steps", [])
        
        # 策略1：缩短批次时间（提高水泵功率）
        current_time = 0.0
        for step in steps:
            original_duration = step.get("t_end_h", 0) - step.get("t_start_h", 0)
            
            # 缩短批次时间（使用配置常量）
            shortened_duration = original_duration * OptimizationConfig.TIME_REDUCTION_FACTOR
            
            step["t_start_h"] = current_time
            step["t_end_h"] = current_time + shortened_duration
            
            # 更新commands时间
            for cmd in step.get("commands", []):
                cmd["t_start_h"] = current_time
                cmd["t_end_h"] = current_time + shortened_duration
            
            current_time += shortened_duration
        
        # 策略2：使用全部水泵并行
        available_pumps = constraints.get("available_pumps", [])
        if available_pumps:
            scenario["pumps_used"] = available_pumps
        
        # 重新计算总时长和成本
        total_duration = sum(step.get("t_end_h", 0) - step.get("t_start_h", 0) for step in steps)
        
        pump_info = plan.get("calc", {}).get("pump", {})
        power_kw = pump_info.get("power_kw", OptimizationConfig.DEFAULT_PUMP_POWER_KW)
        power_kw = power_kw * len(available_pumps) if available_pumps else power_kw
        electricity_price = pump_info.get("electricity_price", OptimizationConfig.DEFAULT_ELECTRICITY_PRICE)
        
        total_cost = total_duration * power_kw * electricity_price
        
        scenario["total_eta_h"] = total_duration
        scenario["total_electricity_cost"] = total_cost
        scenario["description"] = f"通过使用全部水泵并行作业，缩短总作业时间到{total_duration:.1f}小时"
        
        return scenario
    
    def _optimize_balanced(self, base_scenario: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        """均衡优化"""
        scenario = copy.deepcopy(base_scenario)
        
        plan = scenario.get("plan", {})
        steps = plan.get("steps", [])
        
        # 获取电价信息（使用配置常量作为默认值）
        electricity_prices = constraints.get("electricity_price_schedule", {
            "peak": {
                "hours": OptimizationConfig.DEFAULT_PEAK_HOURS, 
                "price": OptimizationConfig.DEFAULT_PEAK_PRICE
            },
            "valley": {
                "hours": OptimizationConfig.DEFAULT_VALLEY_HOURS, 
                "price": OptimizationConfig.DEFAULT_VALLEY_PRICE
            }
        })
        
        # 策略：保持原有时间，优化时段分配
        valley_start = OptimizationConfig.DEFAULT_VALLEY_START
        current_time = valley_start
        
        for step in steps:
            original_duration = step.get("t_end_h", 0) - step.get("t_start_h", 0)
            
            step["t_start_h"] = current_time
            step["t_end_h"] = current_time + original_duration
            
            # 更新commands时间
            for cmd in step.get("commands", []):
                cmd["t_start_h"] = current_time
                cmd["t_end_h"] = current_time + original_duration
            
            current_time += original_duration
        
        # 使用中等数量水泵
        available_pumps = constraints.get("available_pumps", [])
        if available_pumps and len(available_pumps) > 1:
            scenario["pumps_used"] = available_pumps[:len(available_pumps)//2 + 1]
        
        # 重新计算
        total_duration = sum(step.get("t_end_h", 0) - step.get("t_start_h", 0) for step in steps)
        
        pump_info = plan.get("calc", {}).get("pump", {})
        power_kw = pump_info.get("power_kw", OptimizationConfig.DEFAULT_PUMP_POWER_KW)
        
        # 【修复】使用实际的低谷电价，而不是硬编码的折扣
        valley_price = electricity_prices["valley"]["price"]
        peak_price = electricity_prices["peak"]["price"]
        # 均衡方案：使用混合电价策略（60%低谷+40%峰谷平均）
        electricity_price = valley_price * 0.6 + (valley_price + peak_price) / 2 * 0.4
        
        total_cost = total_duration * power_kw * electricity_price
        
        scenario["total_eta_h"] = total_duration
        scenario["total_electricity_cost"] = total_cost
        scenario["description"] = "综合考虑时间和成本，安排在低谷期执行，使用适中的水泵组合"
        
        return scenario
    
    def _optimize_off_peak(self, base_scenario: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        """避峰用电优化 - 修复时段硬编码"""
        scenario = copy.deepcopy(base_scenario)
        
        electricity_prices = constraints.get("electricity_price_schedule", {
            "peak": {
                "hours": OptimizationConfig.DEFAULT_PEAK_HOURS,
                "price": OptimizationConfig.DEFAULT_PEAK_PRICE
            },
            "valley": {
                "hours": OptimizationConfig.DEFAULT_VALLEY_HOURS,
                "price": OptimizationConfig.DEFAULT_VALLEY_PRICE
            }
        })
        
        plan = scenario.get("plan", {})
        steps = plan.get("steps", [])
        
        # 【修复】根据电价配置动态生成低谷时段，而非硬编码
        peak_hours = set(electricity_prices["peak"]["hours"])
        valley_hours = set(electricity_prices["valley"]["hours"])
        
        # 将低谷小时转换为连续时段
        valley_periods = self._calculate_valley_periods(valley_hours, peak_hours)
        
        period_idx = 0
        current_time = valley_periods[period_idx][0]
        
        for step in steps:
            original_duration = step.get("t_end_h", 0) - step.get("t_start_h", 0)
            
            # 检查是否超出当前时段
            if current_time + original_duration > valley_periods[period_idx][1]:
                # 切换到下一个时段
                period_idx = (period_idx + 1) % len(valley_periods)
                current_time = valley_periods[period_idx][0]
            
            step["t_start_h"] = current_time
            step["t_end_h"] = current_time + original_duration
            
            # 更新commands时间
            for cmd in step.get("commands", []):
                cmd["t_start_h"] = current_time
                cmd["t_end_h"] = current_time + original_duration
            
            current_time += original_duration
        
        # 重新计算
        total_duration = sum(step.get("t_end_h", 0) - step.get("t_start_h", 0) for step in steps)
        
        pump_info = plan.get("calc", {}).get("pump", {})
        power_kw = pump_info.get("power_kw", OptimizationConfig.DEFAULT_PUMP_POWER_KW)
        electricity_price = electricity_prices["valley"]["price"]
        
        total_cost = total_duration * power_kw * electricity_price
        
        scenario["total_eta_h"] = total_duration
        scenario["total_electricity_cost"] = total_cost
        scenario["description"] = "完全避开用电高峰期，分多个低谷时段执行"
        
        return scenario
    
    def _optimize_water_saving(self, base_scenario: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        """节水优化"""
        scenario = copy.deepcopy(base_scenario)
        
        plan = scenario.get("plan", {})
        steps = plan.get("steps", [])
        
        # 策略：延长灌溉时间，降低流量，提高水分渗透率
        current_time = 0.0
        for step in steps:
            original_duration = step.get("t_end_h", 0) - step.get("t_start_h", 0)
            
            # 延长时间（使用配置常量）
            extended_duration = original_duration * OptimizationConfig.WATER_SAVING_EXTENSION_FACTOR
            
            step["t_start_h"] = current_time
            step["t_end_h"] = current_time + extended_duration
            
            # 更新commands时间
            for cmd in step.get("commands", []):
                cmd["t_start_h"] = current_time
                cmd["t_end_h"] = current_time + extended_duration
            
            current_time += extended_duration
        
        # 重新计算
        total_duration = sum(step.get("t_end_h", 0) - step.get("t_start_h", 0) for step in steps)
        
        pump_info = plan.get("calc", {}).get("pump", {})
        power_kw = pump_info.get("power_kw", OptimizationConfig.DEFAULT_PUMP_POWER_KW)
        electricity_price = pump_info.get("electricity_price", OptimizationConfig.DEFAULT_ELECTRICITY_PRICE)
        
        total_cost = total_duration * power_kw * electricity_price
        
        scenario["total_eta_h"] = total_duration
        scenario["total_electricity_cost"] = total_cost
        scenario["water_efficiency"] = 0.95  # 假设提高5%的水分利用率
        scenario["description"] = "通过延长灌溉时间、降低流量，提高水分渗透率和利用效率"
        
        return scenario
    
    def _generate_comparison(self, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成方案对比分析"""
        if not scenarios:
            return {}
        
        costs = [s.get("total_electricity_cost", 0) for s in scenarios]
        times = [s.get("total_eta_h", 0) for s in scenarios]
        
        # 找出最佳方案
        min_cost_idx = costs.index(min(costs)) if costs else 0
        min_time_idx = times.index(min(times)) if times else 0
        
        # 计算均衡分数（归一化后的成本和时间加权平均）
        balance_scores = []
        if costs and times:
            max_cost = max(costs)
            max_time = max(times)
            
            for cost, time in zip(costs, times):
                normalized_cost = cost / max_cost if max_cost > 0 else 0
                normalized_time = time / max_time if max_time > 0 else 0
                balance_score = (normalized_cost + normalized_time) / 2
                balance_scores.append(balance_score)
            
            best_balance_idx = balance_scores.index(min(balance_scores))
        else:
            best_balance_idx = 0
        
        return {
            "cost_range": {
                "min": min(costs) if costs else 0,
                "max": max(costs) if costs else 0,
                "best_scenario": scenarios[min_cost_idx]["name"] if scenarios else ""
            },
            "time_range": {
                "min": min(times) if times else 0,
                "max": max(times) if times else 0,
                "best_scenario": scenarios[min_time_idx]["name"] if scenarios else ""
            },
            "recommended": scenarios[best_balance_idx]["name"] if scenarios and balance_scores else "",
            "total_scenarios": len(scenarios)
        }
    
    def _get_plan_summary(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """获取计划摘要"""
        plan = scenario.get("plan", {})
        batches = plan.get("batches", [])
        
        total_fields = sum(len(b.get("fields", [])) for b in batches)
        total_area = sum(b.get("area_mu", 0) for b in batches)
        
        return {
            "total_batches": len(batches),
            "total_fields": total_fields,
            "total_area_mu": total_area,
            "original_cost": scenario.get("total_electricity_cost", 0),
            "original_duration": scenario.get("total_eta_h", 0)
        }

