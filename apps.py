from django.apps import AppConfig


class FormsConfig(AppConfig):
    name = "stapel_forms"
    label = "forms"
    verbose_name = "Forms: admin-defined schemas, anonymous submissions, response review"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Import-time side effects: system checks, error-key registration,
        # comm providers. Keep each in its own module.
        from . import checks  # noqa: F401
        from . import errors  # noqa: F401
        from . import functions  # noqa: F401

        # Action subscriptions (in-process in a monolith, bus consumer in
        # microservices — same code, transport chosen by STAPEL_COMM):
        # user.deleted, plus this module's own submission event driving the
        # notify subscriber.
        from . import actions  # noqa: F401

        # GDPR provider registration (monolith mode). Hosts must ALSO list
        # "forms" in STAPEL_GDPR["DATA_OWNERS"] — registering without
        # declaring is gdpr.E002, and the erasure closure never completes.
        from stapel_core.gdpr import gdpr_registry

        from .gdpr import FormsGDPRProvider

        if FormsGDPRProvider().section not in gdpr_registry.sections:
            gdpr_registry.register(FormsGDPRProvider())
