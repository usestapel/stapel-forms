"""``user.merged``: a guest folded into an account keeps their answers.

The other half of the account life cycle ``user.deleted`` already answered,
and the opposite instruction. Erasure DESTROYS a respondent's answers ("this
is my data, delete it"); a merge RE-PARENTS them ("this is still my data,
under my other account"). A module that answers only the first leaves a
guest's responses attributed to an id that can no longer sign in — outside
the survivor's export, and outside any future erasure request too, because
none is ever made for a merged-away account.

Pinned here: the rows move, a redelivery moves nothing further, every
malformed payload is ACKed instead of poisoning the bus, and an event naming
users this deployment has no rows for does nothing.
"""
import uuid
from types import SimpleNamespace

import pytest

from stapel_forms.actions import MergeTargetNotReady, handle_user_merged
from stapel_forms.models import Form, FormVersion, Submission

pytestmark = pytest.mark.django_db

BAD_IDS = ["not-a-uuid", "", "  ", "['x']"]


def _user(username):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create(
        username=username, email=f"{username}@example.com"
    )


@pytest.fixture
def guest(db):
    return _user("guest")


@pytest.fixture
def survivor(db):
    return _user("survivor")


def _event(**payload):
    return SimpleNamespace(payload=payload, event_id=str(uuid.uuid4()))


@pytest.fixture
def guest_corpus(published_form, guest, simple_schema):
    """A form the guest built and an answer they gave while signed in."""
    from stapel_forms import services

    own_form = services.create_form(
        workspace_id=published_form.workspace_id,
        title="Guest questionnaire",
        user=guest,
        draft_schema=simple_schema,
    )
    services.publish(own_form, user=guest)
    submission = services.submit(
        published_form,
        answers={"full_name": "Ann", "plan": "pro"},
        user_id=guest.pk,
    )
    return own_form, submission


def _snapshot():
    return (
        sorted(Form.objects.values_list("id", "created_by_id")),
        sorted(FormVersion.objects.values_list("id", "created_by_id")),
        sorted(Submission.objects.values_list("id", "submitted_by")),
    )


class TestHappyPath:
    def test_forms_versions_and_answers_are_re_parented(
        self, guest_corpus, guest, survivor
    ):
        own_form, submission = guest_corpus

        handle_user_merged(
            _event(from_user_id=str(guest.pk), into_user_id=str(survivor.pk))
        )

        own_form.refresh_from_db()
        submission.refresh_from_db()
        assert own_form.created_by_id == survivor.pk
        assert submission.submitted_by == survivor.pk
        assert not FormVersion.objects.filter(created_by_id=guest.pk).exists()

    def test_the_answers_themselves_are_untouched(self, guest_corpus, guest, survivor):
        _own_form, submission = guest_corpus

        handle_user_merged(_event(from_user_id=guest.pk, into_user_id=survivor.pk))

        submission.refresh_from_db()
        assert submission.erased_at is None
        assert submission.answers["full_name"]["value"] == "Ann"

    def test_an_anonymous_answer_stays_anonymous(
        self, published_form, guest_corpus, guest, survivor
    ):
        """``submitted_by`` NULL means nobody was signed in — a merge has no
        claim on it."""
        from stapel_forms import services

        anon = services.submit(
            published_form, answers={"full_name": "Bob", "plan": "basic"}
        )

        handle_user_merged(_event(from_user_id=guest.pk, into_user_id=survivor.pk))

        anon.refresh_from_db()
        assert anon.submitted_by is None

    def test_an_already_erased_answer_is_not_resurrected(
        self, guest_corpus, guest, survivor
    ):
        """The GDPR tombstone carries ``submitted_by = None``; a merge must
        not re-attribute an answer whose owner asked to be forgotten."""
        from stapel_forms.gdpr import FormsGDPRProvider

        _own_form, submission = guest_corpus
        FormsGDPRProvider().delete(guest.pk)

        handle_user_merged(_event(from_user_id=guest.pk, into_user_id=survivor.pk))

        submission.refresh_from_db()
        assert submission.submitted_by is None
        assert submission.erased_at is not None
        assert submission.answers == {}

    def test_another_authors_form_is_untouched(self, guest_corpus, guest, survivor, user):
        theirs = Form.objects.filter(created_by_id=user.pk).first()
        assert theirs is not None

        handle_user_merged(_event(from_user_id=guest.pk, into_user_id=survivor.pk))

        theirs.refresh_from_db()
        assert theirs.created_by_id == user.pk


class TestIdempotency:
    def test_a_redelivery_changes_nothing_further(self, guest_corpus, guest, survivor):
        event = _event(from_user_id=guest.pk, into_user_id=survivor.pk)

        handle_user_merged(event)
        after_first = _snapshot()

        handle_user_merged(event)
        handle_user_merged(event)

        assert _snapshot() == after_first


class TestPoisonPayloads:
    """A raise here is a poison pill: the bus redelivers a payload no retry
    can repair. ``not-a-uuid`` is the one that bites — Django answers an
    uncoercible UUID with ``ValidationError``, which is NOT a ``ValueError``.
    """

    def test_a_malformed_from_id_acks_and_moves_nothing(
        self, guest_corpus, survivor
    ):
        before = _snapshot()
        for bad in BAD_IDS:
            handle_user_merged(_event(from_user_id=bad, into_user_id=str(survivor.pk)))
        assert _snapshot() == before

    def test_a_malformed_into_id_acks_and_moves_nothing(self, guest_corpus, guest):
        before = _snapshot()
        for bad in BAD_IDS:
            handle_user_merged(_event(from_user_id=str(guest.pk), into_user_id=bad))
        assert _snapshot() == before

    def test_a_missing_id_acks_and_moves_nothing(self, guest_corpus, guest, survivor):
        before = _snapshot()
        handle_user_merged(_event())
        handle_user_merged(_event(from_user_id=str(guest.pk)))
        handle_user_merged(_event(into_user_id=str(survivor.pk)))
        assert _snapshot() == before

    def test_a_payload_that_is_not_a_mapping_acks(self, guest_corpus):
        handle_user_merged(SimpleNamespace(payload=None, event_id="evt-empty"))

    def test_a_self_merge_is_a_no_op(self, guest_corpus, guest):
        own_form, _submission = guest_corpus
        handle_user_merged(_event(from_user_id=guest.pk, into_user_id=guest.pk))
        own_form.refresh_from_db()
        assert own_form.created_by_id == guest.pk


class TestUnknownUsers:
    def test_an_event_about_users_with_no_rows_here_does_nothing(
        self, published_form, survivor
    ):
        stranger = _user("stranger")
        before = _snapshot()

        handle_user_merged(_event(from_user_id=stranger.pk, into_user_id=survivor.pk))

        assert _snapshot() == before

    def test_a_survivor_with_no_user_row_yet_is_retried_not_dropped(
        self, guest_corpus, guest
    ):
        """The guest HAS rows and no FK can point at a user that does not
        exist here yet. Returning success would let the outbox mark the event
        delivered and strand them, so the handler raises — the comm layer's
        retry signal."""
        own_form, _submission = guest_corpus

        with pytest.raises(MergeTargetNotReady):
            handle_user_merged(
                _event(from_user_id=guest.pk, into_user_id=str(uuid.uuid4()))
            )

        own_form.refresh_from_db()
        assert own_form.created_by_id == guest.pk


class TestLifecycleCheck:
    """stapel_core.lifecycle.E001 — an app that answers ``user.deleted`` and
    not ``user.merged`` is a system-check ERROR. Registered here so the pair
    cannot be broken by a later refactor without a red test."""

    def test_the_lifecycle_pair_check_is_green(self):
        from stapel_core.comm.lifecycle_checks import check_lifecycle_pairs

        assert check_lifecycle_pairs() == []
