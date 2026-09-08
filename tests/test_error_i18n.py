"""Every code this module's registry can return has a string in every language.

Not "every code this module OWNS" — that is the house gate, and it was green
on a deployment where seven of these codes rendered in English. This module
imports ``stapel_attributes.errors`` (see ``errors.py``) so the thirteen
``error.400.feature_*`` / ``error.400.description_*`` codes its submit path
re-raises land in the registry of every host that mounts it. The registry
travelled; the strings did not.

The two halves of that asymmetry are the two gates here:

* :func:`test_every_registry_code_has_a_string_in_every_shipped_language`
  resolves the whole registry the way a host's loader does — this package's
  catalogs, plus the catalog of whichever package OWNS each key
  (``stapel_core.i18n.catalogs.load_app_catalogs`` walks the package
  directory of every registered error owner, not just INSTALLED_APPS). It
  answers "does the installed dependency carry the sentence".

* :func:`test_the_floor_of_every_upstream_error_owner_ships_those_strings`
  answers the other half — "can a host install a version where it does not".
  It reads the floors this package declares. ``stapel-attributes>=0.4.6``
  admitted eight releases (0.4.6 … 0.9.2) whose wheels carry ``errors.py``
  and no ``translations/`` directory at all, and ``stapel-core>=0.47.0``
  admitted every loader that could not find such a catalog for a library
  outside INSTALLED_APPS. A floor that admits those is the defect; the
  installed-closure test above cannot see it, because pip installs the
  newest.

Nothing here copies an upstream string into this package's catalogs. That
"fix" is what :func:`test_this_module_ships_no_foreign_key` forbids: core's
``check_translation_catalogs`` calls a translated key another package owns
and already ships a ``foreign`` error, and declaring the override would make
this repo the maintainer of a second, drifting copy of somebody else's text.
The strings reach a host from the owner's wheel, which is where they stay
correct.
"""
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TRANSLATIONS = REPO / "translations"

#: Languages this module ships error catalogs in. ``en`` is the canon (the
#: registry literals), so it needs no catalog.
LANGUAGES = ["en", "ru", "es"]
TARGET_LANGUAGES = [lang for lang in LANGUAGES if lang != "en"]

#: Per upstream distribution, the first release whose WHEEL makes the strings
#: for the codes it owns reachable from a host that installs this package.
#: Verified against the built wheels, not against a changelog:
#:
#: * ``stapel-attributes`` 0.9.3 is the first wheel containing
#:   ``stapel_attributes/translations/errors.{ru,es}.json`` — 0.4.6 ships
#:   ``errors.py`` (thirteen registered codes) and no ``translations/`` at all;
#: * ``stapel-core`` 0.60.8 is the first loader whose ``catalog_search_dirs()``
#:   includes the package directory of every registered error owner.
#:   stapel-attributes is an embedded library with no Django app, so on every
#:   earlier core its catalog is invisible however complete it is.
#:
#: Adding a library whose codes this module re-exports means adding it here.
CATALOGUE_FLOORS = {
    "stapel-attributes": (0, 9, 3),
    "stapel-core": (0, 60, 8),
}


def _registry():
    """``{code: owning package}`` for everything this module can return.

    The live registry of the test instance PLUS the committed
    ``docs/errors.json``. The artifact is the wider of the two and it is the
    one a consumer reads: the contract emission harness mounts core surfaces
    (captcha, step-up verification) this instance does not, and those codes
    are in the denominator of every coverage report built from the wheel.
    """
    import json

    import stapel_forms.errors  # noqa: F401  (forces the attributes import too)
    from stapel_core.django.api.errors import error_owners

    owners = dict(error_owners())
    for entry in json.loads((REPO / "docs" / "errors.json").read_text()):
        owners.setdefault(entry["code"], entry.get("owner"))
    return owners


def _declared_floors():
    """``{distribution: (major, minor, patch)}`` from this package's manifest."""
    import re

    with open(REPO / "pyproject.toml", "rb") as handle:
        requirements = tomllib.load(handle)["project"]["dependencies"]
    floors = {}
    for spec in requirements:
        match = re.match(r"^([A-Za-z0-9._-]+)\s*>=\s*(\d+)\.(\d+)\.(\d+)", spec)
        if match:
            floors[match.group(1)] = tuple(int(part) for part in match.groups()[1:])
    return floors


def test_every_registry_code_has_a_string_in_every_shipped_language():
    """The whole registry, whoever owns the code — the host's read path.

    ``load_app_catalogs`` is what renders an error message in a deployment:
    owner packages first, then INSTALLED_APPS in order, then
    ``EXTRA_CATALOG_DIRS``, merged later-wins. A code present here with no
    entry in the merged catalog is a code that renders its English floor on a
    Russian screen.
    """
    from stapel_core.i18n.catalogs import load_app_catalogs

    owners = _registry()
    assert owners, "the error registry came back empty"

    for lang in TARGET_LANGUAGES:
        catalog = load_app_catalogs("errors", lang)
        missing = sorted(code for code in owners if code not in catalog)
        assert not missing, (
            f"{lang}: {len(missing)} code(s) in this module's registry have no "
            f"string — they render the English floor: "
            + ", ".join(f"{code} (owner: {owners[code]})" for code in missing[:10])
        )


@pytest.mark.parametrize("distribution", sorted(CATALOGUE_FLOORS))
def test_the_floor_of_every_upstream_error_owner_ships_those_strings(distribution):
    """A host must not be able to resolve a version where the strings are absent.

    The test above passes on whatever pip installed, which is the newest thing
    the range allows. This one is about the OTHER end of the range: the
    resolution a lockfile is entitled to produce.
    """
    declared = _declared_floors().get(distribution)
    required = CATALOGUE_FLOORS[distribution]
    assert declared is not None, (
        f"{distribution} is not a declared dependency of this package, but this "
        f"module re-exports codes it owns"
    )
    assert declared >= required, (
        f"pyproject declares {distribution}>="
        + ".".join(str(part) for part in declared)
        + ", which admits releases that do not make the strings for the codes "
        "this module re-exports reachable; the floor must be >="
        + ".".join(str(part) for part in required)
    )


def test_the_installed_upstream_owners_actually_ship_their_catalogues():
    """Named per owner, so a regression says which wheel stopped shipping.

    The coverage test reports a missing string; this one reports a missing
    catalog file, which is the shape the defect actually had.
    """
    from stapel_core.i18n.catalogs import owner_catalog

    owners = _registry()
    foreign = {
        owner for code, owner in owners.items() if owner != "stapel_forms"
    }
    assert "stapel_attributes" in foreign, (
        "the attributes registration no longer runs — errors.py must keep "
        "importing stapel_attributes.errors, or the submit path returns codes "
        "no consumer has declared"
    )
    for owner in sorted(foreign):
        owned = {code for code, pkg in owners.items() if pkg == owner}
        for lang in TARGET_LANGUAGES:
            catalog = owner_catalog(owner, "errors", lang)
            missing = sorted(owned - set(catalog))
            assert not missing, (
                f"{owner} owns {len(owned)} code(s) this module can return and "
                f"its installed wheel ships no {lang} string for {len(missing)} "
                f"of them: {missing[:8]}"
            )


def test_this_module_ships_no_foreign_key():
    """Coverage must NOT have been bought by copying somebody else's strings.

    Core's gate: a key this package does not own, translated here while the
    owner already ships that language, is an ``error``-level ``foreign``
    issue — the duplication that had five libraries each maintaining the same
    41 core keys. The fix for the gap the other tests measure is the
    dependency floor, not a copy, and this is what keeps it that way.
    """
    from stapel_core.i18n import check_translation_catalogs, source_texts

    issues = check_translation_catalogs(
        "errors", TRANSLATIONS,
        source_texts=source_texts("errors"),
        languages=LANGUAGES,
    )
    blocking = [issue for issue in issues if issue.level == "error"]
    assert not blocking, "\n".join(
        f"[{issue.code}] {issue.message}" for issue in blocking
    )


def test_the_catalogues_are_packaged():
    """A catalog outside the wheel is a catalog no deployment ever reads."""
    with open(REPO / "pyproject.toml", "rb") as handle:
        patterns = tomllib.load(handle)["tool"]["setuptools"]["package-data"]
    assert "translations/*.json" in patterns["stapel_forms"]
    for lang in TARGET_LANGUAGES:
        assert (TRANSLATIONS / f"errors.{lang}.json").is_file()
