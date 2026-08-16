/**
 * RESEARCH-TEAM-01: 专家名册（前端静态镜像 backend/expert_team/expert_registry.py）
 * 用于「AI投研团队」模式的阵容展示与图标映射。后端为单一数据源，
 * 本文件仅做 UI 展示用途，新增角色须同步后端 registry。
 */

export type ExpertBias = 'bullish' | 'bearish' | 'neutral'

export interface ExpertProfile {
  id: string
  name: string
  team: string
  bias: ExpertBias
  description: string
  /** 单字/emoji 头像 */
  glyph: string
  /** 主题色（Tailwind 文本/边框） */
  accent: string
}

export interface TeamGroup {
  key: string
  name: string
  members: ExpertProfile[]
}

const _E: ExpertProfile[] = [
  // 📊 分析师团队
  { id: 'fundamental_analyst', name: '基本面分析师', team: 'analyst', bias: 'neutral', glyph: '基', accent: 'text-sky-400 border-sky-400/40', description: '三表质量、ROE 趋势、现金流健康度、盈利可持续性' },
  { id: 'technical_analyst', name: '技术面分析师', team: 'analyst', bias: 'neutral', glyph: '技', accent: 'text-indigo-400 border-indigo-400/40', description: '价格趋势、支撑压力位、量价关系、技术形态识别' },
  { id: 'macro_strategist', name: '宏观策略师', team: 'analyst', bias: 'neutral', glyph: '宏', accent: 'text-violet-400 border-violet-400/40', description: '政策影响、利率周期、行业景气度、全球资金流向' },
  { id: 'valuation_expert', name: '估值专家', team: 'analyst', bias: 'neutral', glyph: '估', accent: 'text-blue-400 border-blue-400/40', description: 'DCF 估值、PE/PB 历史分位、同业对比、安全边际' },
  { id: 'industry_analyst', name: '行业分析师', team: 'analyst', bias: 'neutral', glyph: '行', accent: 'text-cyan-400 border-cyan-400/40', description: '行业格局、竞争态势、市场空间、产业链地位' },
  { id: 'sentiment_analyst', name: '情绪分析师', team: 'analyst', bias: 'neutral', glyph: '情', accent: 'text-fuchsia-400 border-fuchsia-400/40', description: '市场情绪指标、资金流向、持仓结构、散户/机构行为' },
  { id: 'news_analyst', name: '新闻分析师', team: 'analyst', bias: 'neutral', glyph: '闻', accent: 'text-teal-400 border-teal-400/40', description: '新闻质量评估、信号噪音分离、叙事转变识别' },
  // 🔬 研究员团队
  { id: 'industry_researcher', name: '产业研究员', team: 'researcher', bias: 'neutral', glyph: '产', accent: 'text-emerald-400 border-emerald-400/40', description: '产业链上下游、竞争壁垒(护城河)、技术路线、行业拐点' },
  { id: 'quant_researcher', name: '量化研究员', team: 'researcher', bias: 'neutral', glyph: '量', accent: 'text-lime-400 border-lime-400/40', description: '因子有效性、统计套利、回测验证、信号衰减' },
  // 💱 交易员
  { id: 'trade_executor', name: '交易执行专家', team: 'trader', bias: 'neutral', glyph: '易', accent: 'text-amber-400 border-amber-400/40', description: '择时策略、仓位管理、TWAP/VWAP、滑点控制、止损纪律' },
  // 🛡️ 风险管理（天然偏空，负责发现风险）
  { id: 'risk_officer', name: '风控官', team: 'risk', bias: 'bearish', glyph: '控', accent: 'text-red-400 border-red-400/40', description: '尾部风险、黑天鹅预警、仓位管理、流动性危机' },
  { id: 'portfolio_risk_manager', name: '组合风控经理', team: 'risk', bias: 'bearish', glyph: '组', accent: 'text-rose-400 border-rose-400/40', description: 'VaR/CVaR、相关性矩阵、压力测试、对冲、回撤控制' },
  // 👔 管理层（首席，负责最终收敛）
  { id: 'chief_investment_officer', name: '首席投资官', team: 'management', bias: 'neutral', glyph: '首', accent: 'text-yellow-300 border-yellow-300/50', description: '大类资产配置、战略方向、投委会决策框架、长期复利' },
  // 💻 代码域
  { id: 'code_architect', name: '架构师', team: 'code', bias: 'neutral', glyph: '构', accent: 'text-purple-400 border-purple-400/40', description: '分层合理性、依赖方向、扩展性、设计模式' },
  { id: 'security_expert', name: '安全专家', team: 'code', bias: 'neutral', glyph: '安', accent: 'text-orange-400 border-orange-400/40', description: '注入/XSS/权限漏洞、敏感数据泄露、依赖安全' },
  { id: 'performance_expert', name: '性能专家', team: 'code', bias: 'neutral', glyph: '能', accent: 'text-pink-400 border-pink-400/40', description: '热路径优化、内存泄漏、GC 压力、并发瓶颈' },
  { id: 'maintainability_expert', name: '可维护性专家', team: 'code', bias: 'neutral', glyph: '维', accent: 'text-slate-300 border-slate-300/40', description: '命名规范、圈复杂度、测试覆盖、文档完整性' },
]

export const EXPERT_PROFILES: Record<string, ExpertProfile> = Object.fromEntries(
  _E.map((e) => [e.id, e]),
)

export const TEAM_GROUPS: TeamGroup[] = [
  { key: 'analyst', name: '📊 分析师团队', members: _E.filter((e) => e.team === 'analyst') },
  { key: 'researcher', name: '🔬 研究员团队', members: _E.filter((e) => e.team === 'researcher') },
  { key: 'trader', name: '💱 交易员', members: _E.filter((e) => e.team === 'trader') },
  { key: 'risk', name: '🛡️ 风险管理', members: _E.filter((e) => e.team === 'risk') },
  { key: 'management', name: '👔 管理层 · 首席', members: _E.filter((e) => e.team === 'management') },
  { key: 'code', name: '💻 代码域', members: _E.filter((e) => e.team === 'code') },
]

export const SCENARIOS: { id: string; name: string; domain: string; desc: string }[] = [
  { id: 'financial_research', name: '金融投研', domain: 'finance', desc: '多专家金融视角研判（默认 12 人团）' },
  { id: 'full_investment', name: '完整投决会', domain: 'finance', desc: '含风控与首席的全流程投资决策' },
  { id: 'trade_decision', name: '交易决策', domain: 'finance', desc: '聚焦择时、仓位与执行' },
  { id: 'code_review', name: '代码审查', domain: 'code', desc: '架构/安全/性能/可维护性多视角' },
]

export function expertById(id: string): ExpertProfile | undefined {
  return EXPERT_PROFILES[id]
}

export function biasBadge(bias: ExpertBias): { label: string; cls: string } {
  switch (bias) {
    case 'bullish':
      return { label: '偏多', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-400/30' }
    case 'bearish':
      return { label: '偏空', cls: 'text-red-400 bg-red-500/10 border-red-400/30' }
    default:
      return { label: '中性', cls: 'text-slate-400 bg-slate-500/10 border-slate-400/30' }
  }
}
