一、核心运行

流水线：C:/Users/00783510/AppData/Local/Programs/Python/Python311/python.exe f:/irrigation_schedule/farm_irrigation/pipeline.py

二、完整步骤

1.数据准备和配置生成

farmgis_convert.py和fix_farmgis_convert.py对原始GIS数据进行预处理和格式转换

2.将GIS数据转换为标准配置

auto_to_config.py

3.计划生成

命令行模式：run_irrigation_plan.py

- 读取 config.json 配置文件
- 调用核心算法生成灌溉计划
- 输出JSON格式的灌溉指令

web模式：web_farm_irrigation_modified.py

- 启动Web服务器
- 提供HTTP API接口
- 接收请求后调用相同的核心算法
