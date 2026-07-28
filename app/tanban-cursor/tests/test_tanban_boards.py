import pytest

from services.tanban_boards import (
    LegacyBoardBinding,
    TanbanBoardConfig,
    TanbanBoardsConfigError,
    board_public_id_from_body,
    board_public_id_from_payload,
    boards_from_legacy,
    parse_boards_json,
    resolve_board,
)


def test_parse_boards_json_multi():
    boards = parse_boards_json(
        """
        {
          "AAA-bbb": {"board_id": 3, "api_key": "tbk_a", "webhook_secret": "tbwh_a"},
          "ccc-DDD": {"board_id": 4, "api_key": "tbk_b", "webhook_secret": "tbwh_b"}
        }
        """
    )
    assert set(boards) == {"aaa-bbb", "ccc-ddd"}
    assert boards["aaa-bbb"].board_id == 3
    assert boards["ccc-ddd"].api_key == "tbk_b"


def test_parse_boards_json_rejects_invalid():
    with pytest.raises(TanbanBoardsConfigError):
        parse_boards_json("[]")
    with pytest.raises(TanbanBoardsConfigError):
        parse_boards_json('{"x": {"board_id": "nope"}}')


def test_boards_from_legacy_requires_public_id():
    assert boards_from_legacy(board_id=4, api_key="k", webhook_secret="s", board_public_id=None) == {}
    boards = boards_from_legacy(
        board_id=4,
        api_key="tbk_x",
        webhook_secret="tbwh_x",
        board_public_id="Pub-Id",
    )
    assert boards["pub-id"].board_id == 4


def test_board_public_id_from_payload_and_body():
    assert board_public_id_from_payload({"board": {"public_id": "AbC"}}) == "abc"
    assert board_public_id_from_payload({}) is None
    body = b'{"board":{"public_id":"7da2efd2-8ff6-4c7f-81c7-e23e9105e139"}}'
    assert board_public_id_from_body(body) == "7da2efd2-8ff6-4c7f-81c7-e23e9105e139"
    assert board_public_id_from_body(b"not-json") is None


def test_resolve_board_prefers_map():
    board = TanbanBoardConfig("abc", 4, "tbk", "tbwh")
    boards = {"abc": board}
    legacy = LegacyBoardBinding(board_id=1, api_key="other", webhook_secret="other")
    assert resolve_board(boards, legacy, "ABC") is board
    assert resolve_board(boards, legacy, "missing") is None


def test_resolve_board_legacy_when_map_empty():
    legacy = LegacyBoardBinding(board_id=4, api_key="tbk", webhook_secret="tbwh")
    assert resolve_board({}, legacy, "any-board") is legacy
    assert resolve_board({}, None, "any-board") is None
