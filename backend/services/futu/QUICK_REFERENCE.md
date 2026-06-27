# FutuService 快速参考指南

## 🚀 快速开始

### 导入方式（完全兼容原有代码）
```python
from backend.services.futu_service import futu_service

# 或者使用新路径
from backend.services.futu import futu_service
```

### 连接 OpenD
```python
futu_service.connect()
```

---

## 📊 行情查询

### 实时行情
```python
quote = await futu_service.get_quote("AAPL")
# 返回: {"status": "success", "ticker": "US.AAPL", "last_price": 150.0, ...}
```

### 历史K线
```python
history = await futu_service.get_history("AAPL", ktype="K_DAY", num=60)
# ktype: K_DAY, K_60M, K_30M, K_15M, K_5M, K_1M
# 返回: {"status": "success", "data": [{"time": "...", "open": ..., ...}]}
```

### 盘口深度
```python
order_book = await futu_service.get_order_book("00700.HK")
# 返回: {"bids": [{"price": 315.2, "size": 1000}], "asks": [...]}
```

---

## 💰 期权与资金

### 期权链
```python
chain = await futu_service.get_option_chain("AAPL", expiration_date="2024-01-19")
# 如果不指定日期，自动获取最近到期日
# 返回: {"options": [{"option_code": "...", "strike_price": 150.0}]}
```

### 资金流向
```python
fund_flow = await futu_service.get_fund_flow("00700.HK")
# 返回: {"main_fund_net_inflow": 45000000.0, "broker_queue": {...}}
# ⚠️ 全局限流：60秒内最多60次请求
```

### 基本面数据
```python
fundamental = await futu_service.get_fundamental("AAPL")
# 返回: {"data": {"trailing_PE": 15.5, "price_to_book": 1.2, ...}}
```

---

## 🔍 选股服务

### 条件选股
```python
filters = [
    {"field": "PRICE", "type": "simple", "min": 10, "max": 100},
    {"field": "MARKET_CAP", "type": "simple", "min": 1000000000},
    {"field": "PE_RATIO", "type": "simple", "max": 20}
]
result = await futu_service.screen_stocks(market="US", filters=filters)
# 返回: {"data": [{"symbol": "AAPL", "name": "Apple Inc.", "price": 150.0}]}
```

**支持的筛选类型：**
- `simple`: 价格、市值、PE、PB 等
- `financial`: 营收、利润、ROE 等财务指标
- `accumulate`: 涨跌幅、换手率、振幅等累计指标
- `featured`: 筹码分布、资金流向等特色指标
- `indicator_pattern`: 金叉、死叉、超买、超卖等技术形态
- `indicator_positional`: 指标上穿/下穿位置关系
- `kline_shape`: 多头排列、红三兵等K线形态
- `broker`: 经纪商持股变化
- `option`: 期权相关指标
- `plate`: 行业板块筛选

### 批量快照
```python
tickers = ["US.AAPL", "US.MSFT", "US.GOOG"]
snapshots = await futu_service.get_market_snapshots(tickers)
# 返回: {"data": [{"code": "US.AAPL", "last_price": 150.0, ...}]}
```

### 股票基本信息
```python
info = await futu_service.get_stock_basicinfo(market="HK", sec_type="STOCK")
# sec_type: STOCK, ETF, INDEX
# 返回: {"data": [{"code": "HK.00700", "name": "腾讯控股", ...}]}
```

---

## 💼 交易操作

### 下单（模拟盘）
```python
from futu import TrdSide, TrdMarket

result = await futu_service.place_order(
    ticker="AAPL",
    qty=100,
    price=150.0,  # 0 表示市价单
    trd_side=TrdSide.BUY,
    market=TrdMarket.US
)
# 返回: {"status": "success", "order_id": "123456", "message": "..."}
```

### 撤单
```python
from futu import ModifyOrderOp, TrdMarket

result = await futu_service.modify_order(
    order_id="123456",
    op=ModifyOrderOp.CANCEL,
    market=TrdMarket.US
)
```

### 查询订单
```python
result = await futu_service.query_order(
    order_id="123456",
    market=TrdMarket.US
)
# 返回: {"order_status": "FILLED_ALL", "dealt_avg_price": 149.5}
```

### 账户信息
```python
account = await futu_service.get_account_info(market="HK")
# 返回: {
#   "total_assets": 1000000.0,
#   "cash": 250000.0,
#   "positions": [{"code": "HK.00700", "qty": 1000, ...}]
# }
```

---

## 🛠️ 工具函数

### Ticker 格式化
```python
formatted = futu_service.format_ticker("00700.HK")  # → "HK.00700"
formatted = futu_service.format_ticker("AAPL")      # → "US.AAPL"
formatted = futu_service.format_ticker("HSI")       # → "HK.800000"
```

### 检查是否支持
```python
is_supported = not futu_service.is_futu_unsupported("BTC-USD")  # → False
is_supported = not futu_service.is_futu_unsupported("AAPL")     # → True
```

---

## ⚙️ 环境变量配置

```bash
# OpenD 连接配置
export FUTU_HOST=127.0.0.1
export FUTU_PORT=11111

# 交易密码（可选，用于自动解锁）
export FUTU_TRD_UNLOCK_PWD=your_password
export FUTU_TRADE_PWD=your_password

# 交易环境
export FUTU_TRD_ENV=SIMULATE  # 或 REAL

# 开发环境（启用 Mock 数据）
export QUANT_ENV=development
```

---

## 🚨 注意事项

### 1. 限流保护
- **资金流向接口**：60秒内最多60次请求，触发限流后自动熔断60秒
- **历史K线**：优先使用订阅额度，失败后降级到历史额度
- **条件选股**：单次超时14秒，最多拉取2000只股票

### 2. 缓存策略
| 数据类型 | TTL | 说明 |
|---------|-----|------|
| 实时行情 | 3秒 | 阻挡前端高频轮询 |
| 历史K线 | 60秒 | 避免重复消耗额度 |
| 期权链 | 1小时 | 变化缓慢 |
| 资金流向 | 60秒 | 实时性要求中等 |
| 盘口深度 | 1秒 | 变化快 |
| 基本面 | 1小时 | 几乎不变 |

### 3. 不支持的资产
以下资产类型富途原生不支持，会自动返回错误：
- 外汇：`EURUSD=X`, `CNY=X`
- 加密货币：`BTC-USD`, `ETH-USD`
- 期指：`GC=F`（黄金）, `CL=F`（原油）
- 宏观指标：`DGS10`（10年期国债收益率）

### 4. 开发环境
设置 `QUANT_ENV=development` 且未连接 OpenD 时，所有接口自动返回 Mock 数据，无需真实账号即可开发调试。

---

## 🐛 常见问题

### Q: 如何清除缓存？
A: 调用 `futu_service.close()` 会清空所有缓存并断开连接。

### Q: 为什么资金流向返回 Mock 数据？
A: 可能触发了限流熔断，等待60秒后自动恢复。

### Q: 如何切换实盘/模拟盘？
A: 设置环境变量 `FUTU_TRD_ENV=REAL` 或 `SIMULATE`。

### Q: 条件选股返回数据太少？
A: 检查过滤条件是否过于严格，可以逐步放宽条件测试。

### Q: 如何查看详细的错误信息？
A: 所有错误响应都包含 `message` 字段，打印即可看到详细原因。

---

## 📚 更多信息

- 详细架构文档：[README.md](./README.md)
- 重构总结：[REFACTOR_SUMMARY.md](./REFACTOR_SUMMARY.md)
- Futu OpenD 官方文档：https://openapi.futunn.com/
