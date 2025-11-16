#!/bin/bash

# 灌溉计划API服务Docker部署脚本
# 使用方法: ./deploy.sh [start|stop|restart|status|logs|update]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Docker是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    if ! command -v docker compose &> /dev/null; then
        log_error "Docker Compose未安装，请先安装Docker Compose"
        exit 1
    fi
    
    log_info "Docker环境检查通过"
}

# 检查必要文件
check_files() {
    # 获取脚本所在目录和项目根目录
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    local project_root=$(cd "$script_dir/.." && pwd)
    
    local required_files=(
        "$project_root/deployment/Dockerfile"
        "$project_root/deployment/docker-compose.yml"
        "$project_root/requirements.txt"
        "$project_root/main_dynamic_execution_api.py"
        "$project_root/src/core/pipeline.py"
    )
    
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            log_error "缺少必要文件: $file"
            exit 1
        fi
    done
    
    log_info "必要文件检查通过"
}

# 创建必要目录
create_directories() {
    # 获取项目根目录
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    local project_root=$(cd "$script_dir/.." && pwd)
    
    local dirs=("data/gzp_farm" "data/output" "data/execution_logs")
    
    for dir in "${dirs[@]}"; do
        local full_path="$project_root/$dir"
        if [[ ! -d "$full_path" ]]; then
            mkdir -p "$full_path"
            log_info "创建目录: $full_path"
        fi
    done
}

# 启动服务
start_service() {
    log_info "启动灌溉计划API服务..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    
    # 构建镜像
    log_info "构建Docker镜像..."
    cd "$script_dir"
    docker compose build
    
    # 启动服务
    log_info "启动服务容器..."
    docker compose up -d
    
    # 等待服务启动
    log_info "等待服务启动..."
    sleep 10
    
    # 检查服务状态
    if check_service_health; then
        log_success "服务启动成功！"
        show_service_info
    else
        log_error "服务启动失败，请检查日志"
        docker compose logs
        exit 1
    fi
}

# 停止服务
stop_service() {
    log_info "停止灌溉计划API服务..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    cd "$script_dir"
    
    docker compose down
    log_success "服务已停止"
}

# 重启服务
restart_service() {
    log_info "重启灌溉计划API服务..."
    stop_service
    sleep 2
    start_service
}

# 检查服务状态
check_status() {
    log_info "检查服务状态..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    cd "$script_dir"
    
    docker compose ps
    
    if check_service_health; then
        log_success "服务运行正常"
        show_service_info
    else
        log_warning "服务可能存在问题"
    fi
}

# 查看日志
show_logs() {
    log_info "显示服务日志..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    cd "$script_dir"
    
    docker compose logs -f
}

# 更新服务
update_service() {
    log_info "更新灌溉计划API服务..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    cd "$script_dir"
    
    # 停止服务
    docker compose down
    
    # 重新构建镜像
    log_info "重新构建镜像..."
    docker compose build --no-cache
    
    # 启动服务
    log_info "启动更新后的服务..."
    docker compose up -d
    
    # 等待服务启动
    sleep 10
    
    if check_service_health; then
        log_success "服务更新成功！"
        show_service_info
    else
        log_error "服务更新失败，请检查日志"
        docker compose logs
        exit 1
    fi
}

# 检查服务健康状态
check_service_health() {
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -s http://localhost:8000/api/system/health-check > /dev/null 2>&1; then
            return 0
        fi
        
        log_info "等待服务启动... ($attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done
    
    return 1
}

# 显示服务信息
show_service_info() {
    echo
    log_success "=== 服务信息 ==="
    echo "API服务地址: http://localhost:8000"
    echo "API文档地址: http://localhost:8000/docs"
    echo "健康检查地址: http://localhost:8000/api/system/health-check"
    echo "Nginx访问地址: http://localhost:80"
    
    if command -v curl &> /dev/null; then
        echo
        log_info "API健康状态:"
        curl -s http://localhost:8000/api/system/health-check || echo "无法连接到API服务"
    fi
    echo
}

# 清理资源
cleanup() {
    log_info "清理Docker资源..."
    
    # 获取脚本目录（deployment目录）
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    cd "$script_dir"
    
    docker compose down
    docker system prune -f
    log_success "清理完成"
}

# 备份数据
backup_data() {
    # 获取项目根目录
    local script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    local project_root=$(cd "$script_dir/.." && pwd)
    
    local backup_file="$project_root/irrigation-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    log_info "备份数据到: $backup_file"
    
    cd "$project_root"
    tar -czf "$backup_file" data/gzp_farm/ data/output/ *.yaml *.json 2>/dev/null || true
    
    if [[ -f "$backup_file" ]]; then
        log_success "备份完成: $backup_file"
    else
        log_error "备份失败"
        exit 1
    fi
}

# 显示帮助信息
show_help() {
    echo "灌溉计划API服务部署脚本"
    echo
    echo "使用方法: $0 [命令]"
    echo
    echo "可用命令:"
    echo "  start     启动服务"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  status    检查服务状态"
    echo "  logs      查看服务日志"
    echo "  update    更新服务"
    echo "  cleanup   清理Docker资源"
    echo "  backup    备份数据"
    echo "  help      显示此帮助信息"
    echo
}

# 主函数
main() {
    local command="${1:-help}"
    
    case "$command" in
        "start")
            check_docker
            check_files
            create_directories
            start_service
            ;;
        "stop")
            stop_service
            ;;
        "restart")
            check_docker
            restart_service
            ;;
        "status")
            check_status
            ;;
        "logs")
            show_logs
            ;;
        "update")
            check_docker
            check_files
            update_service
            ;;
        "cleanup")
            cleanup
            ;;
        "backup")
            backup_data
            ;;
        "help")
            show_help
            ;;
        *)
            log_error "未知命令: $command"
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"