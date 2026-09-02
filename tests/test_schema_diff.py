"""Diffing two published schemas — "what changed between v2 and v3".

Wanted in three places (the version picker, the builder's "publishing this
changes X", and potentially the notification report), which is exactly why
it is a library function and not a loop inside one admin template.

The identity rule the whole diff rests on: **the slug is the identity of a
question**, because the slug is what the answer is stored under. So
changing a field's LABEL is a rename (the same stored column, relabelled),
while changing its SLUG is a removal plus an addition (the old answers stay
where they were and the new ones land somewhere else). Anything else would
be a diff that reads nicely and describes the wrong thing.
"""


def _schema(*fields, **meta):
    return {"fields": list(fields), "meta": meta}


def _field(slug, name, kind="string", **config):
    return {"slug": slug, "name": name, "config": {"type": kind, **config}}


class TestDiffSchemas:
    def test_a_new_field_is_reported_as_added(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("a", "A")),
            _schema(_field("a", "A"), _field("b", "B")),
        )
        assert change["added"] == [{"slug": "b", "label": "B"}]
        assert change["removed"] == []

    def test_a_deleted_field_is_reported_as_removed(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("a", "A"), _field("b", "B")),
            _schema(_field("a", "A")),
        )
        assert change["removed"] == [{"slug": "b", "label": "B"}]
        assert change["added"] == []

    def test_a_changed_label_on_the_same_slug_is_a_rename(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("a", "Old label")),
            _schema(_field("a", "New label")),
        )
        assert change["renamed"] == [
            {"slug": "a", "label": "New label", "was": "Old label"}
        ]
        assert change["added"] == [] and change["removed"] == []

    def test_a_changed_slug_is_a_removal_plus_an_addition_not_a_rename(self):
        """The stored answers do not move. Calling this a rename would tell
        an author their history follows the field when it does not."""
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("old_slug", "Same label")),
            _schema(_field("new_slug", "Same label")),
        )
        assert change["removed"] == [{"slug": "old_slug", "label": "Same label"}]
        assert change["added"] == [{"slug": "new_slug", "label": "Same label"}]
        assert change["renamed"] == []

    def test_a_changed_kind_is_reported_as_retyped(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("a", "A", "string")),
            _schema(_field("a", "A", "int")),
        )
        assert change["retyped"] == [
            {"slug": "a", "label": "A", "was": "string", "now": "int"}
        ]

    def test_a_changed_mandatory_flag_is_reported(self):
        from stapel_forms.schema import diff_schemas

        old = _schema({"slug": "a", "name": "A", "config": {"type": "string"}})
        new = _schema(
            {"slug": "a", "name": "A", "mandatory": True, "config": {"type": "string"}}
        )
        assert diff_schemas(old, new)["required_changed"] == [
            {"slug": "a", "label": "A", "now": True}
        ]

    def test_headers_are_not_reported_as_questions(self):
        """A header is a caption, not a question, and never held answers —
        an author reading "1 field removed" about a caption would go
        looking for lost data that never existed."""
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("cap", "Section", "header"), _field("a", "A")),
            _schema(_field("a", "A")),
        )
        assert change["removed"] == []
        assert change["is_empty"] is True

    def test_an_unchanged_schema_reports_empty(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(_schema(_field("a", "A")), _schema(_field("a", "A")))
        assert change["is_empty"] is True
        assert change["summary"] == ""

    def test_the_first_version_has_no_predecessor_and_reports_its_fields(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(None, _schema(_field("a", "A"), _field("b", "B")))
        assert [entry["slug"] for entry in change["added"]] == ["a", "b"]
        assert change["is_empty"] is False

    def test_the_summary_is_a_single_readable_line(self):
        from stapel_forms.schema import diff_schemas

        change = diff_schemas(
            _schema(_field("a", "A"), _field("b", "B")),
            _schema(_field("a", "A2"), _field("c", "C")),
        )
        assert change["summary"] == "added C; removed B; renamed A → A2"


class TestVersionHistory:
    def test_history_lists_every_version_newest_first_with_its_change(
        self, db, published_form, user
    ):
        from stapel_forms import services
        from stapel_forms.schema import version_history

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

        history = version_history(published_form)
        assert [entry["version"] for entry in history] == [2, 1]
        assert history[0]["is_active"] is True
        assert "added Email" in history[0]["summary"]
        assert "removed" in history[0]["summary"]

    def test_history_carries_the_response_count_per_version(
        self, db, published_form, user
    ):
        """An empty version is obviously skippable only if the count is
        on the row."""
        from stapel_forms import services
        from stapel_forms.schema import version_history

        services.submit(published_form, answers={"full_name": "Ada", "plan": "pro"})
        services.save_draft(
            published_form,
            {"fields": [{"slug": "email", "name": "Email", "config": {"type": "string"}}]},
        )
        services.publish(published_form, user=user)
        published_form.refresh_from_db()

        counts = {e["version"]: e["submission_count"] for e in version_history(published_form)}
        assert counts == {1: 1, 2: 0}
