"""
脚本：生成工具→scopes 映射 JSON（人工审核版）

用法：
  python scripts/scaffold_tool_scopes.py  # 输出 mapping 到终端 + tool_scope_mapping.json

注意事项：
- 本脚本仅基于工具文件名启发式猜测初始 scope（非常粗略）
- 最终仍需人工逐个审核 hermes_agent/tools/*.py 文件并补充完整标注
"""

import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent.resolve()
TOOLS_DIR = SCRIPTS_DIR / "hermes_agent" / "tools"


def main():
    files = []
    for p in TOOLS_DIR.iterdir():
        if p.is_file() and p.suffix == ".py" and p.stem not in ("__init__", "base", "secure_client"):
            files.append(p.stem)

    files.sort()
    print(f"发现 {len(files)} 个工具模块:\n")

    # 1. 启发式猜测（按关键词匹配）
    keyword_rules = {
        "quote": ["broker_market_tool"],  # 盘口价
        "indicators": ["technical_indicators_tool"],  # 技术指标
        "fund_flow": ["broker_fund_flow_tool"],  # 资金流
        "fundamental": [
            "company_profile_tool",
            "fundamental_data_tool",
            "analyst_consensus_tool",
        ],  # 基本面/公司资料/分析师共识
        "macro": ["fred_macro_tool", "cboe_pc_ratio_tool", "economic_calendar_tool"],  # 宏观/Fred/Eco calendar
        "news": ["macro_news_tool", "company_news_tool"],  # 新闻
        "trade": ["broker_trade_tool"],  # 交易 OMS
        "search": ["web_search_tool", "web_scrape_tool"],  # 搜索/抓取
    }

    mapping: dict = {}

    # 为每个工具分配默认全量（保守策略）
    for fname in files:
        matching_scopes = []
        for scope, patterns in keyword_rules.items():
            if any(p in fname for p in patterns):
                matching_scopes.append(scope)

        if matching_scopes:
            mapping[fname] = matching_scopes
        else:
            # 未匹配 → 默认全量（由 register_tool 装饰器隐式处理）
            pass

    # 2. 输出结果
    print("=== 工具→scopes 映射建议（基于关键词启发式） ===\n")
    for fname, scopes in sorted(mapping.items()):
        print(f"{fname}: {scopes}")

    # 3. 写入 JSON 供参考
    output_file = TOOLS_DIR / "tool_scope_mapping.json"
    output_file.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ 已生成映射文件：{output_file}")
    print("\n下一步:")
    print("1. 人工审核每个 hermes_agent/tools/*.py，确认/修正 scope 列表")
    print("2. 为 @register_tool 注入 scopes=[...] 参数（至少覆盖核心场景）")
    print("3. 更新 agent.py/_react_loop 使用 get_schemas_by_scopes(scopes=[...]) 替代 get_all_schemas()")


if __name__ == "__main__":
    main()
