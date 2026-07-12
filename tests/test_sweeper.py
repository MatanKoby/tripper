"""Sweeper tests, driven against the Firestore emulator (``spec/flows.md`` under *Sweeper*).

The sweep is a pure function over a Firestore client, so these seed job docs in whatever stale
state we want, run one pass, and assert the terminal transition. The emulator does not enforce
composite indexes, so the collection-group query runs here without the deployed index.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tripper.sweeper import sweep

VALID_INPUT: dict = {
    "place": {"city": "Porto", "country_code": "PT"},
    "stay": {"check_in": "2026-09-10", "check_out": "2026-09-12"},
}


def _now() -> datetime:
    return datetime.now(UTC)


def _trip(db, uid: str, data: dict) -> object:
    ref = db.collection("users").document(uid).collection("trips").document()
    ref.set({"input": VALID_INPUT, **data})
    return ref


def _running(db, *, uid: str = "u1", lease: datetime, attempts: int = 1, **extra) -> object:
    return _trip(
        db,
        uid,
        {"status": "running", "attempts": attempts, "leaseExpiresAt": lease, **extra},
    )


# --- re-queue vs terminal error ---------------------------------------------------------------


def test_stale_running_is_requeued_when_attempts_remain(db) -> None:
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=1, maxAttempts=3)

    report = sweep(db)

    data = ref.get().to_dict()
    assert data["status"] == "pending"
    assert data["attempts"] == 1  # sweeper does not bump attempts; the next claim will
    assert "error" not in data
    assert report.scanned == 1 and report.requeued == 1 and report.failed == 0


def test_exhausted_attempts_becomes_terminal_error(db) -> None:
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=3, maxAttempts=3)

    report = sweep(db)

    data = ref.get().to_dict()
    assert data["status"] == "error"
    assert data["error"]["kind"] == "LeaseExpired"
    assert data["lastError"] == data["error"]["message"]
    assert report.scanned == 1 and report.failed == 1 and report.requeued == 0


def test_missing_max_attempts_falls_back_to_default(db) -> None:
    # No maxAttempts on the doc: sweep falls back to DEFAULT_MAX_ATTEMPTS (3); attempts=2 requeues
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=2)

    sweep(db)

    assert ref.get().to_dict()["status"] == "pending"


# --- the guard: what the sweep must NOT touch -------------------------------------------------


def test_live_lease_running_is_left_alone(db) -> None:
    ref = _running(db, lease=_now() + timedelta(minutes=10), attempts=1, maxAttempts=3)

    report = sweep(db)

    assert ref.get().to_dict()["status"] == "running"  # a healthy job keeps running
    assert report.scanned == 0


def test_terminal_and_pending_docs_are_ignored(db) -> None:
    done = _trip(db, "u1", {"status": "done", "leaseExpiresAt": _now() - timedelta(minutes=1)})
    errored = _trip(db, "u1", {"status": "error", "leaseExpiresAt": _now() - timedelta(minutes=1)})
    pending = _trip(db, "u1", {"status": "pending", "attempts": 0})

    report = sweep(db)

    assert report.scanned == 0
    assert done.get().to_dict()["status"] == "done"
    assert errored.get().to_dict()["status"] == "error"
    assert pending.get().to_dict()["status"] == "pending"


def test_running_without_lease_is_not_reaped(db) -> None:
    # A just-claimed job may be seen before its lease is written; a missing lease is not "expired".
    ref = _trip(db, "u1", {"status": "running", "attempts": 1})

    report = sweep(db)

    assert ref.get().to_dict()["status"] == "running"
    assert report.scanned == 0


# --- breadth: collection-group scope + mixed batch --------------------------------------------


def test_sweep_spans_users_and_partitions_outcomes(db) -> None:
    stale = _now() - timedelta(minutes=2)
    live = _now() + timedelta(minutes=5)
    requeue_a = _running(db, uid="alice", lease=stale, attempts=1, maxAttempts=3)
    fail_b = _running(db, uid="bob", lease=stale, attempts=3, maxAttempts=3)
    healthy_c = _running(db, uid="carol", lease=live, attempts=1, maxAttempts=3)

    report = sweep(db)

    assert report.scanned == 2  # only the two expired ones across the collection group
    assert report.requeued == 1 and report.failed == 1
    assert requeue_a.get().to_dict()["status"] == "pending"
    assert fail_b.get().to_dict()["status"] == "error"
    assert healthy_c.get().to_dict()["status"] == "running"


def test_empty_sweep_is_a_noop(db) -> None:
    report = sweep(db)

    assert report == type(report)()  # all-zero report
