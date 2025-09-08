#!/bin/bash
# 农场级灌溉设计算法AI 启动脚本

# 设置工作目录
APP_DIR="/opt/farm_irrigation"
cd $APP_DIR

# 激活虚拟环境
source venv/bin/activate

# 设置环境变量
export FLASK_APP=web_farm_irrigation_modified.py
export FLASK_ENV=production
export PYTHONPATH=$APP_DIR:$PYTHONPATH

# 创建日志目录
sudo mkdir -p /var/log/farm_irrigation
sudo chown -R $USER:$USER /var/log/farm_irrigation

# 检查配置文件是否存在
if [ ! -f "config.json" ]; then
    echo "警告: config.json 不存在，请先运行 auto_to_config.py 生成配置文件"
    echo "运行: python auto_to_config.py"
fi

# 启动应用
echo "启动农场级灌溉设计算法AI..."
echo "访问地址: http://your-server-ip:5000"
echo "按 Ctrl+C 停止服务"

# 使用Gunicorn启动
gunicorn -c gunicorn.conf.py farm_irrigation.web_farm_irrigation_modified:app

# 或者使用Flask开发服务器（仅用于测试）
# python farm_irrigation/web_farm_irrigation_modified.py