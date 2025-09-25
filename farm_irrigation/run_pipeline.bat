@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM 农场灌溉调度系统自动化执行脚本 (Windows批处理版本)
REM 使用方法: 双击运行或在命令行中执行

echo ========================================
echo 农场灌溉调度系统自动化流水线
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.7+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 显示Python版本
echo [信息] 检测到Python版本:
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   %%i
echo.

REM 检查当前目录
if not exist "pipeline.py" (
    echo [错误] 未找到pipeline.py文件
    echo 请确保在正确的目录中运行此脚本
    pause
    exit /b 1
)

REM 检查依赖文件
echo [信息] 检查依赖文件...
set "missing_files="
if not exist "auto_to_config.py" set "missing_files=!missing_files! auto_to_config.py"
if not exist "run_irrigation_plan.py" set "missing_files=!missing_files! run_irrigation_plan.py"
if not exist "farmgis_convert.py" set "missing_files=!missing_files! farmgis_convert.py"
if not exist "fix_farmgis_convert.py" set "missing_files=!missing_files! fix_farmgis_convert.py"

if not "!missing_files!"=="" (
    echo [错误] 缺少必要文件:!missing_files!
    pause
    exit /b 1
)

echo [信息] 依赖文件检查通过
echo.

REM 显示菜单
:menu
echo ========================================
echo 请选择执行模式:
echo ========================================
echo 1. 快速执行 (使用默认配置)
echo 2. 使用配置文件执行
echo 3. 自定义参数执行
echo 4. 查看帮助信息
echo 5. 退出
echo ========================================
set /p choice="请输入选项 (1-5): "

if "%choice%"=="1" goto quick_run
if "%choice%"=="2" goto config_run
if "%choice%"=="3" goto custom_run
if "%choice%"=="4" goto show_help
if "%choice%"=="5" goto exit

echo [错误] 无效选项，请重新选择
echo.
goto menu

:quick_run
echo.
echo [信息] 开始快速执行...
echo [信息] 使用默认配置: 输入目录=./gzp_farm, 输出目录=./output
echo.
python pipeline.py --input-dir ./gzp_farm --output-dir ./output
goto end

:config_run
echo.
if exist "pipeline_config.yaml" (
    echo [信息] 使用配置文件执行...
    echo [信息] 配置文件: pipeline_config.yaml
    echo.
    python pipeline.py --config pipeline_config.yaml
) else (
    echo [错误] 未找到配置文件 pipeline_config.yaml
    echo [提示] 请先创建配置文件或选择其他执行模式
    echo.
    pause
    goto menu
)
goto end

:custom_run
echo.
echo [信息] 自定义参数执行
echo.
set /p input_dir="请输入数据目录 (默认: ./gzp_farm): "
if "%input_dir%"=="" set "input_dir=./gzp_farm"

set /p output_dir="请输入输出目录 (默认: ./output): "
if "%output_dir%"=="" set "output_dir=./output"

set /p pumps="请输入启用的泵站 (例如: 1,2,3，可选): "
set /p zones="请输入启用的供区 (例如: A,B,C，可选): "

set /p waterlevels="是否融合实时水位数据? (Y/n，默认: Y): "
if "%waterlevels%"=="" set "waterlevels=Y"

REM 构建命令
set "cmd=python pipeline.py --input-dir \"%input_dir%\" --output-dir \"%output_dir%\""
if not "%pumps%"=="" set "cmd=!cmd! --pumps %pumps%"
if not "%zones%"=="" set "cmd=!cmd! --zones %zones%"
if /i "%waterlevels%"=="n" set "cmd=!cmd! --no-waterlevels"

echo.
echo [信息] 执行命令: !cmd!
echo.
!cmd!
goto end

:show_help
echo.
echo ========================================
echo 帮助信息
echo ========================================
echo.
echo 农场灌溉调度系统自动化流水线包含以下步骤:
echo.
echo 1. 数据预处理
echo    - farmgis_convert.py: GIS数据格式转换
echo    - fix_farmgis_convert.py: GIS数据修复
echo.
echo 2. 配置生成
echo    - auto_to_config.py: 生成系统配置文件
echo.
echo 3. 计划生成
echo    - run_irrigation_plan.py: 生成灌溉计划
echo.
echo 输入文件要求:
echo - segments.geojson 或包含"水路"的GeoJSON文件
echo - gates.geojson 或包含"阀门""节制闸"的GeoJSON文件
echo - fields.geojson 或包含"田块"的GeoJSON文件
echo.
echo 输出文件:
echo - config.json: 系统配置文件
echo - irrigation_plan_*.json: 灌溉计划文件
echo - labeled_output/: 标注后的GeoJSON文件
echo.
echo 更多信息请查看: python pipeline.py --help
echo.
pause
goto menu

:end
echo.
if errorlevel 1 (
    echo [错误] 执行失败，请检查错误信息
) else (
    echo [成功] 执行完成！
)
echo.
echo 按任意键查看输出目录...
pause >nul

REM 尝试打开输出目录
if exist "output" (
    explorer "output"
) else if exist "./output" (
    explorer "./output"
) else (
    echo [提示] 输出目录不存在或未找到
)

:exit
echo.
echo 感谢使用农场灌溉调度系统！
echo.
pause