#!/usr/bin/env python3
"""Scan the repository for credentials before publishing it.

Run before every commit that goes public and before submission
(``phases/PHASE_7_SUBMISSION.md``). Deliberately noisy patterns with an explicit
allowlist: a false positive costs a glance, a missed AWS key costs an account.

Usage::

    python scripts/secret_scan.py
    python scripts/secret_scan.py --staged    # only files staged for commit
"""

import argparse
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Key-to-value separator, tolerating a quoted key: matches both
#   password = "x"        (bare)
#   "password": "x"       (JSON / dict literal)
ASSIGN = r"[\"']?\s*[:=]\s*"

PATTERNS: List[Tuple[str, str]] = [
    ("AWS access key id", r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    # ASSIGN matches the separator between a key and its value, allowing the
    # key to be quoted. Without the optional closing quote these patterns miss
    # the JSON and dict-literal forms entirely -- which is how a planted
    # "aws_secret_access_key": "..." slipped past an earlier version of this
    # scanner while the same value assigned bare was caught.
    ("AWS secret access key", r"(?i)aws_?secret_?access_?key" + ASSIGN + r"['\"][^'\"]{20,}['\"]"),
    ("AWS session token", r"(?i)aws_?session_?token" + ASSIGN + r"['\"][^'\"]{20,}['\"]"),
    ("private key block", r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Anthropic API key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ("generic API key assignment", r"(?i)\b(?:api[_-]?key|apikey)" + ASSIGN + r"['\"][A-Za-z0-9_\-]{16,}['\"]"),
    ("password assignment", r"(?i)\bpassword" + ASSIGN + r"['\"][^'\"]{6,}['\"]"),
    ("secret assignment", r"(?i)\b(?:client_?secret|app_?secret)" + ASSIGN + r"['\"][^'\"]{12,}['\"]"),
    ("bearer token", r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{24,}"),
    ("connection string with credentials", r"(?i)\b(?:postgres|mysql|mongodb)(?:\+\w+)?://[^:\s]+:[^@\s]+@"),
]

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".build",
    ".pytest_cache", ".scads-local", "dist", "build", ".mypy_cache",
}
SKIP_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".pdf",
    ".zip", ".gz", ".so", ".dylib", ".woff", ".woff2", ".ttf",
)

# Lines that legitimately contain a pattern. Each needs a reason.
ALLOWLIST: Dict[str, str] = {
    "ADMIN_API_TOKEN=": "an empty placeholder in .env.example",
    "AdminApiToken": "a NoEcho CloudFormation parameter, supplied at deploy time",
    "admin_api_token": "a settings field name, not a value",
    "X-Admin-Token": "an HTTP header name",
    "x-admin-token": "an HTTP header name",
    "admin-token": "a command-line flag name",
    "local-dev-token": "an offline-only development token; grants nothing",
    "AKIA[0-9A-Z]{16}": "the detection pattern itself, in a test or this scanner",
    "ASIA[0-9A-Z]{16}": "the detection pattern itself",
}


def is_allowlisted(line: str) -> bool:
    return any(marker in line for marker in ALLOWLIST)


def candidate_files(staged: bool) -> List[str]:
    if staged:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=ROOT, capture_output=True, text=True,
        )
        names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
        return [os.path.join(ROOT, n) for n in names if os.path.isfile(os.path.join(ROOT, n))]

    files: List[str] = []
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.endswith(SKIP_SUFFIXES):
                continue
            files.append(os.path.join(root, name))
    return files


def scan(paths: List[str]) -> List[Tuple[str, int, str, str]]:
    findings: List[Tuple[str, int, str, str]] = []
    compiled = [(label, re.compile(pattern)) for label, pattern in PATTERNS]

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                lines = handle.readlines()
        except OSError:
            continue

        for number, line in enumerate(lines, start=1):
            if len(line) > 4000:
                continue
            if is_allowlisted(line):
                continue
            for label, pattern in compiled:
                if pattern.search(line):
                    findings.append(
                        (os.path.relpath(path, ROOT), number, label, line.strip()[:120])
                    )
    return findings


def check_env_not_committed() -> List[str]:
    """A committed .env is the most common way a key leaks."""
    problems = []
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    )
    tracked = set(result.stdout.split())
    for name in (".env", ".env.local", ".env.production"):
        if name in tracked:
            problems.append("%s is tracked by git and must not be" % name)
    if ".env.example" not in tracked:
        problems.append(".env.example is missing; contributors need a template")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="scan only staged files")
    args = parser.parse_args()

    paths = candidate_files(args.staged)
    print("Secret scan: %d files" % len(paths))

    problems = check_env_not_committed()
    findings = scan(paths)

    for problem in problems:
        print("  FAIL  %s" % problem, file=sys.stderr)

    for path, number, label, excerpt in findings:
        print("  FAIL  %s:%d  %s\n        %s" % (path, number, label, excerpt), file=sys.stderr)

    if problems or findings:
        print(
            "\n%d issue(s). If one is a false positive, add a reason to ALLOWLIST "
            "in this script rather than deleting the check." % (len(problems) + len(findings)),
            file=sys.stderr,
        )
        return 1

    print("  clean: no credentials found, no .env tracked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
