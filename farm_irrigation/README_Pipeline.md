# 农场灌溉调度系统 - 自动化执行流水线

## 概述

本自动化流水线将原本需要手动执行的多个步骤整合为一键执行，大大简化了农场灌溉调度系统的使用流程。

### 原始流程 vs 自动化流程

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

## 快速开始

### 1. 环境准备

确保已安装Python 3.7+和所需依赖：
```bash
pip install -r requirements.txt
```

### 2. 准备数据文件

将GIS数据文件放入输入目录（默认：`./gzp_farm`）：
- 渠段数据：`*水路*.geojson` 或 `segments.geojson`
- 节制闸数据：`*阀门*.geojson` 或 `gates.geojson`
- 田块数据：`*田块*.geojson` 或 `fields.geojson`

### 3. 执行流水线

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

## 详细说明

### 执行步骤

流水线自动执行以下步骤：

1. **依赖检查**
   - 检查必要的Python脚本是否存在
   - 验证输入目录和文件

2. **数据预处理**（可选）
   - 如果发现Shapefile文件，自动运行格式转换
   - 执行数据修复和标准化

3. **配置生成**
   - 分析GIS数据的空间关系
   - 生成 `config.json` 配置文件
   - 输出标注文件到 `labeled_output/` 目录

4. **计划生成**
   - 基于配置文件生成灌溉计划
   - 可选融合实时水位数据
   - 输出JSON格式的灌溉指令

### 命令行参数

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `--input-dir` | 输入数据目录 | `./gzp_farm` | `--input-dir ./data` |
| `--output-dir` | 输出目录 | `./output` | `--output-dir ./results` |
| `--config` | 配置文件路径 | - | `--config config.yaml` |
| `--pumps` | 启用的泵站列表 | - | `--pumps 1,2,3` |
| `--zones` | 启用的供区列表 | - | `--zones A,B,C` |
| `--no-waterlevels` | 不融合实时水位 | false | `--no-waterlevels` |
| `--no-summary` | 不打印摘要 | false | `--no-summary` |
| `--verbose` | 详细输出 | false | `--verbose` |

### 配置文件格式

配置文件支持YAML和JSON格式，推荐使用YAML：

```yaml
# 基本配置
input_dir: "./gzp_farm"
output_dir: "./output"

# 执行选项
options:
  pumps: "1,2"                   # 启用的泵站
  zones: "A,B"                   # 启用的供区
  merge_waterlevels: true        # 融合实时水位
  print_summary: true            # 打印摘要

# 高级配置
advanced:
  log_level: "INFO"
  step_timeout: 300
  max_retries: 3

# 文件映射
file_mapping:
  segments: "港中坪水路_code.geojson"
  gates: "港中坪阀门与节制闸_code.geojson"
  fields: "港中坪田块_code.geojson"
```

### 输出文件

执行完成后，输出目录将包含：

```
output/
├── irrigation_plan_20240101_120000.json  # 灌溉计划文件
├── config.json                           # 系统配置文件
└── labeled_output/                       # 标注文件目录
    ├── fields_labeled.geojson
    ├── gates_labeled.geojson
    └── segments_labeled.geojson
```

### 日志文件

执行过程中的详细日志保存在 `pipeline.log` 文件中，包括：
- 每个步骤的执行状态
- 错误信息和警告
- 执行时间统计
- 生成的文件列表

## 故障排除

### 常见问题

1. **找不到Python**
   ```
   [错误] 未找到Python，请先安装Python 3.7+
   ```
   **解决方案：** 安装Python并确保添加到系统PATH

2. **缺少依赖文件**
   ```
   [错误] 缺少必要文件: ['auto_to_config.py']
   ```
   **解决方案：** 确保在正确的目录中运行，包含所有必要的Python脚本

3. **输入目录不存在**
   ```
   [错误] 输入目录不存在: ./data
   ```
   **解决方案：** 检查输入目录路径，确保目录存在且包含GIS数据文件

4. **步骤执行失败**
   ```
   [错误] 步骤2执行失败，流水线终止
   ```
   **解决方案：** 查看详细日志文件 `pipeline.log`，根据错误信息进行修复

### 调试技巧

1. **启用详细输出**
   ```bash
   python pipeline.py --verbose
   ```

2. **查看日志文件**
   ```bash
   tail -f pipeline.log
   ```

3. **单独测试步骤**
   ```bash
   # 测试配置生成
   python auto_to_config.py
   
   # 测试计划生成
   python run_irrigation_plan.py --config config.json
   ```

## 高级用法

### 批量处理

处理多个农场的数据：

```bash
# 创建批量处理脚本
for farm in farm1 farm2 farm3; do
    python pipeline.py --input-dir ./data/$farm --output-dir ./results/$farm
done
```

### 定时任务

设置定时执行（Linux/Mac）：

```bash
# 编辑crontab
crontab -e

# 每天早上6点执行
0 6 * * * cd /path/to/farm_irrigation && python pipeline.py
```

Windows任务计划程序：
1. 打开"任务计划程序"
2. 创建基本任务
3. 设置触发器和操作
4. 操作：启动程序 `run_pipeline.bat`

### 集成到Web服务

```python
# 在web_farm_irrigation_modified.py中集成
from pipeline import IrrigationPipeline

@app.route('/api/run_pipeline', methods=['POST'])
def run_pipeline_api():
    pipeline = IrrigationPipeline()
    success = pipeline.run_pipeline(
        input_dir=request.json.get('input_dir'),
        output_dir=request.json.get('output_dir')
    )
    return {'success': success}
```

## 性能优化

### 并行处理

对于大型农场，可以启用并行处理：

```yaml
# 在配置文件中添加
advanced:
  parallel_processing: true
  max_workers: 4
```

### 缓存机制

启用中间结果缓存：

```yaml
advanced:
  enable_cache: true
  cache_dir: "./cache"
```

## 贡献指南

欢迎提交问题和改进建议：

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 创建Pull Request

## 许可证

本项目采用MIT许可证，详见LICENSE文件。

## 联系方式

如有问题或建议，请联系：
- 邮箱：admin@example.com
- 项目地址：https://github.com/example/farm-irrigation