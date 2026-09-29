"""Local-first authentication, project isolation, and task approval storage.

The store deliberately uses opaque server-side sessions.  Passwords, session
tokens, and CSRF tokens are never persisted in recoverable form.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from pydantic import Field, SecretStr, field_validator, model_validator

from .models import StrictProductModel
from .audit_ledger import AuditLedger, AuditLedgerIntegrityError
from .execution_control import (
    DataTransferApprovalRequest, DataTransferApprovalView,
    ExecutionPolicyUpdate, ProjectExecutionPolicyView, ProjectExecutionUsage,
)
from .governance import (
    ProjectAuditEvent, ProjectAuditLog, ProjectRetentionPolicyUpdate,
    ProjectRetentionPolicyView,
)
from .poc_evaluation import PocDecisionUpdate, PocDecisionView


ACCESS_ROOT_ENV = "AX_PRODUCT_ACCESS_ROOT"
SECURE_COOKIE_ENV = "AX_PRODUCT_SECURE_COOKIES"
SESSION_HOURS_ENV = "AX_PRODUCT_SESSION_HOURS"
LOGIN_MAX_FAILURES_ENV = "AX_PRODUCT_LOGIN_MAX_FAILURES"
LOGIN_WINDOW_MINUTES_ENV = "AX_PRODUCT_LOGIN_WINDOW_MINUTES"
LOGIN_LOCK_MINUTES_ENV = "AX_PRODUCT_LOGIN_LOCK_MINUTES"
COOKIE_NAME = "ax_preflight_session"
STATE_SCHEMA = "ax-access-control-v1"
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


class AccessControlError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class UserView(StrictProductModel):
    user_id: str
    username: str
    display_name: str
    global_role: Literal["ADMIN", "MEMBER"]


class BootstrapRequest(StrictProductModel):
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=256)
    project_name: str = Field(default="사내 PoC", min_length=1, max_length=80)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("username must use 3-32 lowercase letters, numbers, dot, dash, or underscore")
        return normalized

    @field_validator("display_name", "project_name")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def password_not_identity(self) -> "BootstrapRequest":
        if self.username in self.password.get_secret_value().casefold():
            raise ValueError("password must not contain the username")
        return self


class LoginRequest(StrictProductModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class CreateUserRequest(StrictProductModel):
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=256)
    global_role: Literal["ADMIN", "MEMBER"] = "MEMBER"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return BootstrapRequest.normalize_username(value)

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def password_not_identity(self) -> "CreateUserRequest":
        if self.username in self.password.get_secret_value().casefold():
            raise ValueError("password must not contain the username")
        return self


class ProjectCreateRequest(StrictProductModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)

    @field_validator("name", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


class ProjectMemberRequest(StrictProductModel):
    username: str = Field(min_length=3, max_length=32)
    role: Literal["EDITOR", "VIEWER"]

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class ProjectView(StrictProductModel):
    project_id: str
    name: str
    description: str
    member_role: Literal["OWNER", "EDITOR", "VIEWER"]
    member_count: int = Field(ge=1)
    created_at: datetime


class ProjectMemberView(StrictProductModel):
    user: UserView
    role: Literal["OWNER", "EDITOR", "VIEWER"]


class SessionRevocationResult(StrictProductModel):
    user_id: str
    revoked_sessions: int = Field(ge=0)


class TaskCreateRequest(StrictProductModel):
    dataset_profile: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=2_000)
    description: str = Field(min_length=1, max_length=2_000)
    owner_role: str = Field(min_length=1, max_length=120)
    success_criteria: list[str] = Field(min_length=1, max_length=12)

    @field_validator("dataset_profile", "category", "question", "description", "owner_role")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("success_criteria")
    @classmethod
    def clean_criteria(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned or any(len(value) > 300 for value in cleaned):
            raise ValueError("success_criteria must contain 1-12 nonblank values up to 300 characters")
        return cleaned


class ProjectTaskView(StrictProductModel):
    task_id: str
    project_id: str
    dataset_profile: str
    category: str
    question: str
    description: str
    owner_role: str
    success_criteria: list[str]
    status: Literal["DRAFT", "APPROVED"]
    created_by: str
    created_at: datetime
    approval_id: str | None = None
    approved_by: str | None = None
    approved_by_role: str | None = None
    approved_at: datetime | None = None


class AuthSessionResponse(StrictProductModel):
    authentication_required: bool = True
    authenticated: bool
    bootstrap_required: bool
    user: UserView | None = None
    csrf_token: str | None = None
    expires_at: datetime | None = None


class AccessIdentity(StrictProductModel):
    user: UserView
    session_hash: str
    csrf_hashes: list[str]
    expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


class AccessControlStore:
    """Small persistent identity boundary for a single-company PoC instance."""

    def __init__(
        self,
        root: Path,
        *,
        secure_cookie: bool | None = None,
        login_max_failures: int | None = None,
        login_window_minutes: int | None = None,
        login_lock_minutes: int | None = None,
    ):
        self.root = Path(root).resolve()
        self.state_path = self.root / "state.json"
        self.ledger = AuditLedger(self.root)
        self.audit_path = self.ledger.path
        self._lock = RLock()
        self.password_hasher = PasswordHasher()
        self.secure_cookie = (
            os.environ.get(SECURE_COOKIE_ENV, "false").strip().casefold() == "true"
            if secure_cookie is None else secure_cookie
        )
        raw_hours = os.environ.get(SESSION_HOURS_ENV, "8")
        try:
            self.session_hours = int(raw_hours)
        except ValueError as exc:
            raise RuntimeError(f"{SESSION_HOURS_ENV} must be an integer") from exc
        if not 1 <= self.session_hours <= 168:
            raise RuntimeError(f"{SESSION_HOURS_ENV} must be between 1 and 168")
        self.login_max_failures = self._bounded_setting(
            LOGIN_MAX_FAILURES_ENV, login_max_failures, default=5, minimum=3, maximum=20
        )
        self.login_window_minutes = self._bounded_setting(
            LOGIN_WINDOW_MINUTES_ENV, login_window_minutes, default=15, minimum=1, maximum=1440
        )
        self.login_lock_minutes = self._bounded_setting(
            LOGIN_LOCK_MINUTES_ENV, login_lock_minutes, default=15, minimum=1, maximum=1440
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if not self.state_path.exists():
                self._write(self._empty_state())
            else:
                self._read()
            try:
                self.ledger.reconcile_checkpoint()
                self._flush_audit_outbox()
            except (AuditLedgerIntegrityError, OSError):
                # Keep the recoverable outbox in state and allow read/status
                # endpoints to start. Risky writes will continue to fail closed.
                pass
        # A constant dummy hash prevents a missing username from taking a
        # conspicuously faster path than an existing username.
        self._dummy_hash = self.password_hasher.hash(secrets.token_urlsafe(32))

    @staticmethod
    def _empty_state() -> dict:
        return {
            "schema_version": STATE_SCHEMA,
            "users": {},
            "sessions": {},
            "projects": {},
            "tasks": {},
            "login_attempts": {},
            "execution_policies": {},
            "transfer_approvals": {},
            "execution_usage": {},
            "retention_policies": {},
            "poc_decisions": {},
            "deletion_tombstones": {},
            "audit_outbox": {},
        }

    @staticmethod
    def _bounded_setting(
        name: str, override: int | None, *, default: int, minimum: int, maximum: int
    ) -> int:
        raw = str(override) if override is not None else os.environ.get(name, str(default))
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
        return value

    def _read(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise RuntimeError("access-control state is missing or invalid") from exc
        if state.get("schema_version") != STATE_SCHEMA:
            raise RuntimeError("unsupported access-control state schema")
        for key in ("users", "sessions", "projects", "tasks"):
            if not isinstance(state.get(key), dict):
                raise RuntimeError(f"access-control state has no {key} mapping")
        for key in (
            "login_attempts", "execution_policies", "transfer_approvals",
            "execution_usage", "retention_policies", "poc_decisions",
            "deletion_tombstones", "audit_outbox",
        ):
            state.setdefault(key, {})
            if not isinstance(state[key], dict):
                raise RuntimeError(f"access-control state has no {key} mapping")
        return state

    def _write(self, state: dict) -> None:
        _atomic_json(self.state_path, state)

    def _flush_audit_outbox(self) -> None:
        state = self._read()
        pending = dict(state.get("audit_outbox", {}))
        changed = False
        for event_id, event in pending.items():
            self.ledger.append(event_id=event_id, **event)
            state["audit_outbox"].pop(event_id, None)
            changed = True
        if changed:
            self._write(state)

    def _commit(
        self,
        state: dict,
        event: str,
        *,
        user_id: str | None,
        target: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Persist state plus a recoverable, idempotent audit outbox event."""
        inspection = self.ledger.inspect()
        if inspection.status == "INVALID":
            raise AuditLedgerIntegrityError("AUDIT_LEDGER_INVALID")
        event_id = f"audit_{uuid4().hex}"
        state.setdefault("audit_outbox", {})[event_id] = {
            "event": event,
            "user_id": user_id,
            "target": target,
            "project_id": project_id,
        }
        self._write(state)
        self.ledger.append(
            event_id=event_id,
            event=event,
            user_id=user_id,
            target=target,
            project_id=project_id,
        )
        state["audit_outbox"].pop(event_id, None)
        self._write(state)

    def _read_audit_records(self) -> list[dict]:
        return self.ledger.records()

    def _audit(
        self,
        event: str,
        *,
        user_id: str | None,
        target: str | None = None,
        project_id: str | None = None,
    ) -> None:
        with self._lock:
            self.ledger.append(
                event_id=f"audit_{uuid4().hex}",
                event=event,
                user_id=user_id,
                target=target,
                project_id=project_id,
            )

    @staticmethod
    def _user_view(record: dict) -> UserView:
        return UserView(
            user_id=record["user_id"], username=record["username"],
            display_name=record["display_name"], global_role=record["global_role"],
        )

    def bootstrap_required(self) -> bool:
        with self._lock:
            return not bool(self._read()["users"])

    def _create_user_record(
        self, state: dict, request: BootstrapRequest | CreateUserRequest, role: str
    ) -> dict:
        if any(user["username"] == request.username for user in state["users"].values()):
            raise AccessControlError("USERNAME_EXISTS", "이미 사용 중인 아이디입니다.")
        user_id = f"usr_{uuid4().hex}"
        record = {
            "user_id": user_id,
            "username": request.username,
            "display_name": request.display_name,
            "global_role": role,
            "password_hash": self.password_hasher.hash(request.password.get_secret_value()),
            "created_at": _utcnow().isoformat(),
        }
        state["users"][user_id] = record
        return record

    def bootstrap(self, request: BootstrapRequest) -> tuple[UserView, ProjectView, str, str, datetime]:
        with self._lock:
            state = self._read()
            if state["users"]:
                raise AccessControlError("BOOTSTRAP_CLOSED", "초기 관리자 설정이 이미 완료되었습니다.")
            user_record = self._create_user_record(state, request, "ADMIN")
            project = self._create_project_record(
                state, user_record["user_id"], request.project_name,
                "첫 사내 검증을 위한 기본 프로젝트",
            )
            token, csrf, expires_at = self._new_session(state, user_record["user_id"])
            self._commit(state,
                "BOOTSTRAP_COMPLETED", user_id=user_record["user_id"],
                target=project["project_id"], project_id=project["project_id"],
            )
            return (
                self._user_view(user_record),
                self._project_view(project, user_record["user_id"]),
                token, csrf, expires_at,
            )

    def create_user(self, actor: UserView, request: CreateUserRequest) -> UserView:
        if actor.global_role != "ADMIN":
            raise AccessControlError("ADMIN_REQUIRED", "관리자만 사용자를 만들 수 있습니다.")
        with self._lock:
            state = self._read()
            record = self._create_user_record(state, request, request.global_role)
            self._commit(
                state, "USER_CREATED", user_id=actor.user_id,
                target=record["user_id"],
            )
            return self._user_view(record)

    def users(self, actor: UserView) -> list[UserView]:
        if actor.global_role != "ADMIN":
            raise AccessControlError("ADMIN_REQUIRED", "관리자만 사용자 목록을 볼 수 있습니다.")
        with self._lock:
            records = list(self._read()["users"].values())
        return sorted((self._user_view(item) for item in records), key=lambda item: item.username)

    def user_by_id(self, user_id: str) -> UserView:
        """Resolve a previously authenticated batch owner for an internal worker."""
        with self._lock:
            record = self._read()["users"].get(user_id)
        if record is None:
            raise AccessControlError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        return self._user_view(record)

    def _new_session(self, state: dict, user_id: str) -> tuple[str, str, datetime]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires_at = _utcnow() + timedelta(hours=self.session_hours)
        state["sessions"][_digest(token)] = {
            "user_id": user_id,
            "csrf_hashes": [_digest(csrf)],
            "created_at": _utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        return token, csrf, expires_at

    def login(self, request: LoginRequest) -> tuple[UserView, str, str, datetime]:
        username = request.username.strip().casefold()
        with self._lock:
            state = self._read()
            now = _utcnow()
            attempt_key = _digest(username)
            attempt = state["login_attempts"].get(attempt_key, {})
            locked_until_raw = attempt.get("locked_until")
            locked_until = (
                datetime.fromisoformat(locked_until_raw)
                if isinstance(locked_until_raw, str) else None
            )
            if locked_until is not None and locked_until > now:
                self._audit("LOGIN_RATE_LIMITED", user_id=None, target=attempt_key[:12])
                raise AccessControlError(
                    "LOGIN_RATE_LIMITED",
                    f"로그인 시도가 잠시 제한되었습니다. {self.login_lock_minutes}분 뒤 다시 시도하세요.",
                )
            record = next(
                (user for user in state["users"].values() if user["username"] == username),
                None,
            )
            candidate_hash = self._dummy_hash if record is None else record["password_hash"]
            try:
                valid = self.password_hasher.verify(
                    candidate_hash, request.password.get_secret_value()
                )
            except (VerifyMismatchError, InvalidHashError):
                valid = False
            if record is None or not valid:
                cutoff = now - timedelta(minutes=self.login_window_minutes)
                failures = []
                for raw in attempt.get("failures", []):
                    if isinstance(raw, str):
                        observed = datetime.fromisoformat(raw)
                        if observed >= cutoff:
                            failures.append(observed.isoformat())
                failures.append(now.isoformat())
                next_attempt = {"failures": failures}
                if len(failures) >= self.login_max_failures:
                    next_attempt["locked_until"] = (
                        now + timedelta(minutes=self.login_lock_minutes)
                    ).isoformat()
                state["login_attempts"][attempt_key] = next_attempt
                self._commit(
                    state, "LOGIN_FAILED", user_id=None, target=attempt_key[:12]
                )
                if "locked_until" in next_attempt:
                    raise AccessControlError(
                        "LOGIN_RATE_LIMITED",
                        f"로그인 시도가 잠시 제한되었습니다. {self.login_lock_minutes}분 뒤 다시 시도하세요.",
                    )
                raise AccessControlError("INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.")
            state["login_attempts"].pop(attempt_key, None)
            if self.password_hasher.check_needs_rehash(record["password_hash"]):
                record["password_hash"] = self.password_hasher.hash(
                    request.password.get_secret_value()
                )
            token, csrf, expires_at = self._new_session(state, record["user_id"])
            self._commit(state, "LOGIN_SUCCEEDED", user_id=record["user_id"])
            return self._user_view(record), token, csrf, expires_at

    def revoke_sessions(self, actor: UserView, user_id: str) -> SessionRevocationResult:
        if actor.global_role != "ADMIN":
            raise AccessControlError("ADMIN_REQUIRED", "관리자만 로그인 세션을 종료할 수 있습니다.")
        with self._lock:
            state = self._read()
            if user_id not in state["users"]:
                raise AccessControlError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
            matching = [
                token_hash for token_hash, session in state["sessions"].items()
                if session["user_id"] == user_id
            ]
            for token_hash in matching:
                del state["sessions"][token_hash]
            self._commit(
                state, "USER_SESSIONS_REVOKED",
                user_id=actor.user_id, target=user_id,
            )
        return SessionRevocationResult(user_id=user_id, revoked_sessions=len(matching))

    def authenticate(self, token: str | None) -> AccessIdentity | None:
        if not token:
            return None
        token_hash = _digest(token)
        with self._lock:
            state = self._read()
            session = state["sessions"].get(token_hash)
            if session is None:
                return None
            expires_at = datetime.fromisoformat(session["expires_at"])
            if expires_at <= _utcnow():
                del state["sessions"][token_hash]
                self._write(state)
                return None
            user = state["users"].get(session["user_id"])
            if user is None:
                return None
            csrf_hashes = session.get("csrf_hashes")
            if not isinstance(csrf_hashes, list):
                # Read v1 state written before multi-tab CSRF support without
                # forcing an administrator to recreate the local PoC instance.
                legacy_hash = session.get("csrf_hash")
                csrf_hashes = [legacy_hash] if isinstance(legacy_hash, str) else []
            return AccessIdentity(
                user=self._user_view(user), session_hash=token_hash,
                csrf_hashes=csrf_hashes, expires_at=expires_at,
            )

    @staticmethod
    def csrf_valid(identity: AccessIdentity, token: str | None) -> bool:
        if not token:
            return False
        candidate = _digest(token)
        return any(hmac.compare_digest(item, candidate) for item in identity.csrf_hashes)

    def rotate_csrf(self, identity: AccessIdentity) -> str:
        """Issue a fresh browser-readable token while retaining only its digest."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            state = self._read()
            session = state["sessions"].get(identity.session_hash)
            if session is None:
                raise AccessControlError("SESSION_EXPIRED", "로그인 세션이 만료되었습니다.")
            existing = session.get("csrf_hashes")
            if not isinstance(existing, list):
                legacy_hash = session.pop("csrf_hash", None)
                existing = [legacy_hash] if isinstance(legacy_hash, str) else []
            # A bounded digest history keeps writes working across a few open
            # tabs while every browser-readable token remains unrecoverable at
            # rest. Old tokens naturally disappear as sessions are refreshed.
            session["csrf_hashes"] = [*existing, _digest(token)][-8:]
            self._write(state)
        return token

    def logout(self, identity: AccessIdentity) -> None:
        with self._lock:
            state = self._read()
            state["sessions"].pop(identity.session_hash, None)
            self._commit(state, "LOGOUT", user_id=identity.user.user_id)

    @staticmethod
    def _create_project_record(state: dict, owner_id: str, name: str, description: str) -> dict:
        project_id = f"prj_{uuid4().hex}"
        record = {
            "project_id": project_id,
            "name": name,
            "description": description,
            "members": {owner_id: "OWNER"},
            "created_by": owner_id,
            "created_at": _utcnow().isoformat(),
        }
        state["projects"][project_id] = record
        return record

    @staticmethod
    def _project_view(record: dict, user_id: str) -> ProjectView:
        return ProjectView(
            project_id=record["project_id"], name=record["name"],
            description=record["description"], member_role=record["members"][user_id],
            member_count=len(record["members"]),
            created_at=datetime.fromisoformat(record["created_at"]),
        )

    def projects(self, user: UserView) -> list[ProjectView]:
        with self._lock:
            records = [
                record for record in self._read()["projects"].values()
                if user.user_id in record["members"]
            ]
        records.sort(key=lambda item: item["created_at"])
        return [self._project_view(record, user.user_id) for record in records]

    def create_project(self, user: UserView, request: ProjectCreateRequest) -> ProjectView:
        with self._lock:
            state = self._read()
            record = self._create_project_record(state, user.user_id, request.name, request.description)
            self._commit(state,
                "PROJECT_CREATED", user_id=user.user_id,
                target=record["project_id"], project_id=record["project_id"],
            )
            return self._project_view(record, user.user_id)

    def require_project(self, user: UserView, project_id: str, *, write: bool = False, owner: bool = False) -> str:
        with self._lock:
            project = self._read()["projects"].get(project_id)
        role = None if project is None else project["members"].get(user.user_id)
        if role is None:
            raise AccessControlError("PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다.")
        if owner and role != "OWNER":
            raise AccessControlError("PROJECT_OWNER_REQUIRED", "프로젝트 소유자만 이 작업을 할 수 있습니다.")
        if write and role not in {"OWNER", "EDITOR"}:
            raise AccessControlError("PROJECT_WRITE_FORBIDDEN", "이 프로젝트에 쓰기 권한이 없습니다.")
        return role

    def add_member(self, actor: UserView, project_id: str, request: ProjectMemberRequest) -> ProjectMemberView:
        self.require_project(actor, project_id, owner=True)
        with self._lock:
            state = self._read()
            user = next(
                (item for item in state["users"].values() if item["username"] == request.username),
                None,
            )
            if user is None:
                raise AccessControlError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
            state["projects"][project_id]["members"][user["user_id"]] = request.role
            self._commit(state,
                "PROJECT_MEMBER_SET", user_id=actor.user_id,
                target=f"{project_id}:{user['user_id']}", project_id=project_id,
            )
            return ProjectMemberView(user=self._user_view(user), role=request.role)

    def remove_member(self, actor: UserView, project_id: str, user_id: str) -> None:
        self.require_project(actor, project_id, owner=True)
        with self._lock:
            state = self._read()
            project = state["projects"].get(project_id)
            if project is None or user_id not in project["members"]:
                raise AccessControlError("USER_NOT_FOUND", "프로젝트 구성원을 찾을 수 없습니다.")
            if project["members"][user_id] == "OWNER":
                raise AccessControlError("PROJECT_OWNER_REQUIRED", "프로젝트 소유자는 제거할 수 없습니다.")
            del project["members"][user_id]
            self._commit(state,
                "PROJECT_MEMBER_REMOVED", user_id=actor.user_id,
                target=f"{project_id}:{user_id}", project_id=project_id,
            )

    def members(self, actor: UserView, project_id: str) -> list[ProjectMemberView]:
        self.require_project(actor, project_id)
        with self._lock:
            state = self._read()
            project = state["projects"][project_id]
            result = [
                ProjectMemberView(user=self._user_view(state["users"][user_id]), role=role)
                for user_id, role in project["members"].items()
            ]
        return sorted(result, key=lambda item: (item.role != "OWNER", item.user.username))

    @staticmethod
    def _task_view(record: dict) -> ProjectTaskView:
        payload = dict(record)
        payload["created_at"] = datetime.fromisoformat(record["created_at"])
        if record.get("approved_at") is not None:
            payload["approved_at"] = datetime.fromisoformat(record["approved_at"])
        return ProjectTaskView.model_validate(payload)

    def tasks(self, user: UserView, project_id: str, *, dataset_profile: str | None = None) -> list[ProjectTaskView]:
        self.require_project(user, project_id)
        with self._lock:
            records = [
                task for task in self._read()["tasks"].values()
                if task["project_id"] == project_id
                and (dataset_profile is None or task["dataset_profile"] == dataset_profile)
            ]
        records.sort(key=lambda item: item["created_at"])
        return [self._task_view(record) for record in records]

    def create_task(self, user: UserView, project_id: str, request: TaskCreateRequest) -> ProjectTaskView:
        self.require_project(user, project_id, write=True)
        with self._lock:
            state = self._read()
            task_id = f"task_{uuid4().hex}"
            record = {
                "task_id": task_id,
                "project_id": project_id,
                **request.model_dump(),
                "status": "DRAFT",
                "created_by": user.user_id,
                "created_at": _utcnow().isoformat(),
                "approval_id": None,
                "approved_by": None,
                "approved_by_role": None,
                "approved_at": None,
            }
            state["tasks"][task_id] = record
            self._commit(state,
                "TASK_CREATED", user_id=user.user_id,
                target=task_id, project_id=project_id,
            )
            return self._task_view(record)

    def approve_task(self, user: UserView, project_id: str, task_id: str) -> ProjectTaskView:
        role = self.require_project(user, project_id, owner=True)
        with self._lock:
            state = self._read()
            record = state["tasks"].get(task_id)
            if record is None or record["project_id"] != project_id:
                raise AccessControlError("TASK_NOT_FOUND", "업무를 찾을 수 없습니다.")
            if record["status"] != "APPROVED":
                record.update({
                    "status": "APPROVED",
                    "approval_id": f"apr_{uuid4().hex}",
                    "approved_by": user.user_id,
                    "approved_by_role": role,
                    "approved_at": _utcnow().isoformat(),
                })
                self._commit(state,
                    "TASK_APPROVED", user_id=user.user_id,
                    target=task_id, project_id=project_id,
                )
            return self._task_view(record)

    def task(self, user: UserView, project_id: str, task_id: str) -> ProjectTaskView:
        self.require_project(user, project_id)
        with self._lock:
            record = self._read()["tasks"].get(task_id)
        if record is None or record["project_id"] != project_id:
            raise AccessControlError("TASK_NOT_FOUND", "업무를 찾을 수 없습니다.")
        return self._task_view(record)

    @staticmethod
    def _approval_key(project_id: str, dataset_profile: str) -> str:
        return _digest(f"{project_id}\n{dataset_profile}")

    @staticmethod
    def _policy_view(record: dict) -> ProjectExecutionPolicyView:
        payload = dict(record)
        payload["updated_at"] = datetime.fromisoformat(record["updated_at"])
        return ProjectExecutionPolicyView.model_validate(payload)

    @staticmethod
    def _transfer_view(record: dict) -> DataTransferApprovalView:
        payload = dict(record)
        payload["approved_at"] = datetime.fromisoformat(record["approved_at"])
        payload["expires_at"] = datetime.fromisoformat(record["expires_at"])
        return DataTransferApprovalView.model_validate(payload)

    def execution_policy(
        self, user: UserView, project_id: str
    ) -> ProjectExecutionPolicyView | None:
        self.require_project(user, project_id)
        with self._lock:
            record = self._read()["execution_policies"].get(project_id)
        return None if record is None else self._policy_view(record)

    def update_execution_policy(
        self, actor: UserView, project_id: str, request: ExecutionPolicyUpdate
    ) -> ProjectExecutionPolicyView:
        self.require_project(actor, project_id, owner=True)
        now = _utcnow()
        view = ProjectExecutionPolicyView(
            project_id=project_id,
            updated_by=actor.user_id,
            updated_at=now,
            **request.model_dump(),
        )
        with self._lock:
            state = self._read()
            state["execution_policies"][project_id] = view.model_dump(mode="json")
            self._commit(state,
                "EXECUTION_POLICY_UPDATED", user_id=actor.user_id,
                target=project_id, project_id=project_id,
            )
        return view

    def transfer_approval(
        self, user: UserView, project_id: str, dataset_profile: str
    ) -> DataTransferApprovalView | None:
        self.require_project(user, project_id)
        key = self._approval_key(project_id, dataset_profile)
        with self._lock:
            record = self._read()["transfer_approvals"].get(key)
        return None if record is None else self._transfer_view(record)

    def approve_data_transfer(
        self,
        actor: UserView,
        project_id: str,
        request: DataTransferApprovalRequest,
        *,
        pii_affected_file_count: int,
        dataset_revision_fingerprint: str,
    ) -> DataTransferApprovalView:
        self.require_project(actor, project_id, owner=True)
        policy = self.execution_policy(actor, project_id)
        if policy is None:
            raise AccessControlError(
                "EXECUTION_POLICY_REQUIRED", "실행 정책을 먼저 설정해야 합니다."
            )
        if not hmac.compare_digest(
            policy.model.encode("utf-8"), request.model.encode("utf-8")
        ):
            raise AccessControlError(
                "MODEL_NOT_APPROVED", "승인 모델이 프로젝트 실행 정책과 일치하지 않습니다."
            )
        if pii_affected_file_count and request.data_classification == "PUBLIC":
            raise AccessControlError(
                "PII_CLASSIFICATION_REQUIRED",
                "개인정보 가능 패턴이 있는 자료는 PUBLIC으로 승인할 수 없습니다.",
            )
        now = _utcnow()
        view = DataTransferApprovalView(
            approval_id=f"data_{uuid4().hex}",
            project_id=project_id,
            dataset_profile=request.dataset_profile,
            dataset_revision_fingerprint=dataset_revision_fingerprint,
            model=request.model,
            data_classification=request.data_classification,
            pii_affected_file_count=pii_affected_file_count,
            approved_by=actor.user_id,
            approved_at=now,
            expires_at=now + timedelta(days=request.valid_days),
        )
        key = self._approval_key(project_id, request.dataset_profile)
        with self._lock:
            state = self._read()
            state["transfer_approvals"][key] = view.model_dump(mode="json")
            self._commit(state,
                "DATA_TRANSFER_APPROVED", user_id=actor.user_id,
                target=f"{project_id}:{request.dataset_profile}",
                project_id=project_id,
            )
        return view

    def revoke_data_transfer(
        self, actor: UserView, project_id: str, dataset_profile: str
    ) -> None:
        self.require_project(actor, project_id, owner=True)
        key = self._approval_key(project_id, dataset_profile)
        with self._lock:
            state = self._read()
            state["transfer_approvals"].pop(key, None)
            self._commit(state,
                "DATA_TRANSFER_REVOKED", user_id=actor.user_id,
                target=f"{project_id}:{dataset_profile}", project_id=project_id,
            )

    def execution_usage(
        self, user: UserView, project_id: str, *, running_runs: int
    ) -> ProjectExecutionUsage | None:
        self.require_project(user, project_id)
        policy = self.execution_policy(user, project_id)
        if policy is None:
            return None
        now = _utcnow()
        cutoff = now - timedelta(hours=24)
        with self._lock:
            records = list(self._read()["execution_usage"].values())
        recent = []
        for record in records:
            if record.get("project_id") != project_id:
                continue
            try:
                reserved_at = datetime.fromisoformat(record["reserved_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if reserved_at >= cutoff and record.get("status", "FINALIZED") != "RELEASED":
                recent.append(record)
        active = [record for record in recent if record.get("status") == "RESERVED"]
        finalized = [record for record in recent if record.get("status", "FINALIZED") == "FINALIZED"]
        capacity_runs = len(active) + len(finalized)
        reserved_cost = sum(
            int(record.get("estimated_cost_cents", 0)) for record in active
        )
        estimated_spend = sum(
            int(record.get("estimated_cost_cents", 0)) for record in finalized
        )
        return ProjectExecutionUsage(
            window_started_at=cutoff,
            reserved_runs=len(active),
            finalized_runs=len(finalized),
            running_runs=running_runs,
            estimated_reserved_cents=reserved_cost,
            estimated_spend_cents=estimated_spend,
            remaining_run_capacity=max(0, policy.daily_run_limit - capacity_runs),
            remaining_budget_cents=max(
                0, policy.daily_budget_cents - estimated_spend - reserved_cost
            ),
        )

    def record_execution(
        self,
        actor: UserView,
        project_id: str,
        dataset_profile: str,
        model: str,
        run_id: str,
    ) -> None:
        self.require_project(actor, project_id, write=True)
        policy = self.execution_policy(actor, project_id)
        if policy is None:
            raise AccessControlError(
                "EXECUTION_POLICY_REQUIRED", "실행 정책을 먼저 설정해야 합니다."
            )
        now = _utcnow()
        cutoff = now - timedelta(days=30)
        with self._lock:
            state = self._read()
            retained = {}
            for key, record in state["execution_usage"].items():
                try:
                    reserved_at = datetime.fromisoformat(record["reserved_at"])
                except (KeyError, TypeError, ValueError):
                    continue
                if reserved_at >= cutoff:
                    retained[key] = record
            if run_id in retained:
                raise AccessControlError(
                    "EXECUTION_ALREADY_RECORDED", "이미 기록된 실행입니다."
                )
            retained[run_id] = {
                "project_id": project_id,
                "dataset_profile": dataset_profile,
                "model": model,
                "reserved_at": now.isoformat(),
                "estimated_cost_cents": policy.estimated_cost_per_run_cents,
                "requested_by": actor.user_id,
                "status": "RESERVED",
            }
            state["execution_usage"] = retained
            self._commit(state,
                "EXECUTION_BUDGET_RESERVED", user_id=actor.user_id,
                target=f"{project_id}:{run_id}", project_id=project_id,
            )

    def finalize_execution(self, actor: UserView, project_id: str, run_id: str) -> None:
        """Confirm estimated usage immediately before invoking the live runner."""
        self.require_project(actor, project_id, write=True)
        with self._lock:
            state = self._read()
            record = state["execution_usage"].get(run_id)
            if record is None or record.get("project_id") != project_id:
                raise AccessControlError("EXECUTION_RESERVATION_NOT_FOUND", "실행 예약을 찾을 수 없습니다.")
            if record.get("status") == "FINALIZED":
                return
            if record.get("status") != "RESERVED":
                raise AccessControlError("EXECUTION_RESERVATION_RELEASED", "해제된 실행 예약입니다.")
            record["status"] = "FINALIZED"
            record["finalized_at"] = _utcnow().isoformat()
            self._commit(state,
                "EXECUTION_USAGE_FINALIZED", user_id=actor.user_id,
                target=f"{project_id}:{run_id}", project_id=project_id,
            )

    def release_execution(
        self, actor: UserView | None, project_id: str, run_id: str, *, reason: str
    ) -> None:
        """Release a pre-run or interrupted reservation without erasing history."""
        with self._lock:
            state = self._read()
            record = state["execution_usage"].get(run_id)
            if record is None or record.get("project_id") != project_id:
                return
            if record.get("status") != "RESERVED":
                return
            record["status"] = "RELEASED"
            record["released_at"] = _utcnow().isoformat()
            record["release_reason"] = reason
            self._commit(state,
                "EXECUTION_BUDGET_RELEASED",
                user_id=actor.user_id if actor is not None else None,
                target=f"{project_id}:{run_id}:{reason}", project_id=project_id,
            )

    def record_execution_blocked(
        self, actor: UserView | None, *, project_id: str | None, code: str
    ) -> None:
        self._audit(
            "EXECUTION_BLOCKED",
            user_id=actor.user_id if actor is not None else None,
            target=code,
            project_id=project_id,
        )

    def record_deletion_event(
        self,
        event: str,
        *,
        actor: UserView,
        operation_id: str,
        project_id: str | None,
    ) -> None:
        """Audit lifecycle transitions without copying deleted record contents."""
        event_id = f"audit_del_{_digest(f'{operation_id}:{event}')[:32]}"
        with self._lock:
            self.ledger.append(
                event_id=event_id,
                event=event,
                user_id=actor.user_id,
                target=operation_id,
                project_id=project_id,
            )

    @staticmethod
    def _retention_view(
        project_id: str, project: dict, record: dict | None
    ) -> ProjectRetentionPolicyView:
        if record is None:
            managed_days = 90
            audit_days = 365
            legal_hold = False
            updated_by = None
            updated_at = None
            review_base = datetime.fromisoformat(project["created_at"])
        else:
            managed_days = int(record["managed_data_days"])
            audit_days = int(record["audit_event_days"])
            legal_hold = bool(record["legal_hold"])
            updated_by = record["updated_by"]
            updated_at = datetime.fromisoformat(record["updated_at"])
            review_base = updated_at
        return ProjectRetentionPolicyView(
            project_id=project_id,
            managed_data_days=managed_days,
            audit_event_days=audit_days,
            legal_hold=legal_hold,
            next_review_at=review_base + timedelta(days=managed_days),
            updated_by=updated_by,
            updated_at=updated_at,
        )

    def retention_policy(
        self, user: UserView, project_id: str
    ) -> ProjectRetentionPolicyView:
        self.require_project(user, project_id)
        with self._lock:
            state = self._read()
            return self._retention_view(
                project_id,
                state["projects"][project_id],
                state["retention_policies"].get(project_id),
            )

    def update_retention_policy(
        self,
        actor: UserView,
        project_id: str,
        request: ProjectRetentionPolicyUpdate,
    ) -> ProjectRetentionPolicyView:
        self.require_project(actor, project_id, owner=True)
        now = _utcnow()
        record = {
            **request.model_dump(),
            "updated_by": actor.user_id,
            "updated_at": now.isoformat(),
        }
        with self._lock:
            state = self._read()
            state["retention_policies"][project_id] = record
            self._commit(state,
                "RETENTION_POLICY_UPDATED",
                user_id=actor.user_id,
                target=(
                    f"managed={request.managed_data_days};"
                    f"audit={request.audit_event_days};hold={request.legal_hold}"
                ),
                project_id=project_id,
            )
            return self._retention_view(
                project_id, state["projects"][project_id], record
            )

    @staticmethod
    def _record_matches_project(record: dict, project_id: str) -> bool:
        return record.get("project_id") == project_id or (
            record.get("project_id") is None
            and project_id in str(record.get("target") or "")
        )

    def _audit_status_and_records(
        self, project_id: str
    ) -> tuple[str, list[dict]]:
        inspection = self.ledger.inspect()
        if inspection.status == "INVALID":
            return "INVALID", []
        try:
            records = self.ledger.records()
        except AuditLedgerIntegrityError:
            return "INVALID", []
        status = inspection.status
        return status, [
            record for record in records
            if self._record_matches_project(record, project_id)
        ]

    def audit_log(
        self, actor: UserView, project_id: str, *, limit: int = 100
    ) -> ProjectAuditLog:
        self.require_project(actor, project_id, owner=True)
        policy = self.retention_policy(actor, project_id)
        with self._lock:
            status, records = self._audit_status_and_records(project_id)
        visible = records[-max(1, min(limit, 200)):]
        inspection = self.ledger.inspect()
        legacy_sealed = status == "LEGACY_SEALED"
        events = [ProjectAuditEvent(
            event_id=str(
                record.get("event_id")
                or f"legacy_{_digest(json.dumps(record, sort_keys=True))[:24]}"
            ),
            sequence=int(record.get("sequence") or index),
            at=datetime.fromisoformat(record["at"]),
            event=str(record["event"]),
            actor_user_id=record.get("user_id"),
            target=record.get("target"),
            integrity_verified=(
                status != "INVALID"
                and (
                    record.get("schema_version") in {
                        "ax-security-audit-v2", "ax-security-audit-v3"
                    }
                    or legacy_sealed
                )
            ),
        ) for index, record in enumerate(visible, start=1)]
        return ProjectAuditLog(
            project_id=project_id,
            ledger_status=status,
            event_count=len(records),
            returned_event_count=len(events),
            checkpoint_sequence=inspection.checkpoint_sequence,
            protection_mode=inspection.protection_mode,
            repair_required=inspection.status == "INVALID",
            retention_policy=policy,
            events=list(reversed(events)),
        )

    def audit_integrity(self, user: UserView, project_id: str) -> tuple[str, int]:
        self.require_project(user, project_id)
        with self._lock:
            status, records = self._audit_status_and_records(project_id)
        return status, len(records)

    def governance_counts(self, user: UserView, project_id: str) -> dict[str, int]:
        self.require_project(user, project_id)
        with self._lock:
            state = self._read()
            project = state["projects"][project_id]
            return {
                "project_membership_count": len(project["members"]),
                "execution_policy_count": int(project_id in state["execution_policies"]),
                "transfer_approval_count": sum(
                    record.get("project_id") == project_id
                    for record in state["transfer_approvals"].values()
                ),
                "execution_usage_count": sum(
                    record.get("project_id") == project_id
                    for record in state["execution_usage"].values()
                ),
                "poc_decision_count": sum(
                    record.get("project_id") == project_id
                    for record in state["poc_decisions"].values()
                ),
            }

    @staticmethod
    def _poc_decision_key(project_id: str, dataset_profile: str) -> str:
        return _digest(f"{project_id}\n{dataset_profile}")

    @staticmethod
    def _poc_decision_view(record: dict) -> PocDecisionView:
        payload = dict(record)
        payload["decided_at"] = datetime.fromisoformat(record["decided_at"])
        payload["expires_at"] = datetime.fromisoformat(record["expires_at"])
        return PocDecisionView.model_validate(payload)

    def poc_decision(
        self, user: UserView, project_id: str, dataset_profile: str
    ) -> PocDecisionView | None:
        self.require_project(user, project_id)
        key = self._poc_decision_key(project_id, dataset_profile)
        with self._lock:
            record = self._read()["poc_decisions"].get(key)
        return None if record is None else self._poc_decision_view(record)

    def record_poc_decision(
        self,
        actor: UserView,
        project_id: str,
        dataset_profile: str,
        request: PocDecisionUpdate,
        *,
        assessment_fingerprint: str,
    ) -> PocDecisionView:
        self.require_project(actor, project_id, owner=True)
        now = _utcnow()
        view = PocDecisionView(
            decision_id=f"poc_{uuid4().hex}",
            project_id=project_id,
            dataset_profile=dataset_profile,
            decision=request.decision,
            note=request.note,
            assessment_fingerprint=assessment_fingerprint,
            decided_by=actor.user_id,
            decided_at=now,
            expires_at=now + timedelta(days=request.valid_days),
        )
        key = self._poc_decision_key(project_id, dataset_profile)
        with self._lock:
            state = self._read()
            state["poc_decisions"][key] = view.model_dump(mode="json")
            self._commit(state,
                "POC_DECISION_RECORDED",
                user_id=actor.user_id,
                target=f"{dataset_profile}:{request.decision}",
                project_id=project_id,
            )
        return view

    def delete_dataset_tasks(
        self, actor: UserView, project_id: str, dataset_profile: str
    ) -> int:
        self.require_project(actor, project_id, owner=True)
        with self._lock:
            state = self._read()
            task_ids = [
                task_id for task_id, task in state["tasks"].items()
                if task["project_id"] == project_id
                and task["dataset_profile"] == dataset_profile
            ]
            for task_id in task_ids:
                del state["tasks"][task_id]
            state["transfer_approvals"].pop(
                self._approval_key(project_id, dataset_profile), None
            )
            state["poc_decisions"] = {
                key: record
                for key, record in state["poc_decisions"].items()
                if not (
                    record.get("project_id") == project_id
                    and record.get("dataset_profile") == dataset_profile
                )
            }
            self._commit(state,
                "DATASET_TASKS_DELETED", user_id=actor.user_id,
                target=f"{project_id}:{dataset_profile}:{len(task_ids)}",
                project_id=project_id,
            )
        return len(task_ids)

    def delete_project(
        self, actor: UserView, project_id: str, *, purge_receipt_id: str
    ) -> tuple[str, dict[str, int]]:
        with self._lock:
            state = self._read()
            prior = state["deletion_tombstones"].get(purge_receipt_id)
            if prior is not None:
                if prior.get("project_id") != project_id:
                    raise AccessControlError(
                        "PURGE_RECEIPT_CONFLICT", "삭제 영수증 대상이 일치하지 않습니다."
                    )
                return "", dict(prior["counts"])
            self.require_project(actor, project_id, owner=True)
            inspection = self.ledger.inspect()
            if inspection.status == "INVALID":
                raise AccessControlError(
                    "AUDIT_LEDGER_INVALID",
                    "감사 원장 무결성 오류를 조사한 뒤 삭제해야 합니다.",
                )
            project = state["projects"][project_id]
            retention = state["retention_policies"].get(project_id)
            if retention is not None and retention.get("legal_hold") is True:
                raise AccessControlError(
                    "PROJECT_LEGAL_HOLD",
                    "법적 보존이 설정된 프로젝트는 보존을 해제한 뒤 삭제할 수 있습니다.",
                )
            task_ids = [
                task_id for task_id, task in state["tasks"].items()
                if task["project_id"] == project_id
            ]
            for task_id in task_ids:
                del state["tasks"][task_id]
            policy_deleted = int(
                state["execution_policies"].pop(project_id, None) is not None
            )
            approval_keys = [
                key for key, record in state["transfer_approvals"].items()
                if record.get("project_id") == project_id
            ]
            state["transfer_approvals"] = {
                key: record
                for key, record in state["transfer_approvals"].items()
                if record.get("project_id") != project_id
            }
            usage_ids = [
                run_id for run_id, record in state["execution_usage"].items()
                if record.get("project_id") == project_id
            ]
            state["execution_usage"] = {
                run_id: record
                for run_id, record in state["execution_usage"].items()
                if record.get("project_id") != project_id
            }
            decision_keys = [
                key for key, record in state["poc_decisions"].items()
                if record.get("project_id") == project_id
            ]
            state["poc_decisions"] = {
                key: record for key, record in state["poc_decisions"].items()
                if record.get("project_id") != project_id
            }
            state["retention_policies"].pop(project_id, None)
            project_name = project["name"]
            membership_count = len(project["members"])
            del state["projects"][project_id]
            counts = {
                "business_tasks_deleted": len(task_ids),
                "project_memberships_deleted": membership_count,
                "execution_policies_deleted": policy_deleted,
                "transfer_approvals_deleted": len(approval_keys),
                "execution_usage_records_deleted": len(usage_ids),
                "poc_decisions_deleted": len(decision_keys),
                "audit_events_deleted": 0,
            }
            state["deletion_tombstones"][purge_receipt_id] = {
                "project_id": project_id,
                "counts": counts,
            }
            # Never rewrite earlier audit history or restart it at GENESIS.
            # The completion event is a minimal tombstone containing only the
            # opaque receipt ID; project data is removed from mutable state.
            self._commit(state,
                "PROJECT_PURGE_COMPLETED",
                user_id=actor.user_id,
                target=purge_receipt_id,
            )
        return project_name, counts

    def project_exists(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._read()["projects"]

    def audit_contains(self, value: str) -> bool:
        with self._lock:
            return self.audit_path.is_file() and value in self.audit_path.read_text(
                encoding="utf-8"
            )

    def record_runtime_recovery(
        self, *, project_id: str | None, run_id: str, quarantined: bool = False
    ) -> None:
        """Record a system recovery without persisting runtime IDs or input text."""
        if project_id is not None:
            self.release_execution(
                None, project_id, run_id, reason="INTERRUPTED_BY_RESTART"
            )
        self._audit(
            "RUN_RESERVATION_QUARANTINED" if quarantined else "RUN_INTERRUPTED_BY_RESTART",
            user_id=None,
            target=run_id,
            project_id=project_id,
        )
