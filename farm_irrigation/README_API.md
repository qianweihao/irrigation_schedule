# 灌溉计划API

## 概述

本API服务提供农场灌溉计划生成功能，支持文件上传和参数配置的一体化接口。基于现有的灌溉调度算法，提供RESTful API接口供外部系统调用。


### 1. 安装依赖

```bash
cd f:/irrigation_schedule/farm_irrigation
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 基本启动
python api_server.py

# 指定端口和地址
python api_server.py --host 0.0.0.0 --port 8080

# 开发模式（自动重载）
python api_server.py --reload
```

## API接口

### 主要接口

#### POST /api/irrigation/plan-with-upload

生成灌溉计划（支持文件上传）

**请求参数：**


| 参数名            | 类型    | 必填 | 默认值 | 说明                                 |
| ----------------- | ------- | ---- | ------ | ------------------------------------ |
| farm_id           | string  | 是   | 无     | 农场ID（必填，用于获取实时水位数据） |
| target_depth_mm   | float   | 否   | 90.0   | 目标灌溉深度(mm)                     |
| pumps             | string  | 否   | null   | 启用的泵站，逗号分隔                 |
| zones             | string  | 否   | null   | 启用的供区，逗号分隔                 |
| merge_waterlevels | boolean | 否   | true   | 是否融合实时水位                     |
| print_summary     | boolean | 否   | true   | 是否返回摘要信息                     |
| files             | file[]  | 否   | []     | Shapefile文件组合                    |

**请求示例：**

```bash
# 使用现有数据生成计划（farm_id为必填参数）
curl --location 'http://120.55.127.125/api/irrigation/plan-with-upload' \
--header 'Content-Type: application/x-www-form-urlencoded' \
--data-urlencode 'farm_id=13944136728576' \
--data-urlencode 'target_depth_mm=90' \
--data-urlencode 'merge_waterlevels=true' \
--data-urlencode 'print_summary=true'
```

**响应示例：**

```json
{
    "success": true,
    "message": "灌溉计划生成成功",
    "plan": {
        "calc": {
            "A_cover_mu": 159.99992000004,
            "q_avail_m3ph": 480.0,
            "t_win_h": 20.0,
            "d_target_mm": 90.0,
            "active_pumps": [
                "P1",
                "P2"
            ],
            "filtered_by_feed_by": 0,
            "allowed_zones": null,
            "skipped_null_wl_count": 2,
            "skipped_null_wl_fields": [
                "42",
                "43"
            ]
        },
        "drainage_targets": [],
        "batches": [
            {
                "index": 1,
                "area_mu": 155.06,
                "fields": [
                    {
                        "id": "23",
                        "area_mu": 1.983,
                        "segment_id": "S2",
                        "distance_rank": 23,
                        "wl_mm": 0.0,
                        "inlet_G_id": "P2"
                    },
                    {
                        "id": "S3-G2-F1",
                        "area_mu": 5.225,
                        "segment_id": "S3",
                        "distance_rank": 1,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S3-G2"
                    },
                    {
                        "id": "S3-G3-F2",
                        "area_mu": 5.199,
                        "segment_id": "S3",
                        "distance_rank": 2,
                        "wl_mm": 1.0,
                        "inlet_G_id": "S3-G3"
                    },
                    {
                        "id": "S3-G5-F3",
                        "area_mu": 5.15,
                        "segment_id": "S3",
                        "distance_rank": 3,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S3-G5"
                    },
                    {
                        "id": "S3-G6-F4",
                        "area_mu": 5.118,
                        "segment_id": "S3",
                        "distance_rank": 4,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S3-G6"
                    },
                    {
                        "id": "5",
                        "area_mu": 1.819,
                        "segment_id": "S3",
                        "distance_rank": 5,
                        "wl_mm": 1.0,
                        "inlet_G_id": "S3-G12"
                    },
                    {
                        "id": "S3-G7-F5",
                        "area_mu": 5.21,
                        "segment_id": "S3",
                        "distance_rank": 5,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S3-G7"
                    },
                    {
                        "id": "S3-G8-F6",
                        "area_mu": 4.922,
                        "segment_id": "S3",
                        "distance_rank": 6,
                        "wl_mm": 1.2,
                        "inlet_G_id": "S3-G8"
                    },
                    {
                        "id": "S3-G10-F7",
                        "area_mu": 5.332,
                        "segment_id": "S3",
                        "distance_rank": 7,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S3-G10"
                    },
                    {
                        "id": "S3-G11-F8",
                        "area_mu": 5.266,
                        "segment_id": "S3",
                        "distance_rank": 8,
                        "wl_mm": 0.7000000000000001,
                        "inlet_G_id": "S3-G11"
                    },
                    {
                        "id": "10",
                        "area_mu": 1.752,
                        "segment_id": "S3",
                        "distance_rank": 10,
                        "wl_mm": 1.0,
                        "inlet_G_id": "S3-G12"
                    },
                    {
                        "id": "S4-G14-F9",
                        "area_mu": 5.778,
                        "segment_id": "S4",
                        "distance_rank": 9,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G14"
                    },
                    {
                        "id": "S4-G15-F10",
                        "area_mu": 4.853,
                        "segment_id": "S4",
                        "distance_rank": 10,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G15"
                    },
                    {
                        "id": "S4-G17-F11",
                        "area_mu": 5.944,
                        "segment_id": "S4",
                        "distance_rank": 11,
                        "wl_mm": 2.2,
                        "inlet_G_id": "S4-G17"
                    },
                    {
                        "id": "S4-G18-F12",
                        "area_mu": 4.521,
                        "segment_id": "S4",
                        "distance_rank": 12,
                        "wl_mm": 6.2,
                        "inlet_G_id": "S4-G18"
                    },
                    {
                        "id": "S4-G19-F13",
                        "area_mu": 5.963,
                        "segment_id": "S4",
                        "distance_rank": 13,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G19"
                    },
                    {
                        "id": "S4-G20-F14",
                        "area_mu": 4.626,
                        "segment_id": "S4",
                        "distance_rank": 14,
                        "wl_mm": 2.5,
                        "inlet_G_id": "S4-G20"
                    },
                    {
                        "id": "S4-G21-F15",
                        "area_mu": 7.287,
                        "segment_id": "S4",
                        "distance_rank": 15,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G21"
                    },
                    {
                        "id": "16",
                        "area_mu": 5.676,
                        "segment_id": "S4",
                        "distance_rank": 16,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G25"
                    },
                    {
                        "id": "S4-G22-F16",
                        "area_mu": 5.984,
                        "segment_id": "S4",
                        "distance_rank": 16,
                        "wl_mm": 5.2,
                        "inlet_G_id": "S4-G22"
                    },
                    {
                        "id": "S4-G23-F17",
                        "area_mu": 6.504,
                        "segment_id": "S4",
                        "distance_rank": 17,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S4-G23"
                    },
                    {
                        "id": "S4-G24-F18",
                        "area_mu": 4.606,
                        "segment_id": "S4",
                        "distance_rank": 18,
                        "wl_mm": 2.2,
                        "inlet_G_id": "S4-G24"
                    },
                    {
                        "id": "S5-G27-F19",
                        "area_mu": 7.672,
                        "segment_id": "S5",
                        "distance_rank": 19,
                        "wl_mm": 1.7999999999999998,
                        "inlet_G_id": "S5-G27"
                    },
                    {
                        "id": "S5-G29-F20",
                        "area_mu": 7.93,
                        "segment_id": "S5",
                        "distance_rank": 20,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S5-G29"
                    },
                    {
                        "id": "S5-G30-F21",
                        "area_mu": 7.916,
                        "segment_id": "S5",
                        "distance_rank": 21,
                        "wl_mm": 0.8999999999999999,
                        "inlet_G_id": "S5-G30"
                    },
                    {
                        "id": "S5-G32-F22",
                        "area_mu": 10.752,
                        "segment_id": "S5",
                        "distance_rank": 22,
                        "wl_mm": 1.2,
                        "inlet_G_id": "S5-G32"
                    },
                    {
                        "id": "S5-G33-F23",
                        "area_mu": 8.19,
                        "segment_id": "S5",
                        "distance_rank": 23,
                        "wl_mm": 1.3,
                        "inlet_G_id": "S5-G33"
                    },
                    {
                        "id": "S5-G35-F24",
                        "area_mu": 3.882,
                        "segment_id": "S5",
                        "distance_rank": 24,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S5-G35"
                    }
                ],
                "stats": {
                    "deficit_vol_m3": 9303.6046518,
                    "cap_vol_m3": 9600.0,
                    "eta_hours": 19.38250969125
                }
            },
            {
                "index": 2,
                "area_mu": 102.582,
                "fields": [
                    {
                        "id": "S6-G37-F25",
                        "area_mu": 8.36,
                        "segment_id": "S6",
                        "distance_rank": 25,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S6-G37"
                    },
                    {
                        "id": "S6-G39-F26",
                        "area_mu": 8.446,
                        "segment_id": "S6",
                        "distance_rank": 26,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S6-G39"
                    },
                    {
                        "id": "S6-G40-F27",
                        "area_mu": 8.494,
                        "segment_id": "S6",
                        "distance_rank": 27,
                        "wl_mm": 0.0,
                        "inlet_G_id": "S6-G40"
                    },
                    {
                        "id": "S6-G42-F28",
                        "area_mu": 12.532,
                        "segment_id": "S6",
                        "distance_rank": 28,
                        "wl_mm": 0.7000000000000001,
                        "inlet_G_id": "S6-G42"
                    },
                    {
                        "id": "S6-G43-F29",
                        "area_mu": 8.983,
                        "segment_id": "S6",
                        "distance_rank": 29,
                        "wl_mm": 0.7000000000000001,
                        "inlet_G_id": "S6-G43"
                    },
                    {
                        "id": "S6-G45-F30",
                        "area_mu": 6.069,
                        "segment_id": "S6",
                        "distance_rank": 30,
                        "wl_mm": 3.5,
                        "inlet_G_id": "S6-G45"
                    },
                    {
                        "id": "S7-G47-F31",
                        "area_mu": 9.432,
                        "segment_id": "S7",
                        "distance_rank": 31,
                        "wl_mm": 0.8,
                        "inlet_G_id": "S7-G47"
                    },
                    {
                        "id": "S7-G49-F32",
                        "area_mu": 10.288,
                        "segment_id": "S7",
                        "distance_rank": 32,
                        "wl_mm": 1.5,
                        "inlet_G_id": "S7-G49"
                    },
                    {
                        "id": "S7-G50-F33",
                        "area_mu": 9.098,
                        "segment_id": "S7",
                        "distance_rank": 33,
                        "wl_mm": 1.1,
                        "inlet_G_id": "S7-G50"
                    },
                    {
                        "id": "S7-G51-F34",
                        "area_mu": 8.303,
                        "segment_id": "S7",
                        "distance_rank": 34,
                        "wl_mm": 1.3,
                        "inlet_G_id": "S7-G51"
                    },
                    {
                        "id": "S8-G52-F35",
                        "area_mu": 8.921,
                        "segment_id": "S8",
                        "distance_rank": 35,
                        "wl_mm": 4.0,
                        "inlet_G_id": "S8-G52"
                    },
                    {
                        "id": "S8-G53-F36",
                        "area_mu": 3.656,
                        "segment_id": "S8",
                        "distance_rank": 36,
                        "wl_mm": 2.0,
                        "inlet_G_id": "S8-G53"
                    }
                ],
                "stats": {
                    "deficit_vol_m3": 6154.92307746,
                    "cap_vol_m3": 9600.0,
                    "eta_hours": 12.822756411375
                }
            }
        ],
        "steps": [
            {
                "t_start_h": 0.0,
                "t_end_h": 19.38250969125,
                "label": "批次 1",
                "commands": [
                    {
                        "action": "start",
                        "target": "P2",
                        "value": null,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "start",
                        "target": "P1",
                        "value": null,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S1-G1",
                        "value": 0.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S1-G26",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S3-G4",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S3-G9",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S3-G12",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S4-G13",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S4-G16",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S4-G25",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S5-G28",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S5-G31",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S5-G34",
                        "value": 100.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "set",
                        "target": "S5-G36",
                        "value": 0.0,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "stop",
                        "target": "P1",
                        "value": null,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    },
                    {
                        "action": "stop",
                        "target": "P2",
                        "value": null,
                        "t_start_h": 0.0,
                        "t_end_h": 19.38250969125
                    }
                ],
                "sequence": {
                    "pumps_on": [
                        "P2",
                        "P1"
                    ],
                    "gates_open": [
                        "S1-G26",
                        "S3-G4",
                        "S3-G9",
                        "S3-G12",
                        "S4-G13",
                        "S4-G16",
                        "S4-G25",
                        "S5-G28",
                        "S5-G31",
                        "S5-G34"
                    ],
                    "gates_close": [
                        "S1-G1",
                        "S5-G36"
                    ],
                    "gates_set": [
                        {
                            "id": "S1-G1",
                            "open_pct": 0,
                            "type": "main-g"
                        },
                        {
                            "id": "S1-G26",
                            "open_pct": 100,
                            "type": "main-g"
                        },
                        {
                            "id": "S3-G4",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S3-G9",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S3-G12",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S4-G13",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S4-G16",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S4-G25",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S5-G28",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S5-G31",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S5-G34",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S5-G36",
                            "open_pct": 0,
                            "type": "branch-g"
                        }
                    ],
                    "fields": [
                        "23",
                        "S3-G2-F1",
                        "S3-G3-F2",
                        "S3-G5-F3",
                        "S3-G6-F4",
                        "5",
                        "S3-G7-F5",
                        "S3-G8-F6",
                        "S3-G10-F7",
                        "S3-G11-F8",
                        "10",
                        "S4-G14-F9",
                        "S4-G15-F10",
                        "S4-G17-F11",
                        "S4-G18-F12",
                        "S4-G19-F13",
                        "S4-G20-F14",
                        "S4-G21-F15",
                        "16",
                        "S4-G22-F16",
                        "S4-G23-F17",
                        "S4-G24-F18",
                        "S5-G27-F19",
                        "S5-G29-F20",
                        "S5-G30-F21",
                        "S5-G32-F22",
                        "S5-G33-F23",
                        "S5-G35-F24"
                    ],
                    "pumps_off": [
                        "P1",
                        "P2"
                    ]
                },
                "full_order": [
                    {
                        "type": "pump_on",
                        "id": "P2"
                    },
                    {
                        "type": "pump_on",
                        "id": "P1"
                    },
                    {
                        "type": "regulator_set",
                        "id": "S1-G1",
                        "open_pct": 0
                    },
                    {
                        "type": "regulator_set",
                        "id": "S1-G26",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S3-G4",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S3-G9",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S3-G12",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S4-G13",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S4-G16",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S4-G25",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S5-G28",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S5-G31",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S5-G34",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S5-G36",
                        "open_pct": 0
                    },
                    {
                        "type": "field",
                        "id": "23",
                        "inlet_G_id": "P2"
                    },
                    {
                        "type": "field",
                        "id": "S3-G2-F1",
                        "inlet_G_id": "S3-G2"
                    },
                    {
                        "type": "field",
                        "id": "S3-G3-F2",
                        "inlet_G_id": "S3-G3"
                    },
                    {
                        "type": "field",
                        "id": "S3-G5-F3",
                        "inlet_G_id": "S3-G5"
                    },
                    {
                        "type": "field",
                        "id": "S3-G6-F4",
                        "inlet_G_id": "S3-G6"
                    },
                    {
                        "type": "field",
                        "id": "5",
                        "inlet_G_id": "S3-G12"
                    },
                    {
                        "type": "field",
                        "id": "S3-G7-F5",
                        "inlet_G_id": "S3-G7"
                    },
                    {
                        "type": "field",
                        "id": "S3-G8-F6",
                        "inlet_G_id": "S3-G8"
                    },
                    {
                        "type": "field",
                        "id": "S3-G10-F7",
                        "inlet_G_id": "S3-G10"
                    },
                    {
                        "type": "field",
                        "id": "S3-G11-F8",
                        "inlet_G_id": "S3-G11"
                    },
                    {
                        "type": "field",
                        "id": "10",
                        "inlet_G_id": "S3-G12"
                    },
                    {
                        "type": "field",
                        "id": "S4-G14-F9",
                        "inlet_G_id": "S4-G14"
                    },
                    {
                        "type": "field",
                        "id": "S4-G15-F10",
                        "inlet_G_id": "S4-G15"
                    },
                    {
                        "type": "field",
                        "id": "S4-G17-F11",
                        "inlet_G_id": "S4-G17"
                    },
                    {
                        "type": "field",
                        "id": "S4-G18-F12",
                        "inlet_G_id": "S4-G18"
                    },
                    {
                        "type": "field",
                        "id": "S4-G19-F13",
                        "inlet_G_id": "S4-G19"
                    },
                    {
                        "type": "field",
                        "id": "S4-G20-F14",
                        "inlet_G_id": "S4-G20"
                    },
                    {
                        "type": "field",
                        "id": "S4-G21-F15",
                        "inlet_G_id": "S4-G21"
                    },
                    {
                        "type": "field",
                        "id": "16",
                        "inlet_G_id": "S4-G25"
                    },
                    {
                        "type": "field",
                        "id": "S4-G22-F16",
                        "inlet_G_id": "S4-G22"
                    },
                    {
                        "type": "field",
                        "id": "S4-G23-F17",
                        "inlet_G_id": "S4-G23"
                    },
                    {
                        "type": "field",
                        "id": "S4-G24-F18",
                        "inlet_G_id": "S4-G24"
                    },
                    {
                        "type": "field",
                        "id": "S5-G27-F19",
                        "inlet_G_id": "S5-G27"
                    },
                    {
                        "type": "field",
                        "id": "S5-G29-F20",
                        "inlet_G_id": "S5-G29"
                    },
                    {
                        "type": "field",
                        "id": "S5-G30-F21",
                        "inlet_G_id": "S5-G30"
                    },
                    {
                        "type": "field",
                        "id": "S5-G32-F22",
                        "inlet_G_id": "S5-G32"
                    },
                    {
                        "type": "field",
                        "id": "S5-G33-F23",
                        "inlet_G_id": "S5-G33"
                    },
                    {
                        "type": "field",
                        "id": "S5-G35-F24",
                        "inlet_G_id": "S5-G35"
                    },
                    {
                        "type": "pump_off",
                        "id": "P1"
                    },
                    {
                        "type": "pump_off",
                        "id": "P2"
                    }
                ]
            },
            {
                "t_start_h": 19.38250969125,
                "t_end_h": 32.205266102625004,
                "label": "批次 2",
                "commands": [
                    {
                        "action": "start",
                        "target": "P2",
                        "value": null,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "start",
                        "target": "P1",
                        "value": null,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S1-G1",
                        "value": 0.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S1-G26",
                        "value": 0.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S6-G38",
                        "value": 100.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S6-G41",
                        "value": 100.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S6-G44",
                        "value": 100.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S6-G46",
                        "value": 0.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S7-G48",
                        "value": 100.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S7-G52",
                        "value": 0.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "set",
                        "target": "S8-G54",
                        "value": 0.0,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "stop",
                        "target": "P1",
                        "value": null,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    },
                    {
                        "action": "stop",
                        "target": "P2",
                        "value": null,
                        "t_start_h": 19.38250969125,
                        "t_end_h": 32.205266102625004
                    }
                ],
                "sequence": {
                    "pumps_on": [
                        "P2",
                        "P1"
                    ],
                    "gates_open": [
                        "S6-G38",
                        "S6-G41",
                        "S6-G44",
                        "S7-G48"
                    ],
                    "gates_close": [
                        "S1-G1",
                        "S1-G26",
                        "S6-G46",
                        "S7-G52",
                        "S8-G54"
                    ],
                    "gates_set": [
                        {
                            "id": "S1-G1",
                            "open_pct": 0,
                            "type": "main-g"
                        },
                        {
                            "id": "S1-G26",
                            "open_pct": 0,
                            "type": "main-g"
                        },
                        {
                            "id": "S6-G38",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S6-G41",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S6-G44",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S6-G46",
                            "open_pct": 0,
                            "type": "branch-g"
                        },
                        {
                            "id": "S7-G48",
                            "open_pct": 100,
                            "type": "branch-g"
                        },
                        {
                            "id": "S7-G52",
                            "open_pct": 0,
                            "type": "branch-g"
                        },
                        {
                            "id": "S8-G54",
                            "open_pct": 0,
                            "type": "branch-g"
                        }
                    ],
                    "fields": [
                        "S6-G37-F25",
                        "S6-G39-F26",
                        "S6-G40-F27",
                        "S6-G42-F28",
                        "S6-G43-F29",
                        "S6-G45-F30",
                        "S7-G47-F31",
                        "S7-G49-F32",
                        "S7-G50-F33",
                        "S7-G51-F34",
                        "S8-G52-F35",
                        "S8-G53-F36"
                    ],
                    "pumps_off": [
                        "P1",
                        "P2"
                    ]
                },
                "full_order": [
                    {
                        "type": "pump_on",
                        "id": "P2"
                    },
                    {
                        "type": "pump_on",
                        "id": "P1"
                    },
                    {
                        "type": "regulator_set",
                        "id": "S1-G1",
                        "open_pct": 0
                    },
                    {
                        "type": "regulator_set",
                        "id": "S1-G26",
                        "open_pct": 0
                    },
                    {
                        "type": "regulator_set",
                        "id": "S6-G38",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S6-G41",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S6-G44",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S6-G46",
                        "open_pct": 0
                    },
                    {
                        "type": "regulator_set",
                        "id": "S7-G48",
                        "open_pct": 100
                    },
                    {
                        "type": "regulator_set",
                        "id": "S7-G52",
                        "open_pct": 0
                    },
                    {
                        "type": "regulator_set",
                        "id": "S8-G54",
                        "open_pct": 0
                    },
                    {
                        "type": "field",
                        "id": "S6-G37-F25",
                        "inlet_G_id": "S6-G37"
                    },
                    {
                        "type": "field",
                        "id": "S6-G39-F26",
                        "inlet_G_id": "S6-G39"
                    },
                    {
                        "type": "field",
                        "id": "S6-G40-F27",
                        "inlet_G_id": "S6-G40"
                    },
                    {
                        "type": "field",
                        "id": "S6-G42-F28",
                        "inlet_G_id": "S6-G42"
                    },
                    {
                        "type": "field",
                        "id": "S6-G43-F29",
                        "inlet_G_id": "S6-G43"
                    },
                    {
                        "type": "field",
                        "id": "S6-G45-F30",
                        "inlet_G_id": "S6-G45"
                    },
                    {
                        "type": "field",
                        "id": "S7-G47-F31",
                        "inlet_G_id": "S7-G47"
                    },
                    {
                        "type": "field",
                        "id": "S7-G49-F32",
                        "inlet_G_id": "S7-G49"
                    },
                    {
                        "type": "field",
                        "id": "S7-G50-F33",
                        "inlet_G_id": "S7-G50"
                    },
                    {
                        "type": "field",
                        "id": "S7-G51-F34",
                        "inlet_G_id": "S7-G51"
                    },
                    {
                        "type": "field",
                        "id": "S8-G52-F35",
                        "inlet_G_id": "S8-G52"
                    },
                    {
                        "type": "field",
                        "id": "S8-G53-F36",
                        "inlet_G_id": "S8-G53"
                    },
                    {
                        "type": "pump_off",
                        "id": "P1"
                    },
                    {
                        "type": "pump_off",
                        "id": "P2"
                    }
                ]
            }
        ],
        "total_eta_h": 32.205266102625004,
        "total_deficit_m3": 15458.52772926
    },
    "summary": "灌溉计划生成成功"
}
```

### 辅助接口

#### GET /api/health

健康检查接口

**响应示例：**

```json
{
  "status": "healthy",
  "message": "灌溉计划API服务运行正常"
}
```

#### GET /

根路径，返回服务信息

## 文件上传说明

### 支持的文件格式

- **Shapefile组合**：必须包含.shp、.dbf、.shx文件
- **可选文件**：.prj（投影信息）、.cpg（编码信息）等

### 文件命名规范

建议按照以下规范命名文件：

- 水路段：`*水路*.shp`
- 田块：`*田块*.shp` 或 `*field*.shp`
- 闸门：`*阀门*.shp` 或 `*gate*.shp`

### 上传注意事项

1. **文件完整性**：确保上传完整的Shapefile组合
2. **编码格式**：建议使用UTF-8编码
3. **坐标系统**：支持地理坐标系（WGS84等）和投影坐标系
4. **文件大小**：单个文件建议不超过50MB

## 错误处理

### 常见错误码


| 状态码 | 说明                    | 解决方案                           |
| ------ | ----------------------- | ---------------------------------- |
| 400    | 请求参数错误            | 检查参数格式和必填项               |
| 400    | 无效的shapefile文件组合 | 确保上传完整的.shp、.dbf、.shx文件 |
| 500    | 文件保存失败            | 检查磁盘空间和文件权限             |
| 500    | 灌溉计划生成失败        | 检查输入数据格式和算法参数         |

### 错误响应示例

```json
{
  "detail": "无效的shapefile文件组合，需要包含.shp, .dbf, .shx文件"
}
```

```
