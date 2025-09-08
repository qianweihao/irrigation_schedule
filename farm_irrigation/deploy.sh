#!/bin/bash
# 农场级灌溉设计算法AI 自动部署脚本
# 适用于阿里云ECS Ubuntu/CentOS服务器

set -e  # 遇到错误立即退出

echo "=== 农场级灌溉设计算法AI 自动部署脚本 ==="
echo "开始部署..."

# 检测操作系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
else
    echo "无法检测操作系统"
    exit 1
fi

echo "检测到操作系统: $OS"

# 更新系统包
echo "更新系统包..."
if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y python3 python3-pip python3-venv nginx git curl
    # 安装GDAL依赖（geopandas需要）
    sudo apt install -y gdal-bin libgdal-dev python3-gdal
elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
    sudo yum update -y
    sudo yum install -y python3 python3-pip nginx git curl
    # 安装EPEL和GDAL
    sudo yum install -y epel-release
    sudo yum install -y gdal gdal-devel gdal-python3
else
    echo "不支持的操作系统: $OS"
    exit 1
fi

# 设置应用目录
APP_DIR="/opt/farm_irrigation"
echo "创建应用目录: $APP_DIR"
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# 复制项目文件
echo "复制项目文件..."
cp -r . $APP_DIR/
cd $APP_DIR

# 创建Python虚拟环境
echo "创建Python虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 升级pip
pip install --upgrade pip

# 安装Python依赖
echo "安装Python依赖包..."
pip install -r requirements.txt

# 生成配置文件
echo "生成配置文件..."
if [ -f "auto_to_config.py" ]; then
    python auto_to_config.py
    echo "配置文件生成完成"
else
    echo "警告: auto_to_config.py 不存在，请手动生成配置文件"
fi

# 设置权限
echo "设置文件权限..."
chmod +x start.sh
chmod +x deploy.sh

# 创建日志目录
sudo mkdir -p /var/log/farm_irrigation
sudo chown -R $USER:$USER /var/log/farm_irrigation

# 配置防火墙（如果启用）
echo "配置防火墙..."
if command -v ufw &> /dev/null; then
    sudo ufw allow 22    # SSH
    sudo ufw allow 80    # HTTP
    sudo ufw allow 443   # HTTPS
    sudo ufw allow 5000  # 应用端口
fi

echo "=== 部署完成 ==="
echo "应用目录: $APP_DIR"
echo "启动命令: cd $APP_DIR && ./start.sh"
echo "访问地址: http://your-server-ip:5000"
echo ""
echo "后续步骤:"
echo "1. 配置域名和SSL证书（可选）"
echo "2. 设置Nginx反向代理（推荐）"
echo "3. 配置systemd服务实现开机自启"
echo "4. 设置定期备份"
echo ""
echo "启动应用: ./start.sh"
echo "查看日志: tail -f /var/log/farm_irrigation/error.log"