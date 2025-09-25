# auto_to_config.py 配置文件说明

## 概述

`auto_to_config.py` 已经进行了重构，将原本硬编码的参数移到了配置文件 `auto_config_params.yaml` 中。这样做的好处是：

1. **提高灵活性**：无需修改代码即可调整参数
2. **便于维护**：配置集中管理，易于查找和修改
3. **环境适应性**：不同环境可以使用不同的配置文件
4. **保持数据驱动**：从GeoJSON获取的数据参数仍保留在代码中

## 配置文件结构

### auto_config_params.yaml

```yaml
# 默认农场ID
default_farm_id: "13944136728576"

# 默认时间窗口（小时）
default_time_window_h: 20.0

# 默认目标补水深度（毫米）
default_target_depth_mm: 90.0

# 默认渠道ID
default_canal_id: "C_A"

# 默认水位阈值（毫米）
default_water_levels:
  wl_low: 80.0
  wl_opt: 100.0
  wl_high: 140.0

# 默认田块配置
default_field_config:
  has_drain_gate: true
  rel_to_regulator: "downstream"

# 默认泵配置
default_pump:
  name: "AUTO"
  q_rated_m3ph: 300.0
  efficiency: 0.8

# 默认泵列表
default_pumps:
  - name: "P1"
    q_rated_m3ph: 300.0
    efficiency: 0.8

# 坐标系统配置
crs_config:
  geographic_crs: ["EPSG:4326", "EPSG:4490", "WGS84"]
  sqm_to_mu_factor: 666.6667

# 文件搜索路径配置
file_search_paths:
  data_paths: ["gzp_farm", "/mnt/data"]
  waterlevels_paths: ["waterlevels.json", "gzp_farm/waterlevels.json", "/mnt/data/waterlevels.json"]

# 默认文件名（仅在__main__中使用）
default_filenames:
  segments: "港中坪水路_code.geojson"
  gates: "港中坪阀门与节制闸_code.geojson"
  fields: "港中坪田块_code.geojson"

# 输出配置
output_config:
  config_file: "config.json"
  labeled_dir: "labeled_output"

# 环境变量名称配置
env_vars:
  farm_id: ["RICE_IRRIGATION_FARM_ID", "FARM_ID", "FARMID"]

# 默认距离排序值
default_distance_rank: 9999
```

## 保留在代码中的参数

以下参数仍然保留在代码中，因为它们是从GeoJSON数据中动态获取的：

### 从GeoJSON数据获取的参数：
- **段（segments）数据**：
  - `id`：从 `S_id/code/id` 字段获取
  - `type`：从 `type/类型` 字段获取
  - `regulator_gate_ids`：从闸门数据中筛选节制类闸门
  - `feed_by`：从 `feed_by/FEED_BY` 等字段获取

- **闸门（gates）数据**：
  - `id`：从 `code/Code/gate_code` 等字段获取
  - `type`：从 `type/类型` 字段获取
  - `q_max_m3ph`：固定为 9999.0（可考虑后续从数据中获取）

- **田块（fields）数据**：
  - `id`：从 `F_id/code/name/id` 字段获取
  - `sectionID`：严格从 `properties.id` 获取
  - `sectionCode`：从 `sectionCode/section_code/code` 等字段获取
  - `name`：从 `name/Name/地块名称` 等字段获取
  - `area_mu`：从几何形状计算得出
  - `segment_id`：从数据字段或通过算法推断
  - `distance_rank`：从ID中的数字尾缀计算
  - `wl_mm`：从水位数据字段或外部文件获取
  - `inlet_G_id`：从数据字段或通过算法推断

### 算法计算的参数：
- 坐标系统转换
- 最近邻计算
- 几何关系分析
- 数字尾缀解析
- 闸门归属段计算

## 使用方法

### 1. 基本使用

```python
from auto_to_config import convert

# 使用默认配置
result = convert(
    segments_path="segments.geojson",
    gates_path="gates.geojson",
    fields_path="fields.geojson"
)
```

### 2. 自定义配置

```python
# 覆盖特定参数
result = convert(
    segments_path="segments.geojson",
    gates_path="gates.geojson",
    fields_path="fields.geojson",
    t_win_h=24.0,  # 覆盖默认时间窗口
    d_target_mm=100.0,  # 覆盖默认目标深度
    farm_id="custom_farm_id"  # 覆盖默认农场ID
)
```

### 3. 修改配置文件

直接编辑 `auto_config_params.yaml` 文件来调整默认值：

```yaml
# 修改默认时间窗口为24小时
default_time_window_h: 24.0

# 修改默认水位阈值
default_water_levels:
  wl_low: 70.0
  wl_opt: 90.0
  wl_high: 120.0
```

### 4. 环境变量支持

可以通过环境变量设置农场ID：

```bash
export RICE_IRRIGATION_FARM_ID="your_farm_id"
# 或
export FARM_ID="your_farm_id"
# 或
export FARMID="your_farm_id"
```

## 配置优先级

参数的优先级顺序（从高到低）：

1. **函数参数**：直接传递给 `convert()` 函数的参数
2. **环境变量**：特定参数（如 farm_id）的环境变量
3. **配置文件**：`auto_config_params.yaml` 中的设置
4. **代码默认值**：配置文件不存在时的硬编码默认值

## 注意事项

1. **配置文件位置**：`auto_config_params.yaml` 应放在与 `auto_to_config.py` 相同的目录中

2. **YAML格式**：确保配置文件使用正确的YAML格式，注意缩进和语法

3. **依赖安装**：需要安装 PyYAML 依赖：
   ```bash
   pip install PyYAML==6.0.1
   ```

4. **向后兼容**：即使没有配置文件，代码也能正常运行，会使用内置的默认值

5. **数据驱动原则**：从GeoJSON数据中获取的参数不应放在配置文件中，保持数据驱动的设计原则

## 故障排除

### 配置文件读取失败
如果配置文件格式错误或读取失败，程序会自动使用内置默认值，并在日志中记录警告。

### 缺少依赖
如果缺少 PyYAML 依赖，请运行：
```bash
pip install -r requirements.txt
```

### 路径问题
确保配置文件中的路径设置正确，特别是 `file_search_paths` 部分。

## 扩展配置

可以根据需要在配置文件中添加新的参数，然后在代码中使用 `CONFIG.get()` 方法获取：

```python
# 在配置文件中添加
custom_parameter: "custom_value"

# 在代码中使用
custom_value = CONFIG.get("custom_parameter", "default_value")
```

这种设计使得系统既保持了灵活性，又维持了数据驱动的核心原则。