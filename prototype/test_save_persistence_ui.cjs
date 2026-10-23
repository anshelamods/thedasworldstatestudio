// A failed derived JSON refresh must remain a successful committed save.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const state = {busy: false, draft: {profile_id: 'id', revision: 1, name: 'Edited', base_preset: 'base', mode: 'keep', choices: {answer: 'new'}}, profiles: [], touched: true};
let calls = 0, failure = false, warning = 'Current JSON could not be refreshed', notices = [];
const context = vm.createContext({state, previewSequence: 0,
  dirty: () => true, clone: value => JSON.parse(JSON.stringify(value)),
  busy(value) { state.busy = value; }, render() {}, preview: async () => {},
  updateProfile(profile) { state.profiles = [profile]; },
  toast(...args) { notices.push(args); },
  async api(path, draft) {
    assert.equal(path, '/api/save'); calls++;
    if (failure) throw Error('Primary save failed');
    return {...draft, revision: draft.revision + 1, ...(warning ? {storage_warning: warning} : {})};
  }
});
vm.runInContext(source.slice(source.indexOf('function toDraft('), source.indexOf('function dirty(')), context);
vm.runInContext(source.slice(source.indexOf('async function save()'), source.indexOf('async function ensureLeave()')), context);
(async () => {
  assert.equal(await vm.runInContext('save()', context), true);
  assert.equal(state.draft.revision, 2);
  assert.equal(JSON.stringify(state.saved), JSON.stringify(state.draft));
  assert.equal('storage_warning' in state.profiles[0], false, 'warnings must not leak into portable JSON');
  assert.equal(notices.at(-1)[0], 'World State saved');
  assert.equal(notices.at(-1)[1], warning);
  assert.equal(notices.at(-1)[2], true);
  assert.equal(state.busy, false);
  state.draft.choices.answer = 'another'; failure = true;
  const savedBefore = JSON.stringify(state.saved);
  assert.equal(await vm.runInContext('save()', context), false);
  assert.equal(state.draft.revision, 2);
  assert.equal(state.draft.choices.answer, 'another');
  assert.equal(JSON.stringify(state.saved), savedBefore);
  assert.equal(notices.at(-1)[0], 'Could not save your World State');
  assert.equal(state.busy, false);
  failure = false; warning = null;
  assert.equal(await vm.runInContext('save()', context), true);
  assert.equal(state.draft.revision, 3);
  assert.equal(notices.at(-1)[2], false);
  state.busy = true; const beforeBusy = calls;
  assert.equal(await vm.runInContext('save()', context), false);
  assert.equal(calls, beforeBusy);
  console.log('PASS: committed saves survive JSON-refresh errors, warnings stay out of portable profiles, primary failures retain drafts');
})().catch(error => { console.error(error); process.exitCode = 1; });
