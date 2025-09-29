# 使用Python 3.9官方镜像作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（用于地理空间库）
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置GDAL环境变量
ENV GDAL_CONFIG /usr/bin/gdal-config
ENV CPLUS_INCLUDE_PATH /usr/include/gdal
ENV C_INCLUDE_PATH /usr/include/gdal

# 复制并安装Python依赖
COPY requirements.txt .
# 使用清华大学镜像源加速pip安装
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p gzp_farm output logs

# 设置权限
RUN chmod +x api_server.py

# 暴露端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 启动命令
CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000"]