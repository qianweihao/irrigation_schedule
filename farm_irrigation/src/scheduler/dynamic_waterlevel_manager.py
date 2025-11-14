#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态水位管理器

功能：
1. 在批次执行前获取最新水位数据
2. 处理水位数据的验证和清洗
3. 管理水位数据的缓存和历史记录
4. 提供水位变化分析和预警
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

# 导入水位API
try:
    from src.api.waterlevel_api import fetch_waterlevels
except ImportError:
    try:
        from src.api.mock_waterlevel_api import fetch_waterlevels
    except ImportError:
        fetch_waterlevels = None

# 配置日志
logger = logging.getLogger(__name__)

class WaterLevelSource(Enum):
    """水位数据来源"""
    API = "api"                    # API获取
    MANUAL = "manual"              # 手动输入
    CONFIG = "config"              # 配置文件
    INTERPOLATED = "interpolated"  # 插值计算
    CACHED = "cached"              # 缓存数据

class WaterLevelQuality(Enum):
    """水位数据质量"""
    EXCELLENT = "excellent"  # 优秀（实时、准确）
    GOOD = "good"           # 良好（较新、可靠）
    FAIR = "fair"           # 一般（稍旧、基本可用）
    POOR = "poor"           # 较差（过旧、不太可靠）
    INVALID = "invalid"     # 无效（错误、不可用）

@dataclass
class WaterLevelReading:
    """水位读数"""
    field_id: str
    water_level_mm: float
    timestamp: datetime
    source: WaterLevelSource
    quality: WaterLevelQuality = WaterLevelQuality.GOOD
    confidence: float = 1.0  # 置信度 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_valid(self) -> bool:
        """检查读数是否有效"""
        return (
            self.quality != WaterLevelQuality.INVALID and
            0 <= self.water_level_mm <= 1000 and  # 合理的水位范围
            self.confidence > 0
        )
    
    def age_hours(self) -> float:
        """获取数据年龄（小时）"""
        return (datetime.now() - self.timestamp).total_seconds() / 3600

@dataclass
class FieldWaterLevelHistory:
    """田块水位历史"""
    field_id: str
    readings: List[WaterLevelReading] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    
    def add_reading(self, reading: WaterLevelReading):
        """添加新的读数"""
        self.readings.append(reading)
        self.readings.sort(key=lambda x: x.timestamp, reverse=True)  # 按时间倒序
        
        # 保留最近100条记录
        if len(self.readings) > 100:
            self.readings = self.readings[:100]
        
        self.last_updated = datetime.now()
    
    def get_latest_reading(self) -> Optional[WaterLevelReading]:
        """获取最新读数"""
        if self.readings:
            return self.readings[0]
        return None
    
    def get_trend(self, hours: int = 24) -> Optional[float]:
        """
        获取水位变化趋势
        
        Args:
            hours: 分析时间窗口（小时）
            
        Returns:
            float: 变化趋势（mm/h），正值表示上升，负值表示下降
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_readings = [r for r in self.readings if r.timestamp >= cutoff_time and r.is_valid()]
        
        if len(recent_readings) < 2:
            return None
        
        # 简单线性趋势计算
        oldest = recent_readings[-1]
        newest = recent_readings[0]
        
        time_diff_hours = (newest.timestamp - oldest.timestamp).total_seconds() / 3600
        if time_diff_hours == 0:
            return 0.0
        
        level_diff = newest.water_level_mm - oldest.water_level_mm
        return level_diff / time_diff_hours
    
    def get_readings_in_timeframe(self, hours: int = 24) -> List[WaterLevelReading]:
        """
        获取指定时间范围内的历史读数
        
        Args:
            hours: 时间窗口（小时）
            
        Returns:
            List[WaterLevelReading]: 时间范围内的读数列表，按时间倒序排列
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [r for r in self.readings if r.timestamp >= cutoff_time]

class DynamicWaterLevelManager:
    """动态水位管理器"""
    
    def __init__(self, 
                 config_path: str = "config.json",
                 cache_file: str = "waterlevel_cache.json",
                 max_cache_age_hours: int = 24,
                 quality_thresholds: Optional[Dict[str, float]] = None):
        """
        初始化水位管理器
        
        Args:
            config_path: 配置文件路径
            cache_file: 缓存文件路径
            max_cache_age_hours: 缓存最大年龄（小时）
            quality_thresholds: 质量阈值配置
        """
        self.config_path = Path(config_path)
        self.cache_file = Path(cache_file)
        self.max_cache_age_hours = max_cache_age_hours
        
        # 质量阈值配置
        self.quality_thresholds = quality_thresholds or {
            "excellent_max_age_hours": 1,    # 1小时内为优秀
            "good_max_age_hours": 6,         # 6小时内为良好
            "fair_max_age_hours": 24,        # 24小时内为一般
            "min_confidence": 0.5,           # 最小置信度
            "max_water_level": 500,          # 最大合理水位
            "min_water_level": 0             # 最小合理水位
        }
        
        # 数据存储
        self.field_histories: Dict[str, FieldWaterLevelHistory] = {}
        self.last_api_call: Optional[datetime] = None
        self.api_call_interval_minutes = 5  # API调用间隔
        
        # 田块ID映射表（数字ID -> SGF格式）
        self.field_id_mapping: Dict[str, str] = {}
        
        # 加载田块ID映射
        self._load_field_id_mapping()
        
        # 加载缓存数据
        self._load_cache()
    
    def _load_field_id_mapping(self):
        """从GeoJSON文件加载田块ID映射"""
        try:
            # 获取项目根目录（从 src/scheduler/ 向上两级）
            project_root = Path(__file__).parent.parent.parent
            
            # 尝试从labeled_output目录加载
            geojson_path = project_root / "data" / "labeled_output" / "fields_labeled.geojson"
            
            if not geojson_path.exists():
                # 尝试从gzp_farm目录加载
                geojson_path = project_root / "data" / "gzp_farm" / "fields_labeled.geojson"
            
            if geojson_path.exists():
                with open(geojson_path, 'r', encoding='utf-8') as f:
                    geojson_data = json.load(f)
                
                # 提取映射关系
                for feature in geojson_data.get("features", []):
                    props = feature.get("properties", {})
                    numeric_id = str(props.get("id", ""))
                    sgf_id = props.get("F_id", "")
                    
                    if numeric_id and sgf_id:
                        self.field_id_mapping[numeric_id] = sgf_id
                
                logger.info(f"加载了 {len(self.field_id_mapping)} 个田块ID映射")
            else:
                logger.warning(f"未找到田块GeoJSON文件: {geojson_path}")
                
        except Exception as e:
            logger.error(f"加载田块ID映射失败: {e}")
    
    def _load_cache(self):
        """加载缓存数据"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                # 恢复田块历史数据
                for field_id, history_data in cache_data.get("field_histories", {}).items():
                    history = FieldWaterLevelHistory(field_id=field_id)
                    
                    for reading_data in history_data.get("readings", []):
                        reading = WaterLevelReading(
                            field_id=reading_data["field_id"],
                            water_level_mm=reading_data["water_level_mm"],
                            timestamp=datetime.fromisoformat(reading_data["timestamp"]),
                            source=WaterLevelSource(reading_data["source"]),
                            quality=WaterLevelQuality(reading_data["quality"]),
                            confidence=reading_data.get("confidence", 1.0),
                            metadata=reading_data.get("metadata", {})
                        )
                        history.add_reading(reading)
                    
                    self.field_histories[field_id] = history
                
                logger.info(f"从缓存加载了 {len(self.field_histories)} 个田块的水位历史")
                
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
    
    def _save_cache(self):
        """保存缓存数据"""
        try:
            cache_data = {
                "field_histories": {},
                "last_updated": datetime.now().isoformat()
            }
            
            # 保存田块历史数据
            for field_id, history in self.field_histories.items():
                cache_data["field_histories"][field_id] = {
                    "field_id": field_id,
                    "readings": [
                        {
                            "field_id": reading.field_id,
                            "water_level_mm": reading.water_level_mm,
                            "timestamp": reading.timestamp.isoformat(),
                            "source": reading.source.value,
                            "quality": reading.quality.value,
                            "confidence": reading.confidence,
                            "metadata": reading.metadata
                        }
                        for reading in history.readings[:50]  # 只保存最近50条
                    ],
                    "last_updated": history.last_updated.isoformat() if history.last_updated else None
                }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
                
            logger.debug(f"缓存已保存到 {self.cache_file}")
            
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    async def fetch_latest_water_levels(self, farm_id: str, field_ids: Optional[List[str]] = None) -> Dict[str, WaterLevelReading]:
        """
        获取最新水位数据
        
        Args:
            farm_id: 农场ID
            field_ids: 指定田块ID列表，如果为None则获取所有田块
            
        Returns:
            Dict[str, WaterLevelReading]: 田块ID到水位读数的映射
        """
        readings = {}
        
        try:
            # 检查API调用间隔
            now = datetime.now()
            if (self.last_api_call and 
                (now - self.last_api_call).total_seconds() < self.api_call_interval_minutes * 60):
                logger.debug("API调用间隔未到，使用缓存数据")
                return self._get_cached_readings(field_ids)
            
            # 调用水位API
            if callable(fetch_waterlevels):
                api_data = fetch_waterlevels(farm_id)
                self.last_api_call = now
                
                if api_data:
                    for row in api_data:
                        field_id = str(row.get("field_id") or row.get("sectionID") or row.get("id", ""))
                        water_level = row.get("waterlevel_mm") or row.get("water_level")
                        
                        if field_id and water_level is not None:
                            # 过滤指定田块
                            if field_ids and field_id not in field_ids:
                                continue
                            
                            try:
                                water_level_mm = float(water_level)
                                
                                # 创建水位读数
                                reading = WaterLevelReading(
                                    field_id=field_id,
                                    water_level_mm=water_level_mm,
                                    timestamp=now,
                                    source=WaterLevelSource.API,
                                    quality=self._assess_quality(water_level_mm, now),
                                    confidence=self._calculate_confidence(row),
                                    metadata=row
                                )
                                
                                # 验证读数
                                if reading.is_valid():
                                    readings[field_id] = reading
                                    
                                    # 添加到历史记录
                                    if field_id not in self.field_histories:
                                        self.field_histories[field_id] = FieldWaterLevelHistory(field_id)
                                    
                                    self.field_histories[field_id].add_reading(reading)
                                
                            except (ValueError, TypeError) as e:
                                logger.warning(f"田块 {field_id} 水位数据无效: {water_level}, 错误: {e}")
                
                logger.info(f"从API获取到 {len(readings)} 个有效水位读数")
                
                # 保存缓存
                self._save_cache()
                
            else:
                logger.warning("水位API不可用")
                return self._get_cached_readings(field_ids)
                
        except Exception as e:
            logger.error(f"获取水位数据失败: {e}")
            return self._get_cached_readings(field_ids)
        
        return readings
    
    def _get_cached_readings(self, field_ids: Optional[List[str]] = None) -> Dict[str, WaterLevelReading]:
        """获取缓存的水位读数"""
        readings = {}
        
        for field_id, history in self.field_histories.items():
            if field_ids and field_id not in field_ids:
                continue
            
            latest_reading = history.get_latest_reading()
            if latest_reading and latest_reading.is_valid():
                # 检查数据年龄
                age_hours = latest_reading.age_hours()
                if age_hours <= self.max_cache_age_hours:
                    readings[field_id] = latest_reading
        
        return readings
    
    def _assess_quality(self, water_level_mm: float, timestamp: datetime) -> WaterLevelQuality:
        """评估水位数据质量"""
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600
        
        # 基于数据年龄评估质量
        if age_hours <= self.quality_thresholds["excellent_max_age_hours"]:
            return WaterLevelQuality.EXCELLENT
        elif age_hours <= self.quality_thresholds["good_max_age_hours"]:
            return WaterLevelQuality.GOOD
        elif age_hours <= self.quality_thresholds["fair_max_age_hours"]:
            return WaterLevelQuality.FAIR
        else:
            return WaterLevelQuality.POOR
    
    def _calculate_confidence(self, api_row: Dict[str, Any]) -> float:
        """计算数据置信度"""
        confidence = 1.0
        
        # 基于数据完整性调整置信度
        if not api_row.get("timestamp"):
            confidence *= 0.8
        
        if not api_row.get("sensor_id"):
            confidence *= 0.9
        
        # 基于数据范围调整置信度
        water_level = api_row.get("waterlevel_mm") or api_row.get("water_level", 0)
        try:
            wl = float(water_level)
            if wl < 0 or wl > 500:  # 异常范围
                confidence *= 0.5
        except (ValueError, TypeError):
            confidence *= 0.3
        
        return max(confidence, 0.1)  # 最小置信度0.1
    
    def get_field_water_level(self, field_id: str) -> Optional[WaterLevelReading]:
        """
        获取指定田块的最新水位
        
        Args:
            field_id: 田块ID
            
        Returns:
            Optional[WaterLevelReading]: 水位读数，如果没有则返回None
        """
        if field_id in self.field_histories:
            return self.field_histories[field_id].get_latest_reading()
        return None
    
    def get_water_level_trend(self, field_id: str, hours: int = 24) -> Optional[float]:
        """
        获取田块水位变化趋势
        
        Args:
            field_id: 田块ID
            hours: 分析时间窗口（小时）
            
        Returns:
            Optional[float]: 变化趋势（mm/h），正值表示上升，负值表示下降
        """
        if field_id in self.field_histories:
            return self.field_histories[field_id].get_trend(hours)
        return None
    
    def add_manual_reading(self, field_id: str, water_level_mm: float, 
                          confidence: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        添加手动水位读数
        
        Args:
            field_id: 田块ID
            water_level_mm: 水位（毫米）
            confidence: 置信度
            metadata: 元数据
            
        Returns:
            bool: 是否添加成功
        """
        try:
            reading = WaterLevelReading(
                field_id=field_id,
                water_level_mm=water_level_mm,
                timestamp=datetime.now(),
                source=WaterLevelSource.MANUAL,
                quality=WaterLevelQuality.GOOD,
                confidence=confidence,
                metadata=metadata or {}
            )
            
            if reading.is_valid():
                if field_id not in self.field_histories:
                    self.field_histories[field_id] = FieldWaterLevelHistory(field_id)
                
                self.field_histories[field_id].add_reading(reading)
                self._save_cache()
                
                logger.info(f"手动添加田块 {field_id} 水位读数: {water_level_mm}mm")
                return True
            else:
                logger.warning(f"无效的水位读数: 田块 {field_id}, 水位 {water_level_mm}mm")
                return False
                
        except Exception as e:
            logger.error(f"添加手动水位读数失败: {e}")
            return False
    
    def get_quality_summary(self) -> Dict[str, int]:
        """
        获取数据质量摘要
        
        Returns:
            Dict[str, int]: 各质量等级的数据数量
        """
        summary = {quality.value: 0 for quality in WaterLevelQuality}
        
        for history in self.field_histories.values():
            latest_reading = history.get_latest_reading()
            if latest_reading:
                summary[latest_reading.quality.value] += 1
        
        return summary
    
    def cleanup_old_data(self, max_age_days: int = 30):
        """
        清理过期数据
        
        Args:
            max_age_days: 最大保留天数
        """
        cutoff_time = datetime.now() - timedelta(days=max_age_days)
        cleaned_count = 0
        
        for history in self.field_histories.values():
            original_count = len(history.readings)
            history.readings = [r for r in history.readings if r.timestamp >= cutoff_time]
            cleaned_count += original_count - len(history.readings)
        
        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 条过期水位数据")
            self._save_cache()
    
    def get_water_level_summary(self, field_ids: Optional[List[str]] = None, use_sgf_format: bool = False) -> Dict[str, Any]:
        """
        获取水位数据摘要
        
        Args:
            field_ids: 指定田块ID列表，如果为None则返回所有田块的摘要
            use_sgf_format: 是否使用SGF格式的田块ID（如S1-G2-F03），默认False使用数字ID
            
        Returns:
            Dict[str, Any]: 水位摘要数据
        """
        try:
            # 确定要统计的田块
            target_fields = field_ids if field_ids else list(self.field_histories.keys())
            
            summary = {
                "total_fields": len(target_fields),
                "fields_with_data": 0,
                "fields_without_data": [],
                "quality_distribution": {quality.value: 0 for quality in WaterLevelQuality},
                "source_distribution": {source.value: 0 for source in WaterLevelSource},
                "field_details": {},
                "last_updated": datetime.now().isoformat()
            }
            
            for field_id in target_fields:
                if field_id in self.field_histories:
                    history = self.field_histories[field_id]
                    latest_reading = history.get_latest_reading()
                    
                    if latest_reading:
                        summary["fields_with_data"] += 1
                        summary["quality_distribution"][latest_reading.quality.value] += 1
                        summary["source_distribution"][latest_reading.source.value] += 1
                        
                        # 计算数据年龄
                        age_hours = (datetime.now() - latest_reading.timestamp).total_seconds() / 3600
                        
                        # 决定使用哪种格式的田块ID
                        display_field_id = field_id
                        if use_sgf_format and field_id in self.field_id_mapping:
                            display_field_id = self.field_id_mapping[field_id]
                        
                        field_detail = {
                            "water_level_mm": latest_reading.water_level_mm,
                            "quality": latest_reading.quality.value,
                            "source": latest_reading.source.value,
                            "confidence": latest_reading.confidence,
                            "age_hours": round(age_hours, 2),
                            "timestamp": latest_reading.timestamp.isoformat(),
                            "readings_count": len(history.readings)
                        }
                        
                        # 如果使用SGF格式，同时保留原始数字ID
                        if use_sgf_format:
                            field_detail["numeric_id"] = field_id
                        
                        summary["field_details"][display_field_id] = field_detail
                    else:
                        display_field_id = field_id
                        if use_sgf_format and field_id in self.field_id_mapping:
                            display_field_id = self.field_id_mapping[field_id]
                        summary["fields_without_data"].append(display_field_id)
                else:
                    display_field_id = field_id
                    if use_sgf_format and field_id in self.field_id_mapping:
                        display_field_id = self.field_id_mapping[field_id]
                    summary["fields_without_data"].append(display_field_id)
            
            # 计算统计信息
            summary["coverage_rate"] = summary["fields_with_data"] / summary["total_fields"] if summary["total_fields"] > 0 else 0
            
            logger.info(f"生成水位摘要: {summary['fields_with_data']}/{summary['total_fields']} 个田块有数据")
            return summary
            
        except Exception as e:
            logger.error(f"生成水位摘要失败: {e}")
            return {
                "total_fields": 0,
                "fields_with_data": 0,
                "fields_without_data": [],
                "quality_distribution": {},
                "source_distribution": {},
                "field_details": {},
                "error": str(e),
                "last_updated": datetime.now().isoformat()
            }

if __name__ == "__main__":
    # 示例用法
    import asyncio
    
    async def main():
        # 创建水位管理器
        manager = DynamicWaterLevelManager(
            config_path="config.json",
            cache_file="waterlevel_cache.json",
            max_cache_age_hours=24
        )
        
        # 获取最新水位数据
        readings = await manager.fetch_latest_water_levels("gzp_farm")
        
        print(f"获取到 {len(readings)} 个田块的水位数据:")
        for field_id, reading in readings.items():
            print(f"  {field_id}: {reading.water_level_mm}mm ({reading.quality.value}, {reading.source.value})")
        
        # 获取摘要
        summary = manager.get_water_level_summary()
        print(f"\n水位数据摘要:")
        print(f"  总田块数: {summary['total_fields']}")
        print(f"  有数据田块数: {summary['fields_with_data']}")
        print(f"  质量分布: {summary['quality_distribution']}")
    
    # 运行示例
    asyncio.run(main())