"""The fixture corpus: one definition of every scenario SCADS is tested against.

Shared by the unit tests, the evaluation harness and the deployed demo, so a
scenario that passes locally is the same scenario a judge sees.

Every tampered fixture is labelled ``synthetic_tamper``. It is a controlled
proxy for measuring which feature responds to which kind of change — not a
counterfeit sample, and not a basis for any accuracy claim about real
counterfeits (``docs/EVALUATION.md`` section 1).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..contracts.records import ReferenceProfile, SerialRecord, SkuRecord
from . import seed_data
from .render import CaptureSettings, RenderedPack, Tamper, render_pack, simulate_capture


@dataclass(frozen=True)
class FixtureSpec:
    """One test capture: which pack, tampered how, photographed how."""

    name: str
    serial_id: str
    # genuine          — real pack, real identity, honest capture
    # synthetic_tamper  — the *artwork* was perturbed
    # identity_tamper   — artwork untouched, the *identity* was altered
    # hard_capture      — real pack, difficult photograph
    #
    # The identity/artwork split matters for evaluation. An altered serial
    # leaves the packaging genuine, so its physical score *should* look like a
    # genuine pack's. Grouping those with artwork tampers made the physical
    # score appear unable to separate anything, when it was being asked about
    # the wrong dimension.
    label: str
    tamper: Tamper = field(default_factory=Tamper)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    printed_batch_code: Optional[str] = None
    printed_serial_code: Optional[str] = None
    qr_serial_override: Optional[str] = None
    expectation: str = ""
    notes: str = ""

    @property
    def is_genuine(self) -> bool:
        return self.label == "genuine"


def _profile_for(serial_id: str) -> Tuple[ReferenceProfile, SkuRecord, SerialRecord]:
    serial = seed_data.serial_by_id(serial_id)
    sku = seed_data.sku_by_id(serial.sku_id)
    profile = seed_data.reference_profile_by_id(sku.reference_profile_id)
    return profile, sku, serial


def build_reference(serial_id: str) -> RenderedPack:
    """Render the enrolled reference artwork for a product.

    Captured under ideal studio conditions by definition: this is the artwork
    the manufacturer enrolled, not a photograph of a pack.
    """
    profile, sku, serial = _profile_for(serial_id)
    batch = seed_data.batch_by_id(serial.batch_id)
    return render_pack(
        profile=profile,
        sku=sku,
        batch=batch,
        serial=None,  # the reference carries no unit overprint
        qr_payload=None,
        tamper=Tamper(),
    )


def build_fixture(spec: FixtureSpec):
    """Render and photograph one fixture.

    Returns ``(image, words, lines, profile)``.
    """
    profile, sku, serial = _profile_for(spec.serial_id)
    batch = seed_data.batch_by_id(serial.batch_id)

    qr_serial = spec.qr_serial_override or serial.serial_code
    qr_payload = seed_data.build_qr_payload(
        serial_code=qr_serial,
        batch_code=batch.batch_code,
        gtin=sku.gtin,
        expiry=batch.expiry_date,
        product=sku.product_name,
    )

    pack = render_pack(
        profile=profile,
        sku=sku,
        batch=batch,
        serial=serial,
        qr_payload=qr_payload,
        tamper=spec.tamper,
        printed_batch_code=spec.printed_batch_code,
        printed_serial_code=spec.printed_serial_code,
    )
    image, words = simulate_capture(pack, spec.capture)
    return image, words, pack.lines, profile


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------

CLEAN_CAPTURE = CaptureSettings()

# A competent but imperfect handheld capture. A genuine pack photographed this
# way must still pass: this is the false-positive side of the evaluation.
HARD_CAPTURE = CaptureSettings(
    rotation_deg=-7.5, perspective=0.075, pack_scale=0.60, offset_x=0.05, offset_y=-0.04,
    blur_sigma=1.3, noise=0.02, brightness=0.82, background=70, jpeg_quality=72, seed=909,
)

ALTERNATE_CAPTURE = CaptureSettings(
    rotation_deg=5.5, perspective=0.05, pack_scale=0.80, background=150,
    blur_sigma=0.9, noise=0.015, brightness=1.08, jpeg_quality=94, seed=4242,
)

BLURRED_CAPTURE = CaptureSettings(blur_sigma=7.5, noise=0.02, jpeg_quality=60, seed=77)
DARK_CAPTURE = CaptureSettings(brightness=0.14, noise=0.02, seed=78)
GLARE_CAPTURE = CaptureSettings(glare=0.85, seed=79)
TINY_CAPTURE = CaptureSettings(pack_scale=0.14, frame_width=640, frame_height=480, seed=80)


FIXTURES: List[FixtureSpec] = [
    # --- genuine ---------------------------------------------------------
    FixtureSpec(
        name="genuine_clean_a",
        serial_id="ser_demo_a_001",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="identity valid, packaging matches, history clean",
        notes="demo scenario A",
    ),
    FixtureSpec(
        name="genuine_clean_b",
        serial_id="ser_demo_b_001",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="second product resolves and matches its own reference",
    ),
    FixtureSpec(
        name="genuine_alternate_angle",
        serial_id="ser_demo_a_001",
        label="genuine",
        capture=ALTERNATE_CAPTURE,
        expectation="a different angle and lighting still matches",
    ),
    FixtureSpec(
        name="genuine_hard_capture",
        serial_id="ser_demo_a_001",
        label="hard_capture",
        capture=HARD_CAPTURE,
        expectation="must not be reported as suspicious",
        notes="false-positive guard: awkward but honest photograph",
    ),
    FixtureSpec(
        name="genuine_clone_serial",
        serial_id="ser_demo_a_clone",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="packaging and identity both pass; only history objects",
        notes="demo scenario C — the pack itself is flawless",
    ),
    FixtureSpec(
        name="genuine_expired_batch",
        serial_id="ser_demo_a_expired",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="authentic pack, expired product status",
    ),
    FixtureSpec(
        name="genuine_recalled_batch",
        serial_id="ser_demo_a_recalled",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="authentic pack, recalled product status",
    ),
    FixtureSpec(
        name="genuine_dispensed_unit",
        serial_id="ser_demo_a_dispensed",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="registry says already dispensed; post-sale reuse",
    ),
    FixtureSpec(
        name="genuine_revoked_unit",
        serial_id="ser_demo_a_revoked",
        label="genuine",
        capture=CLEAN_CAPTURE,
        expectation="packaging fine, serial revoked",
    ),

    # --- synthetic tampers ----------------------------------------------
    FixtureSpec(
        name="tamper_logo_shift",
        serial_id="ser_demo_a_002",
        label="synthetic_tamper",
        tamper=Tamper(kind="logo_shift", strength=0.9),
        capture=CLEAN_CAPTURE,
        expectation="structural mismatch in the logo region",
        notes="demo scenario B",
    ),
    FixtureSpec(
        name="tamper_text_shift",
        serial_id="ser_demo_a_002",
        label="synthetic_tamper",
        tamper=Tamper(kind="text_shift", strength=1.0, target="brand_block"),
        capture=CLEAN_CAPTURE,
        expectation="text layout mismatch: right words, wrong place",
    ),
    FixtureSpec(
        name="tamper_reprint",
        serial_id="ser_demo_a_002",
        label="synthetic_tamper",
        tamper=Tamper(kind="reprint", strength=0.95),
        capture=CLEAN_CAPTURE,
        expectation="reported as an inadequate capture, not as a print mismatch",
        notes=(
            "Documents a real confound rather than a capability. Defocus and "
            "poor printing both reduce edge energy, and a single image cannot "
            "separate them, so a uniformly soft reprint trips the quality gate "
            "and returns UNABLE_TO_VERIFY. That is the safe outcome, and it is "
            "honest: SCADS does not claim to detect this case. tamper_resample "
            "covers print degradation that a sharp capture can establish."
        ),
    ),
    FixtureSpec(
        name="tamper_patch",
        serial_id="ser_demo_a_002",
        label="synthetic_tamper",
        tamper=Tamper(kind="patch", strength=0.9, target="warning_strip"),
        capture=CLEAN_CAPTURE,
        expectation="structural mismatch where a block was replaced",
    ),
    FixtureSpec(
        name="tamper_resample",
        serial_id="ser_demo_a_002",
        label="synthetic_tamper",
        tamper=Tamper(kind="resample", strength=0.9),
        capture=CLEAN_CAPTURE,
        expectation="print and structural detail loss",
    ),

    # --- identity fixtures ----------------------------------------------
    FixtureSpec(
        name="identity_qr_print_conflict",
        serial_id="ser_demo_a_001",
        label="identity_tamper",
        capture=CLEAN_CAPTURE,
        printed_serial_code="SER-A-002",
        expectation="QR says one serial, the print says another",
        notes="packaging is otherwise perfect; only the cross-check objects",
    ),
    FixtureSpec(
        name="identity_unknown_serial",
        serial_id="ser_demo_a_001",
        label="identity_tamper",
        capture=CLEAN_CAPTURE,
        qr_serial_override="SER-A-NEVER-ISSUED",
        printed_serial_code="SER-A-NEVER-ISSUED",
        expectation="unissued serial on a convincing pack",
    ),
    FixtureSpec(
        name="identity_altered_batch_digit",
        serial_id="ser_demo_a_001",
        label="identity_tamper",
        capture=CLEAN_CAPTURE,
        printed_batch_code="BND-2026-A9",
        expectation="printed batch disagrees with the code; packaging unaffected",
        notes="the batch overprint is a dynamic region, so structure must not move",
    ),

    # --- capture-quality fixtures ---------------------------------------
    FixtureSpec(
        name="quality_blurred",
        serial_id="ser_demo_a_001",
        label="hard_capture",
        capture=BLURRED_CAPTURE,
        expectation="UNABLE_TO_VERIFY, never suspicious",
    ),
    FixtureSpec(
        name="quality_dark",
        serial_id="ser_demo_a_001",
        label="hard_capture",
        capture=DARK_CAPTURE,
        expectation="UNABLE_TO_VERIFY with underexposure advice",
    ),
    FixtureSpec(
        name="quality_glare",
        serial_id="ser_demo_a_001",
        label="hard_capture",
        capture=GLARE_CAPTURE,
        expectation="UNABLE_TO_VERIFY with glare advice",
    ),
    FixtureSpec(
        name="quality_pack_too_small",
        serial_id="ser_demo_a_001",
        label="hard_capture",
        capture=TINY_CAPTURE,
        expectation="UNABLE_TO_VERIFY: move closer",
    ),
]

FIXTURES_BY_NAME: Dict[str, FixtureSpec] = {f.name: f for f in FIXTURES}


def get_fixture(name: str) -> FixtureSpec:
    return FIXTURES_BY_NAME[name]


def fixtures_labelled(label: str) -> List[FixtureSpec]:
    return [f for f in FIXTURES if f.label == label]


def tamper_sweep(
    serial_id: str = "ser_demo_a_002", kind: str = "logo_shift", steps: int = 6
) -> List[FixtureSpec]:
    """A sensitivity sweep for one perturbation.

    Shows how a feature responds as a change grows. This is a sensitivity
    curve, not a severity scale for real counterfeits
    (``docs/EVALUATION.md`` section 3).
    """
    specs = []
    for index in range(steps):
        strength = index / float(max(1, steps - 1))
        specs.append(
            FixtureSpec(
                name="sweep_{}_{:.2f}".format(kind, strength),
                serial_id=serial_id,
                label="genuine" if strength == 0.0 else "synthetic_tamper",
                tamper=Tamper(kind=kind, strength=strength),
                capture=CLEAN_CAPTURE,
                expectation="sensitivity sweep",
            )
        )
    return specs
