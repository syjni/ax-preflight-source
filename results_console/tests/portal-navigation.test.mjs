import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { Portal, tabFromHash } from '../src/components/Portal.tsx';

let dom;
let root;
let container;

beforeEach(() => {
  dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://127.0.0.1:5173/' });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.history = dom.window.history;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  dom.window.scrollTo = () => {};
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.requestAnimationFrame = (callback) => dom.window.setTimeout(callback, 0);
  dom.window.cancelAnimationFrame = (handle) => dom.window.clearTimeout(handle);
  container = document.getElementById('root');
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  dom.window.close();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.location;
  delete globalThis.history;
  delete globalThis.IS_REACT_ACT_ENVIRONMENT;
});

function consoleContent() {
  return React.createElement('main', { 'data-testid': 'existing-console' }, '기존 결과 콘솔');
}

async function renderPortal() {
  await act(async () => root.render(React.createElement(Portal, { consoleContent: consoleContent() })));
}

async function changeHash(hash) {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new window.HashChangeEvent('hashchange'));
  });
}

test('primary tabs switch when the URL hash changes', async () => {
  window.history.replaceState(null, '', '/#intro');
  await renderPortal();
  assert.match(container.textContent, /파일 점검은 100점이었지만/);
  assert.equal(container.querySelector('.portal-nav a[href="#intro"]').getAttribute('aria-current'), 'page');

  await changeHash('#guide');
  assert.match(container.textContent, /결과 콘솔 읽는 법/);
  assert.equal(container.querySelector('.portal-nav a[href="#guide"]').getAttribute('aria-current'), 'page');
  assert.doesNotMatch(container.textContent, /파일 점검은 100점이었지만/);
});

test('hands-on guide is expanded by default and remains collapsible', async () => {
  window.history.replaceState(null, '', '/#guide');
  await renderPortal();

  const toggle = container.querySelector('.guide-run-toggle');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.match(toggle.textContent, /접기/);
  assert.ok(container.querySelector('.guide-run'));
  assert.match(container.textContent, /TERMINAL 1 · 로컬 검토 API/);
  assert.match(container.textContent, /create_local_review_app_from_env/);

  await act(async () => toggle.click());

  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.match(toggle.textContent, /펼치기/);
  assert.equal(container.querySelector('.guide-run'), null);
});

test('hash parsing defaults to intro while existing section anchors stay on the console tab', async () => {
  assert.equal(tabFromHash(''), 'intro');
  assert.equal(tabFromHash('#summary'), 'console');
  assert.equal(tabFromHash('#local-audit'), 'console');
  assert.equal(tabFromHash('#featured-case'), 'console');
  assert.equal(tabFromHash('#findings'), 'console');
  assert.equal(tabFromHash('#unknown'), 'intro');

  window.history.replaceState(null, '', '/#intro');
  await renderPortal();
  await changeHash('#summary');
  assert.equal(container.querySelector('[data-active-tab]').getAttribute('data-active-tab'), 'console');
  assert.ok(container.querySelector('[data-testid="existing-console"]'));
});

test('empty hash renders the introduction as the default entry screen', async () => {
  window.history.replaceState(null, '', '/');
  await renderPortal();
  assert.match(container.textContent, /파일 점검은 100점이었지만/);
  assert.equal(container.querySelector('[data-testid="existing-console"]'), null);
  assert.doesNotMatch(container.textContent, /이 탭에서 기존 결과 콘솔이 열립니다/);
  assert.equal(container.querySelector('.portal-nav a[href="#intro"]').getAttribute('aria-current'), 'page');
});

test('console hash renders the existing console content instead of a placeholder', async () => {
  window.history.replaceState(null, '', '/#console');
  await renderPortal();
  assert.equal(container.querySelector('[data-testid="existing-console"]').textContent, '기존 결과 콘솔');
  assert.doesNotMatch(container.textContent, /이 탭에서 기존 결과 콘솔이 열립니다/);
  assert.equal(container.querySelector('.portal-nav a[href="#console"]').getAttribute('aria-current'), 'page');
});
