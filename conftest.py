def pytest_configure(config):
    from django.conf import settings
    if not settings.configured:
        from stapel_forms._codegen_settings import settings_kwargs

        settings.configure(**settings_kwargs())
        import django
        django.setup()

        from stapel_core.comm.schemas import autoload_schemas
        autoload_schemas()


import pytest  # noqa: E402

# ── Workspace capability provider (test double for stapel-workspaces) ──
#
# authz.authorize() asks the `workspaces.check_capability` comm Function
# (fail-closed). Tests register this in-process provider backed by an
# explicit grant table: nothing is allowed until a test grants it, which
# keeps deny-by-default honestly exercised.

_CAPABILITY_GRANTS: dict = {}


def _check_capability(payload):
    granted = _CAPABILITY_GRANTS.get((payload["workspace_id"], payload["user_id"]))
    if not granted:
        return {"allowed": False, "role": None}
    cap = payload["capability"]
    allowed = (
        "*" in granted
        or cap in granted
        or any(g.endswith(".*") and cap.startswith(g[:-1]) for g in granted)
    )
    return {"allowed": allowed, "role": "owner" if allowed else None}


def pytest_sessionstart(session):
    from stapel_core.comm import register_function

    register_function("workspaces.check_capability", _check_capability)


@pytest.fixture
def grant_capabilities():
    """``grant(workspace_id, user_id, *caps)`` — no caps means all ("*")."""

    def _grant(workspace_id, user_id, *caps):
        _CAPABILITY_GRANTS[(str(workspace_id), str(user_id))] = set(caps) or {"*"}

    yield _grant
    _CAPABILITY_GRANTS.clear()


@pytest.fixture(autouse=True)
def _isolate_caches():
    """Capability verdicts (30 s) and the notify cooldown both live in the
    Django cache — flush per test so one test's verdict or cooldown never
    leaks into the next."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create(username="author", email="author@example.com")


@pytest.fixture
def workspace_id():
    import uuid

    return uuid.uuid4()


@pytest.fixture
def simple_schema():
    """Three fields covering the shapes the spike exercised: a mandatory
    string, an optional int, a mandatory select, plus a header section."""
    return {
        "fields": [
            {"slug": "sec", "name": "About you", "config": {"type": "header"}},
            {
                "slug": "full_name",
                "name": "Full name",
                "mandatory": True,
                "config": {"type": "string", "maxLength": 40},
            },
            {
                "slug": "age",
                "name": "Age",
                "config": {"type": "int", "min": 0, "max": 130},
            },
            {
                "slug": "plan",
                "name": "Plan",
                "mandatory": True,
                "config": {
                    "type": "select",
                    "options": [
                        {"value": "basic", "label": "Basic"},
                        {"value": "pro", "label": "Pro"},
                    ],
                },
            },
        ],
        "meta": {
            "title": "Sign up",
            "confirmation_text": "Thanks — we will be in touch.",
            "submit_label": "Send",
        },
    }


@pytest.fixture
def published_form(db, workspace_id, user, simple_schema):
    from stapel_forms import services

    form = services.create_form(
        workspace_id=workspace_id,
        title="Sign up",
        user=user,
        settings={"notify_emails": ["sales@example.com"]},
        draft_schema=simple_schema,
    )
    services.publish(form, user=user)
    services.set_state(form, "open")
    form.refresh_from_db()
    return form
