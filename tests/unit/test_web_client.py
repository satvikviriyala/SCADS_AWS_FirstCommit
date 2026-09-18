"""Static consistency checks for the web client.

There is no Node runtime here to execute the client, and the most likely defect
in hand-written DOM code is a mismatched identifier: ``el("preview-wrap")``
against a markup element named ``preview_wrap`` fails silently at runtime and
only in the browser. These checks catch that class of error, plus the safety
and accessibility properties that must not regress.
"""

import json
import os
import re

import pytest

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "web")


def read(name):
    with open(os.path.join(WEB, name), "r", encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def html():
    return read("index.html")


@pytest.fixture(scope="module")
def js():
    return read("app.js")


@pytest.fixture(scope="module")
def css():
    return read("styles.css")


@pytest.fixture(scope="module")
def html_ids(html):
    return set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))


# --- wiring --------------------------------------------------------------


def test_every_element_the_script_looks_up_exists(js, html_ids):
    """A typo here is invisible until the page is open in a browser."""
    referenced = set(re.findall(r'\bel\("([A-Za-z0-9_-]+)"\)', js))
    referenced |= set(re.findall(r'openSheet\("([A-Za-z0-9_-]+)"\)', js))
    referenced |= set(re.findall(r'wireSheet\("([A-Za-z0-9_-]+)"\)', js))
    missing = sorted(referenced - html_ids)
    assert not missing, "app.js references ids not present in index.html: %s" % missing


def test_every_view_the_script_switches_to_exists(js, html_ids):
    views = set(re.findall(r'^\s*(\w+): el\("(view-[a-z]+)"\)', js, re.M))
    for _key, element_id in views:
        assert element_id in html_ids, element_id


def test_script_queries_resolve_to_markup(js, html):
    """Attribute selectors used by the script must match the markup."""
    for selector in re.findall(r'querySelector(?:All)?\(\'(\.[a-z-]+)\[data-([a-z]+)="', js):
        class_name, attribute = selector
        assert class_name.lstrip(".") in html, class_name
        assert "data-" + attribute in html, attribute


def test_stage_names_match_the_markup(js, html):
    declared = set(re.findall(r'data-stage="([a-z]+)"', html))
    used = set(re.findall(r'const STAGES = \[(.*?)\]', js, re.S)[0].replace('"', "").replace(" ", "").split(","))
    assert used == declared, "stage names differ: script %s vs markup %s" % (used, declared)


def test_classes_used_by_the_script_are_styled(js, css):
    """A class set in JS but never styled renders as unstyled content."""
    assigned = set()
    for match in re.findall(r'className = "([a-z0-9_ -]+)"', js):
        assigned.update(match.split())
    unstyled = sorted(c for c in assigned if ("." + c) not in css)
    assert not unstyled, "classes set by app.js with no rule in styles.css: %s" % unstyled


def test_referenced_assets_exist(html):
    for href in re.findall(r'(?:href|src)="([^":]+)"', html):
        if href.startswith("#") or href.startswith("http"):
            continue
        assert os.path.exists(os.path.join(WEB, href)), href


def test_manifest_is_valid_and_points_at_a_real_icon():
    manifest = json.loads(read("manifest.webmanifest"))
    assert manifest["name"] and manifest["short_name"]
    for icon in manifest["icons"]:
        assert os.path.exists(os.path.join(WEB, icon["src"])), icon["src"]


# --- contract agreement --------------------------------------------------


def test_decision_classes_match_the_backend_enum(js):
    """The client must render exactly the four classes the engine can emit."""
    from scads.contracts.enums import Decision

    block = re.search(r"const VERDICTS = \{(.*?)\n\};", js, re.S).group(1)
    rendered = set(re.findall(r"^\s*([A-Z_]+):", block, re.M))
    assert rendered == {d.value for d in Decision}, rendered


def test_severity_names_match_the_backend(js):
    from scads.contracts.reason_codes import Severity

    block = re.search(r"const SEVERITY_GLYPH = \{(.*?)\};", js, re.S).group(1)
    rendered = set(re.findall(r"([A-Z]+):", block))
    assert rendered == {s.name for s in Severity}, rendered


def test_dimension_keys_match_what_the_backend_sends(js):
    """The client reads dimensions by key; the backend builds them by key.

    Asserted against the keys the backend actually emits, not against its
    source text, so a rename shows up here rather than in the browser.
    """
    from conftest import bundle
    from scads.decision import decide
    from scads.decision.explain import build_dimensions

    evidence = bundle()
    keys = [d.key for d in build_dimensions(evidence, decide(evidence))]
    assert keys == ["identity", "physical", "history"]

    # The client's label map must cover every key the backend can emit.
    label_block = re.search(r"const STATE_WORD = \{(.*?)\};", js, re.S)
    assert label_block, "client has no state label map"
    for key in keys:
        assert '"' + key + '"' in js, key


def test_demo_packs_reference_real_fixtures(js):
    from scads.demo.fixtures import FIXTURES_BY_NAME

    block = re.search(r"const DEMO_PACKS = \[(.*?)\n\];", js, re.S).group(1)
    files = re.findall(r'file: "([a-z0-9_]+)\.jpg"', block)
    assert files, "no demo packs declared"
    for name in files:
        assert name in FIXTURES_BY_NAME, "demo pack %s is not a known fixture" % name


# --- safety and accessibility --------------------------------------------


def test_no_forbidden_safety_language_anywhere_in_the_client(html, js):
    """``CLAUDE.md``: never claim a pack is genuine or safe from a phone scan."""
    combined = (html + " " + js).lower()
    for phrase in (
        "100% genuine", "safe to consume", "safe to use", "guaranteed authentic",
        "certified genuine", "proven genuine", "verified authentic",
        "chemically genuine", "definitely fake", "confirmed counterfeit",
    ):
        assert phrase not in combined, phrase


def test_the_limitation_is_present_in_the_markup(html):
    assert "cannot tell you" in html
    assert 'id="limitation"' in html


def test_simulated_locations_are_labelled_as_simulated(html):
    assert "simulated" in html.lower()
    assert "real location is never requested" in html.lower()


def test_synthetic_tampering_is_not_described_as_counterfeit(html):
    assert "synthetically" in html.lower()
    assert "not real counterfeit samples" in html.lower()


def test_state_is_never_conveyed_by_colour_alone(js):
    """Colour-only status is unreadable for many people, in a health context."""
    assert "STATE_GLYPH" in js
    assert "STATE_WORD" in js
    # The badge must append both a glyph node and a text node.
    assert "badge.appendChild(glyph)" in js
    assert "document.createTextNode(STATE_WORD" in js


def test_tap_targets_meet_the_minimum_size(css):
    """44px is the accepted floor for a touch target."""
    button = re.search(r"\.btn \{(.*?)\}", css, re.S).group(1)
    assert "min-height: 44px" in button


def test_dark_mode_is_supported(css):
    assert "prefers-color-scheme: dark" in css
    assert "--bg:" in css


def test_reduced_motion_is_respected(css):
    assert "prefers-reduced-motion: reduce" in css


def test_focus_is_visible(css):
    assert ":focus-visible" in css
    assert "outline:" in css


# --- no secrets or hardcoded endpoints -----------------------------------


def _strip_comments(source: str) -> str:
    """Remove block and line comments, so prose is not mistaken for content."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def test_config_contains_no_secrets():
    """Checks assigned values, not prose.

    config.js is served to every visitor, and its own comment says so — which
    is exactly why this scans the code with comments stripped.
    """
    config = _strip_comments(read("config.js"))
    assert not re.search(r"AKIA[0-9A-Z]{16}", config)
    assert not re.search(r"ASIA[0-9A-Z]{16}", config)
    for key in ("secret", "password", "privateKey", "apiKey", "token", "credential"):
        assert not re.search(key + r"\s*:", config, re.I), key


def test_client_has_no_hardcoded_aws_endpoints(js):
    """The API base URL must come from config, written at deploy time."""
    assert "execute-api" not in js
    assert "amazonaws.com" not in js
    assert "window.SCADS_CONFIG" in js


def test_client_never_uses_innerhtml(js):
    """Backend text flows into the DOM; textContent keeps it inert.

    Reason-code detail and history summaries are server-supplied strings. Using
    innerHTML anywhere in that path would turn a content change into a scripting
    vector.
    """
    assert "innerHTML" not in js
    assert "outerHTML" not in js
    assert "insertAdjacentHTML" not in js
