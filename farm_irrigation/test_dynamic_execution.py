"""
动态执行功能测试脚本

该脚本用于测试新实现的动态批次执行功能，包括：
1. 启动动态执行
2. 获取执行状态
3. 手动更新水位数据
4. 手动重新生成批次
5. 获取执行历史
6. 停止动态执行
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Any

class DynamicExecutionTester:
    """动态执行功能测试器"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        """
        初始化测试器
        
        Args:
            base_url: API服务器基础URL
        """
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def test_health_check(self) -> bool:
        """测试健康检查端点"""
        try:
            response = self.session.get(f"{self.base_url}/api/health")
            if response.status_code == 200:
                print("✅ 健康检查通过")
                return True
            else:
                print(f"❌ 健康检查失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ 健康检查异常: {str(e)}")
            return False
    
    def test_root_endpoint(self) -> bool:
        """测试根端点"""
        try:
            response = self.session.get(f"{self.base_url}/")
            if response.status_code == 200:
                data = response.json()
                print("✅ 根端点正常")
                print(f"   服务名称: {data.get('service')}")
                print(f"   版本: {data.get('version')}")
                
                # 检查是否包含新的动态执行端点
                endpoints = data.get('endpoints', {})
                dynamic_endpoints = [ep for ep in endpoints.keys() if 'dynamic-execution' in ep]
                print(f"   动态执行端点数量: {len(dynamic_endpoints)}")
                for ep in dynamic_endpoints:
                    print(f"     - {ep}: {endpoints[ep]}")
                
                return True
            else:
                print(f"❌ 根端点失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ 根端点异常: {str(e)}")
            return False
    
    def test_execution_status(self) -> Dict[str, Any]:
        """测试获取执行状态"""
        try:
            response = self.session.get(f"{self.base_url}/api/irrigation/dynamic-execution/status")
            if response.status_code == 200:
                data = response.json()
                print("✅ 获取执行状态成功")
                print(f"   当前状态: {data.get('status')}")
                print(f"   批次ID: {data.get('batch_id', 'N/A')}")
                print(f"   进度: {data.get('progress', 0):.1f}%")
                return data
            else:
                print(f"❌ 获取执行状态失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return {}
        except Exception as e:
            print(f"❌ 获取执行状态异常: {str(e)}")
            return {}
    
    def test_start_execution(self) -> bool:
        """测试启动动态执行"""
        try:
            # 构造启动请求 - 使用正确的字段名
            request_data = {
                "plan_file_path": "irrigation_plan_modified_20241230_143028.json",
                "farm_id": "test_farm_001",
                "config_file_path": "farm_config.json",
                "auto_start": True,
                "water_level_update_interval_minutes": 5,
                "enable_plan_regeneration": True,
                "execution_mode": "simulation"
            }
            
            response = self.session.post(
                f"{self.base_url}/api/irrigation/dynamic-execution/start",
                json=request_data
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 启动动态执行成功")
                print(f"   执行ID: {data.get('execution_id')}")
                print(f"   调度器状态: {data.get('scheduler_status')}")
                print(f"   消息: {data.get('message')}")
                return True
            else:
                print(f"❌ 启动动态执行失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 启动动态执行异常: {str(e)}")
            return False
    
    def test_update_waterlevels(self) -> bool:
        """测试手动更新水位数据"""
        try:
            # 构造水位更新请求 - 使用正确的字段名
            request_data = {
                "farm_id": "test_farm_001",
                "field_ids": ["field_001", "field_002", "field_003"],
                "force_update": True
            }
            
            response = self.session.post(
                f"{self.base_url}/api/irrigation/dynamic-execution/update-waterlevels",
                json=request_data
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 手动更新水位数据成功")
                print(f"   更新时间: {data.get('update_timestamp')}")
                print(f"   更新字段数: {len(data.get('updated_fields', {}))}")
                print(f"   数据质量摘要: {data.get('data_quality_summary')}")
                return True
            else:
                print(f"❌ 手动更新水位数据失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 手动更新水位数据异常: {str(e)}")
            return False
    
    def test_regenerate_batch(self) -> bool:
        """测试手动重新生成批次"""
        try:
            # 构造批次重新生成请求 - 使用正确的字段名
            request_data = {
                "batch_index": 0,
                "custom_water_levels": {
                    "field_001": 0.85,
                    "field_002": 0.92,
                    "field_003": 0.78
                },
                "force_regeneration": True
            }
            
            response = self.session.post(
                f"{self.base_url}/api/irrigation/dynamic-execution/regenerate-batch",
                json=request_data
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 手动重新生成批次成功")
                print(f"   批次索引: {data.get('batch_index')}")
                print(f"   变更数量: {data.get('changes_count')}")
                print(f"   变更摘要: {data.get('change_summary')}")
                return True
            else:
                print(f"❌ 手动重新生成批次失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 手动重新生成批次异常: {str(e)}")
            return False
    
    def test_get_history(self) -> bool:
        """测试获取执行历史"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/irrigation/dynamic-execution/history?limit=10"
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 获取执行历史成功")
                print(f"   历史记录数: {len(data.get('history', []))}")
                print(f"   总记录数: {data.get('total_count', 0)}")
                return True
            else:
                print(f"❌ 获取执行历史失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 获取执行历史异常: {str(e)}")
            return False
    
    def test_waterlevel_summary(self) -> bool:
        """测试获取水位数据摘要"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/irrigation/dynamic-execution/waterlevel-summary"
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 获取水位数据摘要成功")
                print(f"   字段数量: {len(data.get('field_summaries', []))}")
                print(f"   最后更新: {data.get('last_update_time', 'N/A')}")
                return True
            else:
                print(f"❌ 获取水位数据摘要失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 获取水位数据摘要异常: {str(e)}")
            return False
    
    def test_field_trend(self, field_id: str = "field_001") -> bool:
        """测试获取田块水位趋势"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/irrigation/dynamic-execution/field-trend/{field_id}?days=7"
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ 获取田块 {field_id} 水位趋势成功")
                print(f"   数据点数: {len(data.get('trend_data', []))}")
                print(f"   趋势方向: {data.get('trend_direction', 'N/A')}")
                return True
            else:
                print(f"❌ 获取田块水位趋势失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 获取田块水位趋势异常: {str(e)}")
            return False
    
    def test_stop_execution(self) -> bool:
        """测试停止动态执行"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/irrigation/dynamic-execution/stop"
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ 停止动态执行成功")
                print(f"   状态: {data.get('status')}")
                print(f"   消息: {data.get('message')}")
                return True
            else:
                print(f"❌ 停止动态执行失败: {response.status_code}")
                if response.text:
                    print(f"   错误信息: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 停止动态执行异常: {str(e)}")
            return False
    
    def run_full_test(self):
        """运行完整测试套件"""
        print("=" * 60)
        print("动态执行功能测试开始")
        print("=" * 60)
        
        test_results = []
        
        # 1. 基础连接测试
        print("\n1. 基础连接测试")
        print("-" * 30)
        test_results.append(("健康检查", self.test_health_check()))
        test_results.append(("根端点", self.test_root_endpoint()))
        
        # 2. 状态查询测试
        print("\n2. 状态查询测试")
        print("-" * 30)
        test_results.append(("执行状态", bool(self.test_execution_status())))
        test_results.append(("执行历史", self.test_get_history()))
        test_results.append(("水位摘要", self.test_waterlevel_summary()))
        test_results.append(("田块趋势", self.test_field_trend()))
        
        # 3. 动态执行测试（注意：这些测试可能会因为缺少实际的灌溉计划文件而失败）
        print("\n3. 动态执行测试")
        print("-" * 30)
        test_results.append(("启动执行", self.test_start_execution()))
        
        # 等待一下，让系统有时间处理
        time.sleep(2)
        
        test_results.append(("更新水位", self.test_update_waterlevels()))
        test_results.append(("重新生成批次", self.test_regenerate_batch()))
        
        # 等待一下
        time.sleep(1)
        
        test_results.append(("停止执行", self.test_stop_execution()))
        
        # 4. 测试结果汇总
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        
        passed = 0
        failed = 0
        
        for test_name, result in test_results:
            status = "✅ 通过" if result else "❌ 失败"
            print(f"{test_name:<15} {status}")
            if result:
                passed += 1
            else:
                failed += 1
        
        print(f"\n总计: {len(test_results)} 个测试")
        print(f"通过: {passed} 个")
        print(f"失败: {failed} 个")
        print(f"成功率: {(passed/len(test_results)*100):.1f}%")
        
        if failed == 0:
            print("\n🎉 所有测试都通过了！动态执行功能集成成功！")
        else:
            print(f"\n⚠️  有 {failed} 个测试失败，请检查相关功能。")
        
        return failed == 0

def main():
    """主函数"""
    print("动态执行功能测试脚本")
    print("确保API服务器正在运行在 http://127.0.0.1:8000")
    print("开始测试...")
    
    # 创建测试器并运行测试
    tester = DynamicExecutionTester()
    success = tester.run_full_test()
    
    if success:
        print("\n✅ 所有功能测试通过，系统集成成功！")
    else:
        print("\n❌ 部分功能测试失败，请检查系统配置。")

if __name__ == "__main__":
    main()