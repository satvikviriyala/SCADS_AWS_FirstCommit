"""History evidence assembly.

Turns the rule findings into a :class:`HistoryEvidence` value, including the
scoring and — most importantly — the distinction between *no contradiction
found* and *could not check*. Those must never collapse into the same output:
one is evidence, the other is the absence of it
(``docs/AWS_DEPLOYMENT.md`` section 11).
"""

import datetime as _dt
from typing import List, Optional

from ..adapters.base import DependencyUnavailable, ScanEventStore
from ..contracts.enums import ActorType, Decision, EvidenceState, LocationMode
from ..contracts.models import (
    HistoryEvidence,
    HistoryFinding,
    PriorScanSummary,
    ScanLocation,
)
from ..contracts.reason_codes import ReasonCode, Severity, severity_of
from ..contracts.records import ScanEvent, SerialRecord
from .rules import HistoryContext, evaluate_rules

# Score floors per finding severity. The history score is intentionally blunt:
# it is a summary for the result card, while the hard caps in the fusion policy
# are what actually make a contradiction decisive.
SCORE_CLEAN_WITH_HISTORY = 0.95
SCORE_CLEAN_FIRST_SCAN = 0.88
SCORE_WARNING = 0.45
SCORE_SEVERE = 0.10

MAX_PRIOR_EVENTS = 25
MAX_TIMELINE_ENTRIES = 5


def evaluate_history(
    events: ScanEventStore,
    serial_id: Optional[str],
    location: ScanLocation,
    now: _dt.datetime,
    serial_record: Optional[SerialRecord] = None,
    current_scan_id: Optional[str] = None,
) -> HistoryEvidence:
    """Evaluate scan history for one unit.

    Returns ``available=False`` when there is no unit identity to look up or the
    event store could not be queried. A batch-level scan has no unit history by
    definition, and saying so is more honest than reporting a clean history for
    a unit that was never identified.
    """
    if not serial_id:
        return HistoryEvidence(
            score=0.0,
            state=EvidenceState.UNKNOWN,
            available=False,
            reason_codes=[ReasonCode.HISTORY_UNAVAILABLE],
            details={
                "reason": "no unit serial was resolved, so there is no unit history to check"
            },
        )

    try:
        prior = events.query_by_serial(serial_id, limit=MAX_PRIOR_EVENTS)
    except DependencyUnavailable as exc:
        return HistoryEvidence(
            score=0.0,
            state=EvidenceState.UNKNOWN,
            available=False,
            reason_codes=[ReasonCode.HISTORY_UNAVAILABLE],
            details={"reason": "scan-history lookup failed", "dependency": exc.dependency},
        )

    # The event for the scan being analysed is already persisted (status
    # CREATED/UPLOADED) before analysis runs, so it must be excluded or every
    # scan would detect itself as a duplicate of itself.
    prior = [
        event
        for event in prior
        if event.scan_id != current_scan_id and _is_countable(event)
    ]

    ctx = HistoryContext(
        serial_id=serial_id,
        now=now,
        location=location,
        prior_events=prior,
        serial_record=serial_record,
    )
    findings = evaluate_rules(ctx)
    codes = [f.code for f in findings]

    if not findings:
        codes = [ReasonCode.NO_HISTORY_CONTRADICTION]
        score = SCORE_CLEAN_WITH_HISTORY if prior else SCORE_CLEAN_FIRST_SCAN
        state = EvidenceState.OK
    else:
        worst = max(severity_of(c) for c in codes)
        if worst >= Severity.SEVERE:
            score = SCORE_SEVERE
            state = EvidenceState.FAIL
        else:
            score = SCORE_WARNING
            state = EvidenceState.WARN

    return HistoryEvidence(
        score=score,
        state=state,
        available=True,
        findings=findings,
        reason_codes=codes,
        prior_scans=[_summarise(event) for event in prior[:MAX_TIMELINE_ENTRIES]],
        details={
            "prior_event_count": len(prior),
            "first_scan_of_unit": not prior,
            "current_location": location.to_public(),
        },
    )


def _is_countable(event: ScanEvent) -> bool:
    """Whether a stored event counts as an observation of the unit.

    A scan that failed or never completed is not evidence that the pack was
    somewhere. Counting abandoned uploads would let a flaky network manufacture
    a duplicate-serial finding against a genuine pack.
    """
    from ..contracts.enums import ScanStatus

    if event.status in (ScanStatus.FAILED, ScanStatus.CREATED):
        return False
    if event.decision is Decision.UNABLE_TO_VERIFY:
        return False
    return True


def _summarise(event: ScanEvent) -> PriorScanSummary:
    return PriorScanSummary(
        scan_id=event.scan_id,
        event_time=event.event_time,
        location_label=event.location_label,
        location_mode=event.location_mode,
        actor_type=event.actor_type,
        decision=event.decision,
    )
