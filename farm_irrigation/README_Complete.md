# 农场灌溉调度系统 - 完整文档

## 目录

1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [自动化流水线](#自动化流水线)
4. [API接口文档](#api接口文档)
5. [批次重新生成功能](#批次重新生成功能)
6. [配置文件说明](#配置文件说明)
7. [故障排除](#故障排除)

---

## 系统概述

农场灌溉调度系统是一个智能化的农业灌溉管理平台，提供从数据预处理到灌溉计划生成的完整解决方案。系统支持多种运行模式，包括命令行、Web API和自动化流水线。

### 核心功能

- **智能调度算法**：基于田块水位、面积和距离的优化调度
- **实时数据融合**：支持实时水位数据的动态融合
- **批次管理**：灵活的批次重新生成和修改功能
- **多种接口**：命令行、Web API、自动化流水线
- **可视化输出**：生成详细的灌溉计划和统计报告

---

## 快速开始

### 环境准备

1. **安装依赖**

```bash
cd f:/irrigation_schedule/farm_irrigation
pip install -r requirements.txt
```

2. **准备数据文件**
   将GIS数据文件放入输入目录（默认：`./gzp_farm`）：

- 渠段数据：`港中坪水路_code.geojson`
- 节制闸数据：`港中坪阀门与节制闸_code.geojson`
- 田块数据：`港中坪田块_code.geojson`

### 运行方式

**方式1：自动化流水线（推荐）**

```bash
python pipeline.py
```

**方式2：分步执行**

```bash
# 1. 数据预处理
python farmgis_convert.py
python fix_farmgis_convert.py

# 2. 配置生成
python auto_to_config.py

# 3. 计划生成
python run_irrigation_plan.py --config config.json --output plan.json
```

**方式3：API服务**

```bash
python api_server.py
```

---

## 自动化流水线

### 概述

自动化流水线将原本需要手动执行的多个步骤整合为一键执行，大大简化了使用流程。

#### 原始流程 vs 自动化流程

**原始流程（手动执行）：**

```bash
# 1. 数据预处理
python farmgis_convert.py
python fix_farmgis_convert.py

# 2. 配置生成
python auto_to_config.py

# 3. 计划生成
python run_irrigation_plan.py --config config.json --output plan.json
```

**自动化流程（一键执行）：**

```bash
# 方式1: 命令行
python pipeline.py --input-dir ./gzp_farm --output-dir ./output

# 方式2: 配置文件
python pipeline.py --config pipeline_config.yaml

# 方式3: Windows批处理（双击运行）
run_pipeline.bat
```

### 执行方式

#### 方式1：快速执行（推荐新手）

**Windows用户：**

```bash
# 双击运行批处理文件
run_pipeline.bat
```

**Linux/Mac用户：**

```bash
python pipeline.py
```

#### 方式2：命令行参数

```bash
# 基本用法
python pipeline.py --input-dir ./data --output-dir ./results

# 指定泵站和供区
python pipeline.py --pumps 1,2,3 --zones A,B --input-dir ./data

# 不融合实时水位数据
python pipeline.py --no-waterlevels --input-dir ./data

# 详细输出
python pipeline.py --verbose --input-dir ./data
```

#### 方式3：配置文件（推荐生产环境）

1. 编辑配置文件 `pipeline_config.yaml`：

```yaml
input_dir: "./gzp_farm"
output_dir: "./output"
options:
  pumps: "1,2"
  zones: "A,B"
  merge_waterlevels: true
  print_summary: true
```

2. 执行：

```bash
python pipeline.py --config pipeline_config.yaml
```

### 命令行参数


| 参数               | 说明           | 默认值       | 示例                     |
| ------------------ | -------------- | ------------ | ------------------------ |
| `--input-dir`      | 输入数据目录   | `./gzp_farm` | `--input-dir ./data`     |
| `--output-dir`     | 输出目录       | `./output`   | `--output-dir ./results` |
| `--config`         | 配置文件路径   | -            | `--config config.yaml`   |
| `--pumps`          | 启用的泵站列表 | -            | `--pumps 1,2,3`          |
| `--zones`          | 启用的供区列表 | -            | `--zones A,B,C`          |
| `--no-waterlevels` | 不融合实时水位 | false        | `--no-waterlevels`       |
| `--no-summary`     | 不打印摘要     | false        | `--no-summary`           |
| `--verbose`        | 详细输出       | false        | `--verbose`              |

---

## API接口文档

### 服务启动

```bash
# 基本启动
python api_server.py

# 指定端口和地址
python api_server.py --host 0.0.0.0 --port 8080

# 开发模式（自动重载）
python api_server.py --reload
```

### API端点

#### POST `/api/irrigation/plan-with-upload`

生成灌溉计划（支持文件上传）

**请求参数：**


| 参数名               | 类型    | 必填 | 默认值           | 说明                           |
| -------------------- | ------- | ---- | ---------------- | ------------------------------ |
| farm_id              | string  | 否   | "13944136728576" | 农场ID（用于获取实时水位数据） |
| target_depth_mm      | float   | 否   | 90.0             | 目标灌溉深度(mm)               |
| pumps                | string  | 否   | null             | 启用的泵站，逗号分隔           |
| zones                | string  | 否   | null             | 启用的供区，逗号分隔           |
| merge_waterlevels    | boolean | 否   | true             | 是否融合实时水位               |
| print_summary        | boolean | 否   | true             | 是否返回摘要信息               |
| multi_pump_scenarios | boolean | 否   | false            | 是否生成多泵方案               |
| custom_waterlevels   | string  | 否   | null             | 自定义水位数据                 |
| files                | file[]  | 否   | []               | Shapefile文件组合              |

#### POST `/api/irrigation/multi-pump-scenarios`

生成多水泵方案

#### POST `/api/irrigation/regenerate-batch`

批次重新生成（详见批次重新生成功能章节）

#### GET `/api/irrigation/batch-info/{plan_id}`

获取批次信息

#### GET `/api/health`

健康检查

#### GET `/`

服务根路径

**请求示例：**

```bash
# 使用现有数据生成计划
curl --location 'http://127.0.0.1:8000/api/irrigation/plan-with-upload' \
--header 'Content-Type: application/x-www-form-urlencoded' \
--data-urlencode 'farm_id=13944136728576' \
--data-urlencode 'target_depth_mm=90' \
--data-urlencode 'merge_waterlevels=true' \
--data-urlencode 'print_summary=true'
```

**响应格式：**

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
            "active_pumps": ["P1", "P2"],
            "filtered_by_feed_by": 0,
            "allowed_zones": null,
            "skipped_null_wl_count": 2,
            "skipped_null_wl_fields": ["42", "43"]
        },
        "drainage_targets": [],
        "batches": [
            {
                "index": 1,
                "area_mu": 155.06,
                "fields": [...],
                "stats": {
                    "deficit_vol_m3": 9303.6046518,
                    "cap_vol_m3": 9600.0,
                    "eta_hours": 19.38250969125
                }
            }
        ],
        "steps": [...]
    }
}
```

---

## 批次重新生成功能

### 概述

批次重新生成API允许前端根据用户的修改（添加或移除田块）重新生成灌溉批次计划，而无需重新运行完整的灌溉管道。

### API端点

#### POST `/api/irrigation/regenerate-batch`

根据田块修改请求重新生成灌溉批次计划。

#### 请求参数

```json
{
  "original_plan_id": "irrigation_plan_20250926_134301.json",
  "field_modifications": [
    {
      "field_id": "S5-G33-F23",
      "action": "remove"
    },
    {
      "field_id": "S5-G35-F24",
      "action": "add",
      "custom_water_level": 5.0
    }
  ],
  "regeneration_params": {
    "batch_size_limit": 10,
    "priority_segments": ["S4", "S5"]
  }
}
```

#### 参数说明

- **original_plan_id** (string): 原始计划ID或文件路径
- **field_modifications** (array): 田块修改列表
  - **field_id** (string): 田块ID
  - **action** (string): 操作类型，`"add"` 或 `"remove"`
  - **custom_water_level** (number, 可选): 自定义水位(mm)
- **regeneration_params** (object, 可选): 重新生成参数

#### 响应格式

```json
{
  "success": true,
  "message": "批次计划重新生成成功，已保存到 irrigation_plan_modified_1640995200.json",
  "original_plan": {...},
  "modified_plan": {...},
  "modifications_summary": {
    "added_fields": ["S5-G35-F24"],
    "removed_fields": ["S5-G33-F23"],
    "total_modifications": 2,
    "regeneration_timestamp": 1640995200
  }
}
```

### 功能特性

1. **智能田块管理**

   - 添加田块：将新田块添加到灌溉计划中
   - 移除田块：从现有计划中移除指定田块
   - 自定义水位：支持为添加的田块设置自定义水位
2. **批次重新生成**

   - 自动重排：根据段ID和距离重新排列田块
   - 批次优化：按照配置的批次大小限制重新分组
   - 统计更新：自动更新面积、缺水量等统计信息
3. **缓存机制**

   - 智能缓存：基于请求参数生成缓存键
   - 性能优化：相同请求直接返回缓存结果
   - 过期管理：5分钟缓存过期时间

### 使用示例

#### 基本用法

```python
import requests

# 移除一个田块，添加另一个田块
request_data = {
    "original_plan_id": "irrigation_plan_20250926_134301.json",
    "field_modifications": [
        {
            "field_id": "S5-G33-F23",
            "action": "remove"
        },
        {
            "field_id": "S5-G35-F24",
            "action": "add",
            "custom_water_level": 10.0
        }
    ]
}

response = requests.post(
    "http://127.0.0.1:8000/api/irrigation/regenerate-batch",
    json=request_data
)

result = response.json()
print(f"修改成功: {result['success']}")
print(f"新计划包含 {len(result['modified_plan']['batches'])} 个批次")
```

---

## 配置文件说明

### pipeline_config.yaml

自动化流水线的配置文件，包含以下主要配置项：

```yaml
# 输入输出目录配置
input_dir: "./gzp_farm"          # GIS数据输入目录
output_dir: "./output"           # 输出目录

# 执行选项
options:
  pumps: "1,2"                   # 启用的泵站列表，逗号分隔
  zones: "A,B"                   # 启用的供区列表，逗号分隔
  merge_waterlevels: true        # 是否融合实时水位数据
  print_summary: true            # 是否打印执行摘要

# 高级配置（可选）
advanced:
  log_level: "INFO"              # 日志级别
  log_file: "pipeline.log"       # 日志文件名
  step_timeout: 300              # 每个步骤的超时时间（秒）
```

### auto_to_config.py 配置

`auto_to_config.py` 使用硬编码的默认配置参数，主要包括：

- **默认农场ID**: "13944136728576"
- **默认时间窗口**: 20.0小时
- **默认目标补水深度**: 90.0毫米
- **默认水位阈值**: 低水位80mm，最优100mm，高水位140mm
- **默认泵配置**: 额定流量300m³/h，效率0.8

### config.json

由 `auto_to_config.py` 生成的主配置文件，包含：

- 农场基本信息
- 渠段、闸门、田块数据
- 泵站配置
- 灌溉参数

---

## 故障排除

### 常见问题

#### 1. Python环境问题

**问题：** 找不到Python或版本不兼容

```
[错误] 未找到Python，请先安装Python 3.7+
```

**解决方案：**

- 安装Python 3.7+
- 确保Python添加到系统PATH
- 使用虚拟环境：

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

#### 2. 依赖包问题

**问题：** 缺少必要的Python包

```
ModuleNotFoundError: No module named 'fastapi'
```

**解决方案：**

```bash
pip install -r requirements.txt
```

#### 3. 数据文件问题

**问题：** 找不到GIS数据文件

```
[错误] 输入目录不存在: ./gzp_farm
```

**解决方案：**

- 检查数据文件路径
- 确保文件格式正确（GeoJSON）
- 验证文件权限

#### 4. API服务问题

**问题：** API服务启动失败

```
[ERROR] Address already in use
```

**解决方案：**

```bash
# 查找占用端口的进程
netstat -tulpn | grep :8000

# 杀死进程
kill -9 <process_id>

# 或使用不同端口
python api_server.py --port 8080
```

### 调试技巧

#### 1. 启用详细日志

```bash
python pipeline.py --verbose
```

#### 2. 查看日志文件

```bash
tail -f pipeline.log
```

#### 3. 单独测试模块

```bash
# 测试配置生成
python auto_to_config.py

# 测试计划生成
python run_irrigation_plan.py --config config.json

# 测试API服务
curl -X GET http://localhost:8000/api/health
```

---

*最后更新时间：2025年10月*
