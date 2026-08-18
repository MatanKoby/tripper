"""Sweeper tests, driven against the Firestore emulator (``spec/flows.md`` under *Sweeper*).

The sweep is a pure function over a Firestore client, so these seed ``domains/{domain}`` docs in
whatever stale state we want, run one pass, and assert the terminal transition. The emulator does
not enforce composite indexes, so the collection-group query runs here without the deployed index.
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


def _domain(db, uid: str, data: dict) -> object:
    """Seed a ``.../trips/{tripId}/domains/accommodations`` doc (the sweep's collection group)."""
    trip = db.collection("users").document(uid).collection("trips").document()
    trip.set({"input": VALID_INPUT, "status": "active"})
    domain_ref = trip.collection("domains").document("accommodations")
    domain_ref.set({"domain": "accommodations", **data})
    return domain_ref


def _running(db, *, uid: str = "u1", lease: datetime, attempts: int = 1, **extra) -> object:
    return _domain(
        db,
        uid,
        {"agentStatus": "running", "attempts": attempts, "leaseExpiresAt": lease, **extra},
    )


# --- terminal reap: a stale run always errors, it is never re-queued ---------------------------


def test_stale_running_becomes_terminal_error(db) -> None:
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=1, maxAttempts=3)

    report = sweep(db)

    data = ref.get().to_dict()
    # Attempts remaining is irrelevant. Nothing can re-fire an onCreate trigger, so a re-queue to
    # "pending" would park the doc forever (``spec/flows.md`` under *Sweeper*).
    assert data["agentStatus"] == "error"
    assert data["error"]["kind"] == "LeaseExpired"
    assert data["lastError"] == data["error"]["message"]
    assert data["attempts"] == 1  # the sweeper never bumps attempts
    assert report.scanned == 1 and report.failed == 1 and report.skipped == 0


def test_exhausted_attempts_also_becomes_terminal_error(db) -> None:
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=3, maxAttempts=3)

    report = sweep(db)

    assert ref.get().to_dict()["agentStatus"] == "error"
    assert report.scanned == 1 and report.failed == 1


def test_missing_max_attempts_still_errors(db) -> None:
    # maxAttempts no longer gates the reap, so a doc without it is reaped like any other.
    ref = _running(db, lease=_now() - timedelta(minutes=1), attempts=2)

    sweep(db)

    assert ref.get().to_dict()["agentStatus"] == "error"


# --- the guard: what the sweep must NOT touch -------------------------------------------------


def test_live_lease_running_is_left_alone(db) -> None:
    ref = _running(db, lease=_now() + timedelta(minutes=10), attempts=1, maxAttempts=3)

    report = sweep(db)

    assert ref.get().to_dict()["agentStatus"] == "running"  # a healthy run keeps running
    assert report.scanned == 0


def test_terminal_and_pending_docs_are_ignored(db) -> None:
    idle = _domain(
        db, "u1", {"agentStatus": "idle", "leaseExpiresAt": _now() - timedelta(minutes=1)}
    )
    errored = _domain(
        db, "u1", {"agentStatus": "error", "leaseExpiresAt": _now() - timedelta(minutes=1)}
    )
    pending = _domain(db, "u1", {"agentStatus": "pending"})

    report = sweep(db)

    assert report.scanned == 0
    assert idle.get().to_dict()["agentStatus"] == "idle"
    assert errored.get().to_dict()["agentStatus"] == "error"
    assert pending.get().to_dict()["agentStatus"] == "pending"


def test_running_without_lease_is_not_reaped(db) -> None:
    # A just-claimed run may be seen before its lease is written; a missing lease is not "expired".
    ref = _domain(db, "u1", {"agentStatus": "running", "attempts": 1})

    report = sweep(db)

    assert ref.get().to_dict()["agentStatus"] == "running"
    assert report.scanned == 0


# --- breadth: collection-group scope + mixed batch --------------------------------------------


def test_sweep_spans_users_and_partitions_outcomes(db) -> None:
    stale = _now() - timedelta(minutes=2)
    live = _now() + timedelta(minutes=5)
    fail_a = _running(db, uid="alice", lease=stale, attempts=1, maxAttempts=3)
    fail_b = _running(db, uid="bob", lease=stale, attempts=3, maxAttempts=3)
    healthy_c = _running(db, uid="carol", lease=live, attempts=1, maxAttempts=3)

    report = sweep(db)

    assert report.scanned == 2  # only the two expired ones across the collection group
    assert report.failed == 2 and report.skipped == 0
    assert fail_a.get().to_dict()["agentStatus"] == "error"
    assert fail_b.get().to_dict()["agentStatus"] == "error"
    assert healthy_c.get().to_dict()["agentStatus"] == "running"


def test_empty_sweep_is_a_noop(db) -> None:
    report = sweep(db)

    assert report == type(report)()  # all-zero report


# --- refinement docs join the sweep (Batch 13) ------------------------------------------------


def _domain_with_refinement(
    db, *, uid: str = "u1", domain_status: str, refine: dict
) -> tuple[object, object]:
    """Seed a domain doc + a ``refinements/{id}`` under it; return (domain_ref, refinement_ref)."""
    trip = db.collection("users").document(uid).collection("trips").document()
    trip.set({"input": VALID_INPUT, "status": "active"})
    domain_ref = trip.collection("domains").document("accommodations")
    domain_ref.set(
        {
            "domain": "accommodations",
            "agentStatus": domain_status,
            "leaseExpiresAt": _now() + timedelta(minutes=10),
        }
    )
    refinement_ref = domain_ref.collection("refinements").document("rf1")
    refinement_ref.set(refine)
    return domain_ref, refinement_ref


def test_stale_refinement_with_attempts_left_still_errors(db) -> None:
    domain_ref, refinement_ref = _domain_with_refinement(
        db,
        domain_status="running",
        refine={"round": 2, "status": "running", "attempts": 1, "maxAttempts": 3,
                "leaseExpiresAt": _now() - timedelta(minutes=1)},
    )

    report = sweep(db)

    assert refinement_ref.get().to_dict()["status"] == "error"
    assert report.scanned == 1 and report.failed == 1
    # Every terminal refine resets the busy domain, whatever the attempt count.
    assert domain_ref.get().to_dict()["agentStatus"] == "idle"


def test_exhausted_refinement_errors_and_resets_the_domain(db) -> None:
    domain_ref, refinement_ref = _domain_with_refinement(
        db,
        domain_status="running",  # the refine had set the domain busy
        refine={"round": 2, "status": "running", "attempts": 3, "maxAttempts": 3,
                "leaseExpiresAt": _now() - timedelta(minutes=1)},
    )

    report = sweep(db)

    refinement = refinement_ref.get().to_dict()
    assert refinement["status"] == "error"
    assert refinement["error"]["kind"] == "LeaseExpired"
    assert report.failed == 1
    # A dead refine must not strand the domain as perpetually "thinking".
    assert domain_ref.get().to_dict()["agentStatus"] == "idle"


def test_terminal_refinement_leaves_an_idle_domain_untouched(db) -> None:
    # If the domain is not running (e.g. already settled), the terminal refine does not touch it.
    domain_ref, refinement_ref = _domain_with_refinement(
        db,
        domain_status="idle",
        refine={"round": 2, "status": "running", "attempts": 3, "maxAttempts": 3,
                "leaseExpiresAt": _now() - timedelta(minutes=1)},
    )

    sweep(db)

    assert refinement_ref.get().to_dict()["status"] == "error"
    assert domain_ref.get().to_dict()["agentStatus"] == "idle"


def test_live_lease_refinement_is_left_alone(db) -> None:
    _domain_ref, refinement_ref = _domain_with_refinement(
        db,
        domain_status="running",
        refine={"round": 2, "status": "running", "attempts": 1, "maxAttempts": 3,
                "leaseExpiresAt": _now() + timedelta(minutes=10)},
    )

    report = sweep(db)

    assert refinement_ref.get().to_dict()["status"] == "running"
    assert report.scanned == 0


def test_one_pass_reaps_both_domains_and_refinements(db) -> None:
    stale = _now() - timedelta(minutes=1)
    stuck_search = _running(db, uid="alice", lease=stale, attempts=1, maxAttempts=3)
    _domain_ref, stuck_refine = _domain_with_refinement(
        db,
        uid="bob",
        domain_status="running",
        refine={"round": 2, "status": "running", "attempts": 1, "maxAttempts": 3,
                "leaseExpiresAt": stale},
    )

    report = sweep(db)

    assert report.scanned == 2 and report.failed == 2  # one search + one refine, both reaped
    assert stuck_search.get().to_dict()["agentStatus"] == "error"
    assert stuck_refine.get().to_dict()["status"] == "error"
