"""The two anonymous routes and the abuse ladder standing behind them."""
import json

import pytest

from stapel_forms.models import Submission

pytestmark = pytest.mark.django_db


def _schema_url(form):
    return f"/forms/api/v1/public/{form.public_id}/"


def _submit_url(form):
    return f"/forms/api/v1/public/{form.public_id}/submissions/"


def test_schema_fetch_needs_no_session(api_client, published_form):
    resp = api_client.get(_schema_url(published_form))
    assert resp.status_code == 200
    body = resp.json()
    assert body["public_id"] == published_form.public_id
    assert body["version"] == 1
    assert [f["slug"] for f in body["fields"]] == ["sec", "full_name", "age", "plan"]
    assert body["meta"]["submit_label"] == "Send"


def test_public_envelope_leaks_nothing(api_client, published_form):
    body = api_client.get(_schema_url(published_form)).json()
    leaked = {"workspace_id", "id", "created_by", "settings", "submission_count", "draft_schema"}
    assert leaked.isdisjoint(body)
    assert str(published_form.workspace_id) not in json.dumps(body)
    assert str(published_form.id) not in json.dumps(body)


def test_unknown_handle_is_the_same_404_as_a_draft(api_client, published_form):
    from stapel_forms import services

    unknown = api_client.get("/forms/api/v1/public/aaaaaaaaaaaaaaaaaaaaaa/")
    services.set_state(published_form, "draft")
    draft = api_client.get(_schema_url(published_form))
    assert unknown.status_code == draft.status_code == 404
    assert unknown.json()["localizable_error"] == draft.json()["localizable_error"]


def test_closed_form_is_410_not_404(api_client, published_form):
    from stapel_forms import services

    services.set_state(published_form, "closed")
    resp = api_client.get(_schema_url(published_form))
    assert resp.status_code == 410
    assert resp.json()["localizable_error"] == "error.410.forms_closed"


def test_submit_accepts_a_valid_anonymous_answer(api_client, published_form):
    resp = api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "Ann", "plan": "pro", "age": 33},
         "version_id": str(published_form.active_version_id)},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json() == {"accepted": True, "confirmation": "Thanks — we will be in touch."}
    row = Submission.objects.get()
    assert row.submitted_by is None
    assert row.answers["full_name"]["value"] == "Ann"
    # The closed switch: no respondent IP on disk by default.
    assert row.client_meta is None


def test_submit_returns_no_submission_id(api_client, published_form):
    resp = api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "Ann", "plan": "pro"}},
        format="json",
    )
    assert "id" not in resp.json() and "submission_id" not in resp.json()


def test_missing_mandatory_field_is_a_per_field_400(api_client, published_form):
    resp = api_client.post(
        _submit_url(published_form), {"answers": {"plan": "pro"}}, format="json"
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["localizable_error"] == "error.400.feature_mandatory_missing"
    assert body["params"]["field"] == "full_name"
    assert {f["field"] for f in body["params"]["fields"]} == {"full_name"}


def test_unknown_slug_cannot_be_smuggled_into_storage(api_client, published_form):
    resp = api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "Ann", "plan": "pro", "evil": "payload"}},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["localizable_error"] == "error.400.forms_unknown_field"
    assert not Submission.objects.exists()


def test_non_object_answers_refuse(api_client, published_form):
    resp = api_client.post(
        _submit_url(published_form), {"answers": ["nope"]}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["localizable_error"] == "error.400.forms_answers_not_object"


def test_a_racing_publish_rejects_the_stale_fill_wholesale(api_client, published_form, user, simple_schema):
    from stapel_forms import services

    stale = str(published_form.active_version_id)
    services.save_draft(published_form, simple_schema)
    services.publish(published_form, user=user)

    resp = api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "Ann", "plan": "pro"}, "version_id": stale},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["localizable_error"] == "error.409.forms_version_superseded"
    assert not Submission.objects.exists()


def test_grace_window_is_shipped_closed(published_form, user, simple_schema):
    from stapel_forms.conf import forms_settings

    assert forms_settings.ACCEPT_PREVIOUS_VERSION_SECONDS == 0


def test_grace_window_when_a_host_opens_it(published_form, user, simple_schema, settings):
    from stapel_forms import services

    settings.STAPEL_FORMS = {"ACCEPT_PREVIOUS_VERSION_SECONDS": 600}
    stale = published_form.active_version_id
    services.save_draft(published_form, simple_schema)
    services.publish(published_form, user=user)
    published_form.refresh_from_db()

    services.submit(
        published_form, answers={"full_name": "Ann", "plan": "pro"}, version_id=stale
    )
    assert Submission.objects.count() == 1


def test_submission_cap_refuses_beyond_the_limit(api_client, published_form, settings):
    settings.STAPEL_FORMS = {"MAX_SUBMISSIONS_PER_FORM": 1}
    ok = api_client.post(
        _submit_url(published_form), {"answers": {"full_name": "A", "plan": "pro"}}, format="json"
    )
    over = api_client.post(
        _submit_url(published_form), {"answers": {"full_name": "B", "plan": "pro"}}, format="json"
    )
    assert ok.status_code == 201 and over.status_code == 409
    assert over.json()["localizable_error"] == "error.409.forms_submission_cap"


def test_oversized_body_is_refused_before_parsing(api_client, published_form, settings):
    settings.STAPEL_FORMS = {"MAX_SUBMISSION_BYTES": 32}
    resp = api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "A" * 200, "plan": "pro"}},
        format="json",
    )
    assert resp.status_code == 413
    assert resp.json()["localizable_error"] == "error.413.forms_body_too_large"


def test_submitting_to_a_closed_form_is_410(api_client, published_form):
    from stapel_forms import services

    services.set_state(published_form, "closed")
    resp = api_client.post(
        _submit_url(published_form), {"answers": {"full_name": "A", "plan": "pro"}}, format="json"
    )
    assert resp.status_code == 410


def test_a_signed_in_respondent_is_attributed(api_client, published_form, user):
    api_client.force_authenticate(user=user)
    api_client.post(
        _submit_url(published_form), {"answers": {"full_name": "A", "plan": "pro"}}, format="json"
    )
    assert Submission.objects.get().submitted_by == user.pk


def test_client_meta_is_stored_only_when_the_host_asks(api_client, published_form, settings):
    settings.STAPEL_FORMS = {"STORE_CLIENT_META": True}
    api_client.post(
        _submit_url(published_form),
        {"answers": {"full_name": "A", "plan": "pro"}},
        format="json",
        HTTP_USER_AGENT="probe/1.0",
    )
    assert Submission.objects.get().client_meta["ua"] == "probe/1.0"


def test_throttle_is_wired_to_the_module_namespace(settings):
    from stapel_forms.views import PublicSchemaThrottle, SubmitThrottle

    settings.STAPEL_FORMS = {"SUBMIT_THROTTLE": "3/h", "PUBLIC_SCHEMA_THROTTLE": None}
    assert SubmitThrottle().get_rate() == "3/h"
    assert PublicSchemaThrottle().get_rate() is None


def test_error_responses_on_the_token_path_are_not_logged(api_client, published_form):
    resp = api_client.get("/forms/api/v1/public/aaaaaaaaaaaaaaaaaaaaaa/")
    assert getattr(resp, "_has_been_logged", False) is True
