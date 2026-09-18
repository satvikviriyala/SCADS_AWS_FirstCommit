#!/usr/bin/env python3
"""Build the Lambda deployment package.

No Docker and no SAM CLI. ``pip`` downloads manylinux x86_64 wheels for the
target Python directly, which needs neither emulation nor a container build —
and the whole reason this works is that the detection pipeline depends only on
numpy and Pillow. With OpenCV it would be 223 MB against a 250 MB hard limit;
without, it is about 80 MB. See MEMORY.md, "Environment reality".

Usage::

    python scripts/package_lambda.py                 # build .build/api
    python scripts/package_lambda.py --zip           # also produce the zip
    python scripts/package_lambda.py --check         # verify, do not rebuild
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from typing import List, Tuple

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUILD_DIR = os.path.join(ROOT, ".build", "api")
ZIP_PATH = os.path.join(ROOT, ".build", "scads-api.zip")

# Must match Globals.Function in infra/template.yaml.
TARGET_PYTHON = "3.12"
TARGET_PLATFORM = "manylinux2014_x86_64"

# Lambda's hard limit on the unzipped deployment package.
LAMBDA_UNZIPPED_LIMIT = 250 * 1024 * 1024
# Warn well before the limit so a dependency bump does not fail a deploy.
SIZE_WARNING = 200 * 1024 * 1024

# Removed after install. None of it is reachable at runtime, and every megabyte
# here is unzipped-size headroom.
PRUNE_DIRS = ("tests", "__pycache__", "test", "testing")
PRUNE_SUFFIXES = (".pyc", ".pyo", ".c", ".h", ".pyx", ".pxd")
PRUNE_GLOBS = ("*.dist-info", "*.egg-info")


def run(command: List[str]) -> None:
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("command failed: " + " ".join(command))


def directory_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def human(size: int) -> str:
    return "%.1f MB" % (size / (1024.0 * 1024.0))


def clean() -> None:
    if os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR, exist_ok=True)


def copy_source() -> None:
    """Copy the handler and the scads package into the build directory."""
    shutil.copy2(os.path.join(ROOT, "apps", "api", "handler.py"), BUILD_DIR)

    source = os.path.join(ROOT, "packages", "scads", "scads")
    target = os.path.join(BUILD_DIR, "scads")
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "demo"),
    )
    # scads.demo holds the pack renderer and the fixture corpus. It is used by
    # seeding and evaluation, never by the request path, and it pulls in
    # rendering code the API has no reason to carry.
    print("  source: handler.py + scads (excluding scads.demo)")


def install_dependencies() -> None:
    requirements = os.path.join(ROOT, "apps", "api", "requirements.txt")
    print("  deps  : installing %s wheels for Python %s" % (TARGET_PLATFORM, TARGET_PYTHON))
    run([
        sys.executable, "-m", "pip", "install",
        "--quiet", "--disable-pip-version-check",
        "--platform", TARGET_PLATFORM,
        "--python-version", TARGET_PYTHON,
        "--implementation", "cp",
        "--only-binary=:all:",
        "--target", BUILD_DIR,
        "-r", requirements,
    ])


def prune() -> Tuple[int, int]:
    """Strip everything unreachable at runtime. Returns (before, after)."""
    import fnmatch

    before = directory_size(BUILD_DIR)

    for root, dirs, files in os.walk(BUILD_DIR, topdown=True):
        for name in list(dirs):
            if name in PRUNE_DIRS or any(fnmatch.fnmatch(name, g) for g in PRUNE_GLOBS):
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                dirs.remove(name)
        for name in files:
            if name.endswith(PRUNE_SUFFIXES):
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass

    # numpy's f2py is a command-line Fortran wrapper generator. Nothing in the
    # request path touches it.
    f2py = os.path.join(BUILD_DIR, "numpy", "f2py")
    if os.path.isdir(f2py):
        shutil.rmtree(f2py, ignore_errors=True)

    return before, directory_size(BUILD_DIR)


def verify() -> None:
    """Check the package has what Lambda will look for."""
    problems = []

    handler = os.path.join(BUILD_DIR, "handler.py")
    if not os.path.isfile(handler):
        problems.append("handler.py is missing")

    for module in ("scads/api/router.py", "scads/decision/fusion.py", "scads/physical/pipeline.py"):
        if not os.path.isfile(os.path.join(BUILD_DIR, module)):
            problems.append(module + " is missing")

    for package in ("numpy", "PIL"):
        if not os.path.isdir(os.path.join(BUILD_DIR, package)):
            problems.append(package + " is missing")

    # The build must not carry a macOS wheel: the local interpreter is macOS,
    # and a silently-wrong platform would fail only at cold start in AWS.
    for root, _dirs, files in os.walk(BUILD_DIR):
        for name in files:
            if name.endswith(".dylib") or ".cpython-39-darwin" in name:
                problems.append("macOS binary found: " + os.path.join(root, name)[len(BUILD_DIR):])
                break

    linux_objects = 0
    for root, _dirs, files in os.walk(BUILD_DIR):
        linux_objects += sum(1 for f in files if f.endswith(".so"))
    if linux_objects == 0:
        problems.append("no Linux shared objects found; wrong platform wheels?")

    problems.extend(_check_excluded_imports())

    size = directory_size(BUILD_DIR)
    if size > LAMBDA_UNZIPPED_LIMIT:
        problems.append("unzipped size %s exceeds the Lambda limit" % human(size))

    if problems:
        for problem in problems:
            print("  FAIL  " + problem, file=sys.stderr)
        raise SystemExit(1)

    print("  verify: handler, scads, numpy and PIL present; %d Linux objects" % linux_objects)
    print("  deps  : no imports of excluded packages (%s)" % ", ".join(EXCLUDED_PACKAGES))
    print("  size  : %s unzipped (limit %s)" % (human(size), human(LAMBDA_UNZIPPED_LIMIT)))
    if size > SIZE_WARNING:
        print("  WARN  : within %s of the limit" % human(LAMBDA_UNZIPPED_LIMIT - size))


# Packages deliberately left out of the deployment. Importing one at runtime
# would raise ImportError inside a live request.
EXCLUDED_PACKAGES = ("scads.demo",)


def _check_excluded_imports() -> List[str]:
    """Scan the built package for imports of anything excluded.

    This exists because the exclusion silently broke a real endpoint: the admin
    reset handler imported DEMO_TAG from scads.demo inside the function body, so
    nothing failed at build time, nothing failed at import time, and the route
    would have raised ImportError the first time it was called in production.
    A static scan catches the whole class of mistake at build time instead.
    """
    import ast

    problems: List[str] = []
    scads_root = os.path.join(BUILD_DIR, "scads")
    if not os.path.isdir(scads_root):
        return ["scads package missing from the build"]

    excluded_leaves = {name.rsplit(".", 1)[-1] for name in EXCLUDED_PACKAGES}

    for root, _dirs, files in os.walk(scads_root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, BUILD_DIR)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
            except (OSError, SyntaxError) as exc:
                problems.append("%s: %s" % (relative, exc))
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(p) for p in EXCLUDED_PACKAGES):
                            problems.append("%s imports %s" % (relative, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if any(module.startswith(p) for p in EXCLUDED_PACKAGES):
                        problems.append("%s imports from %s" % (relative, module))
                    # Relative imports: `from ..demo.seed_data import X` has
                    # module "demo.seed_data" and level > 0.
                    if node.level and module.split(".")[0] in excluded_leaves:
                        problems.append(
                            "%s relatively imports %s" % (relative, module)
                        )
    return problems


def build_zip() -> str:
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for root, _dirs, files in os.walk(BUILD_DIR):
            for name in sorted(files):
                full = os.path.join(root, name)
                archive.write(full, os.path.relpath(full, BUILD_DIR))

    print("  zip   : %s (%s)" % (os.path.relpath(ZIP_PATH, ROOT), human(os.path.getsize(ZIP_PATH))))
    return ZIP_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", action="store_true", help="also build the zip archive")
    parser.add_argument("--check", action="store_true", help="verify an existing build only")
    args = parser.parse_args()

    if args.check:
        if not os.path.isdir(BUILD_DIR):
            print("no build found; run without --check first", file=sys.stderr)
            return 1
        verify()
        return 0

    print("Building the SCADS API Lambda package")
    clean()
    copy_source()
    install_dependencies()
    before, after = prune()
    print("  prune : %s -> %s" % (human(before), human(after)))
    verify()
    if args.zip:
        build_zip()
    print("\nbuilt %s" % os.path.relpath(BUILD_DIR, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
