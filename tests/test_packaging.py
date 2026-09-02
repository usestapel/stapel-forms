"""Every runtime asset in the tree is listed in `package-data`.

The failure this prevents is invisible in development and total in
production: Django's `APP_DIRS` template loader and `AppDirectoriesFinder`
walk the *installed* package, so a template or a script missing from the
wheel raises `TemplateDoesNotExist` (or 404s the bundle) on the first real
page view — while a source checkout, where the files are on disk regardless
of packaging, stays green forever.

So the gate is not "does the admin render" — it is "would these files be in
the wheel at all".
"""
import fnmatch
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Directories whose contents Django loads by walking the installed package.
RUNTIME_ASSET_DIRS = ("templates", "static")


def _patterns():
    with open(ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    return data["tool"]["setuptools"]["package-data"]["stapel_forms"]


def test_every_template_and_static_file_is_packaged():
    patterns = _patterns()
    missing = []
    for directory in RUNTIME_ASSET_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            relative = path.relative_to(ROOT).as_posix()
            if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
                missing.append(relative)
    assert not missing, (
        "not covered by [tool.setuptools.package-data]; these would be "
        f"absent from the wheel: {missing}"
    )


def test_the_admin_templates_the_code_names_actually_exist():
    """A packaging pattern that matches nothing still passes the test above."""
    for name in (
        "templates/admin/forms/responses.html",
        "templates/admin/forms/submission_answers.html",
        "templates/admin/forms/change_form.html",
        "static/stapel_forms/forms-builder.js",
    ):
        assert (ROOT / name).is_file(), f"{name} is referenced in admin.py but absent"
