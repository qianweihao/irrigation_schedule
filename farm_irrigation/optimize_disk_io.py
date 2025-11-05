#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磁盘 I/O 优化脚本
用于优化文件读写操作，减少磁盘 I/O 瓶颈
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import List, Dict, Any
import json

logger = logging.getLogger(__name__)

class DiskIOOptimizer:
    """磁盘 I/O 优化器"""
    
    def __init__(self, temp_dir: str = None):
        """初始化优化器
        
        Args:
            temp_dir: 临时目录路径，如果为None则使用系统默认
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.temp_files = []  # 跟踪临时文件
        
    def create_temp_workspace(self, prefix: str = "irrigation_") -> str:
        """创建临时工作空间
        
        Args:
            prefix: 临时目录前缀
            
        Returns:
            临时目录路径
        """
        temp_workspace = tempfile.mkdtemp(prefix=prefix, dir=self.temp_dir)
        self.temp_files.append(temp_workspace)
        logger.info(f"创建临时工作空间: {temp_workspace}")
        return temp_workspace
    
    def optimize_file_copy(self, src: str, dst: str, buffer_size: int = 1024*1024) -> bool:
        """优化文件复制操作
        
        Args:
            src: 源文件路径
            dst: 目标文件路径
            buffer_size: 缓冲区大小（字节）
            
        Returns:
            是否成功
        """
        try:
            # 确保目标目录存在
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            
            # 使用大缓冲区进行文件复制
            with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
                while True:
                    buf = fsrc.read(buffer_size)
                    if not buf:
                        break
                    fdst.write(buf)
            
            logger.debug(f"文件复制完成: {src} -> {dst}")
            return True
            
        except Exception as e:
            logger.error(f"文件复制失败: {src} -> {dst}, 错误: {e}")
            return False
    
    def batch_copy_files(self, file_pairs: List[tuple], max_workers: int = 4) -> bool:
        """批量复制文件
        
        Args:
            file_pairs: 文件对列表 [(src1, dst1), (src2, dst2), ...]
            max_workers: 最大并发数
            
        Returns:
            是否全部成功
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        success_count = 0
        total_count = len(file_pairs)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有复制任务
            future_to_pair = {
                executor.submit(self.optimize_file_copy, src, dst): (src, dst)
                for src, dst in file_pairs
            }
            
            # 等待完成
            for future in as_completed(future_to_pair):
                src, dst = future_to_pair[future]
                try:
                    if future.result():
                        success_count += 1
                except Exception as e:
                    logger.error(f"批量复制任务失败: {src} -> {dst}, 错误: {e}")
        
        logger.info(f"批量复制完成: {success_count}/{total_count}")
        return success_count == total_count
    
    def optimize_json_operations(self, data: Dict[str, Any], file_path: str) -> bool:
        """优化 JSON 文件操作
        
        Args:
            data: 要写入的数据
            file_path: 文件路径
            
        Returns:
            是否成功
        """
        try:
            # 先写入临时文件，然后原子性移动
            temp_file = file_path + '.tmp'
            
            with open(temp_file, 'w', encoding='utf-8', buffering=8192) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子性移动
            shutil.move(temp_file, file_path)
            logger.debug(f"JSON 文件写入完成: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"JSON 文件写入失败: {file_path}, 错误: {e}")
            # 清理临时文件
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False
    
    def create_memory_mapped_file(self, file_path: str, size: int = None):
        """创建内存映射文件（用于大文件操作）
        
        Args:
            file_path: 文件路径
            size: 文件大小（如果为None则使用现有文件大小）
            
        Returns:
            内存映射对象
        """
        import mmap
        
        try:
            if size is None:
                # 读取现有文件
                with open(file_path, 'r+b') as f:
                    return mmap.mmap(f.fileno(), 0)
            else:
                # 创建新文件
                with open(file_path, 'w+b') as f:
                    f.write(b'\0' * size)
                    f.flush()
                    return mmap.mmap(f.fileno(), size)
                    
        except Exception as e:
            logger.error(f"创建内存映射文件失败: {file_path}, 错误: {e}")
            return None
    
    def cleanup_temp_files(self):
        """清理临时文件"""
        for temp_path in self.temp_files:
            try:
                if os.path.isfile(temp_path):
                    os.remove(temp_path)
                elif os.path.isdir(temp_path):
                    shutil.rmtree(temp_path)
                logger.debug(f"清理临时文件: {temp_path}")
            except Exception as e:
                logger.warning(f"清理临时文件失败: {temp_path}, 错误: {e}")
        
        self.temp_files.clear()
    
    def __del__(self):
        """析构函数，确保清理临时文件"""
        self.cleanup_temp_files()

def optimize_shapefile_operations(input_dir: str, output_dir: str) -> bool:
    """优化 Shapefile 操作
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        
    Returns:
        是否成功
    """
    optimizer = DiskIOOptimizer()
    
    try:
        # 创建临时工作空间
        temp_workspace = optimizer.create_temp_workspace("shapefile_")
        
        # 查找所有 shapefile 相关文件
        input_path = Path(input_dir)
        shapefile_groups = {}
        
        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
            for file_path in input_path.glob(f'*{ext}'):
                base_name = file_path.stem
                if base_name not in shapefile_groups:
                    shapefile_groups[base_name] = []
                shapefile_groups[base_name].append(str(file_path))
        
        # 批量复制到临时空间
        file_pairs = []
        for base_name, files in shapefile_groups.items():
            for file_path in files:
                src = file_path
                dst = os.path.join(temp_workspace, os.path.basename(file_path))
                file_pairs.append((src, dst))
        
        if file_pairs:
            success = optimizer.batch_copy_files(file_pairs)
            if success:
                logger.info(f"Shapefile 文件已优化复制到临时空间: {temp_workspace}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Shapefile 操作优化失败: {e}")
        return False
    finally:
        optimizer.cleanup_temp_files()

if __name__ == "__main__":
    # 测试优化器（修复编码问题）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('optimize_disk_io.log', encoding='utf-8')
        ]
    )
    
    optimizer = DiskIOOptimizer()
    
    # 测试临时工作空间
    temp_dir = optimizer.create_temp_workspace("test_")
    print(f"临时工作空间: {temp_dir}")
    
    # 清理
    optimizer.cleanup_temp_files()