"""Each tool called directly, without the agent."""

import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from helpdesk.data import load_helpdesk, load_service_status, load_ticket_template
from helpdesk.tools import (
    HELPDESK_TOOLS,
    check_service_status,
    find_instructions,
    prepare_ticket,
)


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path / "tickets"))
    return tmp_path


@pytest.mark.parametrize("topic,guide_id", [("wifi", "GUIDE-WIFI"), ("password", "GUIDE-PASSWORD")])
def test_find_instructions(topic, guide_id):
    result = find_instructions(topic)
    assert result["instruction_id"] == guide_id
    assert result["steps"] == load_helpdesk()["instructions"][topic]["steps"]
    assert result["source"] == "data/helpdesk.json"


def test_find_instructions_unknown_topic():
    result = find_instructions("printer")
    assert "error" in result and result["allowed"] == ["wifi", "password"]


PROFILES = load_service_status()["profiles"]
CASES = [(p, s) for p, services in PROFILES.items() for s in services]


@pytest.mark.parametrize("profile,service", CASES)
def test_every_service_in_every_snapshot(profile, service):
    result = check_service_status(service, profile)
    assert result["status"] == PROFILES[profile][service]["status"]
    assert result["status_profile"] == profile


def test_unknown_stays_unknown():
    for service in ("wifi", "account_recovery"):
        assert check_service_status(service, "status_unavailable")["status"] == "unknown"


def test_password_uses_account_recovery():
    assert load_helpdesk()["topic_services"]["password"] == "account_recovery"
    assert check_service_status("account_recovery", "recovery_outage")["status"] == "outage"
    assert check_service_status("wifi", "recovery_outage")["status"] == "operational"


@pytest.mark.parametrize("service,profile", [("printer", "normal"), ("wifi", "no_such_profile")])
def test_unknown_service_or_profile_is_error_dict(service, profile):
    result = check_service_status(service, profile)
    assert "error" in result and "allowed" in result


def test_ticket_has_template_fields_and_only_given_steps(temp_dirs):
    steps = ["Enabled Wi-Fi", "Forgot the saved network"]
    result = prepare_ticket(
        "wifi", "Campus-Demo will not connect", steps, "operational",
        user_id="demo-user-a", thread_id="t1", status_profile="normal",
    )
    path = temp_dirs / "tickets" / f"{result['ticket_id']}.json"
    ticket = json.loads(path.read_text(encoding="utf-8"))
    assert set(ticket) == set(load_ticket_template()["ticket"])
    assert ticket["steps_tried"] == steps
    assert ticket["status"] == "draft"
    assert ticket["service_status"] == "operational"
    assert ticket["reference_ids"] == ["GUIDE-WIFI"]
    assert (ticket["user_id"], ticket["thread_id"], ticket["status_profile"]) == ("demo-user-a", "t1", "normal")
    assert result["ticket_id"].startswith("TKT-")


def test_ticket_status_not_checked_and_password_reference(temp_dirs):
    result = prepare_ticket(
        "password", "Recovery page shows an error", ["Opened Forgot password"],
        user_id="demo-user-a", thread_id="t2", status_profile="normal",
    )
    ticket = json.loads((temp_dirs / "tickets" / f"{result['ticket_id']}.json").read_text(encoding="utf-8"))
    assert ticket["service_status"] == "not checked"
    assert ticket["reference_ids"] == ["GUIDE-PASSWORD"]


def test_model_schemas_hide_application_values():
    hidden = {"status_profile", "user_id", "thread_id", "store"}
    for t in HELPDESK_TOOLS:
        params = convert_to_openai_tool(t)["function"]["parameters"]["properties"]
        assert hidden.isdisjoint(params), t.name
