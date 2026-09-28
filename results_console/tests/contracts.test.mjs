import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const schema = (name) => JSON.parse(readFileSync(new URL(`../schemas/${name}.schema.json`, import.meta.url), 'utf8'));

test('readiness keeps unscored observations outside the score', () => {
  const response = schema('ReadinessResponse');
  const observation = schema('UnscoredObservation');
  assert.ok(response.properties.readiness);
  assert.ok(response.properties.unscored_observations);
  assert.ok(!('score' in observation.properties));
  assert.ok(!('readiness_score' in observation.properties));
});

test('delivery contract exposes only accepted answer and explicit evidence-link state', () => {
  const envelope = schema('DeliveryEnvelope');
  const payload = schema('SubmitAnswerInput');
  assert.deepEqual(envelope.properties.delivery_status.enum, ['DELIVERED', 'REJECTED']);
  assert.deepEqual(payload.properties.status.enum, ['ANSWERED', 'ABSTAINED']);
  assert.ok(envelope.properties.source_link_status.anyOf[0].enum.includes('NOT_CHECKED'));
  assert.ok(envelope.properties.dataset);
  assert.ok(payload.properties.abstention_reason);
  assert.ok(payload.properties.source_ids);
  for (const forbidden of ['raw_assistant_prose', 'finalText', 'ground_truth', 'expected_answer']) {
    assert.ok(!(forbidden in envelope.properties));
    assert.ok(!(forbidden in payload.properties));
  }
});

test('task catalog distinguishes approved work from unverified candidates', () => {
  const tasks = schema('TasksResponse');
  assert.deepEqual(tasks.properties.catalog_status.enum, ['CANDIDATES_AVAILABLE', 'VERIFIED_TASKS_AVAILABLE']);
  assert.deepEqual(tasks.$defs.BusinessTaskView.properties.status.enum, ['CANDIDATE', 'VERIFIED']);
  assert.ok(tasks.$defs.BusinessTaskView.properties.approval);
  assert.deepEqual(tasks.$defs.BusinessTaskApprovalSummary.properties.approval_scope.enum, ['CUSTOMER', 'CONTROLLED_DEMO']);
});

test('dataset list accepts validated local profiles and identifies their origin', () => {
  const response = schema('DatasetsResponse');
  const option = response.$defs.DatasetOption;
  assert.equal(response.properties.schema_version.const, 'ax-datasets-response-v1');
  assert.equal(option.properties.profile.type, 'string');
  assert.equal(option.properties.profile.pattern, '^[a-z0-9][a-z0-9-]*$');
  assert.deepEqual(option.properties.origin.enum, ['BUNDLED', 'LOCAL']);
  assert.ok(option.properties.dataset_name);
  assert.ok(option.properties.display_label);
  assert.ok(option.properties.scanned_at);
  assert.ok(option.properties.source_root_name);
  assert.equal(option.additionalProperties, false);
});

test('running response includes dataset provenance', () => {
  const running = schema('RunningRun');
  assert.ok(running.properties.dataset);
});

test('batch orchestration contract is bounded and exposes durable control state', () => {
  const request = schema('BatchCreateRequest');
  const status = schema('BatchStatus');
  assert.equal(request.properties.tasks.maxItems, 10);
  assert.equal(request.properties.repetitions.maximum, 5);
  assert.equal(request.properties.max_attempts.maximum, 3);
  assert.equal(status.properties.total_items.maximum, 50);
  assert.equal(status.properties.schema_version.const, 'ax-batch-status-v1');
  assert.deepEqual(status.properties.state.enum, [
    'QUEUED', 'RUNNING', 'PAUSE_REQUESTED', 'PAUSED',
    'CANCEL_REQUESTED', 'CANCELLED', 'COMPLETED', 'COMPLETED_WITH_ERRORS',
  ]);
  assert.ok(status.properties.progress_percent);
  assert.ok(status.properties.items);
});

test('evidence checker contract stays separate and marks unconfirmed conservatively', () => {
  const evidence = schema('EvidenceCheckResult');
  assert.deepEqual(evidence.properties.verdict.enum,
    ['DIRECT_MATCH', 'DERIVABLE', 'PARTIAL_SUPPORT', 'UNCONFIRMED']);
  assert.equal(evidence.properties.schema_version.const, 'ax-evidence-check-v1');
  assert.equal(evidence.properties.unconfirmed_is_not_incorrect.const, true);
  for (const forbidden of ['raw_assistant_prose', 'ground_truth', 'expected_answer', 'source_file']) {
    assert.ok(!(forbidden in evidence.properties));
  }
});

test('finding contract separates affected tasks, observed runs, and comparison status', () => {
  const response = schema('FindingsResponse');
  const finding = response.$defs.DataFinding;
  assert.equal(response.properties.schema_version.const, 'ax-data-findings-v1');
  assert.ok(response.properties.diagnostics);
  assert.ok(response.properties.findings);
  assert.ok(finding.properties.affected_task_count);
  assert.ok(finding.properties.observed_run_count);
  assert.ok(finding.properties.evidence);
  assert.deepEqual(finding.properties.comparison_status.default, 'OPEN');
  for (const forbidden of ['root_cause', 'source_file', 'raw_assistant_prose']) {
    assert.ok(!(forbidden in finding.properties));
  }
});
