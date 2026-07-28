from services.label_rules import build_prompt, evaluate_labels, normalize_label_names, resolve_mode


def test_normalize_label_names_casefold():
    assert normalize_label_names(["Cursor", " PLAN ", ""]) == {"cursor", "plan"}


def test_resolve_mode_prefers_work():
    assert resolve_mode({"cursor", "plan", "work"}) == "work"
    assert resolve_mode({"cursor", "plan"}) == "plan"
    assert resolve_mode({"cursor"}) is None


def test_evaluate_dispatches_when_cursor_and_plan_added():
    decision = evaluate_labels(
        current_labels={"cursor", "plan"},
        added_labels={"cursor", "plan"},
    )
    assert decision.should_dispatch is True
    assert decision.mode == "plan"


def test_evaluate_dispatches_when_plan_added_to_existing_cursor():
    decision = evaluate_labels(
        current_labels={"cursor", "plan", "urgent"},
        added_labels={"plan"},
    )
    assert decision.should_dispatch is True
    assert decision.mode == "plan"


def test_evaluate_skips_without_cursor():
    decision = evaluate_labels(current_labels={"plan"}, added_labels={"plan"})
    assert decision.should_dispatch is False


def test_evaluate_skips_unrelated_label_add_when_combo_already_present():
    decision = evaluate_labels(
        current_labels={"cursor", "work", "urgent"},
        added_labels={"urgent"},
    )
    assert decision.should_dispatch is False
    assert decision.mode == "work"


def test_build_prompt_contains_mode_and_title():
    plan = build_prompt(mode="plan", title="Ship it", description="Do X", card_public_id="abc")
    assert "implementation plan" in plan.casefold()
    assert "Ship it" in plan
    work = build_prompt(mode="work", title="Ship it", description=None, card_public_id="abc")
    assert "Implement" in work
