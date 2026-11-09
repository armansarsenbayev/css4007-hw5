"""Ticket rules enforced in Python, not left to the model."""

import pytest

from helpdesk.tools import prepare_ticket

APP = {"user_id": "demo-user-a", "thread_id": "t", "status_profile": "normal"}


@pytest.fixture()
def tickets(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path / "tickets"))
    return tmp_path / "tickets"


def written(folder):
    return list(folder.glob("*.json")) if folder.exists() else []


@pytest.mark.parametrize(
    "summary,steps,missing",
    [
        ("", ["Enabled Wi-Fi"], ["summary"]),
        ("   ", ["Enabled Wi-Fi"], ["summary"]),
        ("Wi-Fi fails", [], ["steps_tried"]),
        ("Wi-Fi fails", ["  "], ["steps_tried"]),
        ("", [], ["summary", "steps_tried"]),
    ],
)
def test_missing_details_need_info_and_no_file(tickets, summary, steps, missing):
    result = prepare_ticket("wifi", summary, steps, **APP)
    assert result["needs_info"] == missing
    assert written(tickets) == []


@pytest.mark.parametrize(
    "summary,steps",
    [
        ("Cannot sign in, password: Hunter22", ["Tried twice"]),
        ("My password is Hunter22", ["Tried twice"]),
        ("Recovery fails", ["Entered recovery code: 123456"]),
        ("Please use my api key to check", ["Nothing"]),
        ("Token sk-abc123def456 does not work", ["Nothing"]),
    ],
)
def test_secret_looking_text_is_refused(tickets, summary, steps):
    result = prepare_ticket("password", summary, steps, **APP)
    assert "error" in result and "ticket_id" not in result
    assert written(tickets) == []


def test_describing_a_password_problem_is_allowed(tickets):
    result = prepare_ticket("password", "My password is not accepted", ["Opened Forgot password"], **APP)
    assert "ticket_id" in result
    assert len(written(tickets)) == 1


def test_unknown_category_is_refused(tickets):
    result = prepare_ticket("printer", "Paper jam", ["Opened tray"], **APP)
    assert "error" in result
    assert written(tickets) == []
