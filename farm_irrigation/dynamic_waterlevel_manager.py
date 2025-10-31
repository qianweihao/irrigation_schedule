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
    from waterlevel_api import fetch_waterlevels
except ImportError:
    try:
        from mock_waterlevel_api import fetch_waterlevels
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
        self.config_data: Dict[str, Any] = {}
        
        # 加载配置和缓存
        self._load_config()
        self._load_cache()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
                logger.info(f"配置文件加载成功: {self.config_path}")
            else:
                logger.warning(f"配置文件不存在: {self.config_path}")
                self.config_data = {}
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.config_data = {}
    
    def _load_cache(self):
        """加载缓存数据"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                # 重建历史数据
                for field_id, field_data in cache_data.get("fields", {}).items():
                    history = FieldWaterLevelHistory(field_id=field_id)
                    
                    for reading_data in field_data.get("readings", []):
                        reading = WaterLevelReading(
                            field_id=field_id,
                            water_level_mm=reading_data["water_level_mm"],
                            timestamp=datetime.fromisoformat(reading_data["timestamp"]),
                            source=WaterLevelSource(reading_data["source"]),
                            quality=WaterLevelQuality(reading_data.get("quality", "good")),
                            confidence=reading_data.get("confidence", 1.0),
                            metadata=reading_data.get("metadata", {})
                        )
                        history.add_reading(reading)
                    
                    self.field_histories[field_id] = history
                
                logger.info(f"缓存数据加载成功: {len(self.field_histories)} 个田块")
            else:
                logger.info("缓存文件不存在，将创建新的缓存")
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            self.field_histories = {}
    
    def _save_cache(self):
        """保存缓存数据"""
        try:
            cache_data = {
                "last_updated": datetime.now().isoformat(),
                "fields": {}
            }
            
            for field_id, history in self.field_histories.items():
                field_data = {
                    "last_updated": history.last_updated.isoformat() if history.last_updated else None,
                    "readings": []
                }
                
                for reading in history.readings:
                    reading_data = {
                        "water_level_mm": reading.water_level_mm,
                        "timestamp": reading.timestamp.isoformat(),
                        "source": reading.source.value,
                        "quality": reading.quality.value,
                        "confidence": reading.confidence,
                        "metadata": reading.metadata
                    }
                    field_data["readings"].append(reading_data)
                
                cache_data["fields"][field_id] = field_data
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            logger.debug("缓存数据保存成功")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    async def fetch_latest_water_levels(self, farm_id: str, field_ids: Optional[List[str]] = None) -> Dict[str, WaterLevelReading]:
        """
        获取最新水位数据
        
        Args:
            farm_id: 农场ID
            field_ids: 指定田块ID列表，None表示获取所有田块
            
        Returns:
            Dict[str, WaterLevelReading]: 田块ID到水位读数的映射
        """
        logger.info(f"开始获取农场 {farm_id} 的最新水位数据")
        
        latest_readings = {}
        
        # 1. 尝试从API获取实时数据
        api_readings = await self._fetch_from_api(farm_id, field_ids)
        latest_readings.update(api_readings)
        
        # 2. 对于API未获取到的田块，尝试使用缓存数据
        if field_ids:
            missing_fields = set(field_ids) - set(latest_readings.keys())
        else:
            # 从配置文件获取所有田块ID
            all_field_ids = self._get_all_field_ids()
            missing_fields = set(all_field_ids) - set(latest_readings.keys())
        
        for field_id in missing_fields:
            cached_reading = self._get_cached_reading(field_id)
            if cached_reading and cached_reading.is_valid():
                latest_readings[field_id] = cached_reading
        
        # 3. 对于仍然缺失的田块，使用配置文件默认值
        still_missing = missing_fields - set(latest_readings.keys())
        for field_id in still_missing:
            config_reading = self._get_config_reading(field_id)
            if config_reading:
                latest_readings[field_id] = config_reading
        
        # 4. 更新历史记录
        for field_id, reading in latest_readings.items():
            self._add_reading_to_history(field_id, reading)
        
        # 5. 保存缓存
        self._save_cache()
        
        logger.info(f"获取到 {len(latest_readings)} 个田块的水位数据")
        
        return latest_readings
    
    async def _fetch_from_api(self, farm_id: str, field_ids: Optional[List[str]] = None) -> Dict[str, WaterLevelReading]:
        """从API获取水位数据"""
        api_readings = {}
        
        try:
            if not callable(fetch_waterlevels):
                logger.warning("水位API不可用")
                return api_readings
            
            # 调用API
            realtime_rows = fetch_waterlevels(farm_id)
            
            if not realtime_rows:
                logger.warning("API返回空数据")
                return api_readings
            
            current_time = datetime.now()
            
            for row in realtime_rows:
                field_id = self._extract_field_id(row)
                water_level = self._extract_water_level(row)
                
                if field_id and water_level is not None:
                    # 如果指定了田块列表，只处理指定的田块
                    if field_ids and field_id not in field_ids:
                        continue
                    
                    # 创建读数对象
                    reading = WaterLevelReading(
                        field_id=field_id,
                        water_level_mm=water_level,
                        timestamp=current_time,
                        source=WaterLevelSource.API,
                        quality=self._assess_quality(water_level, current_time, WaterLevelSource.API),
                        confidence=0.9,  # API数据置信度较高
                        metadata={"raw_data": row}
                    )
                    
                    if reading.is_valid():
                        api_readings[field_id] = reading
                    else:
                        logger.warning(f"田块 {field_id} 的API数据无效: {water_level}")
            
            logger.info(f"从API获取到 {len(api_readings)} 个有效水位数据")
            
        except Exception as e:
            logger.error(f"从API获取水位数据失败: {e}")
        
        return api_readings
    
    def _extract_field_id(self, row: Dict[str, Any]) -> Optional[str]:
        """从API返回的行数据中提取田块ID"""
        for key in ["field_id", "sectionID", "id", "F_id"]:
            if key in row and row[key]:
                return str(row[key])
        return None
    
    def _extract_water_level(self, row: Dict[str, Any]) -> Optional[float]:
        """从API返回的行数据中提取水位值"""
        for key in ["waterlevel_mm", "water_level", "wl_mm", "level"]:
            if key in row and row[key] is not None:
                try:
                    return float(row[key])
                except (ValueError, TypeError):
                    continue
        return None
    
    def _get_all_field_ids(self) -> List[str]:
        """从配置文件获取所有田块ID"""
        field_ids = []
        
        fields = self.config_data.get("fields", [])
        for field in fields:
            field_id = field.get("id")
            if field_id:
                field_ids.append(str(field_id))
        
        return field_ids
    
    def _get_cached_reading(self, field_id: str) -> Optional[WaterLevelReading]:
        """获取缓存的水位读数"""
        if field_id in self.field_histories:
            history = self.field_histories[field_id]
            latest = history.get_latest_reading()
            
            if latest and latest.age_hours() <= self.max_cache_age_hours:
                # 更新质量评估（基于年龄）
                latest.quality = self._assess_quality(
                    latest.water_level_mm, 
                    latest.timestamp, 
                    WaterLevelSource.CACHED
                )
                return latest
        
        return None
    
    def _get_config_reading(self, field_id: str) -> Optional[WaterLevelReading]:
        """从配置文件获取默认水位读数"""
        fields = self.config_data.get("fields", [])
        
        for field in fields:
            if str(field.get("id")) == field_id:
                wl_mm = field.get("wl_mm")
                if wl_mm is not None:
                    try:
                        water_level = float(wl_mm)
                        reading = WaterLevelReading(
                            field_id=field_id,
                            water_level_mm=water_level,
                            timestamp=datetime.now(),
                            source=WaterLevelSource.CONFIG,
                            quality=WaterLevelQuality.FAIR,
                            confidence=0.5,  # 配置文件数据置信度较低
                            metadata={"from_config": True}
                        )
                        return reading
                    except (ValueError, TypeError):
                        pass
        
        return None
    
    def _assess_quality(self, water_level: float, timestamp: datetime, source: WaterLevelSource) -> WaterLevelQuality:
        """评估水位数据质量"""
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600
        
        # 检查水位范围
        if (water_level < self.quality_thresholds["min_water_level"] or 
            water_level > self.quality_thresholds["max_water_level"]):
            return WaterLevelQuality.INVALID
        
        # 基于数据源和年龄评估质量
        if source == WaterLevelSource.API:
            if age_hours <= self.quality_thresholds["excellent_max_age_hours"]:
                return WaterLevelQuality.EXCELLENT
            elif age_hours <= self.quality_thresholds["good_max_age_hours"]:
                return WaterLevelQuality.GOOD
            elif age_hours <= self.quality_thresholds["fair_max_age_hours"]:
                return WaterLevelQuality.FAIR
            else:
                return WaterLevelQuality.POOR
        
        elif source == WaterLevelSource.CACHED:
            if age_hours <= self.quality_thresholds["good_max_age_hours"]:
                return WaterLevelQuality.GOOD
            elif age_hours <= self.quality_thresholds["fair_max_age_hours"]:
                return WaterLevelQuality.FAIR
            else:
                return WaterLevelQuality.POOR
        
        elif source == WaterLevelSource.CONFIG:
            return WaterLevelQuality.FAIR
        
        else:
            return WaterLevelQuality.GOOD
    
    def _add_reading_to_history(self, field_id: str, reading: WaterLevelReading):
        """添加读数到历史记录"""
        if field_id not in self.field_histories:
            self.field_histories[field_id] = FieldWaterLevelHistory(field_id=field_id)
        
        self.field_histories[field_id].add_reading(reading)
    
    def get_water_level_summary(self, field_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        获取水位数据摘要
        
        Args:
            field_ids: 指定田块ID列表
            
        Returns:
            Dict[str, Any]: 水位摘要信息
        """
        summary = {
            "total_fields": 0,
            "fields_with_data": 0,
            "quality_distribution": {q.value: 0 for q in WaterLevelQuality},
            "source_distribution": {s.value: 0 for s in WaterLevelSource},
            "fields": {}
        }
        
        target_fields = field_ids or list(self.field_histories.keys())
        summary["total_fields"] = len(target_fields)
        
        for field_id in target_fields:
            if field_id in self.field_histories:
                history = self.field_histories[field_id]
                latest = history.get_latest_reading()
                
                if latest:
                    summary["fields_with_data"] += 1
                    summary["quality_distribution"][latest.quality.value] += 1
                    summary["source_distribution"][latest.source.value] += 1
                    
                    # 获取趋势
                    trend = history.get_trend(hours=24)
                    
                    summary["fields"][field_id] = {
                        "water_level_mm": latest.water_level_mm,
                        "age_hours": latest.age_hours(),
                        "quality": latest.quality.value,
                        "source": latest.source.value,
                        "confidence": latest.confidence,
                        "trend_mm_per_hour": trend,
                        "readings_count": len(history.readings)
                    }
        
        return summary
    
    def add_manual_reading(self, field_id: str, water_level_mm: float, confidence: float = 0.8) -> bool:
        """
        添加手动水位读数
        
        Args:
            field_id: 田块ID
            water_level_mm: 水位（毫米）
            confidence: 置信度
            
        Returns:
            bool: 是否添加成功
        """
        try:
            reading = WaterLevelReading(
                field_id=field_id,
                water_level_mm=water_level_mm,
                timestamp=datetime.now(),
                source=WaterLevelSource.MANUAL,
                quality=self._assess_quality(water_level_mm, datetime.now(), WaterLevelSource.MANUAL),
                confidence=confidence,
                metadata={"manual_input": True}
            )
            
            if reading.is_valid():
                self._add_reading_to_history(field_id, reading)
                self._save_cache()
                logger.info(f"手动添加田块 {field_id} 水位读数: {water_level_mm}mm")
                return True
            else:
                logger.warning(f"手动水位读数无效: 田块 {field_id}, 水位 {water_level_mm}mm")
                return False
                
        except Exception as e:
            logger.error(f"添加手动水位读数失败: {e}")
            return False
    
    def get_field_trend_analysis(self, field_id: str, hours: int = 48) -> Optional[Dict[str, Any]]:
        """
        获取田块水位趋势分析
        
        Args:
            field_id: 田块ID
            hours: 分析时间窗口（小时）
            
        Returns:
            Dict[str, Any]: 趋势分析结果
        """
        if field_id not in self.field_histories:
            return None
        
        history = self.field_histories[field_id]
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_readings = [r for r in history.readings if r.timestamp >= cutoff_time and r.is_valid()]
        
        if len(recent_readings) < 2:
            return None
        
        # 计算统计信息
        levels = [r.water_level_mm for r in recent_readings]
        
        analysis = {
            "field_id": field_id,
            "analysis_period_hours": hours,
            "readings_count": len(recent_readings),
            "latest_level_mm": levels[0],
            "min_level_mm": min(levels),
            "max_level_mm": max(levels),
            "avg_level_mm": sum(levels) / len(levels),
            "level_range_mm": max(levels) - min(levels),
            "trend_mm_per_hour": history.get_trend(hours),
            "data_quality": recent_readings[0].quality.value,
            "last_updated": recent_readings[0].timestamp.isoformat()
        }
        
        # 趋势判断
        trend = analysis["trend_mm_per_hour"]
        if trend is not None:
            if trend > 1.0:
                analysis["trend_description"] = "快速上升"
            elif trend > 0.1:
                analysis["trend_description"] = "缓慢上升"
            elif trend > -0.1:
                analysis["trend_description"] = "基本稳定"
            elif trend > -1.0:
                analysis["trend_description"] = "缓慢下降"
            else:
                analysis["trend_description"] = "快速下降"
        else:
            analysis["trend_description"] = "数据不足"
        
        return analysis

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