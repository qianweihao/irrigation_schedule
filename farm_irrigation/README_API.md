# 灌溉计划API服务

## 概述

本API服务提供农场灌溉计划生成功能，支持文件上传和参数配置的一体化接口。基于现有的灌溉调度算法，提供RESTful API接口供外部系统调用。

## 特性

- **单一接口设计**：一个接口完成文件上传和计划生成
- **文件上传支持**：支持Shapefile格式的GIS数据上传
- **参数化配置**：支持farm_id、target_depth_mm等关键参数
- **自动备份恢复**：上传失败时自动恢复原有数据
- **完整的错误处理**：提供详细的错误信息和状态码

## 快速开始

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

### 3. 访问API文档

启动服务后，访问以下地址查看交互式API文档：
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## API接口

### 主要接口

#### POST /api/irrigation/plan-with-upload

生成灌溉计划（支持文件上传）

**请求参数：**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| farm_id | string | 是 | 无 | 农场ID（必填，用于获取实时水位数据） |
| target_depth_mm | float | 否 | 90.0 | 目标灌溉深度(mm) |
| pumps | string | 否 | null | 启用的泵站，逗号分隔 |
| zones | string | 否 | null | 启用的供区，逗号分隔 |
| merge_waterlevels | boolean | 否 | true | 是否融合实时水位 |
| print_summary | boolean | 否 | true | 是否返回摘要信息 |
| files | file[] | 否 | [] | Shapefile文件组合 |

**请求示例：**

```bash
# 使用现有数据生成计划（farm_id为必填参数）
curl -X POST "http://127.0.0.1:8000/api/irrigation/plan-with-upload" \
  -F "farm_id=13944136728576" \
  -F "target_depth_mm=90.0"

# 上传新文件并生成计划（farm_id为必填参数）
curl -X POST "http://127.0.0.1:8000/api/irrigation/plan-with-upload" \
  -F "farm_id=13944136728576" \
  -F "target_depth_mm=90.0" \
  -F "pumps=P1,P2" \
  -F "files=@港中坪水路.shp" \
  -F "files=@港中坪水路.dbf" \
  -F "files=@港中坪水路.shx" \
  -F "files=@港中坪田块.shp" \
  -F "files=@港中坪田块.dbf" \
  -F "files=@港中坪田块.shx" \
  -F "files=@港中坪阀门与节制闸.shp" \
  -F "files=@港中坪阀门与节制闸.dbf" \
  -F "files=@港中坪阀门与节制闸.shx"
```

**响应示例：**

```json
{
  "success": true,
  "message": "灌溉计划生成成功",
  "plan": {
    "farm_id": "13944136728576",
    "t_win_h": 20.0,
    "d_target_mm": 90.0,
    "plan": [
      {
        "pump_name": "P1",
        "start_time": "2024-01-01T08:00:00",
        "duration_h": 2.5,
        "flow_rate_m3ph": 300.0
      }
    ]
  },
  "summary": "灌溉决策摘要：共需灌溉3个田块，总用时5.2小时"
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

| 状态码 | 说明 | 解决方案 |
|--------|------|----------|
| 400 | 请求参数错误 | 检查参数格式和必填项 |
| 400 | 无效的shapefile文件组合 | 确保上传完整的.shp、.dbf、.shx文件 |
| 500 | 文件保存失败 | 检查磁盘空间和文件权限 |
| 500 | 灌溉计划生成失败 | 检查输入数据格式和算法参数 |

### 错误响应示例

```json
{
  "detail": "无效的shapefile文件组合，需要包含.shp, .dbf, .shx文件"
}
```

## 开发指南

### 项目结构

```
farm_irrigation/
├── api_server.py          # API服务主文件
├── pipeline.py            # 核心算法流程
├── requirements.txt       # 依赖包列表
├── auto_config_params.yaml # 配置参数
├── gzp_farm/             # 输入数据目录
└── output/               # 输出结果目录
```

### 扩展开发

1. **添加新接口**：在`api_server.py`中添加新的路由
2. **修改数据模型**：更新`IrrigationRequest`和`IrrigationResponse`类
3. **自定义验证**：扩展`validate_shp_files`函数
4. **错误处理**：添加特定的异常处理逻辑

### 部署建议

#### 开发环境
```bash
python api_server.py --reload
```

#### 生产环境
```bash
# 使用Gunicorn
gunicorn api_server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# 使用Uvicorn
uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 4
```

## 性能优化

### 建议配置

- **并发处理**：根据服务器配置调整worker数量
- **文件缓存**：考虑实现文件上传缓存机制
- **异步处理**：对于大文件处理，可考虑异步任务队列
- **监控日志**：配置详细的访问日志和错误日志

### 资源限制

- **内存使用**：单次请求建议不超过1GB内存
- **处理时间**：单次计划生成建议控制在60秒内
- **并发连接**：根据服务器性能调整最大并发数

## 常见问题

### Q: 如何处理中文文件名？
A: 确保客户端使用UTF-8编码上传文件，服务端已配置UTF-8支持。

### Q: 上传失败后数据会丢失吗？
A: 不会，服务会自动备份原有数据，上传失败时会自动恢复。

### Q: 为什么farm_id是必填参数？
A: farm_id用于获取该农场的实时水位数据，这是灌溉计划算法的重要输入。每个农场都有独特的水位监测点和数据，因此必须提供正确的farm_id。

### Q: 可以同时处理多个农场的数据吗？
A: 当前版本使用单一数据目录，建议为不同农场部署独立的服务实例。

### Q: 如何查看详细的错误信息？
A: 检查服务器日志，或启用`print_summary`参数获取详细的处理信息。

## 联系支持

如有问题或建议，请联系开发团队或查看项目文档。