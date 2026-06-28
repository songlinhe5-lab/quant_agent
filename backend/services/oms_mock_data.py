# 追加到 backend/services/oms_mock_data.py 文件末尾

INITIAL_BOTS = [
    {
        "id": "bot_01",
        "name": "Alpha-Trend-Follower",
        "ticker": "US.QQQ",
        "status": "running",
        "cpu": 12.5,
        "mem": 128.0,
        "logs": [
            {"time": "09:30:00", "msg": "Bot started. Subscribed to market data.", "type": "info"},  # noqa: E501
            {"time": "09:35:12", "msg": "Volume breakout detected. Scanning signals...", "type": "info"}  # noqa: E501
        ]
    },
    {
        "id": "bot_02",
        "name": "Pairs-Arbitrage",
        "ticker": "HK.00700",
        "status": "paused",
        "cpu": 0.0,
        "mem": 64.0,
        "logs": [
            {"time": "10:00:00", "msg": "Spread deviation too low, strategy paused.", "type": "warn"}  # noqa: E501
        ]
    }
]

ACTIVE_ORDERS = [
    {
        "id": "ord_1001",
        "symbol": "US.QQQ",
        "side": "BUY",
        "price": "430.50",
        "qty": 100,
        "filled": 0,
        "status": "PENDING",
        "time": "09:35:15"
    }
]

HISTORICAL_TRADES = [
    {
        "id": "trd_2001",
        "symbol": "US.AAPL",
        "side": "SELL",
        "avg_price": "190.20",
        "qty": 50,
        "pnl": 125.50,
        "time": "09:40:00"
    }
]

ALGO_EXECUTIONS = [
    {
        "id": "algo_twap_8801",
        "algo_type": "TWAP",
        "symbol": "US.QQQ",
        "target_qty": 10000,
        "filled_qty": 6500,
        "avg_price": "435.20",
        "progress": 65,
        "status": "RUNNING",
        "message": "执行平稳，剩余时间约 45 分钟"
    },
    {
        "id": "algo_vwap_8802",
        "algo_type": "VWAP",
        "symbol": "HK.09988",
        "target_qty": 50000,
        "filled_qty": 6000,
        "avg_price": "72.45",
        "progress": 12,
        "status": "PAUSED",
        "message": "算法探测到当前盘口成交低迷，暂停挂单等待放量"
    },
    {
        "id": "algo_iceberg_8803",
        "algo_type": "ICEBERG",
        "symbol": "US.NVDA",
        "target_qty": 2000,
        "filled_qty": 2000,
        "avg_price": "125.60",
        "progress": 100,
        "status": "COMPLETED",
        "message": "冰山委托拆单已全部成交完毕"
    },
    {
        "id": "algo_twap_8804",
        "algo_type": "TWAP",
        "symbol": "US.AAPL",
        "target_qty": 5000,
        "filled_qty": 1200,
        "avg_price": "189.50",
        "progress": 24,
        "status": "ERROR",
        "message": "风控拦截：超出单日个股最大资金暴露限额"
    }
]
