# 🏛️ OPT-001~004架构评审会议材料

**会议主题**: Phase 1 核心架构整治范围与优先级确认  
**会议时长**: 2 小时  
**参会人员**: Backend Lead, Data Engineer, QA Lead, Tech Lead, PM  
**会议日期**: TBD  

---

## 📋 会议议程（120 分钟）

| 时间段 | 议题 | 负责人 | 产出物 |
|--------|------|--------|--------|
| **00:00-00:10** | 开场与背景介绍 | Tech Lead | 明确会议目标 |
| **00:10-00:40** | OPT-001: Router 层解耦深度分析 | Backend Lead | 决策：技术方案 + 工作量评估 |
| **00:40-01:10** | OPT-002: Point-in-Time 财务数据处理方案 | Data Engineer | 决策：数据源 + 实施策略 |
| **01:10-01:20** | 茶歇休息 | - | - |
| **01:20-01:50** | OPT-003+004: Application 重构与数据正确性测试 | QA Lead + Backend Dev | 决策：迁移顺序 + 测试覆盖标准 |
| **01:50-02:00** | 总结与下一步行动 | PM | 任务分配表 + 时间线确认 |

---

## 🔍 **议题一：OPT-001 Router 层解耦（30 分钟）**

### 问题描述

**当前反模式代码示例**（`backend/routers/market.py` L156-162）:

```python
# ❌ 违反整洁架构原则：Router 直连 Adapter
if is_a_share and (msg and msg != "Futu OpenD 未连接且无可用远程节点"):
    ak_res = await data_source_router.fetch_akshare("stock_quote", ticker=ticker)
    if ak_res.get("status") == "success":   
        return ak_res
```

**问题分析**:
1. `market.py` → `data_source_router` → `akshare_service` 形成硬耦合
2. 新增数据源需修改 Router 代码（违反开闭原则）
3. 无法单元测试（依赖真实外部 API）

### 技术方案对比

#### **方案 A：完全抽象化（推荐 ✅）**

```
架构变更:
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Router Layer  │─────▶│ ApplicationSvc   │─────▶│ DataSourcePort  │
│  (market.py)    │      │ (services/*_app) │      │ (Protocol ABC)  │
└─────────────────┘      └──────────────────┘      └────────┬────────┘
                                                             │
                                          ┌──────────────────┴──────────────────┐
                                          ▼                  ▼                  ▼
                                  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
                                  │ AkShareImpl   │  │ FutuImpl      │  │ YFinanceImpl  │
                                  │ (Adapter)     │  │ (Adapter)     │  │ (Adapter)     │
                                  └───────────────┘  └───────────────┘  └───────────────┘
```

**优点**:
- ✅ 严格遵循 Clean Architecture，依赖只向内
- ✅ Router 零感知底层数据源变化
- ✅ 可 Mock DataSourcePort 进行单元测试

**缺点**:
- ⚠️ 工作量较大（约 8h）
- ⚠️ 需重构所有 Router 代码

**实施步骤**:
1. 定义 `DataSourceInterface` Protocol（1h）
2. 将 `data_source_router.fetch_*` 封装为 Application Service（3h）
3. Router 调用 Service 而非直接调 Router（3h）
4. 静态扫描验证无直连 import（1h）

---

#### **方案 B：渐进式过渡（备选 ⚠️）**

```
保留 data_source_router 中间层，但禁止新业务接入
逐步迁移至 Application Service 模式
```

**优点**:
- ✅ 改动小，短期压力低
- ✅ 团队适应期长

**缺点**:
- ❌ 长期维护双模式，认知负担重
- ❌ 无法彻底解决耦合问题

**结论**: 推荐方案 A，虽然初期投入大但一劳永逸

**决策点**: 
- [ ] 同意采用方案 A 完全抽象化
- [ ] 选择方案 B 渐进式过渡
- [ ] 其他意见：_______

---

## 📊 **议题二：OPT-002 Point-in-Time 财务数据处理（30 分钟）**

### 问题描述

**当前风险**: 回测中使用"未来信息"，导致结果失真

**典型场景**:
```python
# ❌ 错误用法：使用最新财报日期对齐历史 K 线
backtest.run(
    start_date="2023-01-01",
    earnings_data=df  # 包含 2023-04-20 发布的 2022Q4 财报
)
# 实际在 2023-01-01 ~ 2023-04-19 期间，市场还不知道这份财报
```

### 技术实施方案

#### **数据源选择**

| 数据源 | 覆盖范围 | PIT 支持 | 成本 | 建议 |
|--------|---------|---------|------|------|
| **SEC EDGAR** | 美股 | ✅ Native | 免费 | 必选 |
| **港交所披露易** | 港股 | ⚠️ 需解析 | 免费 | 可选 |
| **东财/同花顺** | A 股 | ❌ 不支持 | $/月 | 暂缓 |
| **自建爬虫** | 全市场 | ⚠️ 高维护 | 人力 | 不推荐 |

**决策**: 
- ✅ Phase 1 仅支持美股 SEC EDGAR（成熟稳定）
- 🟡 Phase 2 扩展至港股（视资源而定）
- ❌ Phase 1 暂不支持 A 股（数据源不可靠）

#### **实现策略**

```python
class PitEarningsDataset:
    """Point-in-Time 财报数据集"""
    
    def __init__(self):
        self.earnings_records = []  # 每条含：ticker, report_date, filed_date, period_end
    
    def get_available_at(self, ticker: str, as_of_date: datetime) -> List[Earning]:
        """返回截至 as_of_date 时已公开的财报"""
        return [
            e for e in self.earnings_records 
            if e.ticker == ticker and e.file_date <= as_of_date
        ]
```

**工作量估算**:
- SEC EDGAR API 对接：4h
- 历史数据清洗与入库：6h
- BacktestEngine 集成改造：4h
- 单元测试 + 验证：2h
- **总计**: 16h

**决策点**:
- [ ] 同意仅支持美股 SEC EDGAR（Phase 1 范围限制）
- [ ] 是否增加港股数据源（+8h）
- [ ] 是否需要 A 股替代方案（如 Proxy 指标）

---

## 🏗️ **议题三：OPT-003 Application 层重构（15 分钟）**

### 现状分析

**当前目录结构**（混乱）:
```
backend/
├── routers/          # Router 层
├── services/         # ❌ 职责混杂：既有 Application 逻辑又有 Adapter 实现
│   ├── futu_service.py     # Adapter
│   ├── yfinance_service.py # Adapter
│   ├── screener_app.py     # Application 编排
│   └── market_app.py       # Application 编排
└── domain/           # Domain 层（缺失）
```

**理想结构**（整洁架构）:
```
backend/
├── routers/              # Router 层（参数校验）
├── app/                  # ✅ Application 层（用例编排）
│   ├── screener_app.py
│   ├── backtest_app.py
│   └── alert_app.py
├── domain/               # ✅ Domain 层（纯业务逻辑）
│   ├── entities/
│   │   ├── Order.py
│   │   ├── Strategy.py
│   │   └── AlertRule.py
│   └── ports/
│       ├── QuotePort.py
│       ├── BrokerPort.py
│       └── StorePort.py
└── adapters/             # ✅ Adapter 层（具体实现）
    ├── futu/
    ├── yfinance/
    └── akshare/
```

**迁移策略**:
1. 先创建 `backend/app/` + `backend/domain/` 目录（0.5h）
2. 逐个移动 `services/*.py` 中的 Application 逻辑到新目录（4h）
3. 将 Adapter 逻辑移至 `adapters/`（4h）
4. 更新所有 import 路径（3h）
5. **总计**: 12h

**决策点**:
- [ ] 同意上述目录结构
- [ ] 是否有其他架构偏好
- [ ] 是否需要并行运行旧 structures（过渡期）

---

## 🧪 **议题四：OPT-004 数据正确性单元测试（15 分钟）**

### 测试范围定义

| 测试类型 | 测试内容 | 数据量 | 预计时间 |
|---------|---------|--------|---------|
| **退市数据集** | 验证回测包含已退市标的 | 500+ 股票 | 2h |
| **PIT 验证** | 确保财报发布日期前不可见 | 1000+ 财报 | 4h |
| **SVC 契约回放** | 模拟外部 API 响应边界条件 | 50+ cases | 2h |

### 测试框架建议

```python
# tests/data_quality/test_pit_earnings.py
def test_earnings_not_available_before_filed_date():
    """财报在正式公布前不应出现在回测数据集中"""
    pit_dataset = PitEarningsDataset.load_from_edgar()
    
    # AAPL 2022Q4 财报于 2023-02-01 公布
    as_of_20230131 = datetime(2023, 1, 31)
    available = pit_dataset.get_available_at("AAPL", as_of_20230131)
    
    assert not any(e.period_end == "2022-12-31" for e in available)
    
    # 但在 2023-02-02 应该可见
    as_of_20230202 = datetime(2023, 2, 2)
    available_later = pit_dataset.get_available_at("AAPL", as_of_20230202)
    assert any(e.period_end == "2022-12-31" for e in available_later)
```

**覆盖率标准**:
- 必须达到 ≥80%（OPT-007 门禁恢复的前提）
- 重点覆盖边界条件（空数据集、极端日期、异常格式）

**决策点**:
- [ ] 同意上述测试范围
- [ ] 是否需要引入 property-based testing（Hypothesis）
- [ ] 测试数据托管位置（fixtures/ vs s3://）

---

## ✅ **决策总结模板**

请参会人员在会议结束时填写：

```markdown
## 决策记录

### OPT-001 Router 解耦
- 技术方案：□方案 A  □方案 B  □其他
- 工作量确认：□8h ✓  □调整至__h
- 开始时间：□Week 1 Day 1  □延后

### OPT-002 Point-in-Time
- 数据源范围：□美股 SEC  □加港股  □全部
- 工作量确认：□16h ✓  □调整至__h
- 外部依赖：□需 SEC API Key  □无需

### OPT-003 Application 重构
- 目录结构：□同意默认  □定制方案
- 迁移顺序：□按服务  □按模块  □混合

### OPT-004 数据正确性测试
- 测试范围：□退市  □PIT  □SVC  □全部
- 覆盖率门槛：□80%  □70%  □90%
- 数据来源：□自制  □购买  □开源

## 风险提示

1. _______
2. _______
3. _______

## 资源承诺

- Backend Lead 投入：□全职 Week 1-2  □半职 Week 1-4
- Data Engineer 投入：□全职 Week 1-2  □半职 Week 1-4
- QA Engineer 投入：□Week 2 开始  □Week 1 开始

## 下一步行动

| 任务 | 责任人 | 截止日期 |
|------|--------|---------|
| 输出详细设计文档 | Backend Lead | 会议后 1 天 |
| 创建 GitHub Issue | PM | 会议后 1 天 |
| 准备测试数据 | Data Engineer | 会议后 3 天 |
```

---

## 📎 **附录：参考文档**

1. `docs/03. 后端架构与执行引擎.md` V5.1 - 整洁架构分层规范
2. `docs/14. 分布式数据源服务架构.md` V2.0 - DataSourceInterface 定义
3. `docs/19. Parquet 数据湖快照版本化设计.md` - PIT 数据模型参考
4. `backend/services/market.py` - 当前 problematic 代码示例
5. SEC EDGAR API 官方文档：https://www.sec.gov/edgar/sec-api-documentation

---

**会议主持人备注**: 确保每个议题都有明确决策，避免模糊结论。如遇争议超过 5 分钟，标记为"待裁决"并由 Tech Lead 会后单独协调。
