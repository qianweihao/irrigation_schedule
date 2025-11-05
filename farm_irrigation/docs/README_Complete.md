# 智能农场灌溉调度系统 API 文档

## 系统概述

智能农场灌溉调度系统是一个基于实时数据的智能灌溉管理平台，支持动态执行、批次管理、水位监控和计划优化等功能。

## 统一响应格式

所有API接口均采用统一的JSON响应格式：

```json
{
  "status": "success|error",
  "message": "操作结果描述信息",
  "data": {
    // 具体的响应数据
  }
}
```

- `status`: 操作状态，`success` 表示成功，`error` 表示失败
- `message`: 操作结果的描述信息
- `data`: 具体的响应数据，根据不同接口返回不同结构

## 服务配置

### 主动态执行服务
- **服务地址**: `http://0.0.0.0:8000`
- **启动命令**: `python main_dynamic_execution_api.py`

### 集成API服务
- **服务地址**: `http://127.0.0.1:8000`
- **启动命令**: `python api_server.py`

### Web可视化服务
- **服务地址**: `http://0.0.0.0:5000`
- **启动命令**: `python web_farm_irrigation_modified.py`

---

## 一、系统管理模块

### 1.1 系统初始化功能

#### 1.1.1 系统初始化
- **请求地址**: `POST /api/system/init`
- **请求方式**: POST
- **请求参数**:
```json
{
  "farm_id": "string",
  "config_path": "string",
  "reset_data": "boolean"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "系统初始化成功",
  "data": {
    "initialization_time": "2025-01-XX 10:00:00",
    "farm_id": "13944136728576",
    "modules_loaded": ["scheduler", "waterlevel_manager", "plan_regenerator"]
  }
}
```

#### 1.1.2 系统状态查询
- **请求地址**: `GET /api/system/status`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "系统状态获取成功",
  "data": {
    "system_status": "running",
    "uptime_seconds": 3600,
    "active_modules": ["scheduler", "waterlevel_manager"],
    "memory_usage_mb": 256,
    "cpu_usage_percent": 15.5
  }
}
```

### 1.2 健康检查功能

#### 1.2.1 系统健康检查
- **请求地址**: `POST /api/system/health-check`
- **请求方式**: POST
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "系统健康检查完成",
  "data": {
    "overall_health": "healthy",
    "components": {
      "database": "healthy",
      "scheduler": "healthy",
      "waterlevel_manager": "healthy"
    },
    "check_time": "2025-01-XX 10:00:00"
  }
}
```

#### 1.2.2 API服务健康检查
- **请求地址**: `GET /api/health`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "API服务运行正常",
  "data": {
    "service": "irrigation_api",
    "version": "1.0.0",
    "timestamp": "2025-01-XX 10:00:00"
  }
}
```

---

## 二、动态执行模块

### 2.1 执行控制功能

#### 2.1.1 启动动态执行
- **请求地址**: `POST /api/execution/start`
- **请求方式**: POST
- **请求参数**:
```json
{
  "plan_file_path": "string",
  "farm_id": "string",
  "config_file_path": "string",
  "auto_start": "boolean",
  "water_level_update_interval_minutes": "integer",
  "enable_plan_regeneration": "boolean",
  "execution_mode": "string"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "动态执行启动成功",
  "data": {
    "execution_id": "exec_20250101_001",
    "scheduler_status": "running",
    "total_batches": 5,
    "current_batch": 1,
    "start_time": "2025-01-XX 10:00:00"
  }
}
```

#### 2.1.2 停止动态执行
- **请求地址**: `POST /api/execution/stop`
- **请求方式**: POST
- **请求参数**:
```json
{
  "execution_id": "string",
  "force_stop": "boolean"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "动态执行已停止",
  "data": {
    "execution_id": "exec_20250101_001",
    "stop_time": "2025-01-XX 12:00:00",
    "final_status": "stopped",
    "completed_batches": 3
  }
}
```

### 2.2 执行状态功能

#### 2.2.1 获取执行状态
- **请求地址**: `GET /api/execution/status`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "执行状态获取成功",
  "data": {
    "execution_id": "exec_20250101_001",
    "status": "running",
    "current_batch": 2,
    "total_batches": 5,
    "progress_percentage": 40.0,
    "start_time": "2025-01-XX 10:00:00",
    "estimated_completion_time": "2025-01-XX 14:00:00",
    "last_water_level_update": "2025-01-XX 11:30:00",
    "total_regenerations": 1,
    "active_fields": ["F001", "F002"],
    "completed_batches": [1]
  }
}
```

#### 2.2.2 获取执行历史
- **请求地址**: `GET /api/execution/history`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "执行历史获取成功",
  "data": {
    "total_executions": 10,
    "executions": [
      {
        "execution_id": "exec_20250101_001",
        "start_time": "2025-01-01 10:00:00",
        "end_time": "2025-01-01 14:00:00",
        "status": "completed",
        "total_batches": 5,
        "success_rate": 100.0
      }
    ]
  }
}
```

---

## 三、水位管理模块

### 3.1 水位更新功能

#### 3.1.1 更新水位数据
- **请求地址**: `POST /api/water-levels/update`
- **请求方式**: POST
- **请求参数**:
```json
{
  "farm_id": "string",
  "field_ids": ["string"],
  "force_update": "boolean"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "水位数据更新成功",
  "data": {
    "updated_fields": {
      "F001": 2.5,
      "F002": 3.1
    },
    "update_timestamp": "2025-01-XX 10:00:00",
    "data_quality_summary": {
      "valid": 2,
      "invalid": 0,
      "missing": 0
    }
  }
}
```

### 3.2 水位查询功能

#### 3.2.1 获取水位汇总
- **请求地址**: `GET /api/water-levels/summary`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "水位汇总获取成功",
  "data": {
    "total_fields": 10,
    "average_water_level": 2.8,
    "min_water_level": 1.5,
    "max_water_level": 4.2,
    "last_update": "2025-01-XX 10:00:00",
    "field_details": {
      "F001": 2.5,
      "F002": 3.1
    }
  }
}
```

#### 3.2.2 获取田块水位趋势
- **请求地址**: `GET /api/water-levels/trend/{field_id}`
- **请求方式**: GET
- **请求参数**: 
  - `field_id`: 田块ID（路径参数）
- **响应内容**:
```json
{
  "status": "success",
  "message": "田块水位趋势获取成功",
  "data": {
    "field_id": "F001",
    "trend_data": [
      {
        "timestamp": "2025-01-XX 09:00:00",
        "water_level": 2.3
      },
      {
        "timestamp": "2025-01-XX 10:00:00",
        "water_level": 2.5
      }
    ],
    "trend_analysis": {
      "direction": "increasing",
      "rate_cm_per_hour": 0.2
    }
  }
}
```

---

## 四、计划重新生成模块

### 4.1 手动重新生成功能

#### 4.1.1 手动重新生成批次
- **请求地址**: `POST /api/regeneration/manual`
- **请求方式**: POST
- **请求参数**:
```json
{
  "batch_index": "integer",
  "custom_water_levels": {
    "F001": 2.5,
    "F002": 3.1
  },
  "force_regeneration": "boolean"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "批次重新生成成功",
  "data": {
    "batch_index": 2,
    "changes_count": 3,
    "execution_time_adjustment_seconds": 300.0,
    "water_usage_adjustment_m3": 15.5,
    "change_summary": "调整了3个田块的灌溉时间，总用水量增加15.5立方米"
  }
}
```

### 4.2 重新生成查询功能

#### 4.2.1 获取重新生成汇总
- **请求地址**: `GET /api/regeneration/summary/{farm_id}`
- **请求方式**: GET
- **请求参数**:
  - `farm_id`: 农场ID（路径参数）
- **响应内容**:
```json
{
  "status": "success",
  "message": "重新生成汇总获取成功",
  "data": {
    "farm_id": "13944136728576",
    "total_regenerations": 5,
    "successful_regenerations": 4,
    "failed_regenerations": 1,
    "last_regeneration_time": "2025-01-XX 10:00:00",
    "average_improvement_percent": 12.5
  }
}
```

---

## 五、批次管理模块

### 5.1 批次查询功能

#### 5.1.1 获取批次详情
- **请求地址**: `GET /api/batches/{batch_index}/details`
- **请求方式**: GET
- **请求参数**:
  - `batch_index`: 批次索引（路径参数）
- **响应内容**:
```json
{
  "status": "success",
  "message": "批次详情获取成功",
  "data": {
    "batch_index": 1,
    "status": "completed",
    "start_time": "2025-01-XX 10:00:00",
    "end_time": "2025-01-XX 11:30:00",
    "fields": ["F001", "F002", "F003"],
    "total_water_usage_m3": 150.5,
    "execution_duration_minutes": 90
  }
}
```

#### 5.1.2 获取当前计划
- **请求地址**: `GET /api/batches/current-plan`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "当前计划获取成功",
  "data": {
    "plan_id": "plan_20250101_001",
    "total_batches": 5,
    "current_batch": 2,
    "plan_status": "executing",
    "created_time": "2025-01-XX 09:00:00",
    "estimated_completion": "2025-01-XX 14:00:00"
  }
}
```

---

## 六、灌溉计划模块

### 6.1 计划生成功能

#### 6.1.1 上传文件生成计划
- **请求地址**: `POST /api/irrigation/plan-with-upload`
- **请求方式**: POST
- **请求参数**: 
  - `file`: 上传的文件（multipart/form-data）
  - `farm_id`: 农场ID
  - `config_options`: 配置选项（JSON字符串）
- **响应内容**:
```json
{
  "status": "success",
  "message": "灌溉计划生成成功",
  "data": {
    "plan_id": "plan_20250101_001",
    "total_batches": 5,
    "total_fields": 20,
    "estimated_duration_hours": 4.5,
    "total_water_usage_m3": 500.0,
    "plan_file_path": "/e:/irrigation_schedule/farm_irrigation/output/irrigation_plan_20251101_143125.json"
  }
}
```

#### 6.1.2 多泵站场景生成
- **请求地址**: `POST /api/irrigation/multi-pump-scenarios`
- **请求方式**: POST
- **请求参数**:
```json
{
  "farm_id": "string",
  "pump_configurations": [
    {
      "pump_id": "string",
      "capacity_m3_per_hour": "number",
      "location": "string"
    }
  ]
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "多泵站场景生成成功",
  "data": {
    "scenarios": [
      {
        "scenario_id": "scenario_001",
        "pump_assignments": ["pump_1", "pump_2"],
        "estimated_duration_hours": 3.5,
        "efficiency_score": 85.5
      }
    ],
    "recommended_scenario": "scenario_001"
  }
}
```

### 6.2 批次重新生成功能

#### 6.2.1 批次重新生成
- **请求地址**: `POST /api/irrigation/regenerate-batch`
- **请求方式**: POST
- **请求参数**:
```json
{
  "original_plan_id": "string",
  "field_modifications": {
    "F001": {
      "target_water_level": 3.0,
      "priority": "high"
    }
  },
  "pump_assignments": ["pump_1"],
  "custom_water_levels": {
    "F001": 2.5
  }
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "批次重新生成成功",
  "data": {
    "new_plan_id": "plan_20250101_002",
    "changes_summary": {
      "modified_fields": 3,
      "time_adjustment_minutes": 15,
      "water_usage_change_m3": 25.5
    },
    "optimization_results": {
      "efficiency_improvement_percent": 12.5,
      "water_savings_m3": 10.0
    }
  }
}
```

---

## 七、Web可视化模块

### 7.1 地理数据功能

#### 7.1.1 获取田块数据
- **请求地址**: `GET /geojson/fields`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "田块数据获取成功",
  "data": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": {
          "F_id": "F001",
          "area": 1000.5,
          "crop_type": "rice"
        },
        "geometry": {
          "type": "Polygon",
          "coordinates": [[[lng, lat], [lng, lat]]]
        }
      }
    ]
  }
}
```

#### 7.1.2 获取闸门数据
- **请求地址**: `GET /geojson/gates`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "闸门数据获取成功",
  "data": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": {
          "G_id": "G001",
          "gate_type": "control",
          "status": "open"
        },
        "geometry": {
          "type": "Point",
          "coordinates": [lng, lat]
        }
      }
    ]
  }
}
```

### 7.2 计划管理功能

#### 7.2.1 生成灌溉计划
- **请求地址**: `GET /v1/plan`
- **请求方式**: GET
- **请求参数**: 无
- **响应内容**:
```json
{
  "status": "success",
  "message": "灌溉计划生成成功",
  "data": {
    "plan": {
      "batches": [
        {
          "batch_index": 1,
          "fields": ["F001", "F002"],
          "start_time": "2025-01-XX 10:00:00",
          "duration_minutes": 90
        }
      ]
    },
    "summary": {
      "total_batches": 5,
      "total_duration_hours": 4.5
    }
  }
}
```

---

## 八、数据管理模块

### 8.1 数据清理功能

#### 8.1.1 清理执行数据
- **请求地址**: `POST /api/data/cleanup`
- **请求方式**: POST
- **请求参数**:
```json
{
  "cleanup_type": "string",
  "days_to_keep": "integer",
  "confirm": "boolean"
}
```
- **响应内容**:
```json
{
  "status": "success",
  "message": "数据清理完成",
  "data": {
    "cleaned_records": 150,
    "freed_space_mb": 25.5,
    "cleanup_time": "2025-01-XX 10:00:00"
  }
}
```

---

## 使用示例

### Python 示例

```python
import requests

# 启动动态执行
response = requests.post('http://0.0.0.0:8000/api/execution/start', json={
    "plan_file_path": "/e:/irrigation_schedule/farm_irrigation/output/irrigation_plan_20251101_143125.json",
    "farm_id": "13944136728576",
    "enable_realtime_waterlevels": True
})
print(response.json())

# 获取执行状态
response = requests.get('http://0.0.0.0:8000/api/execution/status')
print(response.json())

# 更新水位数据
response = requests.post('http://0.0.0.0:8000/api/water-levels/update', json={
    "farm_id": "13944136728576",
    "force_update": True
})
print(response.json())
```

### cURL 示例

```bash
# 启动动态执行
curl -X POST http://0.0.0.0:8000/api/execution/start \
  -H "Content-Type: application/json" \
  -d '{
    "plan_file_path": "/e:/irrigation_schedule/farm_irrigation/output/irrigation_plan_20251101_143125.json",
    "farm_id": "13944136728576",
    "enable_realtime_waterlevels": true
  }'

# 获取执行状态
curl -X GET http://0.0.0.0:8000/api/execution/status

# 更新水位数据
curl -X POST http://0.0.0.0:8000/api/water-levels/update \
  -H "Content-Type: application/json" \
  -d '{
    "farm_id": "13944136728576",
    "force_update": true
  }'

# 健康检查
curl -X GET http://0.0.0.0:8000/api/health
```

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未授权访问 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用 |

---

**最后更新时间**: 2025年1月

**版本**: v2.0.0

**更新日志**:
- 重构API文档结构，采用模块→功能→接口三级组织
- 统一API响应格式为 status、message、data 三字段结构
- 简化文档内容，去除冗余信息
- 完善接口参数和响应示例
- 更新服务配置和使用示例