"""Retention expiry for form responses (spec §6).

Destroys submissions older than the retention horizon and the contents of
forms deleted long enough ago. Irreversible: after retention the count
claim expires too, so these rows leave no tombstone.

    python manage.py forms_purge_expired
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Purge form submissions past their retention horizon"

    def handle(self, *args, **options):
        from ...tasks import purge_expired_submissions

        result = purge_expired_submissions()
        self.stdout.write(
            "forms_purge_expired: purged {submissions} submission(s), "
            "{forms} deleted form(s) with {cascaded} submission(s)".format(**result)
        )
