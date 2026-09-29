// Generated from ax_product Pydantic JSON Schemas. Do not edit.

export type AccessibilityCounts = {
  "accessible_files": number;
  "ocr_required_files": number;
  "parsed_files": number;
  "total_files": number;
};

export type AffectedTask = {
  "label": string;
  "task_id": string;
};

export type AuthSessionResponse = {
  "authenticated": boolean;
  "authentication_required"?: boolean;
  "bootstrap_required": boolean;
  "csrf_token"?: string | null;
  "expires_at"?: string | null;
  "user"?: UserView | null;
};

export type BatchCreateRequest = {
  "batch_id"?: string | null;
  "dataset": string;
  "max_attempts"?: number;
  "model"?: string;
  "repetitions"?: number;
  "tasks": Array<BatchTaskInput>;
};

export type BatchItem = {
  "attempt": number;
  "delivery_status"?: "DELIVERED" | "REJECTED" | null;
  "error_code"?: string | null;
  "item_id": string;
  "repetition": number;
  "request_type": "VERIFIED_BUSINESS_TASK" | "TASK_CANDIDATE";
  "run_id"?: string | null;
  "status": "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  "task_id": string;
  "task_label": string;
};

export type BatchStatus = {
  "batch_id": string;
  "cancelled_items": number;
  "completed_items": number;
  "created_at": string;
  "dataset": string;
  "failed_items": number;
  "items": Array<BatchItem>;
  "max_attempts": number;
  "model": string;
  "progress_percent": number;
  "project_id"?: string | null;
  "queued_items": number;
  "repetitions": number;
  "requested_by_user_id"?: string | null;
  "requested_control": "RUN" | "PAUSE" | "CANCEL";
  "running_items": number;
  "schema_version"?: "ax-batch-status-v1";
  "state": "QUEUED" | "RUNNING" | "PAUSE_REQUESTED" | "PAUSED" | "CANCEL_REQUESTED" | "CANCELLED" | "COMPLETED" | "COMPLETED_WITH_ERRORS";
  "succeeded_items": number;
  "total_items": number;
  "updated_at": string;
};

export type BatchTaskInput = {
  "question"?: string | null;
  "request_type": "VERIFIED_BUSINESS_TASK" | "TASK_CANDIDATE";
  "task_id": string;
};

export type BootstrapRequest = {
  "display_name": string;
  "password": string;
  "project_name"?: string;
  "username": string;
};

export type BusinessTaskApprovalSummary = {
  "approval_id": string;
  "approval_scope": "CUSTOMER" | "CONTROLLED_DEMO";
  "approved_at": string;
  "approved_by_role": string;
  "owner_role": string;
  "success_criteria": Array<string>;
};

export type BusinessTaskView = {
  "approval"?: BusinessTaskApprovalSummary | null;
  "category": string;
  "description": string;
  "question": string;
  "status": "CANDIDATE" | "VERIFIED";
  "task_id": string;
};

export type CompletenessCounts = {
  "eligible_tables": number;
  "estimated_missing_cells": number;
  "total_cells": number;
};

export type CreateUserRequest = {
  "display_name": string;
  "global_role"?: "ADMIN" | "MEMBER";
  "password": string;
  "username": string;
};

export type DataFinding = {
  "abstained_run_count"?: number;
  "abstention_variants"?: Array<FindingAbstentionVariant>;
  "affected_run_ids": Array<string>;
  "affected_task_count": number;
  "affected_task_ids": Array<string>;
  "affected_tasks": Array<AffectedTask>;
  "answer_variants"?: Array<FindingAnswerVariant>;
  "answered_run_count"?: number;
  "attribution_status"?: "DATA_SIGNAL" | "CAUSE_UNCONFIRMED" | "RETRIEVAL_LIMITATION";
  "comparison"?: FindingComparison | null;
  "comparison_status"?: "OPEN" | "NOT_REPRODUCED_AFTER" | "UNKNOWN";
  "evidence": Array<FindingEvidence>;
  "finding_id": string;
  "finding_type": FindingType;
  "observed_run_count": number;
  "recommended_action": string;
  "rejected_run_count"?: number;
  "source_ids": Array<string>;
  "summary": string;
};

export type DatasetOption = {
  "dataset_name": string;
  "display_label": string;
  "origin"?: "BUNDLED" | "LOCAL";
  "profile": string;
  "project_id"?: string | null;
  "scanned_at"?: string | null;
  "source_root_name"?: string | null;
};

export type DatasetsResponse = {
  "datasets": Array<DatasetOption>;
  "schema_version"?: "ax-datasets-response-v1";
};

export type DataTransferApprovalRequest = {
  "data_classification": "PUBLIC" | "INTERNAL" | "CONFIDENTIAL";
  "dataset_profile": string;
  "model": string;
  "provider_policy_reviewed": true;
  "sensitive_data_reviewed": true;
  "tool_output_to_model_acknowledged": true;
  "valid_days"?: number;
};

export type DataTransferApprovalView = {
  "approval_id": string;
  "approved_at": string;
  "approved_by": string;
  "boundary_revision"?: "AX_DATA_BOUNDARY_V1";
  "data_classification": "PUBLIC" | "INTERNAL" | "CONFIDENTIAL";
  "dataset_profile": string;
  "expires_at": string;
  "model": string;
  "pii_affected_file_count": number;
  "project_id": string;
  "provider"?: "KIRO_CLI";
  "provider_policy_reviewed"?: true;
  "schema_version"?: "ax-data-transfer-approval-v1";
  "sensitive_data_reviewed"?: true;
  "tool_output_to_model_acknowledged"?: true;
};

export type DeliveryEnvelope = {
  "dataset"?: string;
  "delivery_status": "DELIVERED" | "REJECTED";
  "model": string;
  "payload"?: SubmitAnswerInput | null;
  "reject_reason"?: "NO_SUBMISSION" | "INVALID_SUBMISSION" | "INVALID_RUN" | "MODEL_FALLBACK" | "FORBIDDEN_TOOL" | "RUNTIME_ERROR" | null;
  "run_id": string;
  "source_link_status"?: "NOT_CHECKED" | "LINKED" | "PARTIAL" | "UNLINKED" | null;
  "task_id"?: string | null;
};

export type EvidenceCheckResult = {
  "cited_source_ids": Array<string>;
  "delivery_sha256": string;
  "derivation"?: EvidenceDerivation | null;
  "evidence": Array<EvidenceReference>;
  "limitations": Array<string>;
  "matched_source_ids": Array<string>;
  "run_id": string;
  "schema_version"?: "ax-evidence-check-v1";
  "unconfirmed_is_not_incorrect"?: true;
  "unmatched_source_ids": Array<string>;
  "verdict": "DIRECT_MATCH" | "DERIVABLE" | "PARTIAL_SUPPORT" | "UNCONFIRMED";
};

export type EvidenceDerivation = {
  "field"?: string | null;
  "operands": Array<number>;
  "operation": "SUM" | "DIFFERENCE" | "COUNT";
  "result": number;
};

export type EvidenceReference = {
  "match": "CITED_RESPONSE" | "DIRECT_VALUE" | "DERIVATION_INPUT" | "PARTIAL_VALUE";
  "sequence": number;
  "source_ids": Array<string>;
  "tool_name": string;
};

export type ExecutionPolicyUpdate = {
  "daily_budget_cents"?: number;
  "daily_run_limit"?: number;
  "estimated_cost_per_run_cents"?: number;
  "max_batch_runs"?: number;
  "max_concurrent_runs"?: number;
  "model"?: string;
};

export type FeaturedCase = {
  "after": FeaturedRunReference;
  "before": FeaturedRunReference;
  "case_id": string;
  "question": string;
  "summary": string;
  "title": string;
};

export type FeaturedCasesResponse = {
  "featured_cases": Array<FeaturedCase>;
  "schema_version"?: "ax-featured-cases-response-v1";
};

export type FeaturedRunReference = {
  "action_label": string;
  "dataset": string;
  "detail": string;
  "label": string;
  "phase": "BEFORE" | "AFTER";
  "result": string;
  "run_id": string;
  "target": "summary" | "evidence";
};

export type FindingAbstentionVariant = {
  "explanation": string;
  "reason": string;
  "run_count": number;
  "run_ids": Array<string>;
};

export type FindingAnswerVariant = {
  "answer": string | number | boolean | Array<string>;
  "normalized_unit"?: string | null;
  "normalized_value": string;
  "run_count": number;
  "run_ids": Array<string>;
  "source_ids": Array<string>;
  "unit"?: string | null;
};

export type FindingComparison = {
  "after_answered_run_count": number;
  "after_dataset": string;
  "after_observed_run_count": number;
  "before_abstained_run_count": number;
  "before_dataset": string;
  "before_observed_run_count": number;
};

export type FindingEvidence = {
  "excerpt"?: string | null;
  "source_id": string;
  "source_title"?: string | null;
  "tool_name": string;
};

export type FindingsResponse = {
  "comparison_version"?: "v1" | "v2";
  "dataset": string;
  "diagnostics": TaskDiagnostics;
  "findings": Array<DataFinding>;
  "legacy_diagnostics"?: TaskDiagnostics | null;
  "schema_version"?: "ax-data-findings-v1";
};

export type FindingType = "CONFLICTING_SOURCES" | "INCONSISTENT_ANSWERS" | "MIXED_OUTCOMES" | "INSUFFICIENT_EVIDENCE" | "MISSING_INFORMATION";

export type LocalDatasetAudit = {
  "as_of_date": string;
  "dataset_name": string;
  "display_label": string;
  "duplicate_group_count": number;
  "error_file_count": number;
  "file_count": number;
  "files": Array<LocalDatasetFile>;
  "issues": Array<LocalDatasetIssue>;
  "local_only"?: true;
  "managed_copy_deleted_with_record"?: boolean;
  "ocr_completed_file_count"?: number;
  "ocr_required_count": number;
  "parsed_file_count": number;
  "pdf_table_count"?: number;
  "pii_finding_count": number;
  "probable_version_group_count": number;
  "profile": string;
  "scanned_at": string;
  "schema_version"?: "ax-local-dataset-audit-v1";
  "source_files_copied"?: boolean;
  "source_mode"?: "PATH" | "UPLOAD";
  "source_root_name": string;
  "supported_extensions": Array<string>;
  "table_count": number;
  "unsupported_file_count": number;
};

export type LocalDatasetDeleteResult = {
  "batch_records_deleted"?: number;
  "deleted"?: true;
  "managed_copy_deleted"?: boolean;
  "profile": string;
  "run_records_deleted"?: number;
  "schema_version"?: "ax-local-dataset-delete-result-v1";
  "source_files_deleted"?: false;
  "task_records_deleted"?: number;
};

export type LocalDatasetFile = {
  "extension": string;
  "issue"?: string | null;
  "modified_at": string;
  "ocr_mean_confidence"?: number | null;
  "ocr_page_count"?: number;
  "ocr_status"?: "NOT_APPLICABLE" | "NOT_REQUIRED" | "COMPLETED" | "DISABLED" | "UNAVAILABLE" | "PAGE_LIMIT_EXCEEDED" | "FAILED";
  "parse_status": "PARSED" | "UNSUPPORTED" | "ERROR";
  "parser"?: string | null;
  "pdf_table_count"?: number;
  "pdf_table_status"?: "NOT_APPLICABLE" | "COMPLETED" | "ERROR";
  "pii_finding_count": number;
  "relative_path": string;
  "requires_ocr": boolean;
  "size_bytes": number;
  "text_char_count": number;
};

export type LocalDatasetIssue = {
  "action": string;
  "code": "PARSE_ERROR" | "UNSUPPORTED_FORMAT" | "OCR_REQUIRED" | "PDF_TABLE_EXTRACTION_FAILED" | "EXACT_DUPLICATE" | "PROBABLE_VERSION_GROUP" | "PII_PATTERN" | "STALE_FILE";
  "count": number;
  "relative_paths"?: Array<string>;
  "severity": "info" | "warning" | "error";
  "title": string;
};

export type LocalDatasetRequest = {
  "display_name"?: string | null;
  "project_id"?: string | null;
  "source_path": string;
};

export type LocalDatasetScanResult = {
  "audit": LocalDatasetAudit;
  "dataset": DatasetOption;
  "readiness": ReadinessResponse;
  "schema_version"?: "ax-local-dataset-scan-result-v1";
};

export type LoginRequest = {
  "password": string;
  "username": string;
};

export type ModelConnectionStatus = {
  "credential_status"?: "ENVIRONMENT_MANAGED_NOT_PROBED";
  "default_model"?: string;
  "executable_status": "AVAILABLE" | "UNAVAILABLE" | "NOT_CHECKED";
  "provider": "KIRO_CLI" | "CONFIGURED_RUNNER";
  "runner_enabled": boolean;
  "schema_version"?: "ax-model-connection-status-v1";
  "timeout_seconds"?: number | null;
};

export type OnboardingAssessment = {
  "blocker_count": number;
  "can_run": boolean;
  "checks": Array<OnboardingCheck>;
  "dataset": string;
  "dataset_name": string;
  "schema_version"?: "ax-onboarding-assessment-v1";
  "status": "READY" | "REVIEW_REQUIRED" | "BLOCKED";
  "warning_count": number;
};

export type OnboardingCheck = {
  "code": "DATASET_INTEGRITY" | "PARSE_COVERAGE" | "RETRIEVAL_SURFACE" | "RUNTIME_RESOURCE_LEAKAGE" | "BUSINESS_TASK_REVIEW";
  "observed"?: number | null;
  "status": "PASS" | "WARN" | "BLOCK";
  "total"?: number | null;
};

export type PocDecisionUpdate = {
  "decision": "APPROVED" | "CONDITIONAL" | "REJECTED";
  "note": string;
  "risk_acknowledged": true;
  "scope_acknowledged": true;
  "valid_days"?: number;
};

export type PocDecisionView = {
  "assessment_fingerprint": string;
  "dataset_profile": string;
  "decided_at": string;
  "decided_by": string;
  "decision": "APPROVED" | "CONDITIONAL" | "REJECTED";
  "decision_id": string;
  "expires_at": string;
  "note": string;
  "project_id": string;
  "schema_version"?: "ax-poc-decision-v1";
};

export type PocEvaluationGate = {
  "code": string;
  "detail": string;
  "label": string;
  "status": "PASS" | "WARN" | "BLOCK";
};

export type PocEvaluationMetrics = {
  "abstained_runs": number;
  "answered_runs": number;
  "approved_tasks": number;
  "direct_evidence_runs": number;
  "observed_runs": number;
  "onboarding_status": "READY" | "REVIEW_REQUIRED" | "BLOCKED";
  "open_findings": number;
  "readiness_score": number;
  "registered_tasks": number;
  "rejected_runs": number;
  "stable_tasks": number;
};

export type PocEvaluationReport = {
  "assessment_fingerprint": string;
  "dataset_name": string;
  "dataset_profile": string;
  "decision"?: PocDecisionView | null;
  "decision_current"?: boolean;
  "decision_expired"?: boolean;
  "gates": Array<PocEvaluationGate>;
  "generated_at": string;
  "metrics": PocEvaluationMetrics;
  "project_id": string;
  "project_name": string;
  "recommendation": "GO" | "CONDITIONAL_GO" | "NO_GO";
  "schema_version"?: "ax-poc-evaluation-v1";
  "scope_note"?: string;
};

export type ProductCapabilities = {
  "ai_task_execution": boolean;
  "bundled_demo": boolean;
  "local_dataset_scan": boolean;
  "local_file_upload": boolean;
  "max_upload_bytes": number;
  "max_upload_files": number;
  "mode": "STATIC_DEMO" | "API" | "LOCAL_REVIEW" | "LIVE";
  "ocr_available": boolean;
  "ocr_engine"?: string | null;
  "ocr_install_hint"?: string | null;
  "ocr_languages"?: Array<string>;
  "pdf_table_extraction"?: boolean;
  "schema_version"?: "ax-product-capabilities-v2";
  "source_files_stay_local"?: true;
  "supported_extensions": Array<string>;
};

export type ProjectAuditEvent = {
  "actor_user_id"?: string | null;
  "at": string;
  "event": string;
  "event_id": string;
  "integrity_verified": boolean;
  "sequence": number;
  "target"?: string | null;
};

export type ProjectAuditLog = {
  "event_count": number;
  "events": Array<ProjectAuditEvent>;
  "ledger_status": "VERIFIED" | "LEGACY_SEALED" | "LEGACY_UNSEALED" | "INVALID";
  "project_id": string;
  "retention_policy": ProjectRetentionPolicyView;
  "returned_event_count": number;
  "schema_version"?: "ax-project-audit-log-v1";
};

export type ProjectCreateRequest = {
  "description"?: string;
  "name": string;
};

export type ProjectDataInventory = {
  "active_batch_count": number;
  "audit_event_count": number;
  "automatic_expiry_enabled"?: false;
  "batch_count": number;
  "business_task_count": number;
  "execution_policy_count": number;
  "execution_usage_count": number;
  "local_dataset_count": number;
  "managed_copy_count": number;
  "poc_decision_count": number;
  "project_id": string;
  "project_membership_count": number;
  "retention_mode"?: "MANUAL_DELETE";
  "retention_policy": ProjectRetentionPolicyView;
  "running_run_count": number;
  "schema_version"?: "ax-project-data-inventory-v1";
  "source_files_will_be_deleted"?: false;
  "transfer_approval_count": number;
  "writable_run_count": number;
};

export type ProjectExecutionControl = {
  "blockers"?: Array<"RUNNER_UNAVAILABLE" | "RUNNER_EXECUTABLE_UNAVAILABLE" | "EXECUTION_POLICY_REQUIRED" | "DATASET_REQUIRED" | "DATA_TRANSFER_APPROVAL_REQUIRED" | "DATA_TRANSFER_APPROVAL_EXPIRED" | "MODEL_NOT_APPROVED" | "BATCH_RUN_LIMIT_EXCEEDED" | "DAILY_RUN_LIMIT_REACHED" | "DAILY_BUDGET_REACHED" | "CONCURRENCY_LIMIT_REACHED">;
  "can_execute": boolean;
  "connection": ModelConnectionStatus;
  "dataset_profile"?: string | null;
  "policy"?: ProjectExecutionPolicyView | null;
  "project_id": string;
  "schema_version"?: "ax-project-execution-control-v1";
  "transfer_approval"?: DataTransferApprovalView | null;
  "usage"?: ProjectExecutionUsage | null;
};

export type ProjectExecutionPolicyView = {
  "daily_budget_cents"?: number;
  "daily_run_limit"?: number;
  "estimated_cost_per_run_cents"?: number;
  "max_batch_runs"?: number;
  "max_concurrent_runs"?: number;
  "model"?: string;
  "project_id": string;
  "provider"?: "KIRO_CLI";
  "schema_version"?: "ax-project-execution-policy-v1";
  "updated_at": string;
  "updated_by": string;
};

export type ProjectExecutionUsage = {
  "estimated_spend_cents": number;
  "remaining_budget_cents": number;
  "remaining_run_capacity": number;
  "reserved_runs": number;
  "running_runs": number;
  "schema_version"?: "ax-project-execution-usage-v1";
  "window"?: "ROLLING_24_HOURS";
  "window_started_at": string;
};

export type ProjectMemberRequest = {
  "role": "EDITOR" | "VIEWER";
  "username": string;
};

export type ProjectMemberView = {
  "role": "OWNER" | "EDITOR" | "VIEWER";
  "user": UserView;
};

export type ProjectPurgeRequest = {
  "confirmation": string;
};

export type ProjectPurgeResult = {
  "audit_events_deleted": number;
  "batches_deleted": number;
  "business_tasks_deleted": number;
  "completed_at": string;
  "execution_policies_deleted": number;
  "execution_usage_records_deleted": number;
  "local_datasets_deleted": number;
  "managed_copies_deleted": number;
  "poc_decisions_deleted": number;
  "project_deleted"?: true;
  "project_id": string;
  "project_memberships_deleted": number;
  "project_name": string;
  "purge_receipt_id": string;
  "raw_project_identifier_retained"?: false;
  "schema_version"?: "ax-project-purge-result-v1";
  "source_files_deleted"?: false;
  "transfer_approvals_deleted": number;
  "verification_status"?: "VERIFIED";
  "writable_runs_deleted": number;
};

export type ProjectRetentionPolicyUpdate = {
  "audit_event_days"?: number;
  "legal_hold"?: boolean;
  "managed_data_days"?: number;
};

export type ProjectRetentionPolicyView = {
  "audit_event_days"?: number;
  "automatic_deletion_enabled"?: false;
  "legal_hold"?: boolean;
  "managed_data_days"?: number;
  "mode"?: "OWNER_REVIEW";
  "next_review_at": string;
  "project_id": string;
  "schema_version"?: "ax-project-retention-policy-v1";
  "updated_at"?: string | null;
  "updated_by"?: string | null;
};

export type ProjectTaskView = {
  "approval_id"?: string | null;
  "approved_at"?: string | null;
  "approved_by"?: string | null;
  "approved_by_role"?: string | null;
  "category": string;
  "created_at": string;
  "created_by": string;
  "dataset_profile": string;
  "description": string;
  "owner_role": string;
  "project_id": string;
  "question": string;
  "status": "DRAFT" | "APPROVED";
  "success_criteria": Array<string>;
  "task_id": string;
};

export type ProjectView = {
  "created_at": string;
  "description": string;
  "member_count": number;
  "member_role": "OWNER" | "EDITOR" | "VIEWER";
  "name": string;
  "project_id": string;
};

export type ReadinessCounts = {
  "accessibility": AccessibilityCounts;
  "completeness": CompletenessCounts;
  "redundancy": RedundancyCounts;
  "safety": SafetyCounts;
  "timeliness": TimelinessCounts;
};

export type ReadinessDimensions = {
  "accessibility": number;
  "completeness": number;
  "redundancy": number;
  "safety": number;
  "timeliness": number;
};

export type ReadinessFlags = {
  "completeness_not_applicable": boolean;
  "empty_file_set": boolean;
  "future_modified_at_count": number;
  "invalid_modified_at_count": number;
  "missing_modified_at_count": number;
  "no_valid_modified_at": boolean;
  "scan_metadata_file_count_mismatch": boolean;
  "unknown_ocr_file_id_count": number;
  "unknown_pii_file_id_count": number;
};

export type ReadinessResponse = {
  "dataset": string;
  "dataset_name": string;
  "readiness": ReadinessScore;
  "unscored_observations": Array<UnscoredObservation>;
};

export type ReadinessScore = {
  "as_of_date": string;
  "counts": ReadinessCounts;
  "dimension_weights": ReadinessDimensions;
  "dimensions": ReadinessDimensions;
  "flags": ReadinessFlags;
  "readiness_score": number;
  "schema_version": "ax-readiness-score-v1";
  "stale_threshold_days": number;
};

export type RedundancyCounts = {
  "exact_duplicate_groups": number;
  "redundant_files": number;
  "total_files": number;
};

export type RetrievalCandidate = {
  "cited": boolean;
  "rank": number;
  "source_ids": Array<string>;
  "title": string;
};

export type RetrievalStep = {
  "candidates": Array<RetrievalCandidate>;
  "cited_source_ids": Array<string>;
  "error_code"?: string | null;
  "request_summary"?: ToolRequestSummary | null;
  "result_count": number;
  "sequence": number;
  "status"?: "SUCCESS" | "ERROR";
  "tool_name": "search_documents" | "read_document" | "lookup_value" | "query_table";
  "truncated"?: boolean | null;
};

export type RetrievalTrace = {
  "cited_source_ids": Array<string>;
  "limitations": Array<string>;
  "run_id": string;
  "schema_version"?: "ax-retrieval-trace-v2";
  "steps": Array<RetrievalStep>;
};

export type RunningRun = {
  "dataset"?: string;
  "run_id": string;
  "run_status"?: "RUNNING";
};

export type RunRequest = {
  "dataset": string;
  "model"?: string;
  "question"?: string | null;
  "request_type": "VERIFIED_BUSINESS_TASK" | "TASK_CANDIDATE" | "AD_HOC_QUESTION";
  "run_id"?: string | null;
  "task_id"?: string | null;
};

export type SafetyCounts = {
  "files_without_detected_pii": number;
  "pii_affected_files": number;
  "total_files": number;
};

export type SessionRevocationResult = {
  "revoked_sessions": number;
  "user_id": string;
};

export type SubmitAnswerInput = {
  "abstention_reason"?: "NOT_FOUND" | "INSUFFICIENT_EVIDENCE" | "CONFLICTING_EVIDENCE" | null;
  "answer"?: string | number | boolean | Array<string> | null;
  "answer_kind"?: "EXACT_TEXT" | "EMPTY_SET" | "ID_LIST" | "NUMERIC_QUANTITY" | null;
  "explanation": string;
  "source_ids"?: Array<string>;
  "status": "ANSWERED" | "ABSTAINED";
  "unit"?: string | null;
};

export type TaskCreateRequest = {
  "category": string;
  "dataset_profile": string;
  "description": string;
  "owner_role": string;
  "question": string;
  "success_criteria": Array<string>;
};

export type TaskDiagnostics = {
  "abstained_run_count": number;
  "answered_run_count": number;
  "blocked_task_count": number;
  "inconclusive_task_count": number;
  "observed_run_count": number;
  "processable_task_count": number;
  "rejected_run_count": number;
  "task_count": number;
};

export type TasksResponse = {
  "catalog_status": "CANDIDATES_AVAILABLE" | "VERIFIED_TASKS_AVAILABLE";
  "dataset": string;
  "tasks"?: Array<BusinessTaskView>;
};

export type TimelinessCounts = {
  "files_with_valid_modified_at": number;
  "future_timestamp_files": number;
  "invalid_timestamp_files": number;
  "missing_timestamp_files": number;
  "non_stale_files": number;
  "stale_files": number;
};

export type ToolRequestSummary = {
  "filter_fields": Array<string>;
  "parameter_names": Array<string>;
  "query_character_count"?: number | null;
  "result_limit"?: number | null;
  "source_ids": Array<string>;
};

export type UnscoredObservation = {
  "code": string;
  "file_ids"?: Array<string>;
  "message": string;
  "severity": "info" | "warning" | "error";
};

export type UserView = {
  "display_name": string;
  "global_role": "ADMIN" | "MEMBER";
  "user_id": string;
  "username": string;
};

