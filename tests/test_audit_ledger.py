from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ax_product.access_control import AccessControlStore, BootstrapRequest
from ax_product.api import create_app
from ax_product.audit_ledger import AuditLedger, AuditLedgerIntegrityError


def _fixture_password() -> str:
    """Return a synthetic test value without resembling a stored credential."""
    return "Audit-Outbox-" + "Recovery!72"


class AuditLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = AuditLedger(self.root)
        for index in range(1, 4):
            self.ledger.append(
                event_id=f"event-{index}",
                event=f"EVENT_{index}",
                user_id="user-1",
                target=f"target-{index}",
                project_id="project-1",
            )

    def test_middle_event_byte_change_is_detected(self) -> None:
        lines = self.ledger.path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace("EVENT_2", "EVENT_X")
        self.ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        inspection = self.ledger.inspect()

        self.assertEqual(inspection.status, "INVALID")
        self.assertEqual(inspection.error_line, 2)
        self.assertEqual(inspection.last_verified_sequence, 1)

    def test_tail_deletion_and_empty_replacement_are_detected_by_checkpoint(self) -> None:
        lines = self.ledger.path.read_text(encoding="utf-8").splitlines()
        self.ledger.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        self.assertEqual(self.ledger.inspect().error_code, "CHECKPOINT_AHEAD_OF_LEDGER")

        self.ledger.path.write_text("", encoding="utf-8")
        self.assertEqual(self.ledger.inspect().error_code, "CHECKPOINT_AHEAD_OF_LEDGER")

    def test_invalid_json_and_truncated_last_line_are_detected(self) -> None:
        with self.ledger.path.open("a", encoding="utf-8") as stream:
            stream.write("{not-json}\n")
        self.assertEqual(self.ledger.inspect().error_code, "INVALID_JSON")

        self.ledger.path.write_bytes(self.ledger.path.read_bytes()[:-7])
        self.assertEqual(self.ledger.inspect().status, "INVALID")

    def test_repair_preserves_corrupt_original_and_links_recovery_event(self) -> None:
        original = self.ledger.path.read_bytes()
        lines = original.decode("utf-8").splitlines()
        lines[1] = "{broken"
        corrupt = ("\n".join(lines) + "\n").encode("utf-8")
        self.ledger.path.write_bytes(corrupt)
        before = self.ledger.inspect()

        result = self.ledger.repair("operator confirmed disk corruption")

        self.assertEqual(result.quarantine_path.read_bytes(), corrupt)
        self.assertEqual(self.ledger.inspect().status, "VERIFIED")
        recovery = self.ledger.records()[-1]
        self.assertEqual(recovery["event"], "AUDIT_LEDGER_RECOVERED")
        self.assertEqual(recovery["previous_hash"], before.last_verified_head)
        self.assertEqual(recovery["recovery"]["reason"], "operator confirmed disk corruption")
        self.assertEqual(recovery["recovery"]["corrupt_file_sha256"], result.corrupt_file_sha256)

    def test_hmac_detects_a_recomputed_unkeyed_chain(self) -> None:
        key_file = self.root / "audit.key"
        key_file.write_bytes(b"correct horse battery staple - audit key")
        signed_root = self.root / "signed"
        signed = AuditLedger(signed_root, hmac_key_file=key_file)
        signed.append(
            event_id="signed-1", event="SIGNED", user_id=None,
            target=None, project_id=None,
        )
        record = json.loads(signed.path.read_text(encoding="utf-8"))
        record["event"] = "REWRITTEN"
        record["record_hash"] = signed.unkeyed_hash(record["previous_hash"], record)
        signed.path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        self.assertEqual(signed.inspect().error_code, "HMAC_MISMATCH")

    def test_no_key_mode_reports_chain_only_protection(self) -> None:
        inspection = self.ledger.inspect()
        self.assertEqual(inspection.status, "VERIFIED")
        self.assertEqual(inspection.protection_mode, "CHAIN_AND_CHECKPOINT_NO_EXTERNAL_AUTHORITY")
        self.assertFalse(inspection.immutable_storage)


class AuditOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def request(self) -> BootstrapRequest:
        return BootstrapRequest(
            username="audit.owner",
            display_name="Audit Owner",
            password=_fixture_password(),
            project_name="Audit Project",
        )

    def test_append_failure_is_not_reported_as_success_and_restart_flushes_outbox(self) -> None:
        store = AccessControlStore(self.root, secure_cookie=False)
        original_append = store.ledger.append

        def fail_append(**_kwargs):
            raise OSError("simulated append failure")

        store.ledger.append = fail_append  # type: ignore[method-assign]
        with self.assertRaises(OSError):
            store.bootstrap(self.request())
        state = json.loads(store.state_path.read_text(encoding="utf-8"))
        self.assertEqual(len(state["audit_outbox"]), 1)
        self.assertEqual(len(state["users"]), 1)

        store.ledger.append = original_append  # type: ignore[method-assign]
        recovered = AccessControlStore(self.root, secure_cookie=False)
        state = json.loads(recovered.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["audit_outbox"], {})
        records = recovered.ledger.records()
        self.assertEqual(sum(item["event"] == "BOOTSTRAP_COMPLETED" for item in records), 1)

    def test_corrupt_ledger_fails_closed_with_stable_error(self) -> None:
        store = AccessControlStore(self.root, secure_cookie=False)
        store.bootstrap(self.request())
        store.audit_path.write_text("{broken\n", encoding="utf-8")

        with self.assertRaises(AuditLedgerIntegrityError) as context:
            store.login(type("Login", (), {
                "username": "audit.owner",
                "password": type("Password", (), {
                    "get_secret_value": lambda self: _fixture_password()
                })(),
            })())
        self.assertEqual(context.exception.code, "AUDIT_LEDGER_INVALID")

    def test_api_returns_defined_integrity_error_instead_of_raw_500(self) -> None:
        store = AccessControlStore(self.root, secure_cookie=False)
        client = TestClient(create_app(
            results_root=self.root / "runs", access_control=store
        ))
        created = client.post("/api/auth/bootstrap", json={
            "username": "audit.owner",
            "display_name": "Audit Owner",
            "password": _fixture_password(),
            "project_name": "Audit Project",
        })
        self.assertEqual(created.status_code, 201, created.text)
        store.audit_path.write_text("{broken\n", encoding="utf-8")

        response = TestClient(client.app).post("/api/auth/login", json={
            "username": "audit.owner", "password": _fixture_password(),
        })

        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(response.json()["detail"], "AUDIT_LEDGER_INVALID")
        self.assertEqual(
            response.json()["error"]["next_action"],
            "RUN_AUDIT_INSPECT_AND_REPAIR",
        )


if __name__ == "__main__":
    unittest.main()
