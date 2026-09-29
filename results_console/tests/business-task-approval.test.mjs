import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { TaskTable } from '../src/components/TaskTable.tsx';
import { runRequestFor } from '../src/viewModel.ts';

const verified = {
  task_id: 'TASK_POLICY_RETURN_WINDOW',
  category: '정책',
  question: '현재 반품 가능 기간은 며칠인가요?',
  description: '승인된 반품 정책 업무',
  status: 'VERIFIED',
  approval: {
    approval_id: 'CUSTOMER_RETURN_V1',
    owner_role: '고객지원 정책 담당자',
    success_criteria: ['현행 기간과 근거를 함께 반환한다.'],
    approval_scope: 'CUSTOMER',
    approved_by_role: '고객 업무 책임자',
    approved_at: '2026-09-28',
  },
};

const candidate = {
  task_id: 'TASK_ORDER_MONTHLY_AMOUNT',
  category: '주문',
  question: '이번 달 주문금액은 얼마인가요?',
  description: '미승인 후보',
  status: 'CANDIDATE',
  approval: null,
};

test('task table distinguishes scoped approval from candidate copy', () => {
  const html = renderToStaticMarkup(React.createElement(TaskTable, {
    data: {
      dataset: 'mini',
      catalog_status: 'VERIFIED_TASKS_AVAILABLE',
      tasks: [verified, candidate],
    },
    error: '',
    activeTaskId: null,
    onTaskSelect: () => {},
  }));

  assert.match(html, /검증 1 · 후보 1/);
  assert.match(html, /고객 승인/);
  assert.match(html, /고객지원 정책 담당자/);
  assert.match(html, /현행 기간과 근거를 함께 반환한다/);
  assert.match(html, /고객 업무 책임자/);
  assert.match(html, /2026-09-28/);
  assert.match(html, /검증 업무 선택/);
  assert.match(html, /후보 질문 선택/);
});

test('verified execution sends only approved identity while candidate keeps question', () => {
  assert.deepEqual(
    runRequestFor('mini', '사용자가 바꾼 문장', verified),
    {
      dataset: 'mini',
      request_type: 'VERIFIED_BUSINESS_TASK',
      task_id: 'TASK_POLICY_RETURN_WINDOW',
    },
  );
  assert.deepEqual(
    runRequestFor('mini', `  ${candidate.question}  `, candidate),
    {
      dataset: 'mini',
      request_type: 'TASK_CANDIDATE',
      task_id: 'TASK_ORDER_MONTHLY_AMOUNT',
      question: candidate.question,
    },
  );
});

test('customer execution carries the exact project-approved model', () => {
  assert.deepEqual(
    runRequestFor('local-customer', '무시되는 변경 문장', verified, 'approved-model-v2'),
    {
      dataset: 'local-customer',
      request_type: 'VERIFIED_BUSINESS_TASK',
      task_id: 'TASK_POLICY_RETURN_WINDOW',
      model: 'approved-model-v2',
    },
  );
});
