#!/usr/bin/env python3
"""Seed the SCADS demo: registry, enrolled references and scan-history fixtures.

This is the admin plane. Reference enrollment and registry writes are the most
security-sensitive operations in the system — whoever controls them controls
what "genuine" means — so they live in a script run with developer credentials
rather than behind any public endpoint (``docs/THREAT_MODEL.md`` section 5).

Runs against either backend. The offline backend is the default so the demo can
be exercised with no AWS account; pass ``--aws`` to seed a deployed stack.

Usage::

    python scripts/seed_demo.py                      # offline, into .scads-local
    python scripts/seed_demo.py --aws                # deployed stack, from the environment
    python scripts/seed_demo.py --reset              # clear seeded history first
    python scripts/seed_demo.py --scenarios          # print the expected outcomes
"""

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages", "scads"))

import numpy as np  # noqa: E402

from scads.adapters.factory import build_adapters  # noqa: E402
from scads.config import load_settings, local_settings  # noqa: E402
from scads.contracts.enums import ActorType, Decision, LocationMode, ScanStatus  # noqa: E402
from scads.contracts.records import ScanEvent  # noqa: E402
from scads.demo import seed_data  # noqa: E402
from scads.demo.fixtures import FIXTURES, build_fixture, build_reference  # noqa: E402
from scads.demo.render import to_jpeg_bytes, to_png_bytes  # noqa: E402
from scads.history.locations import get_location  # noqa: E402
from scads.util.clock import to_iso  # noqa: E402

# The prior observation that makes demo scenario C work: the same serial,
# recorded in a distant city, recently enough that one physical pack could not
# have travelled between them.
CLONE_PRIOR_LOCATION = "DELHI_DEMO"
CLONE_PRIOR_MINUTES_AGO = 58
CLONE_SERIAL_ID = "ser_demo_a_clone"


def seed_registry(adapters) -> dict:
    counts = seed_data.seed_registry(adapters.registry)
    print("  registry: %s" % json.dumps(counts))
    return counts


def seed_references(adapters) -> int:
    """Enroll reference profiles and upload the reference artwork.

    The artwork is rendered here rather than shipped as a binary, so the
    enrolled reference and the fixture generator can never drift apart.
    """
    profiles = seed_data.reference_profiles()
    for profile in profiles:
        adapters.references.put_reference_profile(profile)

        serial = next(s for s in seed_data.SERIALS if s.sku_id == profile.sku_id)
        pack = build_reference(serial.serial_id)
        adapters.store.put_bytes(
            "references", profile.image_s3_key, to_png_bytes(pack.image), "image/png"
        )
        print(
            "  reference: %s -> %s (%d anchors, %d static regions)"
            % (
                profile.reference_profile_id,
                profile.image_s3_key,
                len(profile.ocr_anchors),
                len(profile.static_rois),
            )
        )
    return len(profiles)


def seed_clone_history(adapters, clock_now: _dt.datetime) -> str:
    """Seed the prior scan that demo scenario C contradicts.

    A real recorded observation, written through the normal event store, not a
    special case in the rules. The history evaluator has no knowledge that this
    event is a fixture — it is simply a prior scan of that serial.
    """
    location = get_location(CLONE_PRIOR_LOCATION)
    event_time = clock_now - _dt.timedelta(minutes=CLONE_PRIOR_MINUTES_AGO)
    scan_id = "scn_demoseedclone001"

    serial = seed_data.serial_by_id(CLONE_SERIAL_ID)
    event = ScanEvent(
        scan_id=scan_id,
        event_time=to_iso(event_time),
        status=ScanStatus.COMPLETED,
        actor_type=ActorType.CONSUMER,
        serial_id=serial.serial_id,
        batch_id=serial.batch_id,
        sku_id=serial.sku_id,
        claimed_serial=serial.serial_code,
        location_mode=LocationMode.DEMO,
        location_label=location.key,
        location_lat=location.lat,
        location_lon=location.lon,
        decision=Decision.LOW_OBSERVED_RISK,
        presentation_score=0.86,
        identity_score=0.96,
        physical_score=0.87,
        history_score=0.88,
        scan_quality=0.95,
        reason_codes=["IDENTITY_VALID", "PHYSICAL_MATCH", "NO_HISTORY_CONTRADICTION"],
        pipeline_version="cv_0.1.0",
        fusion_policy_version="fusion_0.1.0",
        reference_version=seed_data.REFERENCE_VERSION,
        demo_tag=seed_data.DEMO_TAG,
        evidence={"seeded": True, "purpose": "prior observation for the cloned-serial scenario"},
    )
    adapters.events.put_event(event)
    print(
        "  history: %s seen at %s, %d minutes before now"
        % (serial.serial_code, location.display_name, CLONE_PRIOR_MINUTES_AGO)
    )
    return scan_id


def seed_fixture_images(adapters, settings, out_dir: str) -> int:
    """Write the fixture captures and their OCR ground truth.

    The OCR sidecars are content-addressed by image digest, so the offline
    provider can only answer for images it has ground truth for. That is what
    keeps a fixture-backed run distinguishable from a Textract-backed one.
    """
    from scads.adapters.fixture_ocr import FixtureOcrProvider

    os.makedirs(out_dir, exist_ok=True)
    sidecar_dir = os.path.join(settings.local_root, "ocr")
    provider = FixtureOcrProvider(sidecar_dir)

    manifest = []
    for spec in FIXTURES:
        image, words, lines, profile = build_fixture(spec)
        data = to_jpeg_bytes(image, 92)

        path = os.path.join(out_dir, spec.name + ".jpg")
        with open(path, "wb") as handle:
            handle.write(data)

        from scads.demo.render import ocr_payload

        digest = provider.write_sidecar(data, ocr_payload(words, lines))
        manifest.append(
            {
                "name": spec.name,
                "label": spec.label,
                "serial_id": spec.serial_id,
                "file": os.path.basename(path),
                "sha256": digest,
                "bytes": len(data),
                "expectation": spec.expectation,
                "notes": spec.notes,
            }
        )

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "note": (
                    "Synthetic fixtures. Tampered entries are labelled synthetic_tamper: "
                    "a controlled proxy for measuring feature sensitivity, not counterfeit "
                    "samples. See docs/EVALUATION.md section 1."
                ),
                "fixtures": manifest,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
    print("  fixtures: %d images + OCR ground truth -> %s" % (len(manifest), out_dir))
    return len(manifest)


def print_scenarios() -> None:
    print()
    print("Demo scenarios")
    print("=" * 78)
    rows = [
        (
            "A  clean pack",
            "genuine_clean_a.jpg",
            "BENGALURU_DEMO",
            "LOW_OBSERVED_RISK",
            "identity valid, packaging matches, history clean",
        ),
        (
            "B  visual tamper",
            "tamper_logo_shift.jpg",
            "BENGALURU_DEMO",
            "SUSPICIOUS / REVIEW_REQUIRED",
            "same valid serial, artwork region does not match",
        ),
        (
            "C  cloned serial",
            "genuine_clone_serial.jpg",
            "BENGALURU_DEMO",
            "SUSPICIOUS",
            "flawless pack, valid serial, seen in Delhi 58 min ago",
        ),
    ]
    for name, fixture, location, expected, why in rows:
        print("  %-18s %s" % (name, fixture))
        print("  %-18s location: %s" % ("", location))
        print("  %-18s expect:   %s" % ("", expected))
        print("  %-18s because:  %s" % ("", why))
        print()
    print("Scenario C is the point of the product: identity and packaging both pass.")
    print("Only the scan history objects, and no database lookup could have caught it.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aws", action="store_true", help="seed the deployed stack")
    parser.add_argument("--reset", action="store_true", help="clear seeded demo history first")
    parser.add_argument("--no-fixtures", action="store_true", help="skip writing fixture images")
    parser.add_argument("--scenarios", action="store_true", help="print scenarios and exit")
    parser.add_argument("--local-root", default=".scads-local", help="offline state directory")
    parser.add_argument("--fixture-dir", default="tests/fixtures/generated")
    args = parser.parse_args()

    if args.scenarios:
        print_scenarios()
        return 0

    if args.aws:
        settings = load_settings()
        if not settings.uses_aws_registry or not settings.uses_aws_storage:
            print(
                "ERROR: --aws requires STORE_BACKEND=s3 and REPO_BACKEND=dynamodb.\n"
                "       Current: %s" % json.dumps(settings.describe_backends()),
                file=sys.stderr,
            )
            return 2
    else:
        settings = local_settings(args.local_root)

    adapters = build_adapters(settings)
    print("Seeding SCADS demo data")
    print("  backends: %s" % json.dumps(adapters.describe()))

    if args.reset:
        removed = adapters.events.delete_events_by_demo_tag(seed_data.DEMO_TAG)
        print("  reset: removed %d seeded events" % removed)

    seed_registry(adapters)
    seed_references(adapters)
    seed_clone_history(adapters, _dt.datetime.now(_dt.timezone.utc))

    if not args.no_fixtures:
        seed_fixture_images(adapters, settings, args.fixture_dir)

    print("\nSeed complete.")
    print_scenarios()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
