# Futu Service 模块化架构

## 📁 目录结构

```
backend/services/futu/
├── __init__.py              # 包初始化，导出主服务
├── service.py               # 主服务入口（单例模式）
├── connection_manager.py    # 连接管理模块
├── cache_manager.py         # 缓存管理模块
├── quote_handler.py         # 行情数据处理模块
├── option_fund_handler.py   # 期权与资金流处理模块
├── screener_handler.py      # 选股服务模块
├── trade_handler.py         # 交易服务模块
├── mock_provider.py         # Mock 数据提供模块
├── utils.py                 # 工具函数模块
└── README.md                # 本文件
```

## 🏗️ 架构设计

### 核心思想
将原来 54KB 的单一庞大文件拆解为 **8 个职责单一的模块**，每个模块专注于一个特定领域，提高代码的可维护性、可测试性和可扩展性。

### 模块说明

#### 1. **connection_manager.py** - 连接管理模块
**职责：**
- 管理 Futu OpenD 行情网关的连接与断开
- 管理多个交易上下文（不同市场/环境）
- 提供交易密码自动解锁功能

**主要类：**
- `ConnectionManager`: 连接管理器单例

**关键方法：**
- `connect()`: 连接到 OpenD
- `close()`: 关闭所有连接
- `get_trade_context()`: 获取或创建交易上下文
- `unlock_trade_if_needed()`: 自动解锁交易

---

#### 2. **cache_manager.py** - 缓存管理模块
**职责：**
- 统一管理所有 L1 内存缓存
- 提供数据压缩工具
- 管理资金流向限流与熔断机制

**主要类：**
- `CacheManager`: 缓存管理器

**缓存类型：**
- Quote Cache (TTL: 3秒) - 实时行情
- History Cache (TTL: 60秒) - 历史K线
- Option Chain Cache (TTL: 3600秒) - 期权链
- Fund Flow Cache (TTL: 60秒) - 资金流向
- Order Book Cache (TTL: 1秒) - 盘口深度
- Fundamental Cache (TTL: 3600秒) - 基本面数据

**关键方法：**
- `get/set_*_cache()`: 各类缓存的读写接口
- `compress_quote_data()`: 压缩行情数据
- `compress_chain_data()`: 压缩期权链数据

---

#### 3. **quote_handler.py** - 行情数据处理模块
**职责：**
- 获取实时行情数据
- 获取历史K线数据（带降级策略）
- 获取 Level 2 盘口深度数据

**主要类：**
- `QuoteHandler`: 行情处理器

**关键方法：**
- `get_quote()`: 获取实时行情（带L1缓存）
- `get_history()`: 获取历史K线（优先使用订阅额度，降级使用历史额度）
- `get_order_book()`: 获取盘口深度（带L1缓存）

**特性：**
- 智能降级：`get_cur_kline` → `request_history_kline`
- 缓存优化：避免重复消耗历史K线额度
- 自动订阅管理

---

#### 4. **option_fund_handler.py** - 期权与资金流处理模块
**职责：**
- 获取期权链数据
- 获取资金流向数据（带熔断机制）
- 获取基本面数据

**主要类：**
- `OptionFundHandler`: 期权与资金流处理器

**关键方法：**
- `get_option_chain()`: 获取期权链
- `get_fund_flow()`: 获取资金流向（含经纪商队列和盘口）
- `get_fundamental()`: 获取基本面数据（PE、PB、股息率等）

**特性：**
- 资金流向全局限流（60秒内不超过60次）
- 熔断保护机制（触发后强制休眠60秒）
- 港股特有数据：经纪商队列、Level 1 盘口

---

#### 5. **screener_handler.py** - 选股服务模块
**职责：**
- 批量获取市场快照
- 条件选股（V2 API）
- 获取股票基本信息

**主要类：**
- `ScreenerHandler`: 选股处理器

**关键方法：**
- `get_market_snapshots()`: 批量获取快照（每次最多400只）
- `screen_stocks()`: 条件选股（支持10种指标类型）
- `get_stock_basicinfo()`: 获取股票/ETF基本信息

**支持的筛选类型：**
1. Simple Property - 简单行情属性（价格、市值等）
2. Financial Property - 财务属性（营收、利润等）
3. Cumulative Property - 累计行情属性（涨跌幅、换手率等）
4. Featured Property - 特色指标（筹码、资金流等）
5. Indicator Pattern - 技术指标形态（金叉、死叉等）
6. Indicator Positional - 技术指标位置关系（上穿、下穿等）
7. K-line Shape - K线形态（多头排列、红三兵等）
8. Broker - 经纪商持股
9. Option - 期权指标
10. Plate - 行业板块

**特性：**
- 智能单位纠偏（百分比自动×100）
- 智能类型纠偏（自动识别字段正确类型）
- 分页拉取（最多2000只股票）
- V2 API 全局唯一值反解析

---

#### 6. **trade_handler.py** - 交易服务模块
**职责：**
- 下单（模拟盘）
- 改单/撤单
- 订单查询
- 账户信息与持仓查询

**主要类：**
- `TradeHandler`: 交易处理器

**关键方法：**
- `place_order()`: 下单
- `modify_order()`: 改单/撤单
- `query_order()`: 查询订单状态
- `get_account_info()`: 获取账户信息和持仓

**特性：**
- 自动解锁交易
- 订单状态变更通知
- 支持实盘/模拟盘切换

---

#### 7. **mock_provider.py** - Mock 数据提供模块
**职责：**
- 为开发环境提供模拟数据
- 避免在开发时依赖真实 OpenD 连接

**主要类：**
- `MockProvider`: Mock 数据提供者（静态方法集合）

**提供的 Mock 数据：**
- `mock_quote()`: 模拟行情
- `mock_history()`: 模拟历史K线
- `mock_option_chain()`: 模拟期权链
- `mock_fund_flow()`: 模拟资金流向
- `mock_fundamental()`: 模拟基本面数据
- `mock_order_book()`: 模拟盘口深度
- `mock_account_info()`: 模拟账户信息

---

#### 8. **utils.py** - 工具函数模块
**职责：**
- 提供通用的 ticker 格式化功能
- 判断资产是否被 Futu 支持

**关键函数：**
- `format_ticker()`: 将各种格式的 ticker 转换为 Futu 标准格式
- `is_futu_unsupported()`: 判断是否为富途不支持的资产（外汇、加密货币等）

**支持的格式转换：**
- 指数简写：`HSI` → `HK.800000`, `SPX` → `US.SPX`
- 港股：`00700.HK` / `HK.00700` → `HK.00700`
- 美股：`AAPL` → `US.AAPL`
- A股：`600000.SH` → `SH.600000`

---

#### 9. **service.py** - 主服务模块
**职责：**
- 整合所有子模块
- 保持单例模式
- 提供统一的对外接口（与原接口完全兼容）

**主要类：**
- `FutuService`: 主服务类（单例）

**架构特点：**
- 组合模式：通过委托给各个 Handler 实现功能
- 接口兼容：所有公共方法与原接口保持一致
- 向后兼容：旧代码无需修改即可使用

**初始化流程：**
```python
FutuService._init()
├── ConnectionManager()      # 连接管理
├── CacheManager()           # 缓存管理
├── QuoteHandler()           # 行情处理
├── OptionFundHandler()      # 期权与资金流处理
├── ScreenerHandler()        # 选股处理
└── TradeHandler()           # 交易处理
```

---

## 🔄 迁移指南

### 对于使用者
**无需任何改动！** 新的模块化架构完全向后兼容：

```python
# 原有代码保持不变
from backend.services.futu_service import futu_service

# 所有方法调用方式不变
quote = await futu_service.get_quote("AAPL")
history = await futu_service.get_history("AAPL", "K_DAY", 60)
```

### 对于开发者
如需扩展新功能，建议：
1. 确定功能归属模块
2. 在对应 Handler 中添加新方法
3. 在 `service.py` 中暴露新接口

例如，添加新的行情指标：
```python
# 在 quote_handler.py 中添加
async def get_new_indicator(self, ticker: str):
    # 实现逻辑
    pass

# 在 service.py 中暴露
async def get_new_indicator(self, ticker: str):
    return await self.quote_handler.get_new_indicator(ticker)
```

---

## ✅ 重构优势

### 1. **可维护性提升**
- 每个模块 < 500 行代码，易于理解和维护
- 职责清晰，修改某功能不影响其他模块
- 降低代码耦合度

### 2. **可测试性提升**
- 可以单独测试每个 Handler
- Mock 更容易注入
- 单元测试覆盖率更高

### 3. **可扩展性提升**
- 新增功能只需添加新模块或扩展现有 Handler
- 不影响现有代码
- 支持插件化扩展

### 4. **代码复用**
- `CacheManager` 可被多个 Handler 共享
- `MockProvider` 独立于业务逻辑
- 工具函数集中管理

### 5. **性能优化**
- 缓存策略集中管理，便于统一优化
- 限流和熔断机制更清晰
- 资源管理更高效

---

## 📊 代码统计

| 模块 | 行数 | 职责 |
|------|------|------|
| connection_manager.py | ~60 | 连接管理 |
| cache_manager.py | ~150 | 缓存管理 |
| quote_handler.py | ~180 | 行情处理 |
| option_fund_handler.py | ~220 | 期权与资金流 |
| screener_handler.py | ~350 | 选股服务 |
| trade_handler.py | ~120 | 交易服务 |
| mock_provider.py | ~120 | Mock 数据 |
| utils.py | ~30 | 工具函数 |
| service.py | ~120 | 主服务整合 |
| **总计** | **~1350** | **模块化架构** |

**对比：** 原文件 54KB (~1400行) → 新架构 9个文件平均 ~150行/文件

---

## 🎯 最佳实践

1. **不要直接访问内部组件**
   ```python
   # ❌ 错误
   futu_service.quote_handler.get_quote(...)
   
   # ✅ 正确
   futu_service.get_quote(...)
   ```

2. **缓存键命名规范**
   ```python
   f"futu_{data_type}_{ticker}_{params}"
   # 例如: "futu_history_US.AAPL_K_DAY"
   ```

3. **错误处理**
   - 所有异步方法返回统一格式：`{"status": "success/error", ...}`
   - 开发环境自动降级到 Mock 数据

4. **限流与熔断**
   - 资金流向接口已实现全局限流
   - 触发限流自动开启熔断保护

---

## 🔧 常见问题

### Q: 为什么要保留 futu_service.py？
A: 为了保持向后兼容，所有导入 `from backend.services.futu_service import futu_service` 的代码无需修改。

### Q: 如何调试某个模块？
A: 可以直接导入对应的 Handler 进行单元测试：
```python
from backend.services.futu.quote_handler import QuoteHandler
```

### Q: 缓存何时清除？
A: 
- 自动过期：根据 TTL 自动失效
- 手动清除：调用 `close()` 会清空所有缓存
- 重启服务：进程重启后缓存自然清空

### Q: 如何添加新的缓存类型？
A: 
1. 在 `CacheManager` 中添加新的缓存字典
2. 添加 `get/set` 方法
3. 在对应 Handler 中使用

---

## 📝 更新日志

**2026-06-08** - 完成模块化重构
- 拆解原 54KB 单一文件为 9 个模块
- 保持 100% 接口兼容性
- 提升代码可维护性和可扩展性
