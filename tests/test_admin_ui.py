"""The operator's admin surface — the answers table, the builder, the MAC.

Through 0.5.0 this module's admin was three read-only `ModelAdmin`s, and a
response was a `JSONField` rendered as its `repr`. That is legible for one
row and unusable for three hundred: no column headers, no labels, no order,
no filter, and the version split showing up as a top-level table an operator
has to reason about before they can read anything.

What these tests pin is the shape of the fix, and — just as importantly —
that fixing it did not open the door the `@access.sensitive` declaration
closes. A prettier leak is still a leak.
"""
import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone


# ── Staff fixtures ────────────────────────────────────────────────────
#
# Clearance reaches the mandate through the default ROLE_SOURCES chain.
# The role goes on the user's `staff_roles` field, which is the SECOND hop
# and the one that actually fires here: the core user model defines
# `staff_roles` with `default=list`, and an empty list is *authoritative*
# ("this user holds no roles"), so it terminates the chain before the
# `role:<name>` group hop is ever consulted. Builtins: viewer=LOW,
# editor=MID, admin=HIGH.
#
# Driving the real chain rather than monkeypatching `has_perm` is what
# makes these tests evidence about the mandate instead of about a stub.


def _staff(role, username):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        username=username,
        password="pw",
        is_staff=True,
        staff_roles=[role] if role else [],
    )


@pytest.fixture
def low_staff(db):
    """LOW clearance: staff, but below the MID that `sensitive` view needs."""
    return _staff("viewer", "lowstaff")


@pytest.fixture
def mid_staff(db):
    """MID clearance: may VIEW responses, may not mutate them."""
    return _staff("editor", "midstaff")


@pytest.fixture
def high_staff(db):
    return _staff("admin", "highstaff")


@pytest.fixture
def answered(db, published_form):
    from stapel_forms import services

    return [
        services.submit(published_form, answers={"full_name": "Ada Lovelace", "plan": "pro"}),
        services.submit(published_form, answers={"full_name": "Grace Hopper", "plan": "basic"}),
    ]


def _responses_url(form):
    return reverse("admin:forms_form_responses", args=[form.id])


# ── 1. The answers table ──────────────────────────────────────────────


class TestAnswersTable:
    def test_columns_are_the_schema_labels_not_the_storage_slugs(
        self, client, published_form, answered, mid_staff
    ):
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "Full name" in body
        assert "Plan" in body

    def test_rows_carry_the_answers(self, client, published_form, answered, mid_staff):
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "Ada Lovelace" in body
        assert "Grace Hopper" in body

    def test_a_select_renders_its_option_label_not_its_stored_value(
        self, client, published_form, answered, mid_staff
    ):
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "Pro" in body

    def test_the_table_is_not_raw_json(self, client, published_form, answered, mid_staff):
        """The regression this whole release exists for."""
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "'type':" not in body
        assert "&#x27;type&#x27;:" not in body

    def test_the_date_filter_narrows_the_table(
        self, client, published_form, answered, mid_staff
    ):
        from stapel_forms.models import Submission

        Submission.objects.filter(pk=answered[1].pk).update(
            submitted_at=timezone.now() - dt.timedelta(days=30)
        )
        client.force_login(mid_staff)
        since = (timezone.now() - dt.timedelta(days=1)).date().isoformat()
        body = client.get(_responses_url(published_form), {"since": since}).content.decode()
        assert "Ada Lovelace" in body
        assert "Grace Hopper" not in body

    def test_the_value_search_narrows_the_table(
        self, client, published_form, answered, mid_staff
    ):
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form), {"q": "Grace"}).content.decode()
        assert "Grace Hopper" in body
        assert "Ada Lovelace" not in body

    def test_paging_survives_more_rows_than_one_page(
        self, client, published_form, mid_staff, settings
    ):
        from stapel_forms import services

        for n in range(7):
            services.submit(published_form, answers={"full_name": f"R{n}", "plan": "pro"})
        client.force_login(mid_staff)
        response = client.get(_responses_url(published_form), {"per_page": 3})
        assert response.status_code == 200
        assert response.context["has_next"] is True
        assert len(response.context["rows"]) == 3

    def test_the_next_page_keeps_the_active_filter(
        self, client, published_form, mid_staff
    ):
        """A cursor that drops the filter silently widens the result set —
        the reviewer pages from a filtered view into an unfiltered one and
        has no way to tell."""
        from stapel_forms import services

        for n in range(6):
            services.submit(published_form, answers={"full_name": f"Ada {n}", "plan": "pro"})
        services.submit(published_form, answers={"full_name": "Grace", "plan": "pro"})
        client.force_login(mid_staff)
        response = client.get(_responses_url(published_form), {"q": "Ada", "per_page": 3})
        assert "q=Ada" in response.context["next_url"]


# ── 2. The mandate is not weakened ────────────────────────────────────


class TestSensitiveStaysSensitive:
    def test_low_clearance_staff_cannot_open_the_answers_table(
        self, client, published_form, answered, low_staff
    ):
        """`Submission` is `@access.sensitive`: view requires MID. The new
        table is a view of submissions and inherits that, or the release
        has quietly downgraded a security decision to a convenience."""
        client.force_login(low_staff)
        response = client.get(_responses_url(published_form))
        assert response.status_code in (302, 403)
        assert b"Ada Lovelace" not in response.content

    def test_the_forms_list_does_not_leak_answers_to_low_clearance_staff(
        self, client, published_form, answered, low_staff
    ):
        """`Form` is standard (view=LOW) and `Submission` is sensitive
        (view=MID). A response count on the form list is fine; a preview of
        what somebody wrote is the leak."""
        client.force_login(low_staff)
        body = client.get(reverse("admin:forms_form_changelist")).content.decode()
        assert "Ada Lovelace" not in body
        assert "Grace Hopper" not in body

    def test_mid_clearance_cannot_delete_a_response(
        self, client, published_form, answered, mid_staff
    ):
        """`sensitive` puts every mutation at HIGH."""
        from stapel_forms.models import Submission

        client.force_login(mid_staff)
        url = reverse("admin:forms_submission_delete", args=[answered[0].id])
        client.post(url, {"post": "yes"})
        assert Submission.objects.filter(pk=answered[0].pk).exists()

    def test_staff_read_does_not_require_a_workspace_membership(
        self, client, published_form, answered, mid_staff
    ):
        """The owner's ruling, and a defect guard. The admin is the STAFF
        door: Django permissions plus the mandate. The workspace capability
        layer gates the REST product surface and must never leak into here
        — a staff reviewer holding table permissions has no membership in
        the workspace that owns the form, and blocking them on one would
        make the admin unusable for exactly the deployment shape a client
        fleet runs (a public feedback form nobody is a "member" of).

        Nothing in the fixture grants a capability; the table must render.
        """
        client.force_login(mid_staff)
        response = client.get(_responses_url(published_form))
        assert response.status_code == 200
        assert "Ada Lovelace" in response.content.decode()


# ── 3. Version/Form split stays out of the way ────────────────────────


class TestVersionsAreNotATopLevelObject:
    def test_the_admin_index_does_not_offer_versions_as_its_own_table(
        self, client, high_staff
    ):
        """The model is right and stays; what must not happen is an
        operator meeting "Form versions" as a thing to reason about before
        they can read a response."""
        client.force_login(high_staff)
        body = client.get(reverse("admin:index")).content.decode()
        assert "Form versions" not in body

    def test_the_reviewer_is_never_asked_to_choose_a_version_first(
        self, client, published_form, answered, mid_staff
    ):
        """The owner's ruling: pick a form, get the answers. A version is
        never a required step, so the bare URL — no query string at all —
        must already render the full table."""
        client.force_login(mid_staff)
        response = client.get(_responses_url(published_form))
        assert response.status_code == 200
        assert "Ada Lovelace" in response.content.decode()

    def test_columns_are_the_union_across_versions_in_current_schema_order(
        self, client, published_form, answered, mid_staff, user
    ):
        """A question that only exists in v2 still gets a column, and a
        question dropped in v2 keeps its own — otherwise half the stored
        answers have nowhere to land and silently vanish from review."""
        from stapel_forms import services

        services.save_draft(
            published_form,
            {
                "fields": [
                    {"slug": "full_name", "name": "Full name", "config": {"type": "string"}},
                    {"slug": "email", "name": "Email", "config": {"type": "string"}},
                ]
            },
        )
        services.publish(published_form, user=user)
        published_form.refresh_from_db()

        client.force_login(mid_staff)
        columns = client.get(_responses_url(published_form)).context["columns"]
        labels = [column["label"] for column in columns]
        # v2's own order leads; questions only v1 had keep a column after it.
        assert labels[:2] == ["Full name", "Email"]
        assert "Plan" in labels

    def test_a_cell_is_blank_where_the_question_did_not_exist_for_that_row(
        self, client, published_form, answered, mid_staff, user
    ):
        from stapel_forms import services

        services.save_draft(
            published_form,
            {
                "fields": [
                    {"slug": "full_name", "name": "Full name", "config": {"type": "string"}},
                    {"slug": "email", "name": "Email", "config": {"type": "string"}},
                ]
            },
        )
        services.publish(published_form, user=user)
        published_form.refresh_from_db()
        services.submit(published_form, answers={"full_name": "Katherine", "email": "k@x.io"})

        client.force_login(mid_staff)
        context = client.get(_responses_url(published_form)).context
        by_slug = {column["slug"]: index for index, column in enumerate(context["columns"])}
        newest, older = context["rows"][0], context["rows"][1]
        assert newest["cells"][by_slug["email"]]["display"] == "k@x.io"
        # The v1 respondent was never asked for an email: blank, and
        # explicitly marked as "not asked" rather than "left empty".
        assert older["cells"][by_slug["email"]]["display"] == ""
        assert older["cells"][by_slug["email"]]["in_schema"] is False

    def test_a_schema_change_is_marked_where_it_happened(
        self, client, published_form, answered, mid_staff, user
    ):
        """Two versions in one table is exactly where the split stops being
        an implementation detail, so that is the one place it is shown."""
        from stapel_forms import services

        services.save_draft(
            published_form,
            {
                "fields": [
                    {"slug": "full_name", "name": "Full name", "config": {"type": "string"}},
                    {"slug": "email", "name": "Email", "config": {"type": "string"}},
                ]
            },
        )
        services.publish(published_form, user=user)
        published_form.refresh_from_db()
        services.submit(published_form, answers={"full_name": "Katherine", "email": "k@x.io"})

        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "v2" in body and "v1" in body
        assert "schema changed" in body.lower()

    def test_an_older_response_still_reads_under_its_own_schema(
        self, client, published_form, answered, mid_staff, user
    ):
        from stapel_forms import services

        services.save_draft(
            published_form,
            {"fields": [{"slug": "email", "name": "Email", "config": {"type": "string"}}]},
        )
        services.publish(published_form, user=user)
        client.force_login(mid_staff)
        body = client.get(_responses_url(published_form)).content.decode()
        assert "Ada Lovelace" in body


# ── 4. The builder ────────────────────────────────────────────────────


class TestBuilder:
    def test_the_form_change_page_offers_a_schema_editor(
        self, client, published_form, high_staff
    ):
        client.force_login(high_staff)
        body = client.get(
            reverse("admin:forms_form_change", args=[published_form.id])
        ).content.decode()
        assert "stapel-forms-builder" in body

    def test_the_builder_payload_is_usable_json_not_a_json_string(
        self, client, published_form, high_staff
    ):
        """The regression this pins shipped in 0.6.0 and rendered an empty
        builder on a form with five questions.

        `json_script` serializes what it is given, so handing it a string
        that was ALREADY `json.dumps`-ed double-encodes it: the page is
        well-formed, the script tag is present, `JSON.parse` succeeds — and
        returns a **string**, so every `payload.x` is `undefined` and the
        builder draws nothing.

        Asserting the mount div exists (as the first test does) cannot see
        any of that. Only parsing the payload the way the browser does can.
        """
        import html as html_mod
        import json
        import re

        client.force_login(high_staff)
        body = client.get(
            reverse("admin:forms_form_change", args=[published_form.id])
        ).content.decode()

        match = re.search(
            r'<script id="stapel-forms-builder-data" type="application/json">(.*?)</script>',
            body,
            re.S,
        )
        assert match, "the builder payload script tag is missing"
        payload = json.loads(html_mod.unescape(match.group(1)))

        assert isinstance(payload, dict), (
            "payload decoded to a %s — it is double-encoded, and every "
            "payload.x in the builder is undefined" % type(payload).__name__
        )
        # The things the builder cannot work without.
        assert [f["slug"] for f in payload["schema"]["fields"]] == [
            "sec", "full_name", "age", "plan",
        ]
        assert payload["schema"]["meta"]["title"] == "Sign up"
        assert "string" in payload["allowedKinds"]
        assert payload["activeVersion"] == 1
        assert payload["publishUrl"].endswith("/publish/")
        assert payload["attributesBundle"].endswith("attributes-admin.js")

    def test_the_change_page_leaks_no_template_comment_as_visible_text(
        self, client, published_form, high_staff
    ):
        """Django's `{# ... #}` is SINGLE-LINE only. A multi-line one is not
        a comment at all — it renders to the operator as literal braces and
        prose, which is what 0.6.0 shipped."""
        client.force_login(high_staff)
        body = client.get(
            reverse("admin:forms_form_change", args=[published_form.id])
        ).content.decode()
        assert "{#" not in body and "#}" not in body

    def test_saving_a_schema_publishes_a_new_version(
        self, client, published_form, high_staff
    ):
        import json

        from stapel_forms.models import FormVersion

        before = FormVersion.objects.filter(form=published_form).count()
        client.force_login(high_staff)
        response = client.post(
            reverse("admin:forms_form_publish", args=[published_form.id]),
            {
                "schema": json.dumps(
                    {
                        "fields": [
                            {
                                "slug": "full_name",
                                "name": "Full name",
                                "mandatory": True,
                                "config": {"type": "string"},
                            },
                            {"slug": "email", "name": "Email", "config": {"type": "string"}},
                        ],
                        "meta": {"title": "Sign up"},
                    }
                )
            },
        )
        assert response.status_code in (200, 302)
        assert FormVersion.objects.filter(form=published_form).count() == before + 1
        published_form.refresh_from_db()
        assert published_form.active_version.version == before + 1

    def test_an_invalid_schema_is_refused_and_publishes_nothing(
        self, client, published_form, high_staff
    ):
        import json

        from stapel_forms.models import FormVersion

        before = FormVersion.objects.filter(form=published_form).count()
        client.force_login(high_staff)
        client.post(
            reverse("admin:forms_form_publish", args=[published_form.id]),
            # `max_length` is not a key the string type knows — the cap
            # would silently not exist, which `validate_schema` refuses.
            {
                "schema": json.dumps(
                    {
                        "fields": [
                            {
                                "slug": "a",
                                "name": "A",
                                "config": {"type": "string", "max_length": 4},
                            }
                        ]
                    }
                )
            },
        )
        assert FormVersion.objects.filter(form=published_form).count() == before

    def test_mid_clearance_cannot_publish(self, client, published_form, mid_staff):
        """Publishing changes what respondents are asked. `Form` is
        standard, so change is MID — but a publish is a change to the
        FORM, and the gate must be the form's change permission, not
        nothing at all."""
        import json

        from stapel_forms.models import FormVersion

        before = FormVersion.objects.filter(form=published_form).count()
        client.force_login(_staff(None, "nostaff"))
        client.post(
            reverse("admin:forms_form_publish", args=[published_form.id]),
            {"schema": json.dumps({"fields": []})},
        )
        assert FormVersion.objects.filter(form=published_form).count() == before

    def test_the_builder_shows_what_a_publish_would_change(
        self, client, published_form, high_staff
    ):
        client.force_login(high_staff)
        body = client.get(
            reverse("admin:forms_form_change", args=[published_form.id])
        ).content.decode()
        assert "old responses stay readable" in body.lower()


# ── 5. The submission detail ──────────────────────────────────────────


class TestSubmissionDetail:
    def test_one_response_renders_as_a_labelled_table(
        self, client, answered, mid_staff
    ):
        client.force_login(mid_staff)
        body = client.get(
            reverse("admin:forms_submission_change", args=[answered[0].id])
        ).content.decode()
        assert "Full name" in body
        assert "Ada Lovelace" in body

    def test_an_unanswered_question_is_shown_as_blank_not_omitted(
        self, client, answered, mid_staff
    ):
        client.force_login(mid_staff)
        body = client.get(
            reverse("admin:forms_submission_change", args=[answered[0].id])
        ).content.decode()
        assert "Age" in body
