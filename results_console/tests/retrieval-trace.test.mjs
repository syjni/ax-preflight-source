import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RetrievalTracePanel } from '../src/components/RetrievalTracePanel.tsx';

const trace = {
  schema_version: 'ax-retrieval-trace-v2',
  run_id: 'return-window-r1',
  cited_source_ids: ['DOC_POLICY'],
  steps: [
    {
      sequence: 1,
      tool_name: 'search_documents',
      result_count: 2,
      candidates: [
        { rank: 1, title: '반품 정책', source_ids: ['DOC_POLICY'], cited: true },
        { rank: 2, title: 'FAQ', source_ids: ['DOC_FAQ'], cited: false },
      ],
      cited_source_ids: ['DOC_POLICY'],
      truncated: null,
      status: 'SUCCESS',
      request_summary: { parameter_names: ['query', 'top_k'], query_character_count: 12, result_limit: 2, source_ids: [], filter_fields: [] },
      error_code: null,
    },
    {
      sequence: 2,
      tool_name: 'read_document',
      result_count: 1,
      candidates: [{ rank: 1, title: '반품 정책', source_ids: ['DOC_POLICY'], cited: true }],
      cited_source_ids: ['DOC_POLICY'],
      truncated: false,
      status: 'SUCCESS',
      request_summary: { parameter_names: ['document_id'], query_character_count: null, result_limit: null, source_ids: ['DOC_POLICY'], filter_fields: [] },
      error_code: null,
    },
  ],
  limitations: ['Candidate presence or rank is not an accuracy judgment.'],
};

test('retrieval trace shows ordered candidates and the final citation path', () => {
  const html = renderToStaticMarkup(React.createElement(RetrievalTracePanel, {
    data: trace, loading: false, missing: false, error: '',
  }));

  assert.match(html, /검색·근거 경로/);
  assert.match(html, /문서 후보 검색/);
  assert.match(html, /원문 확인/);
  assert.match(html, /반품 정책/);
  assert.match(html, /최종 인용/);
  assert.match(html, /후보 2개/);
  assert.match(html, /검색어 12자/);
});

test('failed tool attempts remain visible without raw request values', () => {
  const html = renderToStaticMarkup(React.createElement(RetrievalTracePanel, {
    data: {
      ...trace,
      steps: [{
        sequence: 1,
        tool_name: 'search_documents',
        result_count: 0,
        candidates: [],
        cited_source_ids: [],
        truncated: null,
        status: 'ERROR',
        request_summary: { parameter_names: ['query', 'top_k'], query_character_count: 18, result_limit: null, source_ids: [], filter_fields: [] },
        error_code: 'VALIDATION_ERROR',
      }],
    },
    loading: false, missing: false, error: '',
  }));

  assert.match(html, /호출 실패/);
  assert.match(html, /VALIDATION_ERROR/);
  assert.match(html, /검색어 18자/);
  assert.match(html, /후속 성공 단계와 별도로 보존/);
});

test('an empty trace states that no tool responses were stored without declaring failure', () => {
  const html = renderToStaticMarkup(React.createElement(RetrievalTracePanel, {
    data: { ...trace, steps: [] }, loading: false, missing: false, error: '',
  }));

  assert.match(html, /저장된 데이터 도구 응답이 없습니다/);
  assert.doesNotMatch(html, /오답/);
});

test('the idle state tells reviewers how to reveal a trace', () => {
  const html = renderToStaticMarkup(React.createElement(RetrievalTracePanel, {
    data: null, loading: false, missing: false, error: '',
  }));

  assert.match(html, /대표 흐름 또는 기존 실행을 열면/);
});
