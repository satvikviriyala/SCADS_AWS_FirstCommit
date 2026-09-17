"""AWS backends: S3, DynamoDB, Textract and optional Bedrock.

``boto3`` is imported lazily inside each class so that the pure core and the
offline path stay importable without it — the decision-engine tests must not
need an AWS SDK.

Every call converts a boto3 error into :class:`DependencyUnavailable`. Nothing
here returns a success-shaped fallback on failure.
"""

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..contracts.records import (
    BatchRecord,
    ManufacturerRecord,
    ReferenceProfile,
    ScanEvent,
    SerialRecord,
    SkuRecord,
)
from ..identity.ocr import OcrResult, OcrWord
from .base import (
    DependencyUnavailable,
    Explainer,
    ObjectStore,
    OcrProvider,
    ReferenceStore,
    Registry,
    RegistryWriter,
    ScanEventStore,
)

# Bucket kinds, mapped to real bucket names by S3ObjectStore.
SCANS = "scans"
REFERENCES = "references"


def _boto3():
    try:
        import boto3  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - deployment always has boto3
        raise DependencyUnavailable("boto3", str(exc))
    return boto3


def _to_dynamo(value: Any) -> Any:
    """Convert Python values to DynamoDB-safe ones.

    DynamoDB has no float type; the resource API requires ``Decimal``. Floats
    are routed through ``str`` so a repr artefact such as 0.8600000000000001
    is not persisted as the stored evidence value.
    """
    if isinstance(value, float):
        return Decimal(str(round(value, 6)))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class S3ObjectStore(ObjectStore):
    """Private S3 buckets with presigned, constrained uploads."""

    backend_name = "s3"

    def __init__(self, scan_bucket: str, reference_bucket: str, region: str) -> None:
        self.buckets = {SCANS: scan_bucket, REFERENCES: reference_bucket}
        self.region = region
        self._client = None

    @property
    def client(self):
        if self._client is None:
            boto3 = _boto3()
            # SigV4 is required for presigned URLs to be accepted by newer
            # regions; being explicit avoids a region-dependent signing bug.
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                region_name=self.region,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def _bucket(self, bucket_kind: str) -> str:
        try:
            return self.buckets[bucket_kind]
        except KeyError:
            raise ValueError("unknown bucket kind: " + bucket_kind)

    def presign_put(
        self, bucket_kind: str, key: str, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> Dict[str, Any]:
        """Presign a single ``PUT``.

        The content type is pinned into the signature, so the client cannot
        upload a different type than it declared. Size is additionally enforced
        server-side when the object is read, because a presigned ``PUT`` cannot
        by itself bound the body length.
        """
        try:
            url = self.client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket(bucket_kind),
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=ttl_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise DependencyUnavailable("s3_presign", str(exc))
        return {
            "method": "PUT",
            "url": url,
            "headers": {"Content-Type": content_type},
            "expires_in_seconds": ttl_seconds,
            "backend": self.backend_name,
        }

    def get_bytes(self, bucket_kind: str, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self._bucket(bucket_kind), Key=key)
            return response["Body"].read()
        except Exception as exc:
            raise DependencyUnavailable("s3_get_object", str(exc))

    def put_bytes(self, bucket_kind: str, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self._bucket(bucket_kind),
                Key=key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            raise DependencyUnavailable("s3_put_object", str(exc))

    def head(self, bucket_kind: str, key: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.client.head_object(Bucket=self._bucket(bucket_kind), Key=key)
        except Exception as exc:
            # A missing object is an expected outcome, not a dependency failure:
            # it means the client has not finished uploading yet.
            name = type(exc).__name__
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound") or name == "ClientError":
                return None
            raise DependencyUnavailable("s3_head_object", str(exc))
        return {
            "content_length": int(response.get("ContentLength", 0)),
            "content_type": response.get("ContentType"),
        }

    def exists(self, bucket_kind: str, key: str) -> bool:
        return self.head(bucket_kind, key) is not None


class DynamoRegistry(Registry, RegistryWriter):
    """Registry on a single ``pk``/``sk`` table, per ``docs/DATA_MODEL.md``."""

    backend_name = "dynamodb"

    def __init__(self, table_name: str, region: str) -> None:
        self.table_name = table_name
        self.region = region
        self._table = None

    @property
    def table(self):
        if self._table is None:
            boto3 = _boto3()
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table

    def _get(self, pk: str, sk: str = "META") -> Optional[Dict[str, Any]]:
        try:
            response = self.table.get_item(Key={"pk": pk, "sk": sk})
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_get_item", str(exc))
        item = response.get("Item")
        return _from_dynamo(item) if item else None

    def _put(self, item: Dict[str, Any]) -> None:
        try:
            self.table.put_item(Item=_to_dynamo(item))
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_put_item", str(exc))

    def get_manufacturer(self, manufacturer_id: str) -> Optional[ManufacturerRecord]:
        item = self._get("MFG#" + manufacturer_id)
        return ManufacturerRecord.from_item(item) if item else None

    def get_sku(self, sku_id: str) -> Optional[SkuRecord]:
        item = self._get("SKU#" + sku_id)
        return SkuRecord.from_item(item) if item else None

    def get_batch(self, batch_id: str) -> Optional[BatchRecord]:
        item = self._get("BATCH#" + batch_id)
        return BatchRecord.from_item(item) if item else None

    def find_batch_by_code(self, batch_code: str) -> Optional[BatchRecord]:
        """Resolve a printed batch code via the ``code_lookup`` alias item.

        An alias item rather than a scan or a second GSI: batch codes are read
        from packaging and looked up on every scan, so this must be a single
        ``get_item``, and adding an index for two demo products would be
        premature (``AGENTS.md`` section 9).
        """
        alias = self._get("CODE#BATCH#" + batch_code.upper().replace(" ", ""))
        if not alias or not alias.get("batch_id"):
            return None
        return self.get_batch(alias["batch_id"])

    def get_serial(self, serial_id: str) -> Optional[SerialRecord]:
        item = self._get("SERIAL#" + serial_id)
        return SerialRecord.from_item(item) if item else None

    def find_serial_by_code(self, serial_code: str) -> Optional[SerialRecord]:
        needle = serial_code.upper().replace(" ", "")
        alias = self._get("CODE#SERIAL#" + needle)
        if alias and alias.get("serial_id"):
            return self.get_serial(alias["serial_id"])
        # Serial ids are also accepted directly so a seeded id works as a code.
        return self.get_serial(serial_code)

    # --- admin plane ----------------------------------------------------
    def put_manufacturer(self, record: ManufacturerRecord) -> None:
        self._put(record.to_item())

    def put_sku(self, record: SkuRecord) -> None:
        self._put(record.to_item())

    def put_batch(self, record: BatchRecord) -> None:
        self._put(record.to_item())
        self._put(
            {
                "pk": "CODE#BATCH#" + record.batch_code.upper().replace(" ", ""),
                "sk": "META",
                "entity": "BATCH_CODE_ALIAS",
                "batch_id": record.batch_id,
            }
        )

    def put_serial(self, record: SerialRecord) -> None:
        self._put(record.to_item())
        self._put(
            {
                "pk": "CODE#SERIAL#" + record.serial_code.upper().replace(" ", ""),
                "sk": "META",
                "entity": "SERIAL_CODE_ALIAS",
                "serial_id": record.serial_id,
            }
        )

    def put_reference_profile(self, record: ReferenceProfile) -> None:
        raise NotImplementedError("reference profiles live in the reference table")


class DynamoReferenceStore(ReferenceStore, RegistryWriter):
    backend_name = "dynamodb"

    def __init__(self, table_name: str, region: str) -> None:
        self.table_name = table_name
        self.region = region
        self._table = None

    @property
    def table(self):
        if self._table is None:
            boto3 = _boto3()
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table

    def get_profile(self, reference_profile_id: str) -> Optional[ReferenceProfile]:
        try:
            response = self.table.get_item(
                Key={"reference_profile_id": reference_profile_id}
            )
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_get_item", str(exc))
        item = response.get("Item")
        return ReferenceProfile.from_item(_from_dynamo(item)) if item else None

    def list_profiles(self) -> List[ReferenceProfile]:
        """Scan the reference table.

        A full scan is acceptable here and only here: the table holds one item
        per enrolled packaging variant (single digits for the hackathon), and it
        is read by admin tooling, never by the request path.
        """
        try:
            response = self.table.scan(Limit=100)
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_scan", str(exc))
        return [ReferenceProfile.from_item(_from_dynamo(i)) for i in response.get("Items", [])]

    def put_reference_profile(self, record: ReferenceProfile) -> None:
        try:
            self.table.put_item(Item=_to_dynamo(record.to_item()))
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_put_item", str(exc))

    def put_manufacturer(self, record):  # pragma: no cover - wrong table
        raise NotImplementedError

    def put_sku(self, record):  # pragma: no cover - wrong table
        raise NotImplementedError

    def put_batch(self, record):  # pragma: no cover - wrong table
        raise NotImplementedError

    def put_serial(self, record):  # pragma: no cover - wrong table
        raise NotImplementedError


class DynamoScanEventStore(ScanEventStore):
    """Scan events keyed by ``scan_id``, with a by-serial GSI for history."""

    backend_name = "dynamodb"
    SERIAL_INDEX = "serial-time-index"

    def __init__(self, table_name: str, region: str) -> None:
        self.table_name = table_name
        self.region = region
        self._table = None

    @property
    def table(self):
        if self._table is None:
            boto3 = _boto3()
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table

    def put_event(self, event: ScanEvent) -> None:
        try:
            self.table.put_item(Item=_to_dynamo(event.to_item()))
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_put_item", str(exc))

    def get_event(self, scan_id: str) -> Optional[ScanEvent]:
        try:
            response = self.table.get_item(Key={"scan_id": scan_id})
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_get_item", str(exc))
        item = response.get("Item")
        return ScanEvent.from_item(_from_dynamo(item)) if item else None

    def query_by_serial(self, serial_id: str, limit: int = 50) -> List[ScanEvent]:
        from boto3.dynamodb.conditions import Key

        try:
            response = self.table.query(
                IndexName=self.SERIAL_INDEX,
                KeyConditionExpression=Key("serial_index_key").eq(serial_id),
                ScanIndexForward=False,  # newest first
                Limit=limit,
            )
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_query", str(exc))
        return [ScanEvent.from_item(_from_dynamo(i)) for i in response.get("Items", [])]

    def delete_events_by_demo_tag(self, demo_tag: str) -> int:
        """Delete seeded demo events.

        Scoped to ``demo_tag`` so a reset removes only fixtures the seed script
        created and never a real observation
        (``docs/API_CONTRACTS.md`` section 5).
        """
        from boto3.dynamodb.conditions import Attr

        deleted = 0
        try:
            kwargs: Dict[str, Any] = {
                "FilterExpression": Attr("demo_tag").eq(demo_tag),
                "ProjectionExpression": "scan_id",
            }
            while True:
                response = self.table.scan(**kwargs)
                for item in response.get("Items", []):
                    self.table.delete_item(Key={"scan_id": item["scan_id"]})
                    deleted += 1
                token = response.get("LastEvaluatedKey")
                if not token:
                    break
                kwargs["ExclusiveStartKey"] = token
        except Exception as exc:
            raise DependencyUnavailable("dynamodb_scan_delete", str(exc))
        return deleted


class TextractOcrProvider(OcrProvider):
    """Amazon Textract ``detect_document_text``.

    ``detect_document_text`` rather than ``analyze_document``: SCADS needs word
    strings and their geometry, not forms or tables, and the simpler call is
    cheaper and lower-latency (``docs/AWS_DEPLOYMENT.md`` section 12).
    """

    provider_name = "textract"

    def __init__(self, region: str, max_bytes: int = 5 * 1024 * 1024) -> None:
        self.region = region
        self.max_bytes = max_bytes
        self._client = None

    @property
    def client(self):
        if self._client is None:
            boto3 = _boto3()
            self._client = boto3.client("textract", region_name=self.region)
        return self._client

    def detect_text(self, image_bytes: bytes, hint: Optional[Dict[str, Any]] = None) -> OcrResult:
        if len(image_bytes) > self.max_bytes:
            return OcrResult.failed(
                self.provider_name,
                "image exceeds Textract synchronous limit of {} bytes".format(self.max_bytes),
            )
        try:
            response = self.client.detect_document_text(Document={"Bytes": image_bytes})
        except Exception as exc:
            # Reported as a failed OcrResult, not raised: OCR is one evidence
            # source among several, and losing it should degrade the identity
            # and layout evidence rather than fail the whole scan.
            return OcrResult.failed(self.provider_name, type(exc).__name__)

        words: List[OcrWord] = []
        lines: List[str] = []
        for block in response.get("Blocks", []):
            block_type = block.get("BlockType")
            geometry = (block.get("Geometry") or {}).get("BoundingBox") or {}
            if block_type == "LINE":
                lines.append(block.get("Text", ""))
            elif block_type == "WORD":
                width = float(geometry.get("Width", 0.0))
                height = float(geometry.get("Height", 0.0))
                words.append(
                    OcrWord(
                        text=block.get("Text", ""),
                        x=float(geometry.get("Left", 0.0)) + width / 2.0,
                        y=float(geometry.get("Top", 0.0)) + height / 2.0,
                        width=width,
                        height=height,
                        confidence=float(block.get("Confidence", 0.0)),
                    )
                )
        return OcrResult(words=words, lines=lines, provider=self.provider_name, succeeded=True)


class BedrockExplainer(Explainer):
    """Optional Bedrock rewrite of an already-final result.

    The prompt receives only the decision, the reason codes and the numeric
    dimensions — never the raw OCR text of the pack. That is deliberate: package
    text is attacker-controlled, and feeding it to a model invites prompt
    injection (``docs/THREAT_MODEL.md`` section 7). The model is asked for
    wording, is given no authority over the verdict, and any failure returns
    ``None`` so the caller keeps the deterministic text.
    """

    provider_name = "bedrock"

    _SYSTEM = (
        "You rewrite a completed medicine-pack screening result for a worried member of "
        "the public. You are given a decision and a fixed list of finding codes that were "
        "already determined by a deterministic system.\n"
        "Rules you must follow:\n"
        "1. Never change, soften or strengthen the decision.\n"
        "2. Never introduce a finding that is not in the supplied list.\n"
        "3. Never say a medicine is genuine, safe, or chemically verified. A photograph "
        "cannot establish any of those.\n"
        "4. Never tell the reader to take or not take medication; refer them to a "
        "pharmacist or the manufacturer.\n"
        "5. Reply with two or three plain sentences and nothing else. No preamble, no "
        "lists, no markdown."
    )

    _FORBIDDEN = (
        "genuine",
        "authentic",
        "safe to",
        "counterfeit confirmed",
        "definitely",
        "guaranteed",
    )

    def __init__(
        self,
        model_id: str,
        region: str,
        timeout_seconds: int = 4,
        max_output_tokens: int = 300,
    ) -> None:
        self.model_id = model_id
        self.region = region
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self._client = None

    @property
    def client(self):
        if self._client is None:
            boto3 = _boto3()
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    read_timeout=self.timeout_seconds,
                    connect_timeout=self.timeout_seconds,
                    retries={"max_attempts": 1},
                ),
            )
        return self._client

    def rewrite(
        self, decision: str, reason_codes: List[str], dimensions: Dict[str, float]
    ) -> Optional[str]:
        payload = {
            "decision": decision,
            "findings": list(reason_codes),
            "evidence_scores": {k: round(float(v), 2) for k, v in dimensions.items()},
        }
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_output_tokens,
            "temperature": 0.0,
            "system": self._SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                }
            ],
        }
        try:
            response = self.client.invoke_model(
                modelId=self.model_id, body=json.dumps(body).encode("utf-8")
            )
            parsed = json.loads(response["body"].read())
        except Exception:
            return None

        text = ""
        for chunk in parsed.get("content", []):
            if chunk.get("type") == "text":
                text += chunk.get("text", "")
        text = text.strip()

        if not self._is_safe(text, decision):
            return None
        return text

    def _is_safe(self, text: str, decision: str) -> bool:
        """Validate generated prose before it can reach a user.

        The model is not trusted. Output that is empty, overlong, or contains
        reassurance vocabulary SCADS is not entitled to use is discarded in
        favour of the deterministic text.
        """
        if not text or len(text) > 600:
            return False
        lowered = text.lower()
        for phrase in self._FORBIDDEN:
            if phrase in lowered:
                return False
        # A generated paragraph must not assert a different decision class.
        for other in ("low_observed_risk", "review_required", "suspicious", "unable_to_verify"):
            if other in lowered and other != decision.lower():
                return False
        return True
