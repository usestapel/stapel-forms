"""E2E host settings — a real minimal host mounting auth + workspaces + forms.

Not shipped in the wheel (the setuptools packages list is explicit). Used by
``e2e/run_e2e.py`` to prove the whole lifecycle over real HTTP: a real
session for the admin side, and genuinely no session at all for the
respondent side, which is the property the test suite cannot demonstrate
because its client always has one available.
"""
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "e2e-only-not-a-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "stapel_core.django.apps.CommonDjangoConfig",
    "stapel_core.django.users",
    "stapel_core.django.outbox",
    "stapel_auth",
    "stapel_forms",
    # Answers workspaces.check_capability in-process; see e2e/apps.py.
    "e2e.apps.E2EConfig",
]

AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    # First on purpose: without it this project's own E-gates would run
    # under manage.py and nowhere else (stapel_core.boot.W002).
    "stapel_core.django.boot.BootGateMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "e2e.urls"

from stapel_core.django.settings import get_common_templates  # noqa: E402

TEMPLATES = get_common_templates(BASE_DIR)

_STATE_DIR = Path(os.environ.get("STAPEL_FORMS_E2E_DIR", tempfile.gettempdir() + "/stapel-forms-e2e"))
_STATE_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _STATE_DIR / "db.sqlite3",
    }
}

LOGIN_URL = "admin:login"
LOGIN_REDIRECT_URL = "admin:index"
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "stapel_core.django.jwt.authentication.JWTCookieAuthentication",
    ],
    "EXCEPTION_HANDLER": "stapel_core.django.api.errors.stapel_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {"TITLE": "stapel-forms E2E", "VERSION": "0.1.0"}

STAPEL_COMM = {
    "OUTBOX_ENABLED": True,
    "ACTION_TRANSPORT": "inprocess",
}

# This run speaks plain http on loopback, and a Secure cookie would never
# be sent back — the admin half of the script would look unauthenticated.
JWT_COOKIE_SECURE = False

STAPEL_AUTH = {
    "AUTH_PASSWORD_LOGIN": True,
    "AUTH_EMAIL_LOGIN": False,
    "AUTH_OAUTH_LOGIN": False,
    "AUTH_EMAIL_REGISTRATION": False,
    "AUTH_OAUTH_REGISTRATION": False,
}

STAPEL_FORMS = {
    # This host has no captcha backend, and rather than let the warning sit
    # unexplained in the e2e output it makes the choice the library refuses
    # to make for a deployment. A real public deployment configures
    # STAPEL_CAPTCHA["SECRET"] instead.
    "ALLOW_UNCAPTCHAED_PUBLIC": True,
    # Small enough that the run can actually reach the refusals.
    "MAX_SUBMISSIONS_PER_FORM": 3,
    "SUBMIT_THROTTLE": None,
    "PUBLIC_SCHEMA_THROTTLE": None,
}

STAPEL_SERVICES = [{"name": "stapel-forms E2E", "prefix": ""}]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
