// Exercise the real creation dialog and both existing save-import workflows.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map(), calls = [];
function element() {
  return {value: '', open: false, hidden: false, disabled: false, required: false, children: [], events: {},
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
    addEventListener(event, fn) { this.events[event] = fn; }, focus() {}, click() { this.clicked = true; },
    showModal() { this.open = true; }, close() { this.open = false; this.events.close?.(); }};
}
const $ = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const original = {name: 'Keep my edits', choices: {'da2.hawke_romance': 'anders'}};
const state = {draft: original, profiles: [], busy: false, showImportReview: false, view: 'quick',
  boot: {default_preset: 'default', presets: [{id: 'author', label: 'Authored'}, {id: 'default', label: 'Original game defaults'}]}};
let allowLeave = true, guards = 0, fetches = 0, invalid = false, loads = 0;
const context = vm.createContext({$, state,
  Option: function(text, value) { this.textContent = text; this.value = value; },
  el: (_tag, _class, text) => Object.assign(element(), {textContent: text}),
  setMenu() {}, busy(value) { state.busy = value; },
  async ensureLeave() { guards++; return allowLeave; }, async save() { return true; },
  async newDraft(name, preset) { calls.push(['new', name, preset]); },
  toast(...args) { calls.push(['toast', ...args]); },
  backend: {fetch: async (path, options) => {
    fetches++; assert.equal(options.headers['Content-Type'], 'application/octet-stream');
    const game = path.includes('dao-save') ? 'dao' : 'da2';
    if (invalid) return {ok: false, json: async () => ({error: 'Not a supported save.'})};
    return {ok: true, json: async () => ({game, import_id: game + '-review', suggested_name: 'Imported ' + game,
      character: 'Hero', stage: 'Completed', counts: {dao: {recovered: 1, unresolved: 0}, da2: {recovered: 1, unresolved: 0}},
      recognized: [], unresolved: [], changes: [], restriction_message: 'Preserved', restriction_reasons: [], save_sha256: 'abc'})};
  }},
  api: async (path, data) => {
    calls.push([path, JSON.parse(JSON.stringify(data))]);
    if (path.endsWith('/commit')) return {profile_id: 'new', name: data.name, revision: 1};
    return {};
  }, updateProfile() {}, async loadProfile() { loads++; },
});
const run = code => vm.runInContext(code, context);
run(source.slice(source.indexOf('function setEditorView('), source.indexOf('function filteredChoices(')));
run(source.slice(source.indexOf('function renderNewSource('), source.indexOf('async function init(')));
run(source.slice(source.indexOf("$('import-save-from-manage').onclick"), source.indexOf("$('new-sidebar').onclick")));
run(source.slice(source.indexOf("$('new-sidebar').onclick"), source.indexOf("$('inherit-choice').onclick")));
const submit = () => $('name-form').onsubmit({preventDefault() {}});
const chooseSource = value => { $('new-source').value = value; $('new-source').onchange(); };
(async () => {
  allowLeave = false; await $('new-profile').onclick(); assert.equal($('name-dialog').open, false);
  allowLeave = true; await $('new-sidebar').onclick();
  assert.equal($('name-dialog').open, true); assert.equal($('new-source').value, 'preset');
  assert.equal($('new-preset').children[0].value, 'default');
  assert.equal($('new-name').required, true); assert.equal($('preset-field').hidden, false);
  $('new-name').value = 'Named preset'; $('new-preset').value = 'author'; await submit();
  assert.deepEqual(calls.find(c => c[0] === 'new'), ['new', 'Named preset', 'author']);
  for (const game of ['dao', 'da2']) {
    await $('new-profile').onclick(); chooseSource(game);
    assert.equal($('new-name').disabled, true); assert.equal($('new-name').required, false);
    assert.equal($('preset-field').hidden, true); assert.equal($('new-save-hint').hidden, false);
    assert.equal($('name-submit').textContent, 'Choose ' + game.toUpperCase() + ' save');
    await submit(); assert.equal($('new-save-import-file').clicked, true);
    const beforeFetch = fetches, beforeGuard = guards;
    await $('new-save-import-file').onchange({target: {files: [], value: 'canceled'}});
    assert.equal($('name-dialog').open, true); assert.equal(fetches, beforeFetch);
    invalid = true;
    await $('new-save-import-file').onchange({target: {files: [{name: 'bad.das', size: 4}], value: 'bad'}});
    assert.equal($('name-dialog').open, true); assert.equal($('new-source-error').hidden, false);
    assert.equal($('new-source-error').textContent, 'Not a supported save.');
    assert.equal(loads, game === 'dao' ? 0 : 1);
    invalid = false; await submit();
    await $('new-save-import-file').onchange({target: {files: [{name: 'save.das', size: 4096}], value: 'save'}});
    assert.equal(guards, beforeGuard, 'Creation already reviewed unsaved edits; do not prompt twice');
    assert.equal($('name-dialog').open, false); assert.equal($('save-import-dialog').open, true);
    assert.equal(state.saveImport.game, game); assert.equal($('save-import-name').value, 'Imported ' + game);
    assert.equal($('dao-import-target').value, '', 'A new World State is the default destination');
    assert.equal(state.draft, original, 'Preview cannot replace the open draft');
    $('save-import-dialog').close(); assert.equal(state.saveImport, null);
    assert.equal(state.draft, original);
    await $('new-profile').onclick(); chooseSource(game); await submit();
    await $('new-save-import-file').onchange({target: {files: [{name: 'save.das', size: 4096}], value: 'save'}});
    $('save-import-name').value = 'My ' + game;
    await $('save-import-form').onsubmit({preventDefault() {}});
    assert.equal(state.game, game); assert.equal($('save-import-dialog').open, false);
    assert.equal(!!state.searchEnabled, false, 'unchecked imports do not enable search or filters');
  }
  assert.equal(loads, 2);
  assert.equal(calls.filter(c => c[0].endsWith('/commit')).length, 2);
  await run("nameDialog('duplicate')");
  assert.equal($('new-source-field').hidden, true); assert.equal($('new-name').disabled, false);
  assert.equal($('name-submit').textContent, 'Duplicate World State');
  console.log('PASS: preset creation, both save sources, file/review cancel, invalid-save retry, one unsaved guard, named commit and duplicate isolation');
})().catch(error => { console.error(error); process.exitCode = 1; });
