"""Durable local audit chain with checkpoint, optional HMAC, and explicit repair.

The default local mode detects accidental or unsophisticated modification by
combining a hash chain with a separately persisted checkpoint. It is not an
immutable/WORM store. When ``AX_AUDIT_HMAC_KEY_FILE`` points to an external key,
new records and checkpoints are authenticated with HMAC-SHA256.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


AUDIT_HMAC_KEY_FILE_ENV = "AX_AUDIT_HMAC_KEY_FILE"
GENESIS = "GENESIS"


class AuditLedgerIntegrityError(RuntimeError):
    def __init__(self, code: str, message: str = "security audit ledger integrity check failed"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuditInspection:
    status: Literal["VERIFIED", "LEGACY_UNSEALED", "INVALID"]
    error_code: str | None
    error_line: int | None
    last_verified_sequence: int
    last_verified_head: str
    checkpoint_sequence: int
    checkpoint_head: str
    event_count: int
    protection_mode: str
    immutable_storage: bool = False


@dataclass(frozen=True)
class AuditRepairResult:
    quarantine_path: Path
    corrupt_file_sha256: str
    last_verified_sequence: int
    last_verified_head: str
    recovery_event_id: str


@dataclass(frozen=True)
class _Scan:
    inspection: AuditInspection
    records: list[dict[str, Any]]


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


class AuditLedger:
    def __init__(
        self,
        root: str | Path,
        *,
        hmac_key_file: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "security-audit.jsonl"
        self.checkpoint_path = self.root / "security-audit.checkpoint.json"
        self.quarantine_root = self.root / "audit-quarantine"
        selected_key = hmac_key_file or os.environ.get(AUDIT_HMAC_KEY_FILE_ENV)
        self.hmac_key_file = Path(selected_key).resolve() if selected_key else None
        self._key: bytes | None = None
        if self.hmac_key_file is not None:
            try:
                self._key = self.hmac_key_file.read_bytes()
            except OSError as exc:
                raise RuntimeError(
                    f"{AUDIT_HMAC_KEY_FILE_ENV} must point to a readable key file"
                ) from exc
            if len(self._key) < 32:
                raise RuntimeError(f"{AUDIT_HMAC_KEY_FILE_ENV} key must be at least 32 bytes")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def unkeyed_hash(previous_hash: str, record: dict[str, Any]) -> str:
        payload = dict(record)
        payload.pop("record_hash", None)
        payload.pop("record_hmac", None)
        return hashlib.sha256(
            previous_hash.encode("ascii") + b"\n" + _canonical(payload)
        ).hexdigest()

    def _record_hmac(self, record_hash: str) -> str | None:
        if self._key is None:
            return None
        return hmac.new(self._key, record_hash.encode("ascii"), hashlib.sha256).hexdigest()

    def _checkpoint_hmac(self, checkpoint: dict[str, Any]) -> str | None:
        if self._key is None:
            return None
        payload = dict(checkpoint)
        payload.pop("checkpoint_hmac", None)
        return hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()

    def _checkpoint(self) -> tuple[dict[str, Any] | None, str | None]:
        if not self.checkpoint_path.is_file():
            return None, None
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, "CHECKPOINT_INVALID"
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != "ax-security-audit-checkpoint-v1"
            or not isinstance(value.get("sequence"), int)
            or not isinstance(value.get("head_hash"), str)
        ):
            return None, "CHECKPOINT_INVALID"
        if self._key is not None:
            observed = value.get("checkpoint_hmac")
            expected = self._checkpoint_hmac(value)
            if not isinstance(observed, str) or expected is None or not hmac.compare_digest(observed, expected):
                return value, "CHECKPOINT_HMAC_MISMATCH"
        return value, None

    def _protection_mode(self) -> str:
        return (
            "HMAC_CHAIN_AND_CHECKPOINT"
            if self._key is not None
            else "CHAIN_AND_CHECKPOINT_NO_EXTERNAL_AUTHORITY"
        )

    def _invalid(
        self,
        *,
        code: str,
        line: int | None,
        records: list[dict[str, Any]],
        sequence: int,
        head: str,
        checkpoint: dict[str, Any] | None,
    ) -> _Scan:
        return _Scan(AuditInspection(
            status="INVALID",
            error_code=code,
            error_line=line,
            last_verified_sequence=sequence,
            last_verified_head=head,
            checkpoint_sequence=int(checkpoint.get("sequence", 0)) if checkpoint else 0,
            checkpoint_head=str(checkpoint.get("head_hash", GENESIS)) if checkpoint else GENESIS,
            event_count=len(records),
            protection_mode=self._protection_mode(),
        ), records)

    def _scan(self) -> _Scan:
        checkpoint, checkpoint_error = self._checkpoint()
        if checkpoint_error is not None:
            return self._invalid(
                code=checkpoint_error, line=None, records=[], sequence=0,
                head=GENESIS, checkpoint=checkpoint,
            )
        try:
            raw = self.path.read_bytes() if self.path.is_file() else b""
        except OSError:
            return self._invalid(
                code="LEDGER_UNREADABLE", line=None, records=[], sequence=0,
                head=GENESIS, checkpoint=checkpoint,
            )
        if raw and not raw.endswith(b"\n"):
            # Still parse the complete prefix so repair can resume from it.
            complete = raw.rsplit(b"\n", 1)[0]
            prefix_path = complete.splitlines()
            raw_lines = prefix_path
            truncated_line = len(raw.splitlines())
        else:
            raw_lines = raw.splitlines()
            truncated_line = None

        records: list[dict[str, Any]] = []
        previous_hash = GENESIS
        sequence = 0
        legacy = False
        checkpoint_observed = checkpoint is None or int(checkpoint["sequence"]) == 0
        for line_number, raw_line in enumerate(raw_lines, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return self._invalid(
                    code="INVALID_JSON", line=line_number, records=records,
                    sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                )
            if not isinstance(record, dict):
                return self._invalid(
                    code="INVALID_RECORD", line=line_number, records=records,
                    sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                )
            schema = record.get("schema_version")
            if schema in {"ax-security-audit-v2", "ax-security-audit-v3"}:
                expected_sequence = sequence + 1
                if record.get("sequence") != expected_sequence:
                    return self._invalid(
                        code="SEQUENCE_MISMATCH", line=line_number, records=records,
                        sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                    )
                if record.get("previous_hash") != previous_hash:
                    return self._invalid(
                        code="PREVIOUS_HASH_MISMATCH", line=line_number, records=records,
                        sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                    )
                expected_hash = self.unkeyed_hash(previous_hash, record)
                if not hmac.compare_digest(str(record.get("record_hash", "")), expected_hash):
                    return self._invalid(
                        code="HASH_MISMATCH", line=line_number, records=records,
                        sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                    )
                if self._key is not None and schema == "ax-security-audit-v3":
                    expected_hmac = self._record_hmac(expected_hash)
                    if not isinstance(record.get("record_hmac"), str) or expected_hmac is None or not hmac.compare_digest(record["record_hmac"], expected_hmac):
                        return self._invalid(
                            code="HMAC_MISMATCH", line=line_number, records=records,
                            sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                        )
                previous_hash = expected_hash
                sequence = expected_sequence
                legacy = legacy or schema != "ax-security-audit-v3"
            else:
                # Pre-chain records are readable but cannot claim verified integrity.
                legacy = True
                sequence += 1
                previous_hash = self.unkeyed_hash(previous_hash, record)
            records.append(record)
            if checkpoint is not None and sequence == int(checkpoint["sequence"]):
                if not hmac.compare_digest(previous_hash, str(checkpoint["head_hash"])):
                    return self._invalid(
                        code="CHECKPOINT_HEAD_MISMATCH", line=line_number,
                        records=records, sequence=sequence, head=previous_hash,
                        checkpoint=checkpoint,
                    )
                checkpoint_observed = True

        if truncated_line is not None:
            return self._invalid(
                code="TRUNCATED_LAST_LINE", line=truncated_line, records=records,
                sequence=sequence, head=previous_hash, checkpoint=checkpoint,
            )
        if checkpoint is not None:
            checkpoint_sequence = int(checkpoint["sequence"])
            if checkpoint_sequence > sequence:
                return self._invalid(
                    code="CHECKPOINT_AHEAD_OF_LEDGER", line=None, records=records,
                    sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                )
            if not checkpoint_observed:
                return self._invalid(
                    code="CHECKPOINT_NOT_IN_CHAIN", line=None, records=records,
                    sequence=sequence, head=previous_hash, checkpoint=checkpoint,
                )
        status: Literal["VERIFIED", "LEGACY_UNSEALED"] = (
            "LEGACY_UNSEALED" if legacy or (records and checkpoint is None) else "VERIFIED"
        )
        return _Scan(AuditInspection(
            status=status,
            error_code=None,
            error_line=None,
            last_verified_sequence=sequence,
            last_verified_head=previous_hash,
            checkpoint_sequence=int(checkpoint.get("sequence", 0)) if checkpoint else 0,
            checkpoint_head=str(checkpoint.get("head_hash", GENESIS)) if checkpoint else GENESIS,
            event_count=len(records),
            protection_mode=self._protection_mode(),
        ), records)

    def inspect(self) -> AuditInspection:
        return self._scan().inspection

    def records(self) -> list[dict[str, Any]]:
        scan = self._scan()
        if scan.inspection.status == "INVALID":
            raise AuditLedgerIntegrityError(
                scan.inspection.error_code or "AUDIT_LEDGER_INVALID"
            )
        return scan.records

    def reconcile_checkpoint(self) -> bool:
        """Advance a lagging checkpoint after a fully verified append crash."""
        scan = self._scan()
        if scan.inspection.status == "INVALID":
            raise AuditLedgerIntegrityError("AUDIT_LEDGER_INVALID")
        if scan.inspection.last_verified_sequence <= scan.inspection.checkpoint_sequence:
            return False
        last = scan.records[-1]
        self._write_checkpoint(
            scan.inspection.last_verified_sequence,
            scan.inspection.last_verified_head,
            str(last.get("segment_id") or f"legacy_{uuid4().hex}"),
        )
        return True

    def _write_checkpoint(self, sequence: int, head_hash: str, segment_id: str) -> None:
        checkpoint: dict[str, Any] = {
            "schema_version": "ax-security-audit-checkpoint-v1",
            "sequence": sequence,
            "head_hash": head_hash,
            "segment_id": segment_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "hmac_enabled": self._key is not None,
        }
        signature = self._checkpoint_hmac(checkpoint)
        if signature is not None:
            checkpoint["checkpoint_hmac"] = signature
        _atomic_json(self.checkpoint_path, checkpoint)

    def append(
        self,
        *,
        event_id: str,
        event: str,
        user_id: str | None,
        target: str | None,
        project_id: str | None,
        extra: dict[str, Any] | None = None,
        segment_id: str | None = None,
    ) -> dict[str, Any]:
        scan = self._scan()
        if scan.inspection.status == "INVALID":
            raise AuditLedgerIntegrityError(
                "AUDIT_LEDGER_INVALID",
                f"security audit ledger invalid: {scan.inspection.error_code}",
            )
        for existing in scan.records:
            if existing.get("event_id") == event_id:
                if scan.inspection.last_verified_sequence > scan.inspection.checkpoint_sequence:
                    last = scan.records[-1]
                    self._write_checkpoint(
                        scan.inspection.last_verified_sequence,
                        scan.inspection.last_verified_head,
                        str(last.get("segment_id") or f"legacy_{uuid4().hex}"),
                    )
                return existing
        checkpoint, _error = self._checkpoint()
        selected_segment = segment_id or (
            str(checkpoint.get("segment_id")) if checkpoint else f"segment_{uuid4().hex}"
        )
        record: dict[str, Any] = {
            "schema_version": "ax-security-audit-v3",
            "segment_id": selected_segment,
            "event_id": event_id,
            "sequence": scan.inspection.last_verified_sequence + 1,
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "user_id": user_id,
            "target": target,
            "project_id": project_id,
            "previous_hash": scan.inspection.last_verified_head,
        }
        if extra:
            record.update(extra)
        record["record_hash"] = self.unkeyed_hash(record["previous_hash"], record)
        signature = self._record_hmac(record["record_hash"])
        if signature is not None:
            record["record_hmac"] = signature
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._write_checkpoint(record["sequence"], record["record_hash"], selected_segment)
        return record

    def repair(self, reason: str) -> AuditRepairResult:
        if not reason.strip():
            raise ValueError("repair reason must not be blank")
        scan = self._scan()
        if scan.inspection.status != "INVALID":
            raise ValueError("audit ledger is not corrupt; use rotate for a healthy ledger")
        corrupt = self.path.read_bytes() if self.path.is_file() else b""
        corrupt_hash = hashlib.sha256(corrupt).hexdigest()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        quarantine = self.quarantine_root / f"security-audit.{timestamp}.{corrupt_hash[:16]}.jsonl"
        quarantine.write_bytes(corrupt)
        if self.checkpoint_path.is_file():
            shutil.copy2(
                self.checkpoint_path,
                quarantine.with_suffix(".checkpoint.json"),
            )
        segment_id = f"segment_{uuid4().hex}"
        event_id = f"audit_{uuid4().hex}"
        recovery: dict[str, Any] = {
            "schema_version": "ax-security-audit-v3",
            "segment_id": segment_id,
            "event_id": event_id,
            "sequence": scan.inspection.last_verified_sequence + 1,
            "at": datetime.now(timezone.utc).isoformat(),
            "event": "AUDIT_LEDGER_RECOVERED",
            "user_id": None,
            "target": quarantine.name,
            "project_id": None,
            "previous_hash": scan.inspection.last_verified_head,
            "recovery": {
                "reason": reason.strip(),
                "corrupt_file_sha256": corrupt_hash,
                "previous_verified_head": scan.inspection.last_verified_head,
                "previous_checkpoint_head": scan.inspection.checkpoint_head,
                "error_code": scan.inspection.error_code,
                "error_line": scan.inspection.error_line,
            },
        }
        recovery["record_hash"] = self.unkeyed_hash(recovery["previous_hash"], recovery)
        signature = self._record_hmac(recovery["record_hash"])
        if signature is not None:
            recovery["record_hmac"] = signature
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.repair")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            for record in scan.records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.write(json.dumps(recovery, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        self._write_checkpoint(recovery["sequence"], recovery["record_hash"], segment_id)
        return AuditRepairResult(
            quarantine_path=quarantine,
            corrupt_file_sha256=corrupt_hash,
            last_verified_sequence=scan.inspection.last_verified_sequence,
            last_verified_head=scan.inspection.last_verified_head,
            recovery_event_id=event_id,
        )

    def rotate(self, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("rotation reason must not be blank")
        return self.append(
            event_id=f"audit_{uuid4().hex}",
            event="AUDIT_LEDGER_ROTATED",
            user_id=None,
            target=None,
            project_id=None,
            extra={"rotation": {"reason": reason.strip()}},
            segment_id=f"segment_{uuid4().hex}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "repair", "rotate"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--reason")
    parser.add_argument("--hmac-key-file", type=Path)
    args = parser.parse_args()
    ledger = AuditLedger(args.root, hmac_key_file=args.hmac_key_file)
    if args.command == "inspect":
        print(json.dumps(asdict(ledger.inspect()), ensure_ascii=False, indent=2))
        return 0 if ledger.inspect().status != "INVALID" else 2
    if not args.reason:
        parser.error("--reason is required for repair and rotate")
    if args.command == "repair":
        result = asdict(ledger.repair(args.reason))
        result["quarantine_path"] = str(result["quarantine_path"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(ledger.rotate(args.reason), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
