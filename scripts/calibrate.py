#!/usr/bin/env python3
"""Measure the detection pipeline across the fixture corpus.

Produces the evidence behind every threshold in
:mod:`scads.physical.quality` and :mod:`scads.physical.pipeline`. Thresholds in
this project are set from these measurements, not chosen by feel — and the
separation this prints is the honest statement of what the pipeline can
distinguish.

What it cannot do is establish accuracy against real counterfeits. The corpus is
synthetic tampering: a controlled proxy that shows which feature responds to
which change (``docs/EVALUATION.md`` section 1).

Usage::

    python scripts/calibrate.py                  # table + separation summary
    python scripts/calibrate.py --json out.json  # machine-readable
    python scripts/calibrate.py --sweep logo_shift
"""

import argparse
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages", "scads"))

import numpy as np  # noqa: E402

from scads.demo.fixtures import FIXTURES, FixtureSpec, build_fixture, build_reference, tamper_sweep  # noqa: E402
from scads.demo.render import to_jpeg_bytes  # noqa: E402
from scads.identity.ocr import OcrResult, OcrWord  # noqa: E402
from scads.physical.image import ImageRejected, load_image  # noqa: E402
from scads.physical.pipeline import compare_packaging  # noqa: E402
from scads.physical.quality import assess_quality  # noqa: E402

MAX_BYTES = 8 * 1024 * 1024

_REFERENCE_CACHE: Dict[str, np.ndarray] = {}


def reference_gray(serial_id: str) -> np.ndarray:
    if serial_id not in _REFERENCE_CACHE:
        pack = build_reference(serial_id)
        _REFERENCE_CACHE[serial_id] = (
            np.asarray(pack.image.convert("L"), dtype=np.float32) / 255.0
        )
    return _REFERENCE_CACHE[serial_id]


def measure(spec: FixtureSpec) -> Dict[str, Any]:
    """Run quality and packaging comparison for one fixture."""
    started = time.time()
    image, words, lines, profile = build_fixture(spec)
    data = to_jpeg_bytes(image, 92)

    row: Dict[str, Any] = {
        "name": spec.name,
        "label": spec.label,
        "bytes": len(data),
        "expectation": spec.expectation,
    }

    try:
        loaded = load_image(data, MAX_BYTES)
    except ImageRejected as exc:
        row["rejected"] = exc.code
        return row

    quality = assess_quality(loaded)
    row["quality"] = round(quality.score, 4)
    row["quality_passed"] = quality.passed
    row["quality_codes"] = [c.value for c in quality.reason_codes]
    row["quality_metrics"] = quality.metrics

    ocr = OcrResult(
        words=[OcrWord(w.text, w.x, w.y, w.width, w.height, 99.0) for w in words],
        lines=lines,
        provider="fixture",
    )
    evidence = compare_packaging(
        loaded, reference_gray(spec.serial_id), profile, ocr,
        capture_sharpness=quality.metrics["sharpness"],
    )

    row["physical"] = round(evidence.score, 4)
    row["physical_available"] = evidence.available
    row["registration"] = round(evidence.registration_confidence, 4)
    row["physical_codes"] = [c.value for c in evidence.reason_codes]
    row["features"] = evidence.diagnostics.get("feature_values", {})
    row["roi_ssim"] = (evidence.diagnostics.get("feature_diagnostics", {}) or {}).get("structure", {})
    row["latency_ms"] = int((time.time() - started) * 1000)
    return row


def print_table(rows: List[Dict[str, Any]]) -> None:
    header = "%-30s %-16s %6s %3s %6s %6s | %5s %5s %5s %5s" % (
        "fixture", "label", "Q", "Qok", "reg", "P", "txt", "lay", "str", "prn"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        if "rejected" in row:
            print("%-30s %-16s  rejected at load: %s" % (row["name"], row["label"], row["rejected"]))
            continue
        features = row.get("features", {})

        def cell(key):
            return "%5.2f" % features[key] if key in features else "    -"

        print(
            "%-30s %-16s %6.3f %3s %6.3f %6.3f | %s %s %s %s"
            % (
                row["name"], row["label"], row["quality"],
                "y" if row["quality_passed"] else "N",
                row["registration"], row["physical"],
                cell("text_content"), cell("text_layout"),
                cell("structure"), cell("print_sharpness"),
            )
        )
        codes = row["quality_codes"] + row["physical_codes"]
        if codes:
            print("%32s %s" % ("", ", ".join(codes)))


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Separation between genuine and synthetically tampered fixtures."""
    def scores(label, key):
        return [
            r[key]
            for r in rows
            if r.get("label") == label and r.get("physical_available") and key in r
        ]

    genuine = scores("genuine", "physical")
    tampered = scores("synthetic_tamper", "physical")

    summary: Dict[str, Any] = {
        "genuine_count": len(genuine),
        "tampered_count": len(tampered),
    }
    if genuine:
        summary["genuine_physical_min"] = round(min(genuine), 4)
        summary["genuine_physical_median"] = round(statistics.median(genuine), 4)
    if tampered:
        summary["tampered_physical_max"] = round(max(tampered), 4)
        summary["tampered_physical_median"] = round(statistics.median(tampered), 4)
    if genuine and tampered:
        summary["margin"] = round(min(genuine) - max(tampered), 4)

    hard = [r for r in rows if r.get("label") == "hard_capture"]
    summary["hard_captures"] = len(hard)
    summary["hard_captures_gated"] = sum(1 for r in hard if not r.get("quality_passed", False))

    # The reason codes, not the aggregate score, are what the decision engine
    # acts on — so this is the measurement that matters.
    mismatch_codes = {
        "TEXT_CONTENT_MISMATCH", "TEXT_LAYOUT_MISMATCH",
        "STRUCTURAL_MISMATCH", "PRINT_SHARPNESS_MISMATCH",
    }

    def flagged(row):
        return bool(mismatch_codes.intersection(row.get("physical_codes", [])))

    artwork = [r for r in rows if r.get("label") == "synthetic_tamper"]
    genuine_rows = [r for r in rows if r.get("label") == "genuine"]
    identity_rows = [r for r in rows if r.get("label") == "identity_tamper"]

    summary["artwork_tampers"] = len(artwork)
    summary["artwork_tampers_flagged"] = sum(1 for r in artwork if flagged(r))
    summary["genuine_false_flags"] = sum(1 for r in genuine_rows if flagged(r))
    summary["identity_tampers"] = len(identity_rows)
    summary["identity_tampers_with_genuine_packaging"] = sum(
        1 for r in identity_rows if not flagged(r)
    )

    latencies = [r["latency_ms"] for r in rows if "latency_ms" in r]
    if latencies:
        summary["latency_ms_median"] = int(statistics.median(latencies))
        summary["latency_ms_max"] = max(latencies)
    return summary


def print_summary(summary: Dict[str, Any]) -> None:
    print()
    print("Separation (physical score)")
    print("-" * 46)
    for key in (
        "genuine_count", "genuine_physical_min", "genuine_physical_median",
        "tampered_count", "tampered_physical_max", "tampered_physical_median",
        "margin", "hard_captures", "hard_captures_gated",
        "latency_ms_median", "latency_ms_max",
    ):
        if key in summary:
            print("  %-26s %s" % (key, summary[key]))

    print()
    print("Detection by reason code (what the decision engine acts on)")
    print("-" * 60)
    print("  artwork tampers flagged      %s / %s" % (
        summary.get("artwork_tampers_flagged"), summary.get("artwork_tampers")))
    print("  genuine packs false-flagged  %s / %s" % (
        summary.get("genuine_false_flags"), summary.get("genuine_count")))
    print("  identity tampers correctly")
    print("    left packaging-clean       %s / %s" % (
        summary.get("identity_tampers_with_genuine_packaging"), summary.get("identity_tampers")))
    margin = summary.get("margin")
    if margin is not None:
        print()
        if margin > 0:
            print("  Genuine and synthetic-tamper fixtures are linearly separable")
            print("  on the physical score, with a margin of %.3f." % margin)
        else:
            print("  WARNING: genuine and tampered fixtures OVERLAP by %.3f." % abs(margin))
            print("  A single physical threshold cannot separate them; the")
            print("  per-feature reason codes carry the signal instead.")


def run_sweep(kind: str) -> None:
    print("Sensitivity sweep: %s" % kind)
    print("(a sensitivity curve, not a severity scale for real counterfeits)")
    print()
    print("%8s %6s %6s | %5s %5s %5s %5s" % ("strength", "reg", "P", "txt", "lay", "str", "prn"))
    print("-" * 52)
    for spec in tamper_sweep(kind=kind):
        row = measure(spec)
        features = row.get("features", {})
        print(
            "%8.2f %6.3f %6.3f | %5s %5s %5s %5s"
            % (
                spec.tamper.strength, row.get("registration", 0.0), row.get("physical", 0.0),
                "%.2f" % features.get("text_content", 0) if "text_content" in features else "-",
                "%.2f" % features.get("text_layout", 0) if "text_layout" in features else "-",
                "%.2f" % features.get("structure", 0) if "structure" in features else "-",
                "%.2f" % features.get("print_sharpness", 0) if "print_sharpness" in features else "-",
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the full measurement set to this path")
    parser.add_argument("--sweep", help="run a tamper sensitivity sweep instead (e.g. logo_shift)")
    parser.add_argument("--only", help="measure a single fixture by name")
    args = parser.parse_args()

    if args.sweep:
        run_sweep(args.sweep)
        return 0

    specs = FIXTURES
    if args.only:
        specs = [f for f in FIXTURES if f.name == args.only]
        if not specs:
            print("no fixture named %r" % args.only, file=sys.stderr)
            return 2

    rows = [measure(spec) for spec in specs]
    print_table(rows)
    summary = summarise(rows)
    print_summary(summary)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"fixtures": rows, "summary": summary}, handle, indent=2, sort_keys=True)
        print("\nwrote %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
