"""Offline backends: filesystem object store and JSON registry/event log.

Purpose: run the entire request path, the detection pipeline and the demo
scenarios with no AWS account, so logic can be developed and tested
independently of infrastructure. These are selected only by
``STORE_BACKEND=local`` / ``REPO_BACKEND=local``, are named in ``/health`` and in
every scan record, and the deployed smoke test asserts they are *not* in use.
"""

import json
import os
import shutil
import threading
from typing import Any, Dict, List, Optional

from ..contracts.records import (
    BatchRecord,
    ManufacturerRecord,
    ReferenceProfile,
    ScanEvent,
    SerialRecord,
    SkuRecord,
)
from .base import (
    DependencyUnavailable,
    ObjectStore,
    ReferenceStore,
    Registry,
    RegistryWriter,
    ScanEventStore,
)

# Serialises read-modify-write on the JSON files. The local backend is used by
# the single-threaded dev server and by tests, but the dev server does handle
# concurrent browser requests.
_LOCK = threading.RLock()


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise DependencyUnavailable("local_json", str(exc))


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        raise DependencyUnavailable("local_json", str(exc))


class LocalObjectStore(ObjectStore):
    """Files under ``<root>/objects/<bucket_kind>/<key>``.

    ``presign_put`` returns a URL pointing at the dev server's upload route
    rather than a real presigned S3 URL, so the browser flow is identical:
    request a target, ``PUT`` the bytes to it, then ask for analysis.
    """

    backend_name = "local"

    def __init__(self, root: str, upload_base_url: str = "http://localhost:8000") -> None:
        self.root = root
        self.upload_base_url = upload_base_url.rstrip("/")

    def _path(self, bucket_kind: str, key: str) -> str:
        if ".." in key or key.startswith("/"):
            raise ValueError("unsafe object key")
        return os.path.join(self.root, "objects", bucket_kind, key)

    def presign_put(
        self, bucket_kind: str, key: str, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> Dict[str, Any]:
        return {
            "method": "PUT",
            "url": self.upload_base_url + "/v1/local-upload/" + bucket_kind + "/" + key,
            "headers": {"Content-Type": content_type},
            "expires_in_seconds": ttl_seconds,
            "backend": self.backend_name,
        }

    def get_bytes(self, bucket_kind: str, key: str) -> bytes:
        path = self._path(bucket_kind, key)
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError as exc:
            raise DependencyUnavailable("local_object_store", str(exc))

    def put_bytes(self, bucket_kind: str, key: str, data: bytes, content_type: str) -> None:
        path = self._path(bucket_kind, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            raise DependencyUnavailable("local_object_store", str(exc))

    def head(self, bucket_kind: str, key: str) -> Optional[Dict[str, Any]]:
        path = self._path(bucket_kind, key)
        if not os.path.exists(path):
            return None
        return {"content_length": os.path.getsize(path), "content_type": None}

    def exists(self, bucket_kind: str, key: str) -> bool:
        return os.path.exists(self._path(bucket_kind, key))


class LocalRegistry(Registry, RegistryWriter):
    """Registry and reference profiles in one JSON file per entity type."""

    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = root

    def _file(self, name: str) -> str:
        return os.path.join(self.root, "registry", name + ".json")

    def _load(self, name: str) -> Dict[str, Any]:
        return _read_json(self._file(name), {})

    def _save(self, name: str, data: Dict[str, Any]) -> None:
        _write_json(self._file(name), data)

    # --- reads ----------------------------------------------------------
    def get_manufacturer(self, manufacturer_id: str) -> Optional[ManufacturerRecord]:
        item = self._load("manufacturers").get(manufacturer_id)
        return ManufacturerRecord.from_item(item) if item else None

    def get_sku(self, sku_id: str) -> Optional[SkuRecord]:
        item = self._load("skus").get(sku_id)
        return SkuRecord.from_item(item) if item else None

    def get_batch(self, batch_id: str) -> Optional[BatchRecord]:
        item = self._load("batches").get(batch_id)
        return BatchRecord.from_item(item) if item else None

    def find_batch_by_code(self, batch_code: str) -> Optional[BatchRecord]:
        needle = batch_code.upper().replace(" ", "")
        for item in self._load("batches").values():
            if item.get("batch_code_norm") == needle:
                return BatchRecord.from_item(item)
        return None

    def get_serial(self, serial_id: str) -> Optional[SerialRecord]:
        item = self._load("serials").get(serial_id)
        return SerialRecord.from_item(item) if item else None

    def find_serial_by_code(self, serial_code: str) -> Optional[SerialRecord]:
        needle = serial_code.upper().replace(" ", "")
        for item in self._load("serials").values():
            if item.get("serial_code", "").upper().replace(" ", "") == needle:
                return SerialRecord.from_item(item)
            if item.get("serial_id", "").upper() == needle:
                return SerialRecord.from_item(item)
        return None

    # --- writes (admin plane) -------------------------------------------
    def put_manufacturer(self, record: ManufacturerRecord) -> None:
        with _LOCK:
            data = self._load("manufacturers")
            data[record.manufacturer_id] = record.to_item()
            self._save("manufacturers", data)

    def put_sku(self, record: SkuRecord) -> None:
        with _LOCK:
            data = self._load("skus")
            data[record.sku_id] = record.to_item()
            self._save("skus", data)

    def put_batch(self, record: BatchRecord) -> None:
        with _LOCK:
            data = self._load("batches")
            data[record.batch_id] = record.to_item()
            self._save("batches", data)

    def put_serial(self, record: SerialRecord) -> None:
        with _LOCK:
            data = self._load("serials")
            data[record.serial_id] = record.to_item()
            self._save("serials", data)

    def put_reference_profile(self, record: ReferenceProfile) -> None:
        with _LOCK:
            data = self._load("reference_profiles")
            data[record.reference_profile_id] = record.to_item()
            self._save("reference_profiles", data)


class LocalReferenceStore(ReferenceStore):
    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = root

    def _load(self) -> Dict[str, Any]:
        return _read_json(os.path.join(self.root, "registry", "reference_profiles.json"), {})

    def get_profile(self, reference_profile_id: str) -> Optional[ReferenceProfile]:
        item = self._load().get(reference_profile_id)
        return ReferenceProfile.from_item(item) if item else None

    def list_profiles(self) -> List[ReferenceProfile]:
        return [ReferenceProfile.from_item(i) for i in self._load().values()]


class LocalScanEventStore(ScanEventStore):
    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = root

    def _file(self) -> str:
        return os.path.join(self.root, "scan_events.json")

    def _load(self) -> Dict[str, Any]:
        return _read_json(self._file(), {})

    def put_event(self, event: ScanEvent) -> None:
        with _LOCK:
            data = self._load()
            data[event.scan_id] = event.to_item()
            _write_json(self._file(), data)

    def get_event(self, scan_id: str) -> Optional[ScanEvent]:
        item = self._load().get(scan_id)
        return ScanEvent.from_item(item) if item else None

    def query_by_serial(self, serial_id: str, limit: int = 50) -> List[ScanEvent]:
        events = [
            ScanEvent.from_item(i)
            for i in self._load().values()
            if i.get("serial_id") == serial_id
        ]
        events.sort(key=lambda e: e.event_time, reverse=True)
        return events[:limit]

    def delete_events_by_demo_tag(self, demo_tag: str) -> int:
        with _LOCK:
            data = self._load()
            doomed = [k for k, v in data.items() if v.get("demo_tag") == demo_tag]
            for key in doomed:
                del data[key]
            _write_json(self._file(), data)
            return len(doomed)

    def clear_all(self) -> None:
        """Test helper. Not part of the :class:`ScanEventStore` port."""
        with _LOCK:
            _write_json(self._file(), {})


def reset_local_root(root: str) -> None:
    """Delete an entire local state directory. Used by tests and dev tooling."""
    if os.path.isdir(root):
        shutil.rmtree(root)
