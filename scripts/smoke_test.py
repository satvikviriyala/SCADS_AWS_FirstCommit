#!/usr/bin/env python3
"""Post-deploy smoke test: drive the real HTTP API end to end.

Exercises exactly what the browser does — request an upload target, PUT the
bytes to it, ask for analysis — against a running API, and asserts the three
demo scenarios. Run after every deploy (``docs/AWS_DEPLOYMENT.md`` section 10)
and before every recording.

Uses only the standard library, so it runs against a deployed stack from any
machine with Python and no ``pip install``.

Usage::

    python scripts/smoke_test.py                                   # local dev server
    python scripts/smoke_test.py --base-url https://api.example.com --expect-aws
    python scripts/smoke_test.py --repeat 5                         # rehearsal
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FIXTURE_DIR = os.path.join(ROOT, "apps", "web", "fixtures")

# (fixture, expected decisions, codes that must be present, codes that must not be)
SCENARIOS: List[Tuple[str, Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]] = [
    (
        "genuine_clean_a",
        ("LOW_OBSERVED_RISK",),
        ("IDENTITY_VALID", "PHYSICAL_MATCH", "NO_HISTORY_CONTRADICTION"),
        ("SERIAL_REUSE", "IMPOSSIBLE_TRAVEL", "STRUCTURAL_MISMATCH"),
    ),
    (
        "tamper_logo_shift",
        ("SUSPICIOUS", "REVIEW_REQUIRED"),
        ("IDENTITY_VALID",),
        ("PHYSICAL_MATCH",),
    ),
    (
        "genuine_clone_serial",
        ("SUSPICIOUS",),
        ("IDENTITY_VALID", "PHYSICAL_MATCH", "IMPOSSIBLE_TRAVEL"),
        (),
    ),
    (
        "quality_blurred",
        ("UNABLE_TO_VERIFY",),
        (),
        ("SUSPICIOUS",),
    ),
]


class SmokeFailure(AssertionError):
    pass


def request(
    method: str,
    url: str,
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 60,
    insecure: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        raise SmokeFailure("cannot reach %s: %s" % (url, exc.reason))

    if not raw:
        return status, {}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, {"_raw": raw[:200].decode("utf-8", errors="replace")}


def check_health(base: str, expect_aws: bool, insecure: bool) -> Dict[str, Any]:
    status, body = request("GET", base + "/v1/health", insecure=insecure)
    if status != 200 or not body.get("ok"):
        raise SmokeFailure("health check failed: %s %s" % (status, body))

    print("  service        %s %s (%s)" % (body.get("service"), body.get("version"), body.get("environment")))
    print("  pipeline       %s" % body.get("pipeline_version"))
    print("  fusion policy  %s" % body.get("fusion_policy_version"))
    print("  backends       %s" % json.dumps(body.get("backends", {})))

    # No account identifiers or credentials in a public response.
    serialised = json.dumps(body)
    for leak in ("arn:aws", "AKIA", "secret", "password"):
        if leak.lower() in serialised.lower():
            raise SmokeFailure("health response appears to leak %r" % leak)

    if expect_aws:
        backends = body.get("backends", {})
        # The point of --expect-aws: prove the deployed stack is genuinely using
        # AWS and has not quietly fallen back to offline stubs.
        if backends.get("store") != "s3":
            raise SmokeFailure("expected S3 object storage, got %r" % backends.get("store"))
        if backends.get("registry") != "dynamodb":
            raise SmokeFailure("expected DynamoDB registry, got %r" % backends.get("registry"))
        if backends.get("ocr") != "textract":
            raise SmokeFailure("expected Textract OCR, got %r" % backends.get("ocr"))
    return body


def load_fixture(name: str) -> bytes:
    path = os.path.join(FIXTURE_DIR, name + ".jpg")
    if not os.path.exists(path):
        raise SmokeFailure(
            "fixture %s not found. Run: python scripts/seed_demo.py" % os.path.basename(path)
        )
    with open(path, "rb") as handle:
        return handle.read()


def load_manifest() -> Dict[str, Any]:
    path = os.path.join(FIXTURE_DIR, "manifest.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def qr_payload_for_fixture(name: str) -> Optional[str]:
    """Build the QR payload a phone would have decoded from this pack.

    Reuses the shared seed data when it is importable, so the smoke test cannot
    drift from what was seeded. When running against a remote stack from a
    machine without the package, the payload is simply omitted and the backend
    falls back to OCR.
    """
    try:
        sys.path.insert(0, os.path.join(ROOT, "packages", "scads"))
        from scads.demo import seed_data
        from scads.demo.fixtures import get_fixture
    except ImportError:
        return None

    try:
        spec = get_fixture(name)
    except KeyError:
        return None

    serial = seed_data.serial_by_id(spec.serial_id)
    batch = seed_data.batch_by_id(serial.batch_id)
    sku = seed_data.sku_by_id(serial.sku_id)
    return seed_data.build_qr_payload(
        serial_code=spec.qr_serial_override or serial.serial_code,
        batch_code=batch.batch_code,
        gtin=sku.gtin,
        expiry=batch.expiry_date,
        product=sku.product_name,
    )


def run_scan(
    base: str, fixture: str, location: str, insecure: bool
) -> Tuple[Dict[str, Any], float]:
    data = load_fixture(fixture)
    started = time.time()

    status, created = request(
        "POST", base + "/v1/uploads",
        body=json.dumps({"content_type": "image/jpeg", "content_length": len(data)}).encode(),
        headers={"Content-Type": "application/json"},
        insecure=insecure,
    )
    if status != 200 or "upload" not in created:
        raise SmokeFailure("upload creation failed: %s %s" % (status, created))

    upload = created["upload"]
    put = urllib.request.Request(upload["url"], data=data, method=upload.get("method", "PUT"))
    for key, value in (upload.get("headers") or {}).items():
        put.add_header(key, value)
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(put, timeout=120, context=context) as response:
            if response.status not in (200, 204):
                raise SmokeFailure("upload PUT returned %s" % response.status)
    except urllib.error.HTTPError as exc:
        raise SmokeFailure("upload PUT failed: %s %s" % (exc.code, exc.read()[:200]))

    body: Dict[str, Any] = {"location": {"mode": "DEMO", "label": location}}
    payload = qr_payload_for_fixture(fixture)
    if payload:
        body["qr_payload"] = payload

    status, result = request(
        "POST", base + "/v1/scans/%s/analyze" % created["scan_id"],
        body=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        insecure=insecure,
    )
    if status != 200:
        raise SmokeFailure("analyze failed: %s %s" % (status, result))

    return result, time.time() - started


def check_scenario(base: str, scenario, insecure: bool) -> float:
    fixture, expected, required, forbidden = scenario
    result, elapsed = run_scan(base, fixture, "BENGALURU_DEMO", insecure)

    decision = result.get("decision")
    codes = set(result.get("reason_codes") or [])

    if decision not in expected:
        raise SmokeFailure(
            "%s: expected one of %s, got %s (codes: %s)"
            % (fixture, expected, decision, sorted(codes))
        )
    missing = [c for c in required if c not in codes]
    if missing:
        raise SmokeFailure("%s: missing reason codes %s (got %s)" % (fixture, missing, sorted(codes)))
    present = [c for c in forbidden if c in codes]
    if present:
        raise SmokeFailure("%s: unexpected reason codes %s" % (fixture, present))

    if not result.get("limitation"):
        raise SmokeFailure("%s: result is missing the limitation statement" % fixture)

    dimensions = result.get("explanation", {}).get("dimensions", [])
    if [d.get("key") for d in dimensions] != ["identity", "physical", "history"]:
        raise SmokeFailure("%s: result must show all three dimensions" % fixture)

    print(
        "  %-24s %-18s %5.2fs  %s"
        % (fixture, decision, elapsed, ", ".join(sorted(codes)) or "-")
    )

    # Retrieval must agree with what analysis returned.
    status, fetched = request(
        "GET", base + "/v1/scans/%s" % result["scan_id"], insecure=insecure
    )
    if status != 200 or fetched.get("decision") != decision:
        raise SmokeFailure("%s: stored result disagrees with the response" % fixture)

    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SCADS_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--expect-aws", action="store_true", help="require real AWS backends")
    parser.add_argument("--repeat", type=int, default=1, help="rehearsal runs")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print("SCADS smoke test against %s" % base)
    print()

    failures: List[str] = []
    latencies: List[float] = []

    try:
        check_health(base, args.expect_aws, args.insecure)
    except SmokeFailure as exc:
        print("FAIL health: %s" % exc, file=sys.stderr)
        return 1

    for run in range(1, args.repeat + 1):
        if args.repeat > 1:
            print("\nrun %d of %d" % (run, args.repeat))
        print()
        for scenario in SCENARIOS:
            try:
                latencies.append(check_scenario(base, scenario, args.insecure))
            except SmokeFailure as exc:
                print("  FAIL %s" % exc, file=sys.stderr)
                failures.append(str(exc))

    print()
    if latencies:
        ordered = sorted(latencies)
        print("latency  p50 %.2fs  max %.2fs  n=%d" % (
            ordered[len(ordered) // 2], ordered[-1], len(ordered)
        ))

    total = len(SCENARIOS) * args.repeat
    if failures:
        print("\n%d of %d checks FAILED" % (len(failures), total), file=sys.stderr)
        return 1
    print("\nall %d checks passed" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
