"""The e2e host's own app — it answers the one Function forms asks for.

stapel-forms depends on an ANSWERER for ``workspaces.check_capability``,
not on stapel-workspaces itself ("any provider of that Function satisfies
the contract", MODULE.md §4). Registering the provider here rather than
installing the sibling keeps this run a proof of THIS module: it exercises
the real fail-closed choke point, and it does not go red the next time a
neighbour is mid-migration.

The grant table is deliberately explicit — the owner holds everything, and
anybody else holds nothing, so the deny path is live in the run too.
"""
from django.apps import AppConfig


class E2EConfig(AppConfig):
    name = "e2e"
    label = "e2e_host"

    def ready(self):
        from stapel_core.comm import register_function

        register_function("workspaces.check_capability", _check_capability)
        _make_celery_eager()


def _make_celery_eager():
    """One process, no broker.

    A sibling on the login path enqueues a celery task, and `shared_task`
    binds to celery's DEFAULT app — which reads its own conf, not Django
    settings, so CELERY_TASK_ALWAYS_EAGER in settings.py would be ignored
    and the enqueue would fail against amqp://localhost. Setting it on the
    app the tasks actually bound to is the lever that works.
    """
    try:
        from celery import current_app
    except ImportError:
        return
    current_app.conf.task_always_eager = True
    current_app.conf.task_eager_propagates = True


def _check_capability(payload):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=payload["user_id"]).first()
    if user is None or user.username != "owner":
        return {"allowed": False, "role": None}
    return {"allowed": True, "role": "owner"}
