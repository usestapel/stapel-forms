"""The submission notification — a report, not a doorbell.

Through 0.5.0 the auto-notify letter carried `{form_id, form_title,
new_count}`. That tells a recipient a response exists and nothing about it:
they still have to find the admin, find the form, and find the row. The
owner's summary was exact — «вот пришёл ответ и всё».

Two things are fixed here and they are deliberately different in kind:

- **the link is unconditional.** A deep link to the response is not
  respondent content, it is navigation, and its absence was the actual
  daily cost.
- **the answers are OPT-IN.** Answers are respondent PII and email is the
  least controlled channel this module touches — it leaves the deployment,
  lands in inboxes nobody administers, and gets forwarded. So
  `NOTIFY_INCLUDE_ANSWERS` ships **False**: the letter says what happened
  and where to read it, and a host that wants the content in the mail says
  so explicitly.
"""
import pytest


@pytest.fixture
def sent(monkeypatch):
    """Capture `request_notification` calls without a notifications app."""
    calls = []

    def _capture(notification_type, **kwargs):
        calls.append({"type": notification_type, **kwargs})

    monkeypatch.setattr(
        "stapel_core.notifications.publish.request_notification", _capture
    )
    return calls


class TestTheReportDefaults:
    def test_answers_are_absent_by_default(self, db, published_form, sent, settings):
        """The safer default, stated as a test so a later "helpful" change
        has to argue with it."""
        from stapel_forms import services

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        assert sent, "no notification was requested"
        variables = sent[0]["variables"]
        assert "answers" not in variables or not variables["answers"]
        assert "Ada" not in str(variables)

    def test_the_setting_defaults_to_false(self):
        from stapel_forms.conf import forms_settings

        assert forms_settings.NOTIFY_INCLUDE_ANSWERS is False

    def test_a_review_link_is_always_present(self, db, published_form, sent, settings):
        settings.STAPEL_FORMS = {"ADMIN_BASE_URL": "https://app.example.com"}
        from stapel_forms import services

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        url = sent[0]["variables"]["review_url"]
        assert url.startswith("https://app.example.com/")
        # A deep link to THIS response, not to the form's inbox: the
        # recipient should land on the thing the letter is about.
        assert "/admin/forms/submission/" in url

    def test_no_base_url_means_no_broken_half_link(
        self, db, published_form, sent, settings
    ):
        """A relative path in an email is not a link, it is a bug report
        from the recipient. Absent beats broken."""
        settings.STAPEL_FORMS = {"ADMIN_BASE_URL": ""}
        from stapel_forms import services

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        assert not sent[0]["variables"].get("review_url")


class TestTheReportWithAnswers:
    @pytest.fixture(autouse=True)
    def _opt_in(self, settings):
        settings.STAPEL_FORMS = {
            "NOTIFY_INCLUDE_ANSWERS": True,
            "ADMIN_BASE_URL": "https://app.example.com",
            "NOTIFY_COOLDOWN_SECONDS": 0,
        }

    def test_the_answers_travel_as_labelled_rows_in_schema_order(
        self, db, published_form, sent
    ):
        from stapel_forms import services

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        rows = sent[0]["variables"]["answers"]
        assert [row["label"] for row in rows] == ["Full name", "Age", "Plan"]
        assert rows[0]["display"] == "Ada"

    def test_a_select_reports_its_label_not_its_stored_value(
        self, db, published_form, sent
    ):
        from stapel_forms import services

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        rows = {row["label"]: row["display"] for row in sent[0]["variables"]["answers"]}
        assert rows["Plan"] == "Pro"

    def test_a_folded_batch_reports_the_count_and_no_answers(
        self, db, published_form, sent, settings
    ):
        """The cooldown folds interim submissions into the next letter as a
        count. Attaching "the answers" then would attach ONE response's
        answers under a heading claiming several — a letter that is wrong
        rather than merely terse."""
        settings.STAPEL_FORMS = {
            "NOTIFY_INCLUDE_ANSWERS": True,
            "ADMIN_BASE_URL": "https://app.example.com",
            "NOTIFY_COOLDOWN_SECONDS": 600,
        }
        from stapel_forms import services

        from django.core.cache import cache

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        # The cooldown let exactly one letter out, for the first submission,
        # and it DOES carry answers — it stands for one response.
        assert len(sent) == 1
        assert sent[0]["variables"]["answers"]

        # Two more arrive inside the window and are held as a count.
        services.submit(published_form, answers={"full_name": "Grace", "plan": "basic"})
        services.submit(published_form, answers={"full_name": "Kay", "plan": "pro"})
        assert len(sent) == 1

        # The window expires and a fourth arrives: one letter for three
        # responses (its own plus the two held).
        cache.delete(f"stapel_forms:notify:{published_form.id}")
        services.submit(published_form, answers={"full_name": "Mary", "plan": "pro"})
        folded = sent[-1]["variables"]
        assert folded["new_count"] == 3
        assert not folded.get("answers")
        # …and the link still points somewhere useful.
        assert folded["review_url"]


class TestResend:
    def test_resend_carries_labelled_rows_too(self, db, published_form, sent):
        """Resend always carried answers — it is an operator asking for
        this one response. What it carried was `{slug: value}`, which is
        the same unreadable shape the admin had."""
        from stapel_forms import services

        submission = services.submit(
            published_form, answers={"full_name": "Ada", "plan": "pro"}
        )
        sent.clear()
        services.resend_submission(submission, recipients=["ops@example.com"])
        rows = sent[0]["variables"]["answers"]
        assert [row["label"] for row in rows] == ["Full name", "Age", "Plan"]
        assert rows[0]["display"] == "Ada"

    def test_resend_is_not_gated_by_the_include_answers_setting(
        self, db, published_form, sent, settings
    ):
        """The setting governs the AUTOMATIC letter to a standing address
        list. A resend is an operator, authenticated and holding
        `responses.manage`, asking for one specific response to be sent
        somewhere — gating that on a deployment-wide default would break
        the "send this one to legal" case the endpoint exists for."""
        settings.STAPEL_FORMS = {"NOTIFY_INCLUDE_ANSWERS": False}
        from stapel_forms import services

        submission = services.submit(
            published_form, answers={"full_name": "Ada", "plan": "pro"}
        )
        sent.clear()
        services.resend_submission(submission, recipients=["legal@example.com"])
        assert sent[0]["variables"]["answers"]
