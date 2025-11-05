# 🚀 灌溉系统服务器部署指南

## 📋 概述

本系统使用 **Docker + Docker Compose** 进行部署，包含以下服务：
- **irrigation-api**: 主API服务（FastAPI + Uvicorn）
- **nginx**: Nginx反向代理（可选）

---

## 🔧 部署架构

```
┌─────────────────────────────────────────┐
│          外部访问 (HTTP/HTTPS)           │
└───────────────┬─────────────────────────┘
                │
         ┌──────▼──────┐
         │    Nginx    │  (端口 80)
         │  反向代理    │
         └──────┬──────┘
                │
    ┌───────────▼────────────┐
    │   irrigation-api       │  (端口 8000)
    │   FastAPI + Uvicorn    │
    │ (main_dynamic_execution_api.py)
    └────────────────────────┘
```

---

## 📦 部署前准备

### 1. 安装依赖

确保服务器已安装：
- Docker (>= 20.10)
- Docker Compose (>= 2.0)
- curl

```bash
# 检查Docker版本
docker --version
docker compose version

# 如果未安装，请参考官方文档安装
```

### 2. 上传项目文件

将整个项目目录上传到服务器：

```bash
# 示例：使用scp上传
scp -r ./farm_irrigation user@your-server:/opt/

# 或使用git clone
ssh user@your-server
cd /opt
git clone <your-repo-url> farm_irrigation
```

### 3. 检查必要文件

确保以下文件存在：
```
farm_irrigation/
├── Dockerfile
├── docker-compose.yml
├── irrigation.conf
├── requirements.txt
├── main_dynamic_execution_api.py  ← 主程序
├── config.json
├── gzp_farm/                      ← 地理数据
├── output/                        ← 输出目录
└── deploy.sh                      ← 部署脚本
```

---

## 🎯 快速部署

### 方式1：使用部署脚本（推荐）

```bash
cd /opt/farm_irrigation

# 给部署脚本添加执行权限
chmod +x deploy.sh

# 启动服务
./deploy.sh start
```

**部署脚本支持的命令：**
```bash
./deploy.sh start     # 启动服务
./deploy.sh stop      # 停止服务
./deploy.sh restart   # 重启服务
./deploy.sh status    # 查看状态
./deploy.sh logs      # 查看日志
./deploy.sh update    # 更新服务
./deploy.sh cleanup   # 清理资源
./deploy.sh backup    # 备份数据
```

### 方式2：手动Docker Compose部署

```bash
cd /opt/farm_irrigation

# 构建并启动服务
docker compose up -d --build

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f
```

---

## ✅ 验证部署

### 1. 检查容器状态

```bash
docker compose ps

# 输出示例：
# NAME               STATUS          PORTS
# irrigation-api     Up (healthy)    0.0.0.0:8000->8000/tcp
# irrigation-nginx   Up              0.0.0.0:80->80/tcp
```

### 2. 测试健康检查

```bash
# 直接访问API
curl http://localhost:8000/api/system/health-check

# 通过Nginx访问
curl http://localhost/api/system/health-check
```

**预期响应：**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-09T...",
  "components": {
    "scheduler": "ok",
    "waterlevel_manager": "ok",
    "plan_regenerator": "ok",
    "status_manager": "ok"
  }
}
```

### 3. 访问API文档

在浏览器中访问：
- API文档: `http://YOUR_SERVER_IP/docs`
- API信息: `http://YOUR_SERVER_IP/api/info`

---

## 🔌 Postman配置

### 1. 导入环境配置

1. 打开Postman
2. 导入 `postman/postman_environment_production.json`
3. 修改 `base_url`:
   ```
   http://YOUR_SERVER_IP
   # 或通过Nginx（如果启用）
   http://YOUR_SERVER_IP:80
   ```

### 2. 测试接口

```
1. 健康检查 → ✅
2. 生成灌溉计划 → ✅ (自动设置plan_id)
3. 启动动态执行 → ✅
4. 查询执行状态 → ✅
```

---

## 📊 监控和日志

### 查看实时日志

```bash
# 查看所有服务日志
docker compose logs -f

# 查看API服务日志
docker compose logs -f irrigation-api

# 查看Nginx日志
docker compose logs -f nginx
```

### 日志文件位置

容器内日志：
```
/app/logs/                     ← 应用日志目录
/app/main_dynamic_execution.log ← 主API日志
/app/batch_execution_scheduler.log ← 调度器日志
```

宿主机挂载（通过volume）：
```
./logs/                        ← 本地日志目录
./output/                      ← 计划输出目录
./gzp_farm/                    ← 地理数据目录
```

---

## 🔄 更新部署

### 方式1：使用脚本

```bash
./deploy.sh update
```

### 方式2：手动更新

```bash
# 停止服务
docker compose down

# 拉取最新代码（如果使用git）
git pull

# 重新构建并启动
docker compose up -d --build
```

---

## 🛠️ 故障排查

### 问题1：容器无法启动

```bash
# 查看详细日志
docker compose logs irrigation-api

# 检查配置文件
ls -l config.json gzp_farm/

# 重新构建
docker compose build --no-cache
docker compose up -d
```

### 问题2：健康检查失败

```bash
# 进入容器检查
docker exec -it irrigation-api bash

# 手动测试健康检查
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/system/health-check').read())"

# 检查端口
netstat -tlnp | grep 8000
```

### 问题3：数据持久化问题

确保volume挂载正确：
```bash
docker compose down -v  # 删除volumes
docker compose up -d    # 重新创建
```

---

## 🔐 生产环境优化

### 1. 启用HTTPS

修改 `irrigation.conf`，取消SSL配置注释，并添加证书：

```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    # ...
}
```

### 2. 资源限制

已在 `docker-compose.yml` 中配置：
- API服务：最大 2 CPU核心，2GB 内存
- Nginx：最大 0.5 CPU核心，256MB 内存

根据实际需求调整：
```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2G
```

### 3. 备份策略

```bash
# 使用部署脚本备份
./deploy.sh backup

# 手动备份
tar -czf backup-$(date +%Y%m%d).tar.gz \
    gzp_farm/ output/ config.json auto_config_params.yaml
```

### 4. 定期清理

```bash
# 清理旧的计划文件（30天前）
find output/ -name "*.json" -mtime +30 -delete

# 清理Docker资源
docker system prune -f
```

---

## 📝 服务管理

### 停止服务

```bash
./deploy.sh stop
# 或
docker compose down
```

### 重启服务

```bash
./deploy.sh restart
# 或
docker compose restart
```

### 查看服务状态

```bash
./deploy.sh status
# 或
docker compose ps
```

---

## 🌐 端口说明

| 服务 | 容器端口 | 宿主机端口 | 用途 |
|------|----------|------------|------|
| irrigation-api | 8000 | 8000 | API服务 |
| nginx | 80 | 80 | HTTP反向代理 |

**防火墙配置：**
```bash
# 开放80端口（HTTP）
sudo ufw allow 80/tcp

# 如果需要直接访问API
sudo ufw allow 8000/tcp

# 如果启用HTTPS
sudo ufw allow 443/tcp
```

---

## 📚 相关文件说明

| 文件 | 用途 |
|------|------|
| `Dockerfile` | Docker镜像构建文件 |
| `docker-compose.yml` | 服务编排配置 |
| `irrigation.conf` | Nginx配置（用于docker-compose） |
| `deploy.sh` | 部署管理脚本 |
| `main_dynamic_execution_api.py` | **主API程序（FastAPI）** |
| `api_server.py` | 轻量级API（功能子集，仅供测试） |
| `requirements.txt` | Python依赖 |

---

## ⚠️ 注意事项

1. **不要使用 `api_server.py` 部署**：它是旧的轻量级API，功能不完整
2. **主程序是 `main_dynamic_execution_api.py`**：包含所有功能
3. **健康检查端点**：`/api/system/health-check`（不是 `/api/health`）
4. **数据持久化**：确保 `gzp_farm/`、`output/`、`logs/` 目录有正确的权限
5. **配置文件**：部署前检查 `config.json` 和 `auto_config_params.yaml`

---

## 📞 技术支持

如遇到问题，请检查：
1. Docker日志：`docker compose logs -f`
2. API日志：`./logs/main_dynamic_execution.log`
3. 系统状态：`curl http://localhost:8000/api/system/status`

---

## 🎉 部署完成

部署成功后，您可以：
- ✅ 通过Postman测试所有API接口
- ✅ 访问 `http://YOUR_SERVER_IP/docs` 查看交互式文档
- ✅ 开始使用智能灌溉系统！

