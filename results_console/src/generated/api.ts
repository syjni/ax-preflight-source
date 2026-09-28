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
  "queued_items": number;
  "repetitions": number;
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
  "profile": "mini" | "demo-return-before" | "demo-return-after" | "portfolio-hidden-conflict-before" | "portfolio-ceiling-after";
};

export type DatasetsResponse = {
  "datasets": Array<DatasetOption>;
  "schema_version"?: "ax-datasets-response-v1";
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

export type SubmitAnswerInput = {
  "abstention_reason"?: "NOT_FOUND" | "INSUFFICIENT_EVIDENCE" | "CONFLICTING_EVIDENCE" | null;
  "answer"?: string | number | boolean | Array<string> | null;
  "answer_kind"?: "EXACT_TEXT" | "EMPTY_SET" | "ID_LIST" | "NUMERIC_QUANTITY" | null;
  "explanation": string;
  "source_ids"?: Array<string>;
  "status": "ANSWERED" | "ABSTAINED";
  "unit"?: string | null;
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

