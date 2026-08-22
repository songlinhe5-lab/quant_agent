## 资产风控与高级归因(/risk)· UI/UE 重构设计

> 目标:把"风控仪表盘"升级为**名实相符的资产风控与归因工作台**:修正 VaR 口径误导、兑现导航承诺的"高级归因"、把断连横幅与数据新鲜度真正联动,并把上下堆叠的双账户长页改为聚焦的单账户工作台 + 账户切换。
> 范围:纯 UI/UE 设计,不改代码;设计 tokens 与既有导入稿一致(bg #0F0F14 / panel #16181F / up #34D399 / down #F87171 / warn #FBBF24 / ai #A78BFA / blue #60A5FA)。
> 配套 Figma 稿:《资产风控与高级归因_Figma导入稿.html》(3 帧:账户概览 / 因子归因 / 压测与状态规范)。
> 日期:2026-08-21 · 代码落点已核对 `features/trading/risk*` 与 `backend/services/risk/`(见文末事实索引)

---

### 一、现状诊断(截图 + 代码核对)

本页后端数据链路是真材实料(Futu 模拟盘 → risk_engine 全后端计算),问题集中在**口径误导、命名透支、状态脱节**三类:

1. **P0 · VaR 口径误导。** 截图里 VaR 95% = $322,对着 $88 万净值完全不成比例。根因:`var_95` 是日收益的 5 分位(比率),展示时乘了**硬编码 10000**(`risk_engine.py:452-457`),隐含固定 $10k 名义本金,与账户实际规模脱钩;阈值分档 `-3000 / (2000,3000)` 也基于这个固定量纲。UI 必须改为**按实际净值的金额口径 + 百分比口径并列**,否则风控数字形同虚设。
2. **"高级归因"名不副实。** 导航叫"资产风控与高级归因",但页面上**没有归因 UI**。后端 RISK-02 `GET /risk/attribution`(Jensen's Alpha 单因子:α/β/R²/beta_contrib/alpha_pct/residual_pct)已实现,前端零调用。另有 `/risk/liquidity`、`/risk/positions-breakdown`、`/risk/stress-test/scenarios` 同为未被消费的孤儿端点。**命名承诺要兑现:归因得有自己的 tab。**
3. **断连横幅与数据脱节。** 红色"无法连接服务器"横幅(后端状态 offline)与页面数据**完全解耦**——fetch 成功就全量渲染,无 STALE/降级。对比 OMS 页有 STALE 遮罩(`oms.tsx:46-52`),本页没有等价物。截图里"横幅在但数据全量展示"是实现的必然,却是最伤信任的观感。
4. **双账户上下堆叠,页面超长。** 港股 + 美股两个完整账户面板纵向堆叠,每账户各自 KPI + 净值 + tabs + 雷达 + 敞口 + 持仓,滚动负担重,无法横向对比。账户是**写死的 `['HK','US']`**(前端 `risk.tsx:59`、后端 `risk_engine.py:68`),非动态列表。
5. **雷达维度口径混乱。** 后端 `_build_risk_radar` 返回**六维** Beta/Vol/Liq/Corr/Mom/DD(`risk_engine.py:376-426`),HelpPanel 也写"六维"。截图显示的 5 维含 "Cave" 与当前代码不符(全仓 grep "Cave" 零命中;推测截图为旧构建/移动端/视觉误读)。设计一律按代码事实的**六维**呈现,并给每维"算法口径"说明(Liq 是"简化代理",Mom 有公式)。
6. **持仓表交互缺失 + 数据脏。** 无排序、无行点击下钻、无占比合计校验(`risk-account-section.tsx:303-365`);占比 = 市值/nav 逐行独立算,多头/空头/现金分母不一致。名称透传 Futu 无纠错(截图 HK.00772 显示"闽文集团",官方应为"阅文集团",数据源脏名)。
7. **风险分级文案不统一。** 组件内 4 档(≥70 高 / ≥50 中高 / ≥30 中等 / <30 低)与 `lib/constants.ts:53-59` 注释("低风险/极低风险")语义冲突。需统一到单一 SSOT。
8. **快照口径要点。** 净值曲线 days≤1 读 Redis `lrange(0,287)` 最多 **288 条**,由 NAV 守护进程每 300 秒采样、`ltrim` 保留(`lifecycle.py:154-172`)。"288 快照 / 每 5 分钟采样"是真状态,保留并标注数据时点。
9. 工程债(不在本设计范围,列此备查):`risk-account-section.tsx` 368 行、`risk-charts.tsx` 274 行、后端 `risk_engine.py` 505 行 / `routers/risk.py` 230 行 / `risk_stress.py` 244 行均超宪法上限;OMS 导航徽章 `badge:'3'` 是**硬编码字符串且为绿色**非动态;`'use client'`、`console.error` 残留;截图"+ 净值"按钮在代码中不存在(推测旧版/误读)。

---

### 二、重构后功能分区

改"双账户纵向长页"为**聚焦单账户工作台 + 账户切换**,五区自上而下:

```
┌────────────────────────────────────────────────────────────┐
│ A 账户切换条:[港股模拟账户 ●][美股模拟账户]      [数据时点·新鲜度] │
│    (每 tab 带净值/日涨跌 mini,选中态高亮)                    │
├────────────────────────────────────────────────────────────┤
│ B 核心指标行:总净值(+涨跌) · 现金 · 市值 · VaR95% · Sharpe    │
│    旁:净值曲线(288 快照·5 分钟采样·时点标注)                  │
├────────────────────────────────────────────────────────────┤
│ C 风险画像:总分环 + 雷达(六维·限额线)+ 敞口/集中度(Top1)      │
├────────────────────────────────────────────────────────────┤
│ D Tabs:[概览][因子归因][压测]                                │
│   概览     → 持仓明细表(排序/下钻/合计校验/脏名标注)           │
│   因子归因 → 因子阈值列表 + Jensen α/β/R² + 板块 + 相关性       │
│   压测     → CVaR 瀑布 + 情景压测(历史 3 + 假设 3)            │
├────────────────────────────────────────────────────────────┤
│ E 全局:SANDBOX 横幅(保留)+ 断连 → 全页 STALE 遮罩(联动)       │
└────────────────────────────────────────────────────────────┘
```

**A · 账户切换条**
- 顶部账户 tabs 取代纵向堆叠:每个 tab 展示市场标签 + 净值 mini + 日涨跌徽章,选中态高亮。切换只重渲染下方 B–D,不重新整页拉取(`/risk/dashboard` 本就一次全量返回两账户,前端本地切换即可)。
- 右侧"数据时点"显示 `ts` + 新鲜度:正常 → 灰色时点;断连/滞后 → STALE 琥珀(见 E 区)。

**B · 核心指标行 + 净值曲线**
- 五张 KPI 卡:总净值(含涨跌额/幅,涨绿跌红)/ 现金(占比)/ 市值(杠杆占比)/ **VaR 95%(金额 + %双口径)**/ Sharpe。
- **VaR 卡重设计(P0)**:主数为 `|var_95| × nav` 的金额,副数为占净值百分比;旁挂口径 tooltip"日收益 5 分位 × 当前净值";阈值分档改用百分比而非固定 $ 量纲。修复前若仍用旧口径,UI 必须打 STALE/占位,不得展示误导数字。
- 净值曲线(NavAreaChart)保留,标注"288 快照 · 每 5 分钟采样 · 数据时点 hh:mm"。

**C · 风险画像**
- 总分环(RiskScoreGauge):六维 current 算术平均,分级文案统一 SSOT(高/中高/中等/低),环色随等级。
- 雷达按**代码事实六维** Beta/Vol/Liq/Corr/Mom/DD 呈现,双 series(当前 + 限额);每维 hover 显示算法口径(Liq=简化代理、Mom=50+20日对数动量×200 等),HelpPanel 同步为六维。
- 敞口/集中度条:多头/空头/现金(统一三分量命名,不用"现货"),标注 Top1 集中度与占比合计校验。

**D · 三 tab**
- **概览 = 持仓明细表**:列(代码/名称/方向/数量/市值/盈亏/盈亏%/占比)保留,补交互——点击表头排序、行点击下钻 `/market/:ticker`、底部合计行(市值合计 / 占比合计,校验是否≈100%)、脏名标注(名称来源 Futu,异常名加"以交易所为准"提示)。
- **因子归因(新,兑现命名)**:上半 = 现有因子阈值列表(Market Beta / VaR / Sharpe / Max DD,safe/warn/good/crit 状态);下半 = **接入 `/risk/attribution` 的 Jensen α/β/R² 卡 + 收益贡献分解条(beta_contrib / alpha / residual)**,旁置板块暴露(SectorBarChart)与相关性热力图(CorrelationHeatmap)。
- **压测**:CVaR 瀑布(CVarWaterfallChart,历史模拟法分解)+ 情景压测(历史 2008/2020/2022 + 假设 利率/波动率/汇率)。明示历史情景用**预设 shock/板块冲击系数**,非真实历史 K 线回放,避免口径误导。

**E · 全局状态(断连联动)**
- SANDBOX 横幅保留。断连(backend-status offline)时,本页数据区加 **STALE 遮罩**(对齐 OMS 页):`opacity-60 saturate-50` + 琥珀 STALE 标签 + "数据为最后一次成功快照,可能滞后"文案,禁止无标注展示。恢复(/health 探测成功)自动摘除。

---

### 三、与既有模块的关系

- 数据直连 **Futu 模拟盘**(FUTU_TRD_ENV=SIMULATE),不经 OMS、不读 /paper 纸面组合——口径上需标注"模拟盘账户",与全局 SANDBOX 语义一致。
- 账户摘要已写入 `useCopilotContextStore` 供全局 AI 副驾场景感知(保留)。
- 与 Alert Center / OMS 同属风控副驾导航分组,但数据相互独立;OMS 徽章 `badge:'3'` 硬编码问题另行工单。

---

### 四、状态与闸门规范

| 场景 | 规范 |
|---|---|
| SANDBOX / PAPER / LIVE | 全局横幅常驻;本页数据标注"模拟盘账户"(Futu SIMULATE) |
| 断连 / 数据滞后 | 全页 STALE 遮罩 + 琥珀标签 + 时点文案(对齐 OMS),禁止无标注展示过期数 |
| VaR 口径 | 金额(实际净值口径)+ 百分比并列;旧固定量纲修复前打占位,不展示误导值 |
| 雷达维度 | 按代码事实六维;每维可看算法口径;HelpPanel 同步 |
| 持仓脏名 | 名称透传标注"以交易所为准";不做前端臆测纠错 |
| 压测口径 | 历史情景 = 预设 shock 系数,非历史回放;文案明示 |
| 空态 / 失败 | fetch 失败出错误卡(重试);空持仓 EmptyState;初始化 InitOverlay |
| 占比 | 合计行校验,多头/空头/现金分母统一为 nav |

---

### 五、实施要点(设计层)

1. 账户改顶部 tabs 切换,复用一次全量 `/risk/dashboard` 返回,前端本地切换。
2. VaR 卡改双口径(金额 + %),阈值分档改百分比;后端口径修正另立工单(`risk_engine.py:452`)。
3. 新增"因子归因"tab,接入孤儿端点 `/risk/attribution`(Jensen α/β/R²),兑现导航命名。
4. 断连 → 全页 STALE 遮罩,复用 OMS 页降级模式。
5. 雷达统一六维 + 口径说明;分级文案抽到单一 SSOT,删除 constants 冲突注释。
6. 持仓表补排序/下钻/合计校验/脏名标注。
7. 拆分 `risk-account-section.tsx`(368 行)为 KPI / 画像 / tabs / 持仓四个分子组件,满足行数上限(工程侧)。

---

### 六、验收清单

- [ ] 账户为顶部 tabs 切换,页面不再上下堆叠两套完整面板
- [ ] VaR 展示为实际净值口径金额 + 百分比;无固定 $10k 量纲误导
- [ ] 断连时全页 STALE 遮罩 + 琥珀标签 + 时点文案;恢复自动摘除
- [ ] "因子归因"tab 可见 Jensen α/β/R² 与收益贡献分解(端点已接线)
- [ ] 雷达按六维(Beta/Vol/Liq/Corr/Mom/DD)呈现,每维有口径说明,无 "Cave"
- [ ] 持仓表可排序、行点击下钻 /market/:ticker、有合计校验、脏名有标注
- [ ] 风险分级文案与 constants 一致;净值曲线标注快照数/采样周期/时点
- [ ] 压测文案明示历史情景为预设 shock 系数而非历史回放

---

### 附:现状事实索引(供实施定位)

- 路由 `App.tsx:110`(`/risk`)→ `RiskModule`;入口 `features/trading/risk.tsx`(86 行:fetch `/risk/dashboard` L26、写死账户 L59)
- 账户面板 `risk-account-section.tsx`(368 行:KPI L106-152、净值 L156-175、tabs L178-185、雷达+敞口 L187-249、因子 L251-297、持仓 L303-365、总分环 L33-62)
- 图表 `risk-charts.tsx`(274 行:NavArea/SectorBar/CorrelationHeatmap/CVarWaterfall/RiskRadar)
- 进阶面板 `risk-advanced-panel.tsx`(157 行:sector/corr/cvar/stress 懒加载)
- 类型/常量 `risk-types.ts`(MARKET_LABELS L46、RADAR_HELP L58、FACTOR_HELP L67)
- 后端 `backend/services/risk/risk_engine.py`(505 行:**VaR×10000 L452-457**、雷达六维 L376-426、敞口 L183-193、快照 L285-306)、`routers/risk.py`(230 行)、`risk_stress.py`(244 行,情景 shock L12-54)、`risk_attribution.py`(Jensen α)、`risk_cvar.py`
- 快照守护 `backend/bootstrap/lifecycle.py:154-172`(300s 采样、ltrim 287)
- 断连横幅 `components/layout/backend-status-banner.tsx`(75 行)+ `stores/useBackendStatusStore.ts`(3 次失败→offline);OMS STALE 参照 `oms.tsx:46-52`
- 孤儿端点(前端未消费):`/risk/attribution`、`/risk/liquidity`、`/risk/positions-breakdown`、`/risk/stress-test/scenarios`
