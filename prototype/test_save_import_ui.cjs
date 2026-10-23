// Exercise the actual import handlers without invoking a file dialog or server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map();
function element() {
  return {value: '', hidden: false, open: false, children: [], events: {},
    append(...items) { this.children.push(...items); },
    replaceChildren() { this.children = []; },
    addEventListener(name, fn) { this.events[name] = fn; },
    focus() { this.focused = true; },
    showModal() { this.open = true; },
    close() { this.open = false; this.events.close?.(); },
    click() { this.clicked = true; }};
}
const $ = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const result = {import_id: 'review-id', suggested_name: 'Marian', character: 'Marian', stage: 'Act III',
  counts: {da2: {recovered: 1, unresolved: 1}, dao: {recovered: 0, unresolved: 0}},
  restriction_message: 'No Story Restrictions will be enabled', restriction_reasons: ['Career missing'], save_sha256: 'abc',
  recognized: [{choice_id: 'da2.bethany_fate', title: 'Bethany', label: 'Bethany alive; career unspecified', evidence: 'plot'}],
  unresolved: [{choice_id: 'da2.aveline_remained', title: 'Aveline', reason: 'Not mapped'}]};
const calls = [], state = {draft: {choices: {'dao.dagna': 'helped'}, mode: 'keep'}, busy: false, profiles: [], saveImport: null, showImportReview: false};
const original = JSON.stringify(state.draft);
let fetchCount = 0, loadCount = 0, allowLeave = true;
const context = vm.createContext({$, state,
  Option: function(text, value) { this.textContent = text; this.value = value; },
  el: (_tag, _class, text) => Object.assign(element(), {textContent: text}),
  busy: value => { state.busy = value; },
  toast: (...args) => calls.push(['toast', ...args]),
  ensureLeave: async () => allowLeave,
  backend: {fetch: async (_url, options) => { fetchCount++; assert.equal(options.body.name, 'Test.das'); return {ok: true, json: async () => result}; }},
  api: async (path, data) => { calls.push([path, data]); return {profile_id: 'new', choices: {'da2.bethany_fate': 'alive_unspecified'}}; },
  updateProfile: p => calls.push(['update', p]),
  loadProfile: async p => { loadCount++; state.draft = p; },
});
vm.runInContext(source.slice(source.indexOf('function availableAnswers('), source.indexOf('function choiceExplicit(')), context);
vm.runInContext(source.slice(source.indexOf('function setEditorView('), source.indexOf('function filteredChoices(')), context);
vm.runInContext(source.slice(source.indexOf("$('import-save-from-manage').onclick"), source.indexOf("$('new-sidebar').onclick")), context);
vm.runInContext(source.slice(source.indexOf("$('show-import-review').onchange"), source.indexOf("$('enable-search').onchange")), context);
(async () => {
  state.busy = true; $('import-save').onclick(); assert.equal($('import-save-game-dialog').open, false);
  state.busy = false; $('import-save').onclick(); assert.equal($('import-save-game-dialog').open, true);
  $('import-dao-save').onclick(); assert.equal($('import-save-game-dialog').open, false);
  assert.equal($('dao-save-import-file').clicked, true);
  $('import-save').onclick(); $('import-da2-save').onclick();
  assert.equal($('import-save-game-dialog').open, false); assert.equal($('save-import-file').clicked, true);
  assert.equal(JSON.stringify(state.draft), original, 'opening the game/file chooser preserves edits');
  vm.runInContext("setEditorView('quick')", context);
  const standard = {answers: [{id: 'circle'}, {id: 'alive_unspecified', unrestricted_only: true}]};
  context.testChoice = standard;
  assert.equal(vm.runInContext('availableAnswers(testChoice).length', context), 1);
  state.draft.mode = 'experimental';
  assert.equal(vm.runInContext('availableAnswers(testChoice).length', context), 2);
  state.draft.mode = 'keep';
  const file = {name: 'Test.das', size: 1024};
  const choose = () => $('save-import-file').onchange({target: {files: [file], value: 'x'}});
  allowLeave = false; await choose(); assert.equal(fetchCount, 0);
  allowLeave = true; await choose();
  assert.equal($('review-remaining-after-import').checked, false);
  assert.equal(JSON.stringify(state.draft), original, 'preview must not replace current choices');
  assert.equal(loadCount, 0);
  assert.equal($('save-import-name').focused, true);
  assert.equal($('save-import-unresolved-title').textContent, '1 DA2 + 0 DAO choices still need review');
  assert.equal($('save-import-restrictions').textContent, result.restriction_message);
  assert.equal($('save-import-recognized').hidden, true);
  assert.equal($('save-import-recognized-title').hidden, true);
  assert.equal($('save-import-unresolved-details').hidden, true);
  assert.equal($('save-import-notice').hidden, false);
  assert.match($('save-import-notice').textContent, /1 choice could not be recovered.*manually/);
  $('save-import-name').value = 'Keep this name';
  $('show-save-import-review').onchange({target: {checked: true}});
  assert.equal($('show-import-review').checked, true);
  assert.equal($('save-import-recognized').hidden, false);
  assert.equal($('save-import-unresolved-details').hidden, false);
  assert.equal($('save-import-recognized').children.length, 1);
  assert.equal($('save-import-unresolved').children.length, 1);
  assert.equal($('save-import-name').value, 'Keep this name');
  $('show-import-review').onchange({target: {checked: false}});
  assert.equal($('show-save-import-review').checked, false);
  assert.equal($('save-import-recognized').hidden, true);
  assert.equal($('save-import-unresolved-details').hidden, true);
  assert.equal($('save-import-notice').hidden, false);
  $('save-import-dialog').close();
  assert.equal(state.saveImport, null);
  assert.equal(state.view, 'quick'); assert.equal($('enable-quick').checked, true);
  assert.equal(calls.filter(c => c[0] === '/api/save-import/cancel').length, 1);
  assert.equal(JSON.stringify(state.draft), original);
  await choose(); $('save-import-name').value = 'Named import';
  $('review-remaining-after-import').checked = true;
  state.searchQuery = 'old search'; $('choice-search').value = 'old search';
  state.busy = true; let prevented = false;
  $('save-import-dialog').events.cancel({preventDefault() { prevented = true; }});
  assert.equal(prevented, true, 'Escape must not interrupt an in-flight commit');
  state.busy = false;
  await $('save-import-form').onsubmit({preventDefault() {}});
  assert.equal(loadCount, 1);
  const commit = calls.find(c => c[0] === '/api/save-import/commit')[1];
  assert.equal(commit.import_id, 'review-id'); assert.equal(commit.name, 'Named import');
  assert.equal(state.game, 'da2'); assert.equal(state.category, null);
  assert.equal($('save-import-dialog').open, false);
  assert.equal(state.view, 'tapestry'); assert.equal($('enable-quick').checked, false);
  assert.equal(state.searchEnabled, true); assert.equal(state.unchosenOnly, true);
  assert.equal(state.reviewRemaining, true);
  assert.equal(state.searchQuery, ''); assert.equal($('choice-search').value, '');
  assert.equal($('unchosen-choices-only').checked, true);
  assert.equal(calls.filter(c => c[0] === '/api/save-import/cancel').length, 1, 'commit must not trigger cancel');
  console.log('PASS: optional import review, manual-choice notice, restricted answer visibility, unsaved guard, preview, cancel, named commit and new-profile loading');
})().catch(error => { console.error(error); process.exitCode = 1; });
