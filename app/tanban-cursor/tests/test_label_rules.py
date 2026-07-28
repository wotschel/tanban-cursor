from services.label_rules import (
    blocked_reason_for_mode,
    build_prompt,
    card_content_hash,
    evaluate_labels,
    normalize_label_names,
    resolve_mode,
)


def test_normalize_label_names_casefold():
    assert normalize_label_names(["C-Ask", " C-PLAN ", ""]) == {"c-ask", "c-plan"}


def test_resolve_mode_prefers_work_then_plan_then_ask():
    assert resolve_mode({"c-ask", "c-plan", "c-work"}) == "c-work"
    assert resolve_mode({"c-ask", "c-plan"}) == "c-plan"
    assert resolve_mode({"c-ask"}) == "c-ask"
    assert resolve_mode({"plan", "work", "ask"}) is None


def test_blocked_reason_for_mode():
    assert blocked_reason_for_mode("c-ask") == "cursor ask"
    assert blocked_reason_for_mode("c-plan") == "cursor plan"
    assert blocked_reason_for_mode("c-work") == "cursor work"


def test_evaluate_dispatches_when_c_plan_added():
    decision = evaluate_labels(
        current_labels={"c-plan"},
        added_labels={"c-plan"},
    )
    assert decision.should_dispatch is True
    assert decision.mode == "c-plan"


def test_evaluate_dispatches_when_c_ask_added():
    decision = evaluate_labels(
        current_labels={"c-ask"},
        added_labels={"c-ask"},
    )
    assert decision.should_dispatch is True
    assert decision.mode == "c-ask"


def test_evaluate_dispatches_when_c_plan_added_to_existing_labels():
    decision = evaluate_labels(
        current_labels={"c-plan", "urgent"},
        added_labels={"c-plan"},
    )
    assert decision.should_dispatch is True
    assert decision.mode == "c-plan"


def test_evaluate_skips_plain_plan_without_c_prefix():
    decision = evaluate_labels(current_labels={"plan"}, added_labels={"plan"})
    assert decision.should_dispatch is False


def test_evaluate_skips_unrelated_label_add_when_mode_already_present():
    decision = evaluate_labels(
        current_labels={"c-work", "urgent"},
        added_labels={"urgent"},
    )
    assert decision.should_dispatch is False
    assert decision.mode == "c-work"


def test_build_prompt_contains_mode_and_title():
    plan = build_prompt(mode="c-plan", title="Ship it", description="Do X", card_public_id="abc")
    assert "implementation plan" in plan.casefold()
    assert "Ship it" in plan
    work = build_prompt(mode="c-work", title="Ship it", description=None, card_public_id="abc")
    assert "Implement" in work
    ask = build_prompt(mode="c-ask", title="Why?", description="Explain X", card_public_id="abc")
    assert "answer" in ask.casefold()
    assert "do not implement" in ask.casefold()
    assert "comment" in ask.casefold()
    assert "Why?" in ask


def test_card_content_hash_stable_and_trims():
    a = card_content_hash(mode="c-plan", title="  Ship it  ", description="Do X")
    b = card_content_hash(mode="c-plan", title="Ship it", description="Do X")
    assert a == b
    assert len(a) == 64


def test_card_content_hash_none_description_equals_empty():
    a = card_content_hash(mode="c-plan", title="Ship it", description=None)
    b = card_content_hash(mode="c-plan", title="Ship it", description="")
    assert a == b


def test_card_content_hash_changes_with_mode_or_content():
    base = card_content_hash(mode="c-plan", title="Ship it", description="Do X")
    assert card_content_hash(mode="c-ask", title="Ship it", description="Do X") != base
    assert card_content_hash(mode="c-plan", title="Ship it", description="Do Y") != base
    assert card_content_hash(mode="c-plan", title="Other", description="Do X") != base
