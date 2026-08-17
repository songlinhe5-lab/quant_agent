"""Hermes 运行时 prompt 与 IDE 编码宪法分离（2026-08-17）。"""

import os

from hermes_agent.agent import DEFAULT_SYSTEM_PROMPT_PATH, HermesAgent


def test_default_prompt_is_hermes_not_agents():
    assert DEFAULT_SYSTEM_PROMPT_PATH.endswith("prompts/system/HERMES.md")
    assert os.path.isfile(DEFAULT_SYSTEM_PROMPT_PATH)
    text = open(DEFAULT_SYSTEM_PROMPT_PATH, encoding="utf-8").read()
    assert "量化交易主脑" in text
    assert "```chart-annotations" in text
    assert "附录 A：Vibe Coding" not in text
    assert "禁止 Next.js" not in text


def test_load_system_prompt_reads_file(tmp_path):
    p = tmp_path / "p.md"
    p.write_text("RUNTIME_ONLY", encoding="utf-8")
    agent = HermesAgent.__new__(HermesAgent)
    agent.system_prompt_path = str(p)
    assert agent._load_system_prompt() == "RUNTIME_ONLY"
