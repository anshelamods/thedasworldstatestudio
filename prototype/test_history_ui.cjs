// Exercise the actual history controls, preserving a separately edited draft.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map();
function element() {
  return {open: false, children: [], events: {}, disabled: false,
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
    showModal() { this.open = true; }, close() { this.open = false; this.events.close?.(); },
    addEventListener(name, handler) { this.events[name] = handler; }, focus() { this.focused = true; }};
}
const $ = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const saved = {profile_id: 'identity', revision: 2, name: 'Saved name', updated_at: '2026-10-22T12:00:00Z', choices: {saved: 'answer'}};
const state = {draft: {...saved, name: 'Unsaved new name', choices: {unsaved: 'answer'}}, busy: false};
const draftBefore = JSON.stringify(state.draft);
let history = [saved, {...saved, revision: 1}], calls = [], failure = false;
const context = vm.createContext({$, state, Date, Object,
  busy(value) { state.busy = value; },
  el(_tag, _class, textContent) { return Object.assign(element(), {textContent}); },
  toast(...args) { calls.push(['toast', ...args]); },
  async api(path, body) {
    calls.push([path, body]);
    if (path === '/api/history/identity') return history;
    if (path === '/api/profile/clear-history') {
      if (failure) throw Error('The World State changed');
      history = [saved]; return {cleared: true};
    }
    throw Error('Unexpected API ' + path);
  }
});
vm.runInContext(source.slice(source.indexOf('async function showHistory()'),
  source.indexOf("document.querySelector('.brand').onclick")), context);
(async () => {
  await $('show-history').onclick();
  assert.equal($('history-list').children.length, 2);
  assert.equal($('clear-history').disabled, false);
  $('clear-history').onclick();
  assert.equal($('clear-history-name').textContent, 'Saved name');
  assert.equal($('cancel-clear-history').focused, true);
  $('clear-history-dialog').close();
  assert.equal(state.clearingHistory, null);
  assert.equal(calls.length, 1, 'cancel must not write anything');
  $('clear-history').onclick();
  state.busy = true; let prevented = false;
  $('clear-history-dialog').events.cancel({preventDefault() { prevented = true; }});
  assert.equal(prevented, true); state.busy = false;
  failure = true;
  await $('confirm-clear-history').onclick();
  assert.equal($('clear-history-dialog').open, true);
  assert.equal($('clear-history-error').hidden, false);
  assert.equal($('confirm-clear-history').disabled, true);
  assert.equal(history.length, 2);
  const afterFailure = calls.length;
  await $('confirm-clear-history').onclick();
  assert.equal(calls.length, afterFailure, 'a stale confirmation cannot be retried');
  $('clear-history-dialog').close();
  failure = false; await $('show-history').onclick(); $('clear-history').onclick();
  await $('confirm-clear-history').onclick();
  assert.equal($('clear-history-dialog').open, false);
  const request = calls.findLast(call => call[0] === '/api/profile/clear-history');
  assert.equal(JSON.stringify(request[1]), JSON.stringify({profile_id: 'identity', revision: 2}));
  assert.equal(JSON.stringify(state.draft), draftBefore, 'history cleanup preserves unsaved edits');
  await $('show-history').onclick();
  assert.equal($('history-list').children.length, 1);
  assert.equal($('clear-history').disabled, true);
  assert.ok(calls.every(call => ['/api/profile/clear-history', '/api/history/identity', 'toast'].includes(call[0])));
  console.log('PASS: saved-revision review, clear cancel/confirm, stale guard, current-version retention and unsaved-draft preservation');
})().catch(error => { console.error(error); process.exitCode = 1; });
