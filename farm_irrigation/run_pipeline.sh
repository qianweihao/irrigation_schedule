#!/bin/bash
# 农场灌溉调度系统自动化执行脚本 (Linux/Mac版本)
# 使用方法: ./run_pipeline.sh 或 bash run_pipeline.sh

set -e  # 遇到错误时退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

print_error() {
    echo -e "${RED}[错误]${NC} $1"
}

# 显示标题
echo "========================================"
echo "农场灌溉调度系统自动化流水线"
echo "========================================"
echo

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        print_error "未找到Python，请先安装Python 3.7+"
        echo "Ubuntu/Debian: sudo apt-get install python3"
        echo "CentOS/RHEL: sudo yum install python3"
        echo "macOS: brew install python3"
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# 显示Python版本
print_info "检测到Python版本:"
echo "  $($PYTHON_CMD --version)"
echo

# 检查当前目录
if [ ! -f "pipeline.py" ]; then
    print_error "未找到pipeline.py文件"
    print_error "请确保在正确的目录中运行此脚本"
    exit 1
fi

# 检查依赖文件
print_info "检查依赖文件..."
missing_files=()
for file in "auto_to_config.py" "run_irrigation_plan.py" "farmgis_convert.py" "fix_farmgis_convert.py"; do
    if [ ! -f "$file" ]; then
        missing_files+=("$file")
    fi
done

if [ ${#missing_files[@]} -ne 0 ]; then
    print_error "缺少必要文件: ${missing_files[*]}"
    exit 1
fi

print_success "依赖文件检查通过"
echo

# 显示菜单
show_menu() {
    echo "========================================"
    echo "请选择执行模式:"
    echo "========================================"
    echo "1. 快速执行 (使用默认配置)"
    echo "2. 使用配置文件执行"
    echo "3. 自定义参数执行"
    echo "4. 查看帮助信息"
    echo "5. 退出"
    echo "========================================"
}

# 快速执行
quick_run() {
    echo
    print_info "开始快速执行..."
    print_info "使用默认配置: 输入目录=./gzp_farm, 输出目录=./output"
    echo
    $PYTHON_CMD pipeline.py --input-dir ./gzp_farm --output-dir ./output
}

# 配置文件执行
config_run() {
    echo
    if [ -f "pipeline_config.yaml" ]; then
        print_info "使用配置文件执行..."
        print_info "配置文件: pipeline_config.yaml"
        echo
        $PYTHON_CMD pipeline.py --config pipeline_config.yaml
    else
        print_error "未找到配置文件 pipeline_config.yaml"
        print_warning "请先创建配置文件或选择其他执行模式"
        echo
        read -p "按Enter键返回菜单..."
        return 1
    fi
}

# 自定义参数执行
custom_run() {
    echo
    print_info "自定义参数执行"
    echo
    
    read -p "请输入数据目录 (默认: ./gzp_farm): " input_dir
    input_dir=${input_dir:-"./gzp_farm"}
    
    read -p "请输入输出目录 (默认: ./output): " output_dir
    output_dir=${output_dir:-"./output"}
    
    read -p "请输入启用的泵站 (例如: 1,2,3，可选): " pumps
    read -p "请输入启用的供区 (例如: A,B,C，可选): " zones
    
    read -p "是否融合实时水位数据? (Y/n，默认: Y): " waterlevels
    waterlevels=${waterlevels:-"Y"}
    
    # 构建命令
    cmd="$PYTHON_CMD pipeline.py --input-dir \"$input_dir\" --output-dir \"$output_dir\""
    
    if [ -n "$pumps" ]; then
        cmd="$cmd --pumps $pumps"
    fi
    
    if [ -n "$zones" ]; then
        cmd="$cmd --zones $zones"
    fi
    
    if [[ "$waterlevels" =~ ^[Nn]$ ]]; then
        cmd="$cmd --no-waterlevels"
    fi
    
    echo
    print_info "执行命令: $cmd"
    echo
    eval $cmd
}

# 显示帮助
show_help() {
    echo
    echo "========================================"
    echo "帮助信息"
    echo "========================================"
    echo
    echo "农场灌溉调度系统自动化流水线包含以下步骤:"
    echo
    echo "1. 数据预处理"
    echo "   - farmgis_convert.py: GIS数据格式转换"
    echo "   - fix_farmgis_convert.py: GIS数据修复"
    echo
    echo "2. 配置生成"
    echo "   - auto_to_config.py: 生成系统配置文件"
    echo
    echo "3. 计划生成"
    echo "   - run_irrigation_plan.py: 生成灌溉计划"
    echo
    echo "输入文件要求:"
    echo "- segments.geojson 或包含\"水路\"的GeoJSON文件"
    echo "- gates.geojson 或包含\"阀门\"\"节制闸\"的GeoJSON文件"
    echo "- fields.geojson 或包含\"田块\"的GeoJSON文件"
    echo
    echo "输出文件:"
    echo "- config.json: 系统配置文件"
    echo "- irrigation_plan_*.json: 灌溉计划文件"
    echo "- labeled_output/: 标注后的GeoJSON文件"
    echo
    echo "更多信息请查看: $PYTHON_CMD pipeline.py --help"
    echo
    read -p "按Enter键返回菜单..."
}

# 主循环
while true; do
    show_menu
    read -p "请输入选项 (1-5): " choice
    
    case $choice in
        1)
            quick_run
            break
            ;;
        2)
            if config_run; then
                break
            fi
            ;;
        3)
            custom_run
            break
            ;;
        4)
            show_help
            ;;
        5)
            echo
            print_info "感谢使用农场灌溉调度系统！"
            echo
            exit 0
            ;;
        *)
            print_error "无效选项，请重新选择"
            echo
            ;;
    esac
done

# 执行结果处理
echo
if [ $? -eq 0 ]; then
    print_success "执行完成！"
else
    print_error "执行失败，请检查错误信息"
fi

echo
print_info "按Enter键查看输出目录..."
read

# 尝试打开输出目录
if [ -d "output" ]; then
    if command -v xdg-open &> /dev/null; then
        xdg-open "output"  # Linux
    elif command -v open &> /dev/null; then
        open "output"      # macOS
    else
        print_info "输出目录: $(pwd)/output"
        ls -la "output"
    fi
elif [ -d "./output" ]; then
    if command -v xdg-open &> /dev/null; then
        xdg-open "./output"
    elif command -v open &> /dev/null; then
        open "./output"
    else
        print_info "输出目录: $(pwd)/output"
        ls -la "./output"
    fi
else
    print_warning "输出目录不存在或未找到"
fi

echo
print_info "感谢使用农场灌溉调度系统！"
echo