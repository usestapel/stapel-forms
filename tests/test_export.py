"""CSV export — the place hostile content meets a spreadsheet."""
import pytest

from stapel_forms.export import escape_cell

pytestmark = pytest.mark.django_db

BASE = "/forms/api/v1"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=cmd|'/c calc'!A0", "'=cmd|'/c calc'!A0"),
        ("+1234", "'+1234"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tsneaky", "'\tsneaky"),
        ("\rsneaky", "'\rsneaky"),
        ("plain", "plain"),
        ("", ""),
        (None, ""),
        (True, "true"),
        (["a", "=b"], "a, '=b"),
    ],
)
def test_formula_leads_are_escaped(raw, expected):
    assert escape_cell(raw) == expected


def test_export_streams_the_version_s_columns(api_client, user, workspace_id,
                                              grant_capabilities, published_form):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro", "age": 33})
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.responses.view")

    resp = api_client.get(
        f"{BASE}/forms/{published_form.id}/submissions/export?workspace_id={workspace_id}"
    )
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]

    body = b"".join(resp.streaming_content).decode()
    header, row = body.strip().splitlines()
    # The header field is a section caption, not a question — no column.
    assert header == "submission_id,submitted_at,submitted_by,version,Full name,Age,Plan"
    assert row.endswith("1,Ann,33,pro")


def test_export_escapes_hostile_answers(api_client, user, workspace_id,
                                        grant_capabilities, published_form):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "=1+1", "plan": "pro"})
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.responses.view")

    resp = api_client.get(
        f"{BASE}/forms/{published_form.id}/submissions/export?workspace_id={workspace_id}"
    )
    body = b"".join(resp.streaming_content).decode()
    assert "'=1+1" in body


def test_export_pages_and_hands_back_a_cursor(api_client, user, workspace_id,
                                              grant_capabilities, published_form, settings):
    from stapel_forms import services

    settings.STAPEL_FORMS = {"EXPORT_PAGE_SIZE": 2}
    for i in range(3):
        services.submit(published_form, answers={"full_name": f"P{i}", "plan": "pro"})
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.responses.view")

    url = f"{BASE}/forms/{published_form.id}/submissions/export?workspace_id={workspace_id}"
    first = api_client.get(url)
    cursor = first["X-Forms-Next-Before"]
    assert len(b"".join(first.streaming_content).decode().strip().splitlines()) == 3

    second = api_client.get(f"{url}&before={cursor}")
    assert len(b"".join(second.streaming_content).decode().strip().splitlines()) == 2
    assert "X-Forms-Next-Before" not in second


def test_export_needs_the_responses_capability(api_client, user, workspace_id,
                                               grant_capabilities, published_form):
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.view")
    resp = api_client.get(
        f"{BASE}/forms/{published_form.id}/submissions/export?workspace_id={workspace_id}"
    )
    assert resp.status_code == 403


def test_export_of_an_older_version_uses_that_version_s_columns(
    api_client, user, workspace_id, grant_capabilities, published_form, simple_schema
):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    trimmed = {
        "fields": [f for f in simple_schema["fields"] if f["slug"] != "age"],
        "meta": simple_schema["meta"],
    }
    services.save_draft(published_form, trimmed)
    services.publish(published_form, user=user)

    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.responses.view")
    url = f"{BASE}/forms/{published_form.id}/submissions/export?workspace_id={workspace_id}"

    v1 = b"".join(api_client.get(f"{url}&version=1").streaming_content).decode()
    assert "Age" in v1.splitlines()[0]
    v2 = b"".join(api_client.get(f"{url}&version=2").streaming_content).decode()
    assert "Age" not in v2.splitlines()[0]
