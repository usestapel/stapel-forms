"""The builder's config editors come from another package's static files.

stapel-attributes is an EMBEDDED library, not a Django app — it is imported
directly and never appears in `INSTALLED_APPS`. So `AppDirectoriesFinder`
does not walk it, and its shipped `attributes-admin.js` is invisible to
`collectstatic` unless the host adds it to `STATICFILES_DIRS`. (The fleet
already does exactly this for `stapel_core/static`, which is embedded for
the same reason.)

The failure mode is the reason this check exists rather than a README line:
the builder still renders. The field list, ordering, required flags,
labels and publishing all work. Only the per-kind CONFIG editor is
missing — so a form author sees a builder that looks complete, adds a
`select`, and finds no way to type the options. Nothing errors, nothing
logs, and the deployment looks correct from every angle except the one
that matters.
"""
from django.core import checks


def _ids(results):
    return {r.id for r in results}


class TestAttributesBundleCheck:
    def test_no_warning_when_the_bundle_is_findable(self):
        """The harness configures STATICFILES_DIRS the way W004's hint
        tells a host to, so this also proves the remedy works."""
        from stapel_forms.checks import check_builder_assets

        assert _ids(check_builder_assets(None)) == set()

    def test_warns_when_the_attributes_bundle_cannot_be_found(
        self, settings, monkeypatch
    ):
        from stapel_forms import checks as forms_checks

        monkeypatch.setattr(
            "django.contrib.staticfiles.finders.find", lambda path: None
        )
        results = forms_checks.check_builder_assets(None)
        assert "stapel_forms.W004" in _ids(results)
        warning = next(r for r in results if r.id == "stapel_forms.W004")
        assert isinstance(warning, checks.Warning)
        # The hint has to be actionable: the fix is one settings entry, and
        # a warning that does not say which one is just anxiety.
        assert "STATICFILES_DIRS" in warning.hint

    def test_the_check_is_registered_with_django(self):
        from stapel_forms.checks import check_builder_assets

        registered = {
            getattr(check, "__name__", None)
            for check in checks.registry.registry.get_checks()
        }
        assert check_builder_assets.__name__ in registered


class TestTheBuilderSaysSoInThePage:
    def test_the_builder_script_reports_a_missing_bundle(self):
        """Silent degradation is what this whole release is arguing
        against, so the client half says so too rather than quietly
        rendering fewer controls."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "static" / "stapel_forms" / "forms-builder.js"
        ).read_text(encoding="utf-8")
        # The catch handler must surface something, not swallow.
        assert "configEditorUnavailable" in source
