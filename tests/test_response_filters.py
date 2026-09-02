"""Filters on the response listing — the "каша at scale" half of review.

Keyset paging alone answers "show me the next hundred". It does not answer
the question a reviewer actually arrives with: *which* of these three
thousand responses is the one I am looking for. Before 0.6.0 the only
filter was `version`, so finding a response by date or by what somebody
wrote in it meant paging by hand or exporting to a spreadsheet.

The filters live in the service, not in the admin view, so the REST surface
and the admin inherit the same predicate — a filter that exists on one
review screen and not the other is the seam a second implementation grows
in.
"""
import datetime as dt

import pytest
from django.utils import timezone


@pytest.fixture
def spread(db, published_form):
    """Five responses, backdated one day apart, newest first at day 0."""
    from stapel_forms import services
    from stapel_forms.models import Submission

    names = ["Ada", "Grace", "Katherine", "Dorothy", "Mary"]
    rows = []
    for offset, name in enumerate(names):
        row = services.submit(published_form, answers={"full_name": name, "plan": "pro"})
        Submission.objects.filter(pk=row.pk).update(
            submitted_at=timezone.now() - dt.timedelta(days=offset)
        )
        row.refresh_from_db()
        rows.append(row)
    return rows


class TestDateFilters:
    def test_since_keeps_only_responses_at_or_after_the_boundary(self, published_form, spread):
        from stapel_forms import services

        since = timezone.now() - dt.timedelta(days=2, hours=1)
        rows = services.list_submissions(published_form, since=since)
        assert {r.answers["full_name"]["value"] for r in rows} == {"Ada", "Grace", "Katherine"}

    def test_until_keeps_only_responses_at_or_before_the_boundary(self, published_form, spread):
        from stapel_forms import services

        until = timezone.now() - dt.timedelta(days=2, hours=1)
        rows = services.list_submissions(published_form, until=until)
        assert {r.answers["full_name"]["value"] for r in rows} == {"Dorothy", "Mary"}

    def test_since_and_until_compose_into_a_window(self, published_form, spread):
        from stapel_forms import services

        rows = services.list_submissions(
            published_form,
            since=timezone.now() - dt.timedelta(days=3, hours=1),
            until=timezone.now() - dt.timedelta(days=1, hours=1),
        )
        assert {r.answers["full_name"]["value"] for r in rows} == {"Katherine", "Dorothy"}

    def test_the_date_window_composes_with_the_keyset_cursor(self, published_form, spread):
        """`before` is paging and `since` is filtering; they are different
        axes and must not overwrite one another."""
        from stapel_forms import services

        rows = services.list_submissions(
            published_form,
            since=timezone.now() - dt.timedelta(days=3, hours=1),
            before=timezone.now() - dt.timedelta(days=1, hours=1),
        )
        assert {r.answers["full_name"]["value"] for r in rows} == {"Katherine", "Dorothy"}


class TestValueSearch:
    def test_q_matches_the_text_a_respondent_wrote(self, published_form, spread):
        from stapel_forms import services

        rows = services.list_submissions(published_form, q="Katherine")
        assert [r.answers["full_name"]["value"] for r in rows] == ["Katherine"]

    def test_q_is_case_insensitive(self, published_form, spread):
        from stapel_forms import services

        rows = services.list_submissions(published_form, q="katherine")
        assert [r.answers["full_name"]["value"] for r in rows] == ["Katherine"]

    def test_q_matches_a_substring_not_only_a_whole_value(self, published_form, spread):
        from stapel_forms import services

        rows = services.list_submissions(published_form, q="race")
        assert [r.answers["full_name"]["value"] for r in rows] == ["Grace"]

    def test_q_can_be_scoped_to_one_field(self, published_form, spread):
        """`plan` is "pro" on every row; scoping the same needle to
        full_name must not match it, which is what proves the field scope
        is a predicate and not decoration."""
        from stapel_forms import services

        assert services.list_submissions(published_form, q="pro", field="plan")
        assert services.list_submissions(published_form, q="pro", field="full_name") == []

    def test_an_erased_row_is_not_matched_by_its_erased_content(self, published_form, spread):
        from stapel_forms import services

        target = spread[0]
        target.answers = {}
        target.save(update_fields=["answers"])
        assert services.list_submissions(published_form, q="Ada") == []


class TestListingContract:
    def test_the_page_cap_still_bounds_a_filtered_listing(self, published_form, spread, settings):
        """A filter must never become a way past MAX_PAGE_SIZE."""
        from stapel_forms import services

        settings.STAPEL_FORMS = {"MAX_PAGE_SIZE": 2}
        assert len(services.list_submissions(published_form, limit=100)) == 2

    def test_the_api_accepts_the_new_filters(
        self, api_client, published_form, spread, user, workspace_id, grant_capabilities
    ):
        grant_capabilities(workspace_id, user.id, "forms.responses.view")
        api_client.force_authenticate(user=user)
        response = api_client.get(
            f"/forms/api/v1/forms/{published_form.id}/submissions",
            {
                "workspace_id": str(workspace_id),
                "since": (timezone.now() - dt.timedelta(days=1, hours=1)).isoformat(),
                "q": "Ada",
            },
        )
        assert response.status_code == 200, response.data
        assert [row["answers"]["full_name"] for row in response.data] == ["Ada"]

    def test_an_unknown_field_scope_is_a_400_not_an_empty_page(
        self, api_client, published_form, spread, user, workspace_id, grant_capabilities
    ):
        """An empty page reads as "no matches"; a typo'd field name is a
        different fact and must not be reported as one."""
        grant_capabilities(workspace_id, user.id, "forms.responses.view")
        api_client.force_authenticate(user=user)
        response = api_client.get(
            f"/forms/api/v1/forms/{published_form.id}/submissions",
            {"workspace_id": str(workspace_id), "q": "x", "field": "no_such_field"},
        )
        assert response.status_code == 400
