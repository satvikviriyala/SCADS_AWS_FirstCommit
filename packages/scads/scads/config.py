"""Runtime configuration, read once from the environment.

Two rules shape this module.

**No silent downgrades.** Which backend is in use — real AWS or the local
offline one — is an explicit, named setting that is reported in every scan's
evidence and in ``/health``. A fixture-backed run can therefore never be
mistaken for a Textract-backed one, which is what ``AGENTS.md`` section 5
forbids.

**Fail fast on missing required configuration.** A Lambda with no table name
should refuse to start rather than throw a confusing ``None`` deep inside a
DynamoDB call.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or contradictory."""


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(name + " must be an integer, got " + repr(raw))


def _env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = _env(name)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


# Backend identifiers. These strings appear in API responses and logs.
STORE_S3 = "s3"
STORE_LOCAL = "local"
REPO_DYNAMODB = "dynamodb"
REPO_LOCAL = "local"
OCR_TEXTRACT = "textract"
OCR_FIXTURE = "fixture"
OCR_NONE = "none"


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    region: str = "ap-south-1"

    store_backend: str = STORE_S3
    repo_backend: str = REPO_DYNAMODB
    ocr_provider: str = OCR_TEXTRACT

    scan_bucket: Optional[str] = None
    reference_bucket: Optional[str] = None
    registry_table: Optional[str] = None
    scan_events_table: Optional[str] = None
    reference_table: Optional[str] = None

    local_root: str = ".scads-local"

    upload_max_bytes: int = 8 * 1024 * 1024
    upload_url_ttl_seconds: int = 300
    textract_max_bytes: int = 5 * 1024 * 1024

    bedrock_enabled: bool = False
    bedrock_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    bedrock_region: Optional[str] = None
    bedrock_timeout_seconds: int = 4

    admin_api_token: Optional[str] = None
    allowed_origins: List[str] = field(default_factory=lambda: ["http://localhost:8000"])

    @property
    def uses_aws_storage(self) -> bool:
        return self.store_backend == STORE_S3

    @property
    def uses_aws_registry(self) -> bool:
        return self.repo_backend == REPO_DYNAMODB

    @property
    def admin_enabled(self) -> bool:
        """The demo-reset endpoint exists only when a token is configured.

        An unauthenticated reset of the registry or scan history would let
        anyone erase the evidence the product depends on
        (``docs/API_CONTRACTS.md`` section 5).
        """
        return bool(self.admin_api_token)

    def validate(self) -> None:
        """Raise :class:`ConfigError` if this configuration cannot work."""
        if self.store_backend not in (STORE_S3, STORE_LOCAL):
            raise ConfigError("STORE_BACKEND must be 's3' or 'local'")
        if self.repo_backend not in (REPO_DYNAMODB, REPO_LOCAL):
            raise ConfigError("REPO_BACKEND must be 'dynamodb' or 'local'")
        if self.ocr_provider not in (OCR_TEXTRACT, OCR_FIXTURE, OCR_NONE):
            raise ConfigError("OCR_PROVIDER must be 'textract', 'fixture' or 'none'")

        missing: List[str] = []
        if self.store_backend == STORE_S3:
            if not self.scan_bucket:
                missing.append("SCAN_BUCKET")
            if not self.reference_bucket:
                missing.append("REFERENCE_BUCKET")
        if self.repo_backend == REPO_DYNAMODB:
            if not self.registry_table:
                missing.append("REGISTRY_TABLE")
            if not self.scan_events_table:
                missing.append("SCAN_EVENTS_TABLE")
            if not self.reference_table:
                missing.append("REFERENCE_TABLE")
        if missing:
            raise ConfigError(
                "missing required configuration for the selected backends: "
                + ", ".join(missing)
            )

        if self.upload_max_bytes <= 0:
            raise ConfigError("UPLOAD_MAX_BYTES must be positive")
        if not 1 <= self.upload_url_ttl_seconds <= 3600:
            raise ConfigError("UPLOAD_URL_TTL_SECONDS must be between 1 and 3600")

    def describe_backends(self) -> dict:
        """Backend identities, safe to expose.

        Returned by ``/health`` and stamped onto every scan so that a deployed
        environment quietly running on local stubs is visible rather than
        indistinguishable from a real one.
        """
        return {
            "store": self.store_backend,
            "registry": self.repo_backend,
            "ocr": self.ocr_provider,
            "bedrock": "enabled" if self.bedrock_enabled else "disabled",
        }


def load_settings() -> Settings:
    """Build :class:`Settings` from the process environment."""
    settings = Settings(
        env=_env("SCADS_ENV", "dev"),
        region=_env("AWS_REGION", _env("AWS_DEFAULT_REGION", "ap-south-1")),
        store_backend=(_env("STORE_BACKEND", STORE_S3) or STORE_S3).lower(),
        repo_backend=(_env("REPO_BACKEND", REPO_DYNAMODB) or REPO_DYNAMODB).lower(),
        ocr_provider=(_env("OCR_PROVIDER", OCR_TEXTRACT) or OCR_TEXTRACT).lower(),
        scan_bucket=_env("SCAN_BUCKET"),
        reference_bucket=_env("REFERENCE_BUCKET"),
        registry_table=_env("REGISTRY_TABLE"),
        scan_events_table=_env("SCAN_EVENTS_TABLE"),
        reference_table=_env("REFERENCE_TABLE"),
        local_root=_env("SCADS_LOCAL_ROOT", ".scads-local"),
        upload_max_bytes=_env_int("UPLOAD_MAX_BYTES", 8 * 1024 * 1024),
        upload_url_ttl_seconds=_env_int("UPLOAD_URL_TTL_SECONDS", 300),
        textract_max_bytes=_env_int("TEXTRACT_MAX_BYTES", 5 * 1024 * 1024),
        bedrock_enabled=_env_bool("BEDROCK_ENABLED", False),
        bedrock_model_id=_env(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-haiku-20241022-v1:0"
        ),
        bedrock_region=_env("BEDROCK_REGION"),
        bedrock_timeout_seconds=_env_int("BEDROCK_TIMEOUT_SECONDS", 4),
        admin_api_token=_env("ADMIN_API_TOKEN"),
        allowed_origins=_env_list("ALLOWED_ORIGINS", ["http://localhost:8000"]),
    )
    settings.validate()
    return settings


def local_settings(root: str = ".scads-local", ocr: str = OCR_FIXTURE) -> Settings:
    """Fully offline settings for unit tests and local development.

    Kept as a named constructor rather than a fallback inside
    :func:`load_settings`, so that a misconfigured deployment fails loudly
    instead of quietly running on local stubs.
    """
    settings = Settings(
        env="local",
        store_backend=STORE_LOCAL,
        repo_backend=REPO_LOCAL,
        ocr_provider=ocr,
        local_root=root,
        admin_api_token="local-dev-token",
        allowed_origins=["*"],
    )
    settings.validate()
    return settings
