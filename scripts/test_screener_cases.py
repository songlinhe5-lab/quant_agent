"""
自动单元测试：专门针对大模型在选股时产生的“绝对大数”幻觉进行容错与纠偏验证。
执行方式: python -m unittest scripts/test_screener_cases.py
"""
import unittest
import asyncio
from unittest.mock import MagicMock
import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.services.futu.screener_handler import ScreenerHandler
from futu import RET_OK


class TestScreenerHallucinationDefense(unittest.IsolatedAsyncioTestCase):
    
    async def test_llm_hallucination_defense_logic(self):
        """
        测试：确保所有数值原样透传，遵循 AI_INSTRUCTIONS.md 中要求的绝对百分比格式。
        """
        # 1. 准备 Mock 的连接管理器，切断真实的 Futu OpenD 网络调用
        mock_conn_mgr = MagicMock()
        mock_conn_mgr.status = "CONNECTED"
        mock_conn_mgr.quote_ctx = MagicMock()
        # 模拟富途接口返回空数据列表 (正常拉取无结果)，让函数顺畅执行完毕
        mock_conn_mgr.quote_ctx.get_stock_screen.return_value = (RET_OK, (True, []))
        
        # 2. 实例化 ScreenerHandler
        handler = ScreenerHandler(mock_conn_mgr)
        
        # 3. 构造包含“大模型幻觉”数据的过滤条件字典
        filters = [
            {"field": "HIST_PERCENTILE_PE", "type": "featured", "max": 40.0, "min": -5.0},
            {"field": "CURRENT_RATIO", "type": "financial", "term": "ANNUAL", "min": 200.0},
            {"field": "PROPERTY_RATIO", "type": "financial", "term": "ANNUAL", "max": 100.0},
            # 正常数据: 应该原样通过，不受影响
            {"field": "HIST_PERCENTILE_PB", "type": "featured", "max": 0.8},
            {"field": "DEBT_EQUITY_RATIO", "type": "financial", "term": "ANNUAL", "min": 1.5}
        ]
        
        # 4. 执行选股操作 (内部的防御代码会原地修改 filters 字典)
        res = await handler.screen_stocks(market="HK", filters=filters)
        
        # 5. 断言验证
        self.assertEqual(res.get("status"), "success", "筛选函数应当顺利执行完毕而无异常")
        self.assertEqual(filters[0]["max"], 40.0, "HIST_PERCENTILE_PE 应该保持绝对百分比格式 40.0")
        self.assertEqual(filters[1]["min"], 200.0, "CURRENT_RATIO 应该保持绝对百分比格式 200.0")
        self.assertEqual(filters[3]["max"], 0.8, "正常的 0.8 历史百分位不应被修改")
        self.assertEqual(filters[4]["min"], 1.5, "正常的 1.5 产权比率不应被修改")