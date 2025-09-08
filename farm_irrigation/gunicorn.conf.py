# Gunicorn配置文件
# 用于生产环境部署农场级灌溉设计算法AI

import multiprocessing

# 服务器套接字
bind = "0.0.0.0:5000"
backlog = 2048

# 工作进程
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2

# 重启
max_requests = 1000
max_requests_jitter = 50
preload_app = True

# 日志
accesslog = "/var/log/farm_irrigation/access.log"
errorlog = "/var/log/farm_irrigation/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# 进程命名
proc_name = 'farm_irrigation_app'

# 用户和组（部署时需要创建对应用户）
# user = "farm_app"
# group = "farm_app"

# 临时目录
tmp_upload_dir = None

# SSL（如果需要HTTPS）
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"