export type SortKey = string

// 💡 富途底层字段与中文展示的映射字典
export const FIELD_ZH_MAP: Record<string, string> = {
  "price": "最新价",
  "price_to_52w_high": "距52周最高%",
  "price_to_52w_low": "距52周最低%",
  "high_to_52w_high": "最高距52周最高%",
  "low_to_52w_low": "最低距52周最低%",
  "volume_ratio": "量比",
  "bid_ask_ratio": "委比",
  "lot_price": "每手价格",
  "market_cap": "市值",
  "pe_annual": "市盈率",
  "pe_ttm": "市盈率 TTM",
  "pb": "市净率",
  "dividend_ratio": "股息率",
  "dividend_ratio_ttm": "股息率 TTM",
  "listed_days": "上市天数",
  "change_5min": "5分钟涨跌幅",
  "change_ytd": "年初至今涨跌幅",
  "ps_ttm": "市销率",
  "pcf_ttm": "市现率",
  "total_share": "总股数",
  "float_share": "流通股数",
  "float_market_cap": "流通市值",
  "price_change_pct": "涨跌幅",
  "amplitude": "振幅",
  "avg_volume": "平均成交量",
  "avg_turnover": "平均成交额",
  "turnover_ratio": "换手率",
  "net_profit": "净利润",
  "net_profit_growth": "净利润增长率",
  "revenue": "营业收入",
  "revenue_growth": "营业额增长率",
  "net_profit_ratio": "净利率",
  "gross_profit_ratio": "毛利率",
  "debt_to_assets": "资产负债率",
  "roe": "净资产收益率",
  "roic": "投入资本回报率",
  "roa_ttm": "资产回报率 TTM",
  "ebit_ttm": "息税前利润 TTM",
  "ebitda": "税息折旧及摊销前利润",
  "operating_margin_ttm": "营业利润率 TTM",
  "ebit_margin": "EBIT 利润率",
  "ebitda_margin": "EBITDA 利润率",
  "financial_cost_rate": "财务成本率",
  "operating_profit_ttm": "营业利润 TTM",
  "shareholders_profit_ttm": "归母净利润",
  "net_profit_cash_cover_ttm": "盈利现金收入比",
  "current_ratio": "流动比率",
  "quick_ratio": "速动比率",
  "current_asset_ratio": "流动资产率",
  "current_debt_ratio": "流动负债率",
  "equity_multiplier": "权益乘数",
  "property_ratio": "产权比率",
  "cash_equivalents": "现金等价物",
  "total_asset_turnover": "总资产周转率",
  "fixed_asset_turnover": "固定资产周转率",
  "inventory_turnover": "存货周转率",
  "operating_cash_flow_ttm": "经营活动现金流 TTM",
  "accounts_receivable": "应收账款净额",
  "ebit_growth_rate": "EBIT 同比增长率",
  "operating_profit_growth": "营业利润同比增长率",
  "total_assets_growth": "总资产同比增长率",
  "shareholder_profit_growth": "归母净利润同比增长率",
  "profit_before_tax_growth": "总利润同比增长率",
  "eps_growth_rate": "EPS 同比增长率",
  "roe_growth_rate": "ROE 同比增长率",
  "roic_growth_rate": "ROIC 同比增长率",
  "nocf_growth_rate": "经营现金流同比增长率",
  "nocf_per_share_growth": "每股经营现金流同比增长率",
  "operating_revenue_cash_cover": "经营现金收入比",
  "operating_profit_total_ratio": "营业利润占比",
  "basic_eps": "基本每股收益",
  "diluted_eps": "稀释每股收益",
  "nocf_per_share": "每股经营现金净流量",
  "ma": "简单均线",
  "rsi": "RSI",
  "ema": "指数移动均线",
  "macd_diff": "MACD DIFF",
  "macd_dea": "MACD DEA",
  "macd": "MACD",
  "kdj_k": "KDJ (K)",
  "kdj_d": "KDJ (D)",
  "matched_patterns": "命中形态",
  "chg": "涨跌幅",
  "mktcap": "市值",
  "hist_percentile_pe": "PE历史分位",
  "hist_percentile_pb": "PB历史分位",
  "hist_percentile_ps": "PS历史分位",
  "stock_plate": "行业板块",
  "macd_golden_cross": "MACD金叉形态",
  "rsi_oversold": "RSI超卖形态",
  "rsi_overbought": "RSI超买形态",
  "industry": "所属行业",
  "turnover_ratio_fmt": "换手率",
  "volume_multiple": "成交量倍数",
  "rsi_bottom_diverge": "RSI底背离形态",
  "net_profit_growth_fmt": "EPS同比增长率",
};

// 智能标签转换器：处理带有 "(1)" 这种括号动态参数的 Key
export function getZhLabel(key: string) {
  const match = key.match(/^([^(]+)(\(.*\))?$/);
  if (match) {
    const base = match[1].trim();
    const suffix = match[2] || '';
    if (FIELD_ZH_MAP[base]) return FIELD_ZH_MAP[base] + suffix;
  }
  return FIELD_ZH_MAP[key] || key;
}

// 💡 股票代码展示格式化器 (去掉首缀，更符合人类与主流软件习惯)
export function formatDisplaySymbol(sym: string) {
  if (!sym) return sym;
  if (sym.startsWith('US.')) return sym.replace('US.', '');
  if (sym.startsWith('HK.')) return `${sym.replace('HK.', '')}.HK`;
  if (sym.startsWith('SH.')) return `${sym.replace('SH.', '')}.SH`;
  if (sym.startsWith('SZ.')) return `${sym.replace('SZ.', '')}.SZ`;
  return sym;
}