# 灌溉系统API Postman测试指南

## 📋 准备工作

### 1. 安装Postman
- 下载并安装 [Postman](https://www.postman.com/downloads/)
- 创建Postman账户（可选，用于同步）

### 2. 启动API服务
在开始测试前，确保API服务正在运行：

```bash
# 方式1：启动主动态执行服务
python main_dynamic_execution_api.py

# 方式2：启动集成API服务
python api_server.py --host 127.0.0.1 --port 8000

# 方式3：使用Docker
docker-compose up -d
```

### 3. 验证服务状态
在浏览器中访问：
- 健康检查：`http://127.0.0.1:8000/api/system/health-check`
- 监控面板：`http://127.0.0.1:8000/api/monitoring/dashboard`

## 🚀 导入测试环境

### 步骤1：导入环境配置
1. 打开Postman
2. 点击左侧 **Environments** 标签
3. 点击 **Import** 按钮
4. 选择 `postman_environment.json` 文件
5. 导入成功后，选择 "灌溉系统API环境"

### 步骤2：导入API集合
1. 点击左侧 **Collections** 标签
2. 点击 **Import** 按钮
3. 选择 `postman_collection.json` 文件
4. 导入成功后，可以看到 "灌溉系统API测试集合"

### 步骤3：配置环境变量
检查并根据需要修改环境变量：
- `base_url`: API服务地址（默认：http://127.0.0.1:8000）
- `farm_id`: 您的农场ID（已设置为：13944136728576）
- `plan_file_path`: 灌溉计划文件路径（已设置为：e:/irrigation_schedule/farm_irrigation/output/irrigation_plan_modified_1761982575.json）
- `config_file_path`: 配置文件路径（已设置为：e:/irrigation_schedule/farm_irrigation/config.json）
- `field_id`: 田块ID示例（已设置为：field_001）
- `water_level`: 水位值示例（已设置为：25.5mm）
- `execution_id`: 执行ID（动态获取）
- `plan_id`: 计划ID（动态获取）
- `batch_index`: 批次索引（默认：1）
- `batch_id`: 批次ID（动态获取）

## 🧪 测试流程

### 阶段1：基础功能测试

#### 1.1 健康检查
```
POST {{base_url}}/api/system/health-check
Content-Type: application/json
```
**预期结果**：
- 状态码：200
- 响应：`{"status": "healthy", "timestamp": "..."}`

#### 1.2 系统初始化
```
POST {{base_url}}/api/system/init
Content-Type: application/json

{
  "farm_id": "{{farm_id}}",
  "config_file_path": "/path/to/config.json",
  "force_reinit": false
}
```
**预期结果**：
- 状态码：200
- 响应包含：`"success": true`

### 阶段2：动态执行测试

#### 2.1 启动动态执行
```
POST {{base_url}}/api/execution/start
Content-Type: application/json

{
  "plan_file_path": "{{plan_file_path}}",
  "farm_id": "{{farm_id}}",
  "config_file_path": "{{config_file_path}}",
  "auto_start": true,
  "water_level_update_interval_minutes": 30,
  "enable_plan_regeneration": true,
  "execution_mode": "simulation"
}
```
**重要**：成功后会自动保存 `execution_id` 到环境变量

#### 2.2 查询执行状态
```
GET {{base_url}}/api/execution/status?execution_id={{execution_id}}
```

#### 2.3 停止执行（可选）
```
POST {{base_url}}/api/execution/stop
Content-Type: application/json

{
  "execution_id": "{{execution_id}}",
  "reason": "测试完成"
}
```

### 阶段3：水位管理测试

#### 3.1 更新水位数据
```
POST {{base_url}}/api/water-levels/update
Content-Type: application/json

{
  "farm_id": "{{farm_id}}",
  "field_id": "{{field_id}}",
  "water_level_mm": {{water_level}},
  "timestamp": "2025-01-01T12:00:00Z",
  "source": "manual",
  "quality": "good"
}
```

#### 3.2 获取水位历史
```
GET {{base_url}}/api/water-levels/history?farm_id={{farm_id}}&field_id={{field_id}}&hours=24
```

#### 3.3 获取水位汇总
```
GET {{base_url}}/api/water-levels/summary?farm_id={{farm_id}}
```

### 阶段4：批次管理测试

#### 4.1 获取批次列表
```
GET {{base_url}}/api/batches?farm_id={{farm_id}}&status=active
```

#### 4.2 获取批次详情
```
GET {{base_url}}/api/batches/{{batch_index}}/details
```

### 阶段5：灌溉计划生成测试

#### 5.1 生成灌溉计划
```
POST {{base_url}}/api/irrigation/plan-generation
Content-Type: application/json

{
  "farm_id": "{{farm_id}}",
  "config_path": "{{config_file_path}}",
  "output_dir": "{{output_dir}}",
  "scenario_name": "test_scenario",
  "multi_pump_scenarios": true
}
```
**重要参数说明**：
- `scenario_name`: 灌溉计划的标识名称（可选，默认为null）
- `multi_pump_scenarios`: 是否生成多水泵方案（可选，默认为false）
  - `true`: 生成所有可能的水泵组合方案（P1单独、P2单独、P1+P2组合等）
  - `false`: 仅生成单一最优方案

**预期结果**：
- 状态码：200
- 响应包含：`"success": true`
- 当 `multi_pump_scenarios: true` 时，输出JSON包含 `scenarios` 数组和 `analysis` 字段
- 成功后会自动保存 `plan_id` 到环境变量

#### 5.2 上传并生成计划
```
POST {{base_url}}/api/irrigation/plan-with-upload
Content-Type: multipart/form-data

Form Data:
- config_file: [选择配置文件]
- farm_id: {{farm_id}}
- scenario_name: upload_test
- multi_pump_scenarios: true
```
**重要参数说明**：
- `config_file`: 上传的配置文件（必需）
- `farm_id`: 农场ID（必需）
- `scenario_name`: 灌溉计划的标识名称（可选，默认为"upload_test"）
- `multi_pump_scenarios`: 是否生成多水泵方案（可选，默认为false）

**预期结果**：
- 状态码：200
- 响应包含：`"success": true`
- 当 `multi_pump_scenarios: true` 时，输出包含多个水泵组合方案

### 阶段6：Web可视化测试

#### 6.1 获取GeoJSON数据
```
GET {{base_url}}/geojson/fields?farm_id={{farm_id}}
```

#### 6.2 获取监控面板数据
```
GET {{base_url}}/api/monitoring/dashboard?farm_id={{farm_id}}
```

### 阶段7：计划重新生成测试

#### 7.1 手动重新生成
```
POST {{base_url}}/api/regeneration/manual
Content-Type: application/json

{
  "batch_index": 1,
  "custom_water_levels": {
    "S3-G5-F3": 95.0
  },
  "force_regeneration": true
}
```

#### 7.2 获取执行状态
```
GET {{base_url}}/api/execution/status
```

#### 7.3 获取重新生成摘要
```
GET {{base_url}}/api/regeneration/summary/{{farm_id}}
```

## 📊 API接口完整列表

### 1. 系统管理
- `POST /api/system/init` - 系统初始化
- `POST /api/system/health-check` - 健康检查

### 2. 动态执行
- `POST /api/execution/start` - 启动动态执行
- `GET /api/execution/status` - 查询执行状态
- `POST /api/execution/stop` - 停止执行

### 3. 水位管理
- `POST /api/water-levels/update` - 更新水位数据
- `GET /api/water-levels/history` - 获取水位历史
- `GET /api/water-levels/summary` - 获取水位汇总

### 4. 计划重新生成
- `POST /api/regeneration/manual` - 手动重新生成
- `GET /api/execution/status` - 获取执行状态
- `GET /api/regeneration/summary/{farm_id}` - 获取重新生成摘要

### 5. 批次管理
- `GET /api/batches` - 获取批次列表
- `GET /api/batches/{batch_index}/details` - 获取批次详情

### 6. 灌溉计划生成 ⭐
- `POST /api/irrigation/plan-generation` - 生成灌溉计划（支持多方案模式）
- `POST /api/irrigation/plan-with-upload` - 上传并生成计划（支持多方案模式）

### 7. Web可视化
- `GET /geojson/fields` - 获取GeoJSON数据
- `GET /api/monitoring/dashboard` - 获取监控面板数据

## 🔍 测试技巧

### 1. 多方案功能测试 ⭐
**重要功能**：灌溉计划生成接口支持多水泵方案模式

#### 单方案模式 (`multi_pump_scenarios: false`)
- 生成单一最优灌溉方案
- 输出JSON结构简单，包含一个方案的详细信息
- 适用于快速生成推荐方案

#### 多方案模式 (`multi_pump_scenarios: true`)
- 生成所有可能的水泵组合方案
- 输出JSON包含：
  - `scenarios` 数组：包含所有方案（P1单独、P2单独、P1+P2组合等）
  - `analysis` 字段：方案对比分析
  - `total_scenarios` 计数：总方案数量
- 每个方案包含：
  - `scenario_name`: 方案名称（如"P2单独使用"）
  - `pumps_used`: 使用的水泵列表
  - `total_electricity_cost`: 总电费成本
  - `total_eta_h`: 总运行时间
  - `coverage_info`: 覆盖信息

#### 测试验证要点
1. **参数验证**：确认 `multi_pump_scenarios` 参数正确传递
2. **输出格式**：多方案模式下检查 `scenarios` 数组存在
3. **日志确认**：在 `pipeline.log` 中确认参数值为 `True`
4. **方案完整性**：验证所有可能的水泵组合都已生成

### 2. 使用测试脚本
每个请求都包含自动化测试脚本，会验证：
- 响应状态码
- 响应时间
- 关键字段存在性
- 数据格式正确性

### 2. 环境变量管理
- 动态获取的ID会自动保存到环境变量
- 可以在 **Tests** 标签中查看和修改测试脚本
- 使用 `{{variable_name}}` 语法引用变量

### 3. 批量测试
1. 选择整个集合或文件夹
2. 点击 **Run** 按钮
3. 配置运行参数
4. 查看测试报告

### 4. 调试技巧
- 使用 **Console** 查看详细日志
- 在 **Tests** 中添加 `console.log()` 输出调试信息
- 检查 **Response** 标签中的完整响应

## ⚠️ 常见问题

### 1. 连接失败
- 检查API服务是否启动
- 确认端口号是否正确
- 检查防火墙设置

### 2. 认证错误
- 确认API是否需要认证
- 检查请求头设置

### 3. 参数错误
- 验证JSON格式是否正确
- 检查必需参数是否提供
- 确认参数类型匹配

### 4. 超时问题
- 增加Postman超时设置
- 检查服务器性能
- 优化请求参数

## 📊 测试报告

### 成功标准
- 所有基础API返回200状态码
- 关键业务流程完整执行
- 数据格式符合API文档规范
- 响应时间在可接受范围内
- 自动化测试脚本全部通过

### 性能基准
- 健康检查：< 100ms
- 简单查询：< 500ms
- 复杂操作：< 5s
- 文件上传：< 30s
- 批量操作：< 10s

### 测试覆盖率要求
- 系统管理：100%（2/2接口）
- 动态执行：100%（3/3接口）
- 水位管理：100%（3/3接口）
- 批次管理：100%（2/2接口）
- 灌溉计划生成：100%（2/2接口）
- 计划重新生成：100%（3/3接口）
- Web可视化：100%（2/2接口）

## 🔄 持续测试

### 1. 自动化测试
使用Postman的Newman命令行工具：
```bash
npm install -g newman
newman run postman_collection.json -e postman_environment.json
```

### 2. 集成CI/CD
将测试集成到持续集成流程中，确保API质量。

### 3. 监控告警
设置API监控，及时发现问题。

---

## 📞 技术支持

如果在测试过程中遇到问题，请：
1. 检查API服务日志
2. 验证请求参数格式
3. 查看Postman控制台输出
4. 参考API文档说明

祝您测试顺利！🎉