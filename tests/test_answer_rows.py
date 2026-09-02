"""The definition-driven answer projection.

One primitive answers three consumers that were each inventing their own
shape: the admin's responses table, the notification report, and the CSV
export. What they need is identical and is exactly what the version FK
makes computable — *the schema's* columns, in *the schema's* order, under
*the schema's* labels, with a cell for every question including the ones
this respondent left blank.

The failure this pins is the one the owner hit: a response rendered as its
raw ``answers`` JSON is keyed by slug, ordered by dict insertion, missing
every unanswered question, and silently drops a question that was removed
in a later version. None of that is readable, and at a few hundred rows
none of it is even scannable.
"""
import pytest


@pytest.fixture
def submission(db, published_form):
    from stapel_forms import services

    return services.submit(
        published_form,
        answers={"full_name": "Ada Lovelace", "plan": "pro"},
        version_id=str(published_form.active_version_id),
    )


class TestAnswerRows:
    def test_rows_follow_schema_order_not_answer_insertion_order(self, submission):
        from stapel_forms.presenters import present_answer_rows

        rows = present_answer_rows(submission)
        assert [row["slug"] for row in rows] == ["full_name", "age", "plan"]

    def test_rows_carry_the_label_the_respondent_saw_not_the_slug(self, submission):
        from stapel_forms.presenters import present_answer_rows

        labels = {row["slug"]: row["label"] for row in present_answer_rows(submission)}
        assert labels == {
            "full_name": "Full name",
            "age": "Age",
            "plan": "Plan",
        }

    def test_an_unanswered_optional_question_still_gets_a_row(self, submission):
        """A missing cell is information. Dropping it silently re-orders
        every other row against the header and makes a table lie."""
        from stapel_forms.presenters import present_answer_rows

        age = next(r for r in present_answer_rows(submission) if r["slug"] == "age")
        assert age["answered"] is False
        assert age["display"] == ""

    def test_headers_are_section_captions_not_questions(self, submission):
        """`sec` is a header field: it has no answer and gets no data row —
        the same rule `answer_columns` already applies to the CSV."""
        from stapel_forms.presenters import present_answer_rows

        assert "sec" not in {row["slug"] for row in present_answer_rows(submission)}

    def test_values_render_readable_not_as_python_repr(self, db, workspace_id, user):
        from stapel_forms import services
        from stapel_forms.presenters import present_answer_rows

        form = services.create_form(
            workspace_id=workspace_id,
            title="Shapes",
            user=user,
            draft_schema={
                "fields": [
                    {"slug": "agree", "name": "Agree?", "config": {"type": "bool"}},
                ]
            },
        )
        services.publish(form, user=user)
        services.set_state(form, "open")
        form.refresh_from_db()
        row = services.submit(form, answers={"agree": True})

        agree = present_answer_rows(row)[0]
        assert agree["display"] == "true"

    def test_an_erased_submission_renders_no_answers(self, submission):
        """The tombstone keeps the row and destroys the content (§7). The
        table must not resurrect it, and must not crash on the empty dict."""
        from stapel_forms.presenters import present_answer_rows

        submission.answers = {}
        rows = present_answer_rows(submission)
        assert [r["display"] for r in rows] == ["", "", ""]

    def test_rows_are_read_against_the_version_the_submission_answered(
        self, db, published_form, user
    ):
        """The whole point of the version FK. A question deleted by a later
        publish is still the question this respondent was asked, so the old
        response keeps rendering under the old schema."""
        from stapel_forms import services
        from stapel_forms.presenters import present_answer_rows

        old = services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})

        services.save_draft(
            published_form,
            {"fields": [{"slug": "email", "name": "Email", "config": {"type": "string"}}]},
        )
        services.publish(published_form, user=user)
        published_form.refresh_from_db()

        assert [r["slug"] for r in present_answer_rows(old)] == [
            "full_name",
            "age",
            "plan",
        ]
