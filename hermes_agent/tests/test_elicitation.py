"""AGENT-19 · Elicitation 提问缝 单元测试"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermes_agent.elicitation import (
    Boundary,
    ElicitationBuilder,
    ElicitationContext,
    QuestionType,
    Trigger,
    build_system_fragment,
)


def test_builder_produces_sse_payload():
    ctx = ElicitationContext(last_user_msg="搞个策略")
    b = ElicitationBuilder()
    trig, qt = b.auto_select(ctx)
    assert trig == Trigger.AMBIGUOUS_GOAL
    assert qt == QuestionType.CLARIFY
    e = b.build(
        ctx,
        trig,
        qt,
        "你的离场止损价是多少？",
        options=["-5%", "-10%", "不设"],
        fallback_assumption="默认按 -8% 止损继续。",
    )
    payload = e.to_sse()
    assert payload["type"] == "elicitation"
    assert payload["question_type"] == "clarify"
    assert payload["persona_echo"]  # 人设呼应已注入
    assert len(payload["options"]) == 3


def test_should_skip_user_distressed():
    ctx = ElicitationContext(user_emotion="distressed")
    skip, reason = ctx.should_skip()
    assert skip is True
    assert reason == Boundary.USER_DISTRESSED


def test_should_skip_wants_direct():
    ctx = ElicitationContext(wants_direct=True)
    skip, reason = ctx.should_skip()
    assert skip is True
    assert reason == Boundary.WANTS_DIRECT


def test_should_skip_live_low_uncertainty():
    ctx = ElicitationContext(trading_mode="LIVE", uncertainty=0.3)
    skip, reason = ctx.should_skip()
    assert skip is True
    assert reason == Boundary.HIGH_STAKES_LIVE


def test_should_skip_already_asked():
    ctx = ElicitationContext(asked_this_turn=True)
    skip, reason = ctx.should_skip()
    assert skip is True
    assert reason == Boundary.ALREADY_ASKED


def test_no_skip_normal_context():
    ctx = ElicitationContext(uncertainty=0.8, user_emotion="neutral")
    skip, reason = ctx.should_skip()
    assert skip is False
    assert reason is None


def test_auto_select_challenge_on_fragile_assumption():
    ctx = ElicitationContext(last_user_msg="这次肯定不一样，闭眼冲")
    b = ElicitationBuilder()
    trig, qt = b.auto_select(ctx)
    assert qt == QuestionType.CHALLENGE
    assert trig == Trigger.ASSUMPTION_CHALLENGE


def test_system_fragment_includes_keywords():
    frag = build_system_fragment()
    for kw in ("elicitation", "fail-closed", "挑战型", "澄清型"):
        assert kw in frag
