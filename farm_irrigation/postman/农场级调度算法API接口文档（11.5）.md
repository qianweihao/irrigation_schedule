# 农场级灌溉调度算法API接口文档-First

## 目录
1. [概述](#概述)
2. [业务术语表](#业务术语表)
3. [快速开始](#快速开始)
4. [认证方式](#认证方式)
5. [接口列表](#接口列表)
   - [系统管理](#1-系统管理)
   - [灌溉计划生成](#2-灌溉计划生成)
   - [多水泵方案对比](#3-多水泵方案对比)
   - [计划优化](#4-计划优化)
   - [动态执行管理](#5-动态执行管理)
   - [批次管理](#6-批次管理)
   - [水位管理](#7-水位管理)
   - [计划重新生成](#8-计划重新生成)
6. [典型业务流程](#典型业务流程)
7. [错误码说明](#错误码说明)
8. [常见问题](#常见问题)

---
## 概述
### 系统介绍
农场级灌溉调度算法提供以下核心功能：
- **动态批次执行管理** - 实时调整灌溉计划
- **实时水位数据获取和管理** - 支持多数据源
- **智能计划重新生成** - 基于最新数据自动优化
- **执行状态监控和历史记录** - 完整的追踪体系
- **田块水位趋势分析** - 数据可视化支持
- **多水泵方案对比分析** - 辅助决策
- **灌溉计划智能优化** - 多目标优化算法

### 技术架构
- **框架**: FastAPI + Uvicorn
- **部署**: Docker + Docker Compose + Nginx
- **端口**: 80 (Nginx) / 8000 (API直连)
---

## 业务术语表

### 核心概念
| 术语 | 英文 | 说明 | 示例值 |
|------|------|------|--------|
| **farm_id** | Farm ID | 农场唯一标识符，用于区分不同的农场 | `"13944136728576"` |
| **plan_id** | Plan ID | 灌溉计划文件的完整路径，由生成计划接口返回 | `"/app/output/irrigation_plan_20250109_123456.json"` |
| **execution_id** | Execution ID | 执行任务的唯一标识，由启动执行接口返回 | `"exec_20250109_123456"` |
| **batch_index** | Batch Index | 批次索引号，**从1开始计数**（不是0） | `1, 2, 3, 4` |
| **field_id** | Field ID | 田块唯一标识符，格式：`片区-闸门-田块` | `"S3-G2-F1"` |
| **segment_id** | Segment ID | 片区标识符，表示一个灌溉区域 | `"S3", "S4", "S5"` |

### 灌溉相关
| 术语 | 英文 | 说明 | 单位 |
|------|------|------|------|
| **water_level_mm** | Water Level | 田块当前水位深度 | 毫米 (mm) |
| **target_depth_mm** | Target Depth | 目标灌溉深度，灌溉后期望达到的水位 | 毫米 (mm) |
| **area_mu** | Area | 田块面积 | 亩 (mu) |
| **deficit_vol_m3** | Deficit Volume | 缺水量，需要灌溉的水量 | 立方米 (m³) |
| **eta_hours** | ETA Hours | 预计完成时间 | 小时 (h) |

### 设备相关
| 术语 | 英文 | 说明 | 示例值 |
|------|------|------|--------|
| **pump_id** | Pump ID | 水泵标识符 | `"P1", "P2"` |
| **active_pumps** | Active Pumps | 当前启用的水泵列表 | `["P1", "P2"]` |
| **q_avail_m3ph** | Available Flow | 可用流量（每小时立方米） | `240.0` |
| **power_kw** | Power | 水泵功率 | 千瓦 (kW) |

### 时间相关
| 术语 | 英文 | 说明 | 格式/单位 |
|------|------|------|----------|
| **t_start_h** | Start Time | 开始时间（相对时间） | 小时 (h)，如 `22.0` 表示晚上10点 |
| **t_end_h** | End Time | 结束时间（相对时间） | 小时 (h)，如 `40.28` 表示从起始点后40.28小时 |
| **duration_h** | Duration | 持续时长 | 小时 (h) |
| **timestamp** | Timestamp | 绝对时间戳 | ISO 8601格式，如 `"2025-01-09T12:34:56.789Z"` |

### 优化相关
| 术语 | 英文 | 说明 |
|------|------|------|
| **cost_minimization** | Cost Minimization | 成本最小化，优先降低电费成本 |
| **time_minimization** | Time Minimization | 时间最小化，最快完成灌溉任务 |
| **balanced** | Balanced | 均衡优化，在成本和时间之间平衡 |
| **off_peak** | Off-Peak | 避峰用电，避开峰段电价时段 |
| **water_saving** | Water Saving | 节水优化，减少水资源消耗 |

### 执行模式
| 模式 | 说明 |
|------|------|
| **simulation** | 模拟模式，不实际控制设备，仅用于测试和预览 |
| **production** | 生产模式，实际控制灌溉设备执行 |

### 数据质量
| 等级 | 说明 |
|------|------|
| **good** | 良好，数据来自可靠传感器或经过验证 |
| **fair** | 一般，数据可用但可能存在偏差 |
| **poor** | 较差，数据质量不佳，建议谨慎使用 |

### 数据来源
| 来源 | 说明 |
|------|------|
| **sensor** | 传感器自动采集 |
| **manual** | 人工手动输入 |
| **estimated** | 系统估算值 |

---

## 快速开始

### 基础配置

```javascript
// 环境配置
const BASE_URL = 'http://120.55.127.125';
const API_BASE_URL = `${BASE_URL}/api`;

// 通用请求头
const headers = {
  'Content-Type': 'application/json',
  'Accept': 'application/json'
};
```

### 最简单的调用示例
```javascript
// 1. 健康检查
fetch(`${BASE_URL}/api/system/health-check`, {
  method: 'POST',
  headers: headers
})
.then(res => res.json())
.then(data => console.log(data));

// 2. 获取API信息
fetch(`${BASE_URL}/api/info`)
.then(res => res.json())
.then(data => console.log(data));
```

---
## 认证方式

**当前版本**: 无需认证  
**未来版本**: 将支持 JWT Token 认证

```javascript
// 预留的认证头（未来版本）
headers: {
  'Authorization': 'Bearer YOUR_JWT_TOKEN'
}
```

---

## 接口列表

### 1. 系统管理

#### 1.1 健康检查

**接口说明**: 检查系统各组件的健康状态

**请求**
```
POST /api/system/health-check
```

**响应示例**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-09T12:34:56.789Z",
  "components": {
    "scheduler": "ok",
    "waterlevel_manager": "ok",
    "plan_regenerator": "ok",
    "status_manager": "ok"
  }
}
```

**字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 系统总体状态: `healthy`/`degraded`/`unhealthy` |
| timestamp | string | ISO 8601 格式时间戳 |
| components | object | 各组件状态，值为 `ok`/`not_initialized` |

---

#### 1.2 获取系统状态

**接口说明**: 获取系统运行状态和组件初始化情况

**请求**
```
GET /api/system/status
```

**响应示例**
```json
{
  "system_status": "running",
  "scheduler_initialized": true,
  "waterlevel_manager_initialized": true,
  "plan_regenerator_initialized": true,
  "status_manager_initialized": true,
  "current_time": "2025-01-09T12:34:56.789Z",
  "uptime_seconds": 3600.5
}
```

---

#### 1.3 获取API信息

**接口说明**: 获取API版本和功能列表

**请求**
```
GET /api/info
```

**响应示例**
```json
{
  "title": "智能灌溉动态执行系统API",
  "description": "基于实时水位数据的智能灌溉批次动态执行系统",
  "version": "1.0.0",
  "features": [
    "动态批次执行管理",
    "实时水位数据获取和管理",
    "智能计划重新生成",
    "执行状态监控和历史记录",
    "田块水位趋势分析",
    "多水泵方案对比分析",
    "灌溉计划智能优化"
  ],
  "endpoints": {
    "system": "/api/system/*",
    "execution": "/api/execution/*",
    "water_levels": "/api/water-levels/*",
    "regeneration": "/api/regeneration/*",
    "batches": "/api/batches/*",
    "irrigation": "/api/irrigation/*",
    "data": "/api/data/*"
  }
}
```

---

### 2. 灌溉计划生成

#### 2.1 生成灌溉计划

**接口说明**: 根据配置生成完整的灌溉计划，支持多水泵方案对比

**请求**
```
POST /api/irrigation/plan-generation
Content-Type: application/json
```

**请求参数**
```json
{
  "farm_id": "13944136728576",
  "config_path": "",
  "output_dir": "",
  "scenario_name": "test_scenario",
  "multi_pump_scenarios": true
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| farm_id | string | ✅ 是 | - | 农场唯一标识符。<br>**业务含义**: 标识当前操作的农场，系统根据此ID加载对应的农场配置和田块数据。<br>**示例**: `"13944136728576"` |
| config_path | string | ❌ 否 | `"config.json"` | 配置文件路径。<br>**业务含义**: 指定自定义配置文件，留空则使用系统默认配置文件。配置文件包含水泵参数、电价、灌溉深度等设置。<br>**示例**: `""` (使用默认) 或 `"custom_config.json"` |
| output_dir | string | ❌ 否 | `"/app/output"` | 输出目录路径。<br>**业务含义**: 灌溉计划文件的保存目录，留空则使用系统默认输出目录。<br>**示例**: `""` (使用默认) 或 `"/custom/path"` |
| scenario_name | string | ❌ 否 | `"default"` | 场景名称标识。<br>**业务含义**: 为本次生成的计划命名，便于后续识别和管理不同场景的方案（如"夏季灌溉"、"应急方案"等）。<br>**示例**: `"test_scenario"`, `"summer_plan"` |
| multi_pump_scenarios | boolean | ❌ 否 | `false` | 是否生成多水泵方案对比。<br>**业务含义**: 启用后，系统会自动生成不同水泵组合的方案（如P1单独、P2单独、P1+P2组合），并进行成本和时长对比，帮助决策选择最优方案。<br>**建议**: 首次规划或需要对比时设为`true`。<br>**示例**: `true` |

**响应示例**
```json
{
  "success": true,
  "message": "灌溉计划生成成功",
  "plan_id": "/app/output/irrigation_plan_20250109_123456.json",
  "data": {
    "calc": {
      "A_cover_mu": 79.99996,
      "q_avail_m3ph": 240.0,
      "t_win_h": 20.0,
      "d_target_mm": 90.0
    },
    "batches": [
      {
        "index": 1,
        "area_mu": 73.107,
        "fields": [
          {
            "id": "S3-G2-F1",
            "area_mu": 5.225,
            "segment_id": "S3",
            "wl_mm": 0.0
          }
        ],
        "stats": {
          "deficit_vol_m3": 4386.42,
          "cap_vol_m3": 4800.0,
          "eta_hours": 18.28
        }
      }
    ],
    "steps": [
      {
        "t_start_h": 22.0,
        "t_end_h": 40.28,
        "label": "批次 1",
        "commands": [
          {
            "action": "start",
            "target": "P2",
            "value": null,
            "t_start_h": 22.0,
            "t_end_h": 40.28
          }
        ]
      }
    ]
  },
  "multi_pump_scenarios": {
    "scenarios": [
      {
        "scenario_name": "P2单独使用",
        "pumps_used": ["P2"],
        "total_electricity_cost": 1774.17,
        "total_eta_h": 73.92,
        "coverage_info": {
          "covered_segments": ["S3", "S4", "S5", "S6", "S7", "S8"],
          "total_covered_segments": 6
        }
      }
    ],
    "analysis": {
      "total_fields_below_threshold": 36,
      "min_fields_trigger": 1,
      "trigger_status": "已达到触发条件"
    },
    "total_scenarios": 4
  }
}
```

**关键字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| plan_id | string | **重要！** 生成的计划文件完整路径，用于后续接口 |
| data.batches | array | 灌溉批次列表 |
| data.steps | array | 执行步骤列表 |
| multi_pump_scenarios | object | 多水泵方案对比数据（如果启用） |

---

#### 2.2 上传配置并生成计划

**接口说明**: 上传自定义配置文件并生成灌溉计划

**请求**
```
POST /api/irrigation/plan-with-upload
Content-Type: multipart/form-data
```

**请求参数 (FormData)**
```javascript
const formData = new FormData();
formData.append('farm_id', '13944136728576');
formData.append('scenario_name', 'upload_test');
formData.append('multi_pump_scenarios', 'true');
formData.append('config_file', fileBlob, 'config.json');
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| farm_id | string | 是 | 农场ID |
| scenario_name | string | 否 | 场景名称 |
| multi_pump_scenarios | string | 否 | "true"/"false" |
| config_file | file | 否 | 配置JSON文件 |

**响应格式**: 与接口2.1相同

---

### 3. 多水泵方案对比

#### 3.1 生成多水泵方案

**接口说明**: 独立生成多个水泵组合的灌溉方案，用于方案对比和决策

**请求**
```
POST /api/irrigation/multi-pump-scenarios
Content-Type: application/json
```

**请求参数**
```json
{
  "config_file": "config.json",
  "active_pumps": null,
  "zone_ids": null,
  "use_realtime_wl": true,
  "min_fields_trigger": 1
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| config_file | string | ✅ 是 | - | 配置文件名称。<br>**业务含义**: 系统配置文件，包含农场布局、水泵参数、电价等基础数据。<br>**示例**: `"config.json"` |
| active_pumps | array\|null | ❌ 否 | `null` | 指定参与对比的水泵列表。<br>**业务含义**: 限制对比方案中使用的水泵，`null`表示使用配置文件中所有可用水泵。可用于模拟某台水泵故障时的备用方案。<br>**示例**: `["P1", "P2"]` 或 `null` (全部水泵) |
| zone_ids | array\|null | ❌ 否 | `null` | 指定灌溉的片区列表。<br>**业务含义**: 限制只对指定片区生成方案，`null`表示覆盖所有需要灌溉的片区。可用于分区域灌溉规划。<br>**示例**: `["S3", "S4"]` 或 `null` (全部片区) |
| use_realtime_wl | boolean | ❌ 否 | `true` | 是否使用实时水位数据。<br>**业务含义**: `true`从水位管理系统获取最新数据，`false`使用配置文件中的默认水位。建议开启以获得准确的灌溉方案。<br>**示例**: `true` |
| min_fields_trigger | integer\|null | ❌ 否 | `null` | 触发灌溉的最小田块数阈值。<br>**业务含义**: 只有当低于目标水位的田块数量 ≥ 此值时，才生成灌溉方案。`null`使用配置文件中的默认值。可用于避免为少量田块启动大型水泵。<br>**示例**: `1` (有1块田需要就灌溉) 或 `5` (至少5块田需要才灌溉) |

**响应示例**
```json
{
  "scenarios": [
    {
      "scenario_name": "P1单独使用",
      "pumps_used": ["P1"],
      "total_electricity_cost": 2150.5,
      "total_eta_h": 85.3,
      "total_pump_runtime_hours": {
        "P1": 70.2
      },
      "coverage_info": {
        "covered_segments": ["S1", "S2"],
        "total_covered_segments": 2
      },
      "plan": {
        "batches": [],
        "steps": []
      }
    },
    {
      "scenario_name": "P2单独使用",
      "pumps_used": ["P2"],
      "total_electricity_cost": 1774.17,
      "total_eta_h": 73.92,
      "coverage_info": {
        "covered_segments": ["S3", "S4", "S5", "S6", "S7", "S8"],
        "total_covered_segments": 6
      }
    },
    {
      "scenario_name": "P1+P2组合",
      "pumps_used": ["P1", "P2"],
      "total_electricity_cost": 1950.8,
      "total_eta_h": 65.5,
      "coverage_info": {
        "covered_segments": ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"],
        "total_covered_segments": 8
      }
    }
  ],
  "analysis": {
    "total_fields_below_threshold": 36,
    "min_fields_trigger": 1,
    "trigger_status": "已达到触发条件",
    "total_fields_to_irrigate": 36,
    "required_segments": ["S3", "S4", "S5", "S6", "S7", "S8"],
    "valid_pump_combinations": [["P2"], ["P1", "P2"]]
  },
  "total_scenarios": 3
}
```

**关键字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| scenarios | array | 所有可行方案列表 |
| scenarios[].total_electricity_cost | number | 总电费（元） |
| scenarios[].total_eta_h | number | 总时长（小时） |
| scenarios[].pumps_used | array | 使用的水泵列表 |
| analysis.trigger_status | string | 触发条件状态 |
| analysis.valid_pump_combinations | array | 有效的水泵组合 |

---

### 4. 计划优化

#### 4.1 智能优化灌溉计划

**接口说明**: 基于不同优化目标生成多个优化方案，包括成本最小化、时间最小化、均衡优化、避峰用电等

**请求**
```
POST /api/irrigation/plan-optimization
Content-Type: application/json
```

**请求参数**
```json
{
  "original_plan_id": "/app/output/irrigation_plan_20250109_123456.json",
  "optimization_goals": [
    "cost_minimization",
    "time_minimization",
    "balanced",
    "off_peak"
  ],
  "constraints": {
    "max_duration_hours": 24,
    "electricity_price_schedule": {
      "peak": {
        "hours": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
        "price": 1.0
      },
      "valley": {
        "hours": [22, 23, 0, 1, 2, 3, 4, 5, 6, 7],
        "price": 0.4
      }
    },
    "available_pumps": ["P1", "P2"]
  }
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| original_plan_id | string | ✅ 是 | - | 原始灌溉计划ID。<br>**业务含义**: 由"生成灌溉计划"接口返回的`plan_id`，作为优化的基础方案。系统会基于此方案生成多个优化版本。<br>**来源**: `/api/irrigation/plan-generation` 的响应中的 `plan_id` 字段<br>**示例**: `"/app/output/irrigation_plan_20250109_123456.json"` |
| optimization_goals | array | ✅ 是 | - | 优化目标列表。<br>**业务含义**: 指定要生成的优化方案类型，可同时指定多个目标，系统会为每个目标生成一个独立方案。<br>**建议**: 至少选择2-3个目标进行对比<br>**示例**: `["cost_minimization", "time_minimization", "balanced"]` |
| constraints | object | ❌ 否 | `{}` | 约束条件配置。<br>**业务含义**: 限制优化方案的边界条件，如最大时长、电价时段、可用水泵等。<br>**子字段**:<br>• `max_duration_hours`: 最大允许时长（小时）<br>• `electricity_price_schedule`: 电价时段表<br>• `available_pumps`: 可用水泵列表<br>**示例**: 见下方详细说明 |

**optimization_goals 可选值**

| 值 | 名称 | 业务目标 | 适用场景 |
|---|------|----------|----------|
| `cost_minimization` | 成本最小化 | 降低电费支出，优先在低谷电价时段灌溉 | 电费预算紧张，对时间要求不高 |
| `time_minimization` | 时间最小化 | 最快完成任务，使用最大水泵组合 | 应急灌溉，天气条件紧迫 |
| `balanced` | 均衡优化 | 在成本和时间之间取得平衡 | 日常灌溉，综合考虑效率和成本 |
| `off_peak` | 避峰用电 | 完全避开峰段电价，降低电费 | 执行分时电价政策的农场 |
| `water_saving` | 节水优化 | 减少水资源消耗，提高利用率 | 水资源紧张地区 |

**constraints 详细说明**

| 子参数 | 类型 | 说明 |
|--------|------|------|
| `max_duration_hours` | number | 最大允许执行时长（小时）。超过此时长的方案会被过滤。<br>**示例**: `24` (必须在24小时内完成) |
| `electricity_price_schedule` | object | 电价时段配置。<br>**包含**: `peak`(峰段) 和 `valley`(谷段)<br>**每个时段包含**: `hours`(小时数组) 和 `price`(电价)<br>**示例**: `{"peak": {"hours": [8-21], "price": 1.0}, "valley": {"hours": [22-7], "price": 0.4}}` |
| `available_pumps` | array | 可用水泵列表，限制只使用指定水泵。<br>**示例**: `["P1", "P2"]` |

**响应示例**
```json
{
  "success": true,
  "message": "成功生成 4 个优化方案",
  "total_scenarios": 4,
  "scenarios": [
    {
      "name": "成本最小化方案",
      "description": "优先降低电费成本，在低谷电价时段集中灌溉",
      "total_eta_h": 78.5,
      "total_electricity_cost": 1580.3,
      "optimization_type": "cost_minimization",
      "plan": {
        "batches": [],
        "steps": []
      }
    },
    {
      "name": "时间最小化方案",
      "description": "最快完成灌溉任务，使用最大泵组合",
      "total_eta_h": 55.2,
      "total_electricity_cost": 2150.8,
      "optimization_type": "time_minimization"
    },
    {
      "name": "均衡优化方案",
      "description": "在成本和时间之间寻求最佳平衡",
      "total_eta_h": 65.8,
      "total_electricity_cost": 1820.5,
      "optimization_type": "balanced"
    },
    {
      "name": "避峰用电方案",
      "description": "完全避开峰段电价时段",
      "total_eta_h": 82.3,
      "total_electricity_cost": 1620.7,
      "optimization_type": "off_peak"
    }
  ],
  "comparison": {
    "recommended": "成本最小化方案",
    "cost_range": {
      "min": 1580.3,
      "max": 2150.8,
      "savings_percent": 26.5
    },
    "time_range": {
      "min": 55.2,
      "max": 82.3
    }
  },
  "base_plan_summary": {
    "total_eta_h": 73.92,
    "total_electricity_cost": 1774.17,
    "total_batches": 4
  }
}
```

**关键字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| scenarios | array | 优化方案列表 |
| scenarios[].name | string | 方案名称 |
| scenarios[].description | string | 方案描述 |
| scenarios[].total_eta_h | number | 总时长（小时） |
| scenarios[].total_electricity_cost | number | 总电费（元） |
| comparison.recommended | string | 推荐方案 |
| comparison.cost_range.savings_percent | number | 最大节省百分比 |

---

### 5. 动态执行管理

#### 5.1 启动动态执行

**接口说明**: 启动灌溉计划的动态执行，支持实时水位更新和计划重新生成

**请求**
```
POST /api/execution/start
Content-Type: application/json
```

**请求参数**
```json
{
  "plan_file_path": "/app/output/irrigation_plan_20250109_123456.json",
  "farm_id": "13944136728576",
  "config_file_path": "",
  "auto_start": true,
  "water_level_update_interval_minutes": 30,
  "enable_plan_regeneration": true,
  "execution_mode": "simulation"
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| plan_file_path | string | ✅ 是 | - | 灌溉计划文件路径。<br>**业务含义**: 要执行的灌溉计划，使用"生成灌溉计划"接口返回的`plan_id`。<br>**重要**: 必须使用完整路径，系统会根据此文件的批次、时间、设备信息进行执行调度。<br>**来源**: `/api/irrigation/plan-generation` 或 `/api/irrigation/plan-optimization` 的 `plan_id`<br>**示例**: `"/app/output/irrigation_plan_20250109_123456.json"` |
| farm_id | string | ✅ 是 | - | 农场唯一标识符。<br>**业务含义**: 必须与生成计划时使用的`farm_id`一致，用于加载农场配置和验证计划有效性。<br>**示例**: `"13944136728576"` |
| config_file_path | string | ❌ 否 | `"config.json"` | 配置文件路径。<br>**业务含义**: 系统配置文件，包含设备通信参数、安全阈值等。留空使用默认配置。<br>**示例**: `""` (使用默认) |
| auto_start | boolean | ❌ 否 | `true` | 是否立即开始执行。<br>**业务含义**: <br>• `true`: 启动后立即按计划执行，适合自动化场景<br>• `false`: 启动后进入就绪状态，需手动触发，适合需要人工确认的场景<br>**建议**: 测试时设为`false`，生产环境可设为`true`<br>**示例**: `true` |
| water_level_update_interval_minutes | integer | ❌ 否 | `30` | 水位数据更新间隔（分钟）。<br>**业务含义**: 系统每隔此时长自动获取最新水位数据。设置越小数据越及时，但会增加传感器读取频率。<br>**建议范围**: 15-60分钟<br>**示例**: `30` (每30分钟更新一次) |
| enable_plan_regeneration | boolean | ❌ 否 | `true` | 是否启用智能重新生成。<br>**业务含义**: <br>• `true`: 当水位变化超过阈值时，自动重新生成后续批次计划，实现动态调整<br>• `false`: 严格按原计划执行，不做调整<br>**适用场景**: <br>• 天气多变、水位波动大 → 设为`true`<br>• 计划已经过充分验证、需严格执行 → 设为`false`<br>**示例**: `true` |
| execution_mode | string | ❌ 否 | `"simulation"` | 执行模式。<br>**业务含义**: <br>• `simulation`: **模拟模式**，不实际控制设备，仅记录执行日志，用于测试和预演<br>• `production`: **生产模式**，实际发送指令控制水泵、闸门等设备<br>**⚠️ 重要**: 首次部署或修改配置后，必须先在`simulation`模式下验证！<br>**示例**: `"simulation"` (测试) 或 `"production"` (正式执行) |

**响应示例**
```json
{
  "success": true,
  "message": "动态执行启动成功",
  "data": {
    "execution_id": "exec_20250109_123456",
    "status": "running",
    "start_time": "2025-01-09T12:34:56.789Z",
    "plan_file": "/app/output/irrigation_plan_20250109_123456.json",
    "total_batches": 4,
    "current_batch": 1,
    "execution_mode": "simulation"
  }
}
```

**关键字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| execution_id | string | **重要！** 执行ID，用于查询状态和停止执行 |
| status | string | 执行状态: `running`/`paused`/`completed`/`failed` |
| current_batch | integer | 当前执行批次 |
| total_batches | integer | 总批次数 |

---

#### 5.2 查询执行状态

**接口说明**: 查询当前执行的详细状态

**请求**
```
GET /api/execution/status?execution_id=exec_20250109_123456
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| execution_id | string | 否 | 执行ID，不传返回当前执行 |

**响应示例**
```json
{
  "success": true,
  "data": {
    "execution_id": "exec_20250109_123456",
    "status": "running",
    "start_time": "2025-01-09T12:34:56.789Z",
    "current_batch": 2,
    "total_batches": 4,
    "progress_percent": 50.0,
    "last_water_level_update": "2025-01-09T13:04:56.789Z",
    "total_regenerations": 1,
    "active_fields": [
      {
        "field_id": "S4-G21-F15",
        "status": "irrigating",
        "start_time": "2025-01-09T13:00:00.000Z"
      }
    ],
    "completed_batches": [1],
    "selected_scenario": {
      "scenario_name": "P2单独使用",
      "pumps_used": ["P2"],
      "total_batches": 4
    }
  }
}
```

**关键字段说明**
| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 执行状态 |
| progress_percent | number | 执行进度百分比 |
| total_regenerations | integer | 计划重新生成次数 |
| active_fields | array | 正在灌溉的田块 |
| selected_scenario | object | 当前执行的方案信息 |

---

#### 5.3 停止执行

**接口说明**: 停止当前正在执行的任务

**请求**
```
POST /api/execution/stop
Content-Type: application/json
```

**请求参数**
```json
{
  "execution_id": "exec_20250109_123456",
  "reason": "手动停止"
}
```

**响应示例**
```json
{
  "success": true,
  "message": "执行已停止",
  "data": {
    "execution_id": "exec_20250109_123456",
    "status": "stopped",
    "stop_time": "2025-01-09T14:00:00.000Z",
    "completed_batches": 2,
    "total_batches": 4
  }
}
```

---

#### 5.4 获取执行历史

**接口说明**: 获取最近的执行历史记录

**请求**
```
GET /api/execution/history?limit=10
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | integer | 否 | 返回记录数，默认10 |

**响应示例**
```json
{
  "success": true,
  "total": 25,
  "data": [
    {
      "execution_id": "exec_20250109_123456",
      "start_time": "2025-01-09T12:34:56.789Z",
      "end_time": "2025-01-09T14:00:00.000Z",
      "status": "completed",
      "total_batches": 4,
      "completed_batches": 4,
      "total_regenerations": 2
    }
  ]
}
```

---

### 6. 批次管理

#### 6.1 获取批次列表

**接口说明**: 获取当前计划的所有批次信息

**请求**
```
GET /api/batches?farm_id=13944136728576&status=active
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| farm_id | string | 否 | 农场ID |
| status | string | 否 | 批次状态过滤 |

**响应示例**
```json
{
  "success": true,
  "total_batches": 4,
  "batches": [
    {
      "index": 1,
      "area_mu": 73.107,
      "field_count": 14,
      "fields": ["S3-G2-F1", "S3-G3-F2", "S3-G5-F3"],
      "segment_ids": ["S3", "S4"]
    },
    {
      "index": 2,
      "area_mu": 79.083,
      "field_count": 11,
      "fields": ["S4-G21-F15", "S4-G22-F16"],
      "segment_ids": ["S4", "S5", "S6"]
    }
  ],
  "farm_id": "13944136728576",
  "scenario_name": "P2单独使用",
  "scenario_count": 1,
  "query_time": "2025-01-09T12:34:56.789Z"
}
```

---

#### 6.2 获取批次详情

**接口说明**: 获取指定批次的详细信息

**请求**
```
GET /api/batches/{batch_index}/details
```

**路径参数**
| 参数 | 类型 | 说明 |
|------|------|------|
| batch_index | integer | 批次索引（从1开始） |

**响应示例**
```json
{
  "batch_index": 1,
  "area_mu": 73.107,
  "field_count": 14,
  "fields": [
    {
      "id": "S3-G2-F1",
      "area_mu": 5.225,
      "segment_id": "S3",
      "distance_rank": 1,
      "wl_mm": 0.0,
      "inlet_G_id": "S3-G2"
    }
  ],
  "segment_ids": ["S3", "S4"],
  "execution_details": {
    "status": "completed",
    "start_time": "2025-01-09T12:00:00.000Z",
    "end_time": "2025-01-09T13:30:00.000Z"
  },
  "scenario_name": "P2单独使用",
  "query_time": "2025-01-09T12:34:56.789Z"
}
```

---

#### 6.3 获取当前计划

**接口说明**: 获取当前执行的完整计划数据

**请求**
```
GET /api/batches/current-plan
```

**响应示例**
```json
{
  "plan": {
    "calc": {},
    "batches": [],
    "steps": []
  },
  "farm_id": "13944136728576",
  "query_time": "2025-01-09T12:34:56.789Z"
}
```

---

### 7. 水位管理

#### 7.1 更新水位数据

**接口说明**: 更新指定田块的水位数据

**请求**
```
POST /api/water-levels/update
Content-Type: application/json
```

**请求参数**
```json
{
  "farm_id": "13944136728576",
  "field_id": "S3-G2-F1",
  "water_level_mm": 25.5,
  "timestamp": "2025-01-09T12:00:00Z",
  "source": "sensor",
  "quality": "good"
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| farm_id | string | ✅ 是 | - | 农场唯一标识符。<br>**业务含义**: 标识数据所属的农场，用于数据隔离和关联。<br>**示例**: `"13944136728576"` |
| field_id | string | ✅ 是 | - | 田块唯一标识符。<br>**业务含义**: 指定要更新水位的田块，格式为"片区-闸门-田块"。<br>**格式**: `S{片区编号}-G{闸门编号}-F{田块编号}`<br>**示例**: `"S3-G2-F1"` (第3片区第2闸门第1块田) |
| water_level_mm | number | ✅ 是 | - | 田块当前水位深度（毫米）。<br>**业务含义**: 田块内的实际水深，系统根据此值判断是否需要灌溉。<br>**数值范围**: 通常 0-150mm<br>**特殊值**: `0`表示干田<br>**示例**: `25.5` (水深25.5毫米) |
| timestamp | string | ❌ 否 | 当前时间 | 采集数据的时间戳。<br>**业务含义**: 标记数据的采集时间，留空则使用服务器接收时间。对于批量历史数据导入，建议填写实际采集时间。<br>**格式**: ISO 8601格式 `YYYY-MM-DDTHH:mm:ss.sssZ`<br>**示例**: `"2025-01-09T12:00:00Z"` |
| source | string | ❌ 否 | `"manual"` | 数据来源类型。<br>**业务含义**: 标识数据的获取方式，影响数据可信度权重。<br>**可选值**:<br>• `sensor`: 传感器自动采集，**最可靠**<br>• `manual`: 人工手动输入，需二次确认<br>• `estimated`: 系统估算，仅参考<br>**示例**: `"sensor"` |
| quality | string | ❌ 否 | `"good"` | 数据质量等级。<br>**业务含义**: 评估数据的可靠性，影响是否触发计划重新生成。<br>**可选值**:<br>• `good`: 数据可靠，可直接使用<br>• `fair`: 数据可用，但可能有偏差<br>• `poor`: 数据质量差，建议重新采集<br>**自动判断**: 传感器数据通常为`good`，人工输入建议设为`fair`<br>**示例**: `"good"` |

**响应示例**
```json
{
  "success": true,
  "message": "水位数据更新成功",
  "data": {
    "field_id": "S3-G2-F1",
    "water_level_mm": 25.5,
    "updated_at": "2025-01-09T12:00:00Z"
  }
}
```

---

#### 7.2 获取水位汇总

**接口说明**: 获取农场或指定田块的水位汇总信息

**请求**
```
GET /api/water-levels/summary?farm_id=13944136728576&field_ids=S3-G2-F1,S3-G3-F2
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| farm_id | string | 是 | 农场ID |
| field_ids | string | 否 | 田块ID列表（逗号分隔） |

**响应示例**
```json
{
  "success": true,
  "data": {
    "total_fields": 36,
    "fields_with_data": 30,
    "last_update": "2025-01-09T12:00:00Z",
    "average_level": 15.5,
    "quality_summary": {
      "good": 25,
      "fair": 4,
      "poor": 1
    },
    "field_summaries": {
      "S3-G2-F1": {
        "current_level": 25.5,
        "last_update": "2025-01-09T12:00:00Z",
        "quality": "good"
      }
    }
  }
}
```

---

#### 7.3 获取水位历史

**接口说明**: 获取指定田块的水位历史数据

**请求**
```
GET /api/water-levels/history?farm_id=13944136728576&field_id=S3-G2-F1&hours=24
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| farm_id | string | 是 | 农场ID |
| field_id | string | 是 | 田块ID |
| hours | integer | 否 | 查询时间范围（小时），默认24 |

**响应示例**
```json
{
  "success": true,
  "field_id": "S3-G2-F1",
  "data": [
    {
      "timestamp": "2025-01-09T12:00:00Z",
      "water_level_mm": 25.5,
      "source": "sensor",
      "quality": "good"
    },
    {
      "timestamp": "2025-01-09T11:00:00Z",
      "water_level_mm": 23.2,
      "source": "sensor",
      "quality": "good"
    }
  ],
  "total_records": 24
}
```

---

#### 7.4 获取田块水位趋势

**接口说明**: 获取田块水位变化趋势分析

**请求**
```
GET /api/water-levels/trend/{field_id}?hours=48
```

**路径参数**
| 参数 | 类型 | 说明 |
|------|------|------|
| field_id | string | 田块ID |

**查询参数**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| hours | integer | 否 | 分析时间范围（小时），默认48 |

**响应示例**
```json
{
  "success": true,
  "field_id": "S3-G2-F1",
  "trend": {
    "direction": "increasing",
    "rate_mm_per_hour": 0.5,
    "prediction_24h": 37.5
  },
  "statistics": {
    "min": 10.0,
    "max": 30.0,
    "average": 22.5,
    "std_dev": 5.2
  },
  "data_points": 48
}
```

---

### 8. 计划重新生成

#### 8.1 批次重新生成

**接口说明**: 修改批次并重新生成计划，支持田块修改、水泵分配、时间调整

**请求**
```
POST /api/regeneration/batch
Content-Type: application/json
```

**请求参数**
```json
{
  "original_plan_id": "/app/output/irrigation_plan_20250109_123456.json",
  "field_modifications": [
    {
      "field_id": "S3-G5-F1",
      "action": "add",
      "custom_water_level": 95.0
    },
    {
      "field_id": "S3-G5-F2",
      "action": "remove"
    }
  ],
  "pump_assignments": [
    {
      "batch_index": 1,
      "pump_ids": ["P1", "P2"]
    }
  ],
  "time_modifications": [
    {
      "batch_index": 1,
      "start_time_h": 2.0,
      "duration_h": 10.0
    }
  ],
  "regeneration_params": {
    "force_regeneration": true,
    "optimize_schedule": true
  }
}
```

**参数说明**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| original_plan_id | string | ✅ 是 | - | 原始灌溉计划ID。<br>**业务含义**: 要修改的计划文件路径，使用"生成灌溉计划"接口返回的`plan_id`。<br>**示例**: `"/app/output/irrigation_plan_20250109_123456.json"` |
| field_modifications | array | ❌ 否 | `[]` | 田块修改列表。<br>**业务含义**: 指定要添加或删除的田块。常用于:<br>• 临时增加灌溉田块<br>• 排除故障田块<br>• 调整灌溉优先级<br>**格式**: 见下方详细说明 |
| pump_assignments | array | ❌ 否 | `[]` | 水泵分配列表。<br>**业务含义**: 为特定批次指定使用的水泵组合。常用于:<br>• 某台水泵故障，切换备用<br>• 多泵协同作业<br>• 负载均衡<br>**格式**: `[{"batch_index": 1, "pump_ids": ["P1", "P2"]}]` |
| time_modifications | array | ❌ 否 | `[]` | 时间修改列表。<br>**业务含义**: 调整批次的开始时间或持续时长。常用于:<br>• 避开用电高峰<br>• 适应天气变化<br>• 优化人力调度<br>**格式**: `[{"batch_index": 1, "start_time_h": 2.0, "duration_h": 10.0}]`<br>**⚠️ 注意**: 修改时间会自动级联调整后续批次 |
| regeneration_params | object | ❌ 否 | `{}` | 重新生成参数。<br>**业务含义**: 控制重新生成的行为。<br>**子字段**:<br>• `force_regeneration`: 强制重新生成（即使变化很小）<br>• `optimize_schedule`: 是否优化调度顺序 |

**field_modifications 详细说明**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| field_id | string | ✅ | 田块唯一标识符。<br>**格式**: `S{片区}-G{闸门}-F{田块}`<br>**示例**: `"S3-G5-F1"` |
| action | string | ✅ | 操作类型。<br>**可选值**:<br>• `add`: 添加田块到灌溉计划<br>• `remove`: 从计划中移除田块<br>**示例**: `"add"` |
| custom_water_level | number | ❌ | 自定义水位（仅`add`时需要）。<br>**业务含义**: 为新增田块指定当前水位，用于计算灌溉量。<br>**单位**: 毫米 (mm)<br>**示例**: `95.0` |

**pump_assignments 详细说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| batch_index | integer | 批次索引号（**从1开始**）<br>**示例**: `1` |
| pump_ids | array | 该批次使用的水泵列表<br>**示例**: `["P1", "P2"]` (同时使用P1和P2) |

**time_modifications 详细说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| batch_index | integer | 批次索引号（**从1开始**）<br>**示例**: `1` |
| start_time_h | number | 新的开始时间（小时）<br>**格式**: 相对时间，`0`为计划起始点<br>**示例**: `2.0` (计划开始后2小时) |
| duration_h | number | 新的持续时长（小时）<br>**⚠️ 注意**: 系统会自动验证水泵流量是否足够<br>**示例**: `10.0` (执行10小时) |

**响应示例**
```json
{
  "success": true,
  "message": "批次计划重新生成成功，共进行了 3 项修改",
  "original_plan": {
    "batches": [],
    "steps": []
  },
  "modified_plan": {
    "batches": [],
    "steps": []
  },
  "modifications_summary": {
    "field_modifications": [
      {
        "field_id": "S3-G5-F1",
        "action": "add",
        "result": "success"
      },
      {
        "field_id": "S3-G5-F2",
        "action": "remove",
        "result": "success"
      }
    ],
    "pump_assignments": [
      {
        "batch_index": 1,
        "pump_ids": ["P1", "P2"],
        "result": "success"
      }
    ],
    "time_modifications": [
      {
        "batch_index": 1,
        "start_time_h": 2.0,
        "duration_h": 10.0,
        "result": "success"
      }
    ],
    "total_changes": 3
  }
}
```

---

#### 8.2 手动重新生成（水位）

**接口说明**: 基于新的水位数据重新生成指定批次

**请求**
```
POST /api/regeneration/manual
Content-Type: application/json
```

**请求参数**
```json
{
  "batch_index": 1,
  "custom_water_levels": {
    "S3-G5-F3": 95.0,
    "S3-G6-F4": 88.5
  },
  "force_regeneration": true
}
```

**参数说明**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| batch_index | integer | 是 | 批次索引 |
| custom_water_levels | object | 否 | 自定义水位数据（田块ID: 水位值） |
| force_regeneration | boolean | 否 | 是否强制重新生成，默认false |

**响应示例**
```json
{
  "success": true,
  "message": "批次重新生成成功",
  "data": {
    "batch_index": 1,
    "regenerated_at": "2025-01-09T12:34:56.789Z",
    "changes": {
      "fields_updated": 2,
      "duration_change_h": 1.5
    }
  }
}
```

---

## 典型业务流程

### 流程1：标准灌溉计划生成与执行 

**适用场景**: 最常用的标准流程
```javascript
// 步骤1: 生成灌溉计划
const planResponse = await fetch(`${BASE_URL}/api/irrigation/plan-generation`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    farm_id: "13944136728576",
    multi_pump_scenarios: true
  })
});
const planData = await planResponse.json();
const planId = planData.plan_id; // 保存plan_id

// 步骤2: 启动动态执行
const execResponse = await fetch(`${BASE_URL}/api/execution/start`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    plan_file_path: planId,  // 使用步骤1的plan_id
    farm_id: "13944136728576",
    auto_start: true,
    enable_plan_regeneration: true
  })
});
const execData = await execResponse.json();
const executionId = execData.data.execution_id;

// 步骤3: 轮询查询执行状态
const checkStatus = async () => {
  const statusResponse = await fetch(
    `${BASE_URL}/api/execution/status?execution_id=${executionId}`
  );
  const statusData = await statusResponse.json();
  
  if (statusData.data.status === 'completed') {
    console.log('执行完成！');
  } else if (statusData.data.status === 'running') {
    console.log(`执行中: ${statusData.data.progress_percent}%`);
    setTimeout(checkStatus, 5000); // 5秒后再次查询
  }
};
checkStatus();
```

**流程图**:
```
生成计划 → 获取plan_id → 启动执行 → 获取execution_id → 轮询状态 → 完成
```

---

### 流程2：多方案对比决策

**适用场景**: 需要对比多个方案选择最优解

```javascript
// 步骤1: 生成计划（包含多水泵方案）
const planResponse = await fetch(`${BASE_URL}/api/irrigation/plan-generation`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    farm_id: "13944136728576",
    multi_pump_scenarios: true
  })
});
const planData = await planResponse.json();

// 步骤2: 查看多水泵方案对比
const scenarios = planData.multi_pump_scenarios.scenarios;
scenarios.forEach(scenario => {
  console.log(`方案: ${scenario.scenario_name}`);
  console.log(`  电费: ¥${scenario.total_electricity_cost}`);
  console.log(`  时长: ${scenario.total_eta_h}小时`);
  console.log(`  水泵: ${scenario.pumps_used.join(', ')}`);
});

// 步骤3: 用户选择最优方案后启动执行
const selectedPlanId = planData.plan_id;
// ... 启动执行（参考流程1步骤2）
```

---

### 流程3：智能优化方案生成

**适用场景**: 需要根据不同优化目标生成多个方案

```javascript
// 步骤1: 生成基础计划
const planResponse = await fetch(`${BASE_URL}/api/irrigation/plan-generation`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    farm_id: "13944136728576"
  })
});
const planData = await planResponse.json();
const planId = planData.plan_id;

// 步骤2: 生成优化方案
const optResponse = await fetch(`${BASE_URL}/api/irrigation/plan-optimization`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    original_plan_id: planId,
    optimization_goals: [
      "cost_minimization",
      "time_minimization",
      "balanced",
      "off_peak"
    ],
    constraints: {
      max_duration_hours: 24,
      electricity_price_schedule: {
        peak: { hours: [8,9,10,11,12,13,14,15,16,17,18,19,20,21], price: 1.0 },
        valley: { hours: [22,23,0,1,2,3,4,5,6,7], price: 0.4 }
      }
    }
  })
});
const optData = await optResponse.json();

// 步骤3: 展示优化方案对比
console.log(`推荐方案: ${optData.comparison.recommended}`);
console.log(`最大节省: ${optData.comparison.cost_range.savings_percent}%`);

optData.scenarios.forEach(scenario => {
  console.log(`\n${scenario.name}`);
  console.log(`说明: ${scenario.description}`);
  console.log(`电费: ¥${scenario.total_electricity_cost}`);
  console.log(`时长: ${scenario.total_eta_h}小时`);
});

// 步骤4: 用户选择方案后执行（使用选中方案的plan数据）
```

---

### 流程4：实时水位更新与计划调整

**适用场景**: 执行过程中根据实时水位调整计划

```javascript
// 步骤1: 启动执行（参考流程1）
// ...

// 步骤2: 接收传感器水位数据并更新
const updateWaterLevel = async (fieldId, waterLevel) => {
  await fetch(`${BASE_URL}/api/water-levels/update`, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify({
      farm_id: "13944136728576",
      field_id: fieldId,
      water_level_mm: waterLevel,
      source: "sensor",
      quality: "good"
    })
  });
};

// 模拟传感器数据更新
updateWaterLevel("S3-G2-F1", 28.5);
updateWaterLevel("S3-G3-F2", 32.1);

// 步骤3: 系统会自动根据新水位重新生成计划（如果启用了enable_plan_regeneration）
// 前端可以通过查询执行状态监控重新生成次数
const statusResponse = await fetch(
  `${BASE_URL}/api/execution/status?execution_id=${executionId}`
);
const statusData = await statusResponse.json();
console.log(`计划已重新生成 ${statusData.data.total_regenerations} 次`);
```

---

### 流程5：批次编辑与重新生成 

**适用场景**: 手动调整批次内容（添加/删除田块、调整时间等）

```javascript
// 步骤1: 生成初始计划
const planResponse = await fetch(`${BASE_URL}/api/irrigation/plan-generation`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    farm_id: "13944136728576"
  })
});
const planData = await planResponse.json();
const planId = planData.plan_id;

// 步骤2: 查看批次详情
const batchResponse = await fetch(`${BASE_URL}/api/batches/1/details`);
const batchData = await batchResponse.json();
console.log('当前批次田块:', batchData.fields.map(f => f.id));

// 步骤3: 修改批次（添加田块、调整时间）
const regenResponse = await fetch(`${BASE_URL}/api/regeneration/batch`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    original_plan_id: planId,
    field_modifications: [
      { field_id: "S3-G5-F1", action: "add", custom_water_level: 95.0 },
      { field_id: "S3-G5-F2", action: "remove" }
    ],
    time_modifications: [
      { batch_index: 1, start_time_h: 2.0, duration_h: 10.0 }
    ]
  })
});
const regenData = await regenResponse.json();

// 步骤4: 使用修改后的计划执行
// 使用 regenData.modified_plan 或保存的新计划文件
```

---

## 错误码说明
### HTTP 状态码

| 状态码 | 说明 | 处理建议 |
|--------|------|----------|
| 200 | 成功 | 正常处理响应数据 |
| 400 | 请求参数错误 | 检查请求参数格式和必填项 |
| 404 | 资源不存在 | 检查plan_id、execution_id等是否正确 |
| 500 | 服务器内部错误 | 查看detail字段获取详细错误信息 |

### 业务错误码

错误响应格式：
```json
{
  "detail": "错误描述信息"
}
```

**常见错误及解决方法**:

| 错误信息 | 原因 | 解决方法 |
|---------|------|----------|
| "未找到计划: {plan_id}" | plan_id不存在或路径错误 | 确保使用生成接口返回的完整plan_id |
| "灌溉计划文件不存在" | 计划文件已被删除 | 重新生成计划 |
| "启动动态执行失败: 无法加载灌溉计划" | plan_file_path格式错误 | 使用正确的完整路径 |
| "批次 {index} 不存在" | 批次索引超出范围 | 检查批次索引范围（从1开始） |
| "调度器未初始化" | 系统组件未就绪 | 等待或调用健康检查确认系统状态 |

---

## 常见问题

### Q1: plan_id和execution_id的区别
**A**: 
- `plan_id`: 灌溉计划文件的路径，由**生成计划接口**返回，格式如 `/app/output/irrigation_plan_20250109_123456.json`
- `execution_id`: 执行任务的唯一标识，由**启动执行接口**返回，格式如 `exec_20250109_123456`

**使用场景**:
- `plan_id` → 用于启动执行、优化、重新生成等需要计划文件的接口
- `execution_id` → 用于查询执行状态、停止执行等管理执行任务的接口

---

### Q2: 获取 plan_id的方法
**A**: 有两种方式：

**方式1: 从生成接口获取**（推荐）
```javascript
const response = await fetch('/api/irrigation/plan-generation', {...});
const data = await response.json();
const planId = data.plan_id; // 这就是plan_id
```
**方式2: 从文件系统获取**（不推荐）
```
最新计划文件通常在: /app/output/irrigation_plan_YYYYMMDD_HHMMSS.json
```

---

### Q3: 多水泵方案对比和计划优化的区别
**A**: 

| 特性 | 多水泵方案对比 | 计划优化 |
|------|---------------|----------|
| **对比维度** | 不同水泵组合 | 不同优化目标 |
| **方案类型** | P1单独、P2单独、P1+P2组合等 | 成本最小、时间最小、均衡、避峰等 |
| **使用时机** | 计划生成时或独立调用 | 已有基础计划后优化 |
| **接口** | `/api/irrigation/multi-pump-scenarios` | `/api/irrigation/plan-optimization` |

**推荐用法**:
1. 先生成基础计划（可选multi_pump_scenarios）
2. 如需进一步优化，调用优化接口
3. 对比所有方案，选择最优

---

### Q4: 实现实时水位更新
**A**: 有两种方式：

**方式1: 自动更新**（推荐）
```javascript
// 启动执行时启用自动水位更新
{
  enable_plan_regeneration: true,
  water_level_update_interval_minutes: 30
}
// 系统会自动定期获取最新水位并重新生成计划
```

**方式2: 手动更新**
```javascript
// 1. 主动推送水位数据
await fetch('/api/water-levels/update', {
  body: JSON.stringify({
    field_id: "S3-G2-F1",
    water_level_mm: 28.5
  })
});

// 2. 手动触发重新生成
await fetch('/api/regeneration/manual', {
  body: JSON.stringify({
    batch_index: 1,
    force_regeneration: true
  })
});
```

---

### Q5: 处理执行失败

**A**: 标准错误处理流程：

```javascript
try {
  const response = await fetch('/api/execution/start', {...});
  
  if (!response.ok) {
    const error = await response.json();
    console.error('执行失败:', error.detail);
    
    // 根据错误类型处理
    if (response.status === 404) {
      // 计划文件不存在，重新生成计划
      await generateNewPlan();
    } else if (response.status === 500) {
      // 服务器错误，记录并通知用户
      logError(error.detail);
      notifyUser('系统错误，请联系管理员');
    }
  }
  
  const data = await response.json();
  // 正常处理
  
} catch (error) {
  console.error('网络错误:', error);
  notifyUser('网络连接失败，请检查网络');
}
```

---

### Q6: 批次索引从0开始还是从1开始
**A**: **从1开始**

```javascript
// 正确 ✅
GET /api/batches/1/details  // 获取第1个批次

// 错误 ❌
GET /api/batches/0/details  // 会返回404
```

**注意**: 
- API接口中的batch_index：**从1开始**
- 内部数组索引：从0开始（开发者无需关心）

---

### Q7: 轮询执行状态

**A**: 推荐使用以下轮询策略：

```javascript
const pollExecutionStatus = (executionId, onUpdate, onComplete) => {
  let pollInterval;
  
  const checkStatus = async () => {
    try {
      const response = await fetch(
        `/api/execution/status?execution_id=${executionId}`
      );
      const data = await response.json();
      
      // 回调更新UI
      onUpdate(data.data);
      
      // 检查是否完成
      if (data.data.status === 'completed' || 
          data.data.status === 'failed' ||
          data.data.status === 'stopped') {
        clearInterval(pollInterval);
        onComplete(data.data);
      }
    } catch (error) {
      console.error('状态查询失败:', error);
    }
  };
  
  // 初始查询
  checkStatus();
  
  // 每5秒轮询一次
  pollInterval = setInterval(checkStatus, 5000);
  
  // 返回停止轮询的函数
  return () => clearInterval(pollInterval);
};

// 使用示例
const stopPolling = pollExecutionStatus(
  executionId,
  (status) => {
    // 更新进度条
    updateProgressBar(status.progress_percent);
    updateCurrentBatch(status.current_batch);
  },
  (finalStatus) => {
    console.log('执行完成!', finalStatus);
  }
);
```


## 附录

### A. 完整的请求示例（Axios）

```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://120.55.127.125/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// 请求拦截器（可添加认证）
api.interceptors.request.use(config => {
  // 未来版本可添加 token
  // config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 响应拦截器（统一错误处理）
api.interceptors.response.use(
  response => response.data,
  error => {
    console.error('API Error:', error.response?.data || error.message);
    return Promise.reject(error.response?.data || error);
  }
);

// 使用示例
const generatePlan = async () => {
  try {
    const data = await api.post('/irrigation/plan-generation', {
      farm_id: '13944136728576',
      multi_pump_scenarios: true
    });
    return data;
  } catch (error) {
    throw error;
  }
};
```

---

### B. TypeScript 类型定义

```typescript
// 基础响应类型
interface ApiResponse<T = any> {
  success: boolean;
  message?: string;
  data?: T;
}

// 灌溉计划响应
interface PlanGenerationResponse {
  success: boolean;
  message: string;
  plan_id: string;
  data: IrrigationPlan;
  multi_pump_scenarios?: MultiPumpScenarios;
}

// 灌溉计划数据
interface IrrigationPlan {
  calc: {
    A_cover_mu: number;
    q_avail_m3ph: number;
    t_win_h: number;
    d_target_mm: number;
  };
  batches: Batch[];
  steps: Step[];
}

// 批次数据
interface Batch {
  index: number;
  area_mu: number;
  fields: Field[];
  stats: {
    deficit_vol_m3: number;
    cap_vol_m3: number;
    eta_hours: number;
  };
}

// 田块数据
interface Field {
  id: string;
  area_mu: number;
  segment_id: string;
  distance_rank: number;
  wl_mm: number;
  inlet_G_id: string;
}

// 执行状态
interface ExecutionStatus {
  execution_id: string;
  status: 'running' | 'paused' | 'completed' | 'failed' | 'stopped';
  start_time: string;
  current_batch: number;
  total_batches: number;
  progress_percent: number;
  total_regenerations: number;
}
```

---

### C. 快速参考表

**核心接口速查**

| 功能 | 方法 | 路径 | 关键参数 | 参数含义 |
|------|------|------|----------|----------|
| 生成计划 | POST | `/api/irrigation/plan-generation` | `farm_id`, `multi_pump_scenarios` | 农场ID，是否生成多方案对比 |
| 启动执行 | POST | `/api/execution/start` | `plan_file_path`, `farm_id`, `execution_mode` | 计划文件路径，农场ID，执行模式(模拟/生产) |
| 查询状态 | GET | `/api/execution/status` | `execution_id` | 执行任务ID |
| 多泵对比 | POST | `/api/irrigation/multi-pump-scenarios` | `config_file`, `active_pumps` | 配置文件，可用水泵列表 |
| 计划优化 | POST | `/api/irrigation/plan-optimization` | `original_plan_id`, `optimization_goals` | 原始计划ID，优化目标列表 |
| 批次详情 | GET | `/api/batches/{index}/details` | `batch_index` | 批次索引（从1开始） |
| 更新水位 | POST | `/api/water-levels/update` | `field_id`, `water_level_mm` | 田块ID，水位值(mm) |

**重要ID类型对照**

| ID类型 | 格式 | 示例 | 获取来源 | 用途 |
|--------|------|------|----------|------|
| farm_id | 数字字符串 | `"13944136728576"` | 系统配置 | 标识农场，所有接口都需要 |
| plan_id | 文件路径 | `"/app/output/irrigation_plan_*.json"` | 生成计划接口返回 | 启动执行、优化、重新生成 |
| execution_id | exec_前缀 | `"exec_20250109_123456"` | 启动执行接口返回 | 查询状态、停止执行 |
| field_id | S-G-F格式 | `"S3-G2-F1"` | 配置文件 | 水位更新、田块操作 |
| batch_index | 整数(≥1) | `1`, `2`, `3` | 计划文件中 | 批次查询、批次修改 |

**常用参数值对照**

| 参数名 | 可选值 | 说明 | 推荐值 |
|--------|--------|------|--------|
| execution_mode | `simulation`, `production` | 模拟模式 / 生产模式 | 测试:`simulation`，正式:`production` |
| source | `sensor`, `manual`, `estimated` | 传感器 / 手动 / 估算 | 优先使用:`sensor` |
| quality | `good`, `fair`, `poor` | 良好 / 一般 / 较差 | 传感器:`good`，人工:`fair` |
| optimization_goals | `cost_minimization`, `time_minimization`, `balanced`, `off_peak`, `water_saving` | 成本优先 / 时间优先 / 均衡 / 避峰 / 节水 | 日常使用:`balanced` |




