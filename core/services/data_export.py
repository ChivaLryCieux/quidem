import pandas as pd
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DataExportService:
    def __init__(self, export_dir="exports"):
        """
        初始化数据导出服务
        
        Args:
            export_dir: 导出文件保存目录
        """
        self.export_dir = export_dir
        self.ensure_export_dir()
        
    def ensure_export_dir(self):
        """确保导出目录存在"""
        if not os.path.exists(self.export_dir):
            os.makedirs(self.export_dir)
            
    def export_trades_to_csv(self, trades, filename=None):
        """
        导出交易记录到CSV文件
        
        Args:
            trades: 交易记录列表
            filename: 文件名，如果为None则自动生成
            
        Returns:
            导出的文件路径
        """
        if not trades:
            logger.warning("没有交易数据可导出")
            return None
            
        # 转换为DataFrame
        df = pd.DataFrame(trades)
        
        # 时间戳转换
        if 'entry_time' in df.columns:
            df['entry_time_dt'] = pd.to_datetime(df['entry_time'], unit='ms')
        if 'exit_time' in df.columns:
            df['exit_time_dt'] = pd.to_datetime(df['exit_time'], unit='ms')
            
        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"trades_export_{timestamp}.csv"
            
        filepath = os.path.join(self.export_dir, filename)
        
        # 导出CSV
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        logger.info(f"交易数据已导出到: {filepath}")
        
        return filepath
        
    def export_trades_to_json(self, trades, filename=None):
        """
        导出交易记录到JSON文件
        
        Args:
            trades: 交易记录列表
            filename: 文件名，如果为None则自动生成
            
        Returns:
            导出的文件路径
        """
        if not trades:
            logger.warning("没有交易数据可导出")
            return None
            
        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"trades_export_{timestamp}.json"
            
        filepath = os.path.join(self.export_dir, filename)
        
        # 导出JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
            
        logger.info(f"交易数据已导出到: {filepath}")
        return filepath
        
    def export_portfolio_summary(self, portfolio_data, filename=None):
        """
        导出投资组合摘要
        
        Args:
            portfolio_data: 投资组合数据字典
            filename: 文件名，如果为None则自动生成
            
        Returns:
            导出的文件路径
        """
        if not portfolio_data:
            logger.warning("没有投资组合数据可导出")
            return None
            
        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"portfolio_summary_{timestamp}.json"
            
        filepath = os.path.join(self.export_dir, filename)
        
        # 添加时间戳
        portfolio_data['export_time'] = datetime.now().isoformat()
        
        # 导出JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(portfolio_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"投资组合摘要已导出到: {filepath}")
        return filepath
        
    def export_performance_metrics(self, metrics_data, filename=None):
        """
        导出绩效指标
        
        Args:
            metrics_data: 绩效指标数据字典
            filename: 文件名，如果为None则自动生成
            
        Returns:
            导出的文件路径
        """
        if not metrics_data:
            logger.warning("没有绩效指标数据可导出")
            return None
            
        # 生成文件名
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"performance_metrics_{timestamp}.json"
            
        filepath = os.path.join(self.export_dir, filename)
        
        # 添加时间戳
        metrics_data['export_time'] = datetime.now().isoformat()
        
        # 导出JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(metrics_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"绩效指标已导出到: {filepath}")
        return filepath
        
    def create_daily_archive(self, trades_data, portfolio_data, metrics_data):
        """
        创建每日归档文件
        
        Args:
            trades_data: 交易数据
            portfolio_data: 投资组合数据
            metrics_data: 绩效指标数据
            
        Returns:
            归档文件路径
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_filename = f"daily_archive_{timestamp}.json"
        archive_filepath = os.path.join(self.export_dir, archive_filename)
        
        archive_data = {
            'export_time': datetime.now().isoformat(),
            'trades': trades_data,
            'portfolio': portfolio_data,
            'metrics': metrics_data
        }
        
        with open(archive_filepath, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"每日归档已创建: {archive_filepath}")
        return archive_filepath
        
    def get_export_files(self, file_type=None):
        """
        获取导出文件列表
        
        Args:
            file_type: 文件类型过滤 (csv, json, 或 None表示所有)
            
        Returns:
            文件路径列表
        """
        files = []
        for filename in os.listdir(self.export_dir):
            if file_type:
                if filename.endswith(f'.{file_type}'):
                    files.append(os.path.join(self.export_dir, filename))
            else:
                files.append(os.path.join(self.export_dir, filename))
                
        # 按修改时间排序
        files.sort(key=os.path.getmtime, reverse=True)
        return files