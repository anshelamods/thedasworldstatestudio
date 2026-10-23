// Exercise the actual DAO and DA2 review/merge handlers, including stale-plan failures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const game = process.argv[2] || 'dao';
assert.ok(['dao', 'da2'].includes(game));
const elements = new Map();
function element() {
  return {value: '', hidden: false, open: false, disabled: false, children: [], events: {},
    append(...items) { this.children.push(...items); },
    replaceChildren() { this.children = []; },
    addEventListener(name, fn) { this.events[name] = fn; },
    focus() {}, click() { this.clicked = true; }, showModal() { this.open = true; },
    close() { this.open = false; this.events.close?.(); }};
}
const $ = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const state = {draft: {choices: {'da2.hawke_romance': 'anders'}}, busy: false, showImportReview: false,
  profiles: [{profile_id: 'target', revision: 7, name: 'Existing history'}]};
const original = JSON.stringify(state.draft), calls = [];
let serial = 0, failPlan = false, noChanges = false, loads = 0;
function review(target = null, policy = 'missing') {
  return {game, import_id: 'review-' + ++serial, character: 'Elissa', stage: 'Origins completed',
    suggested_name: 'Elissa — imported DAO', target_profile_id: target,
    target_revision: target ? 7 : 0, target_name: target ? 'Existing history' : null,
    counts: {dao: {recovered: 2, unresolved: 72}, da2: {recovered: 1, unresolved: 62}}, recognized: [],
    unresolved: [{choice_id: 'dao.bevin_fate', title: 'Bevin', reason: 'Shared flags'},
      ...(game === 'da2' ? [{choice_id: 'da2.aveline_remained', title: 'Aveline', reason: 'Missing'}] : [])],
    restriction_message: 'Normal story restrictions remain enabled.', restriction_reasons: [], save_sha256: 'abc',
    policy, has_changes: !noChanges,
    changes: target ? [{title: 'Class', choice_id: 'dao.warden_class', status: 'added', before_label: 'Warrior', after_label: 'Rogue'},
      {title: 'Romance', choice_id: 'dao.warden_romance', status: policy === 'missing' ? 'kept' : 'replaced',
        before_label: 'No romance', incoming_label: 'Alistair', after_label: 'Alistair'}] : []};
}
const context = vm.createContext({$, state,
  Option: function(text, value) { this.textContent = text; this.value = value; },
  el: (_tag, _class, text) => Object.assign(element(), {textContent: text}),
  busy: value => { state.busy = value; }, ensureLeave: async () => true,
  toast: (...args) => calls.push(['toast', ...args]),
  backend: {fetch: async (path, options) => {
    assert.equal(path, game === 'dao' ? '/api/dao-save-import/preview' : '/api/save-import/preview'); assert.equal(options.headers['Content-Type'], 'application/octet-stream');
    return {ok: true, json: async () => review()};
  }},
  api: async (path, data) => {
    calls.push([path, JSON.parse(JSON.stringify(data))]);
    if (path.endsWith('/plan')) {
      if (failPlan) throw Error('The destination world state changed.');
      return review(data.target_profile_id, data.policy);
    }
    if (path.endsWith('/commit')) return {profile_id: 'target', name: 'Existing history', revision: 8,
      choices: {'da2.aveline_remained': 'stayed'}};
    return {};
  },
  updateProfile: p => calls.push(['update', p]), loadProfile: async p => { loads++; state.draft = p; },
});
vm.runInContext(source.slice(source.indexOf('function setEditorView('), source.indexOf('function filteredChoices(')), context);
vm.runInContext(source.slice(source.indexOf("$('import-save-from-manage').onclick"), source.indexOf("$('new-sidebar').onclick")), context);
vm.runInContext(source.slice(source.indexOf("$('show-import-review').onchange"), source.indexOf("$('enable-search').onchange")), context);
const choose = () => $(game === 'dao' ? 'dao-save-import-file' : 'save-import-file').onchange({target: {files: [{name: 'savegame.das', size: 4096}], value: 'x'}});
const plan = async (target, policy) => {
  $('dao-import-target').value = target; $('dao-import-policy').value = policy;
  await $('dao-import-target').onchange();
};
(async () => {
  vm.runInContext("setEditorView('quick')", context);
  $('import-dao-save-from-manage').onclick(); assert.equal($('dao-save-import-file').clicked, true);
  await choose();
  assert.equal(JSON.stringify(state.draft), original); assert.equal(loads, 0);
  assert.equal($('dao-import-target').children.length, 2);
  assert.equal($('dao-import-options').hidden, false); assert.equal($('dao-import-policy-field').hidden, true);
  assert.equal($('save-import-summary').textContent, 'Elissa · Origins completed · ' + (game === 'dao' ? '2 DAO choices recovered' : '1 DA2 choices + 2 DAO choices recovered'));
  assert.equal($('save-import-unresolved-title').textContent, game === 'dao' ? '72 DAO choices still need review' : '62 DA2 + 72 DAO choices still need review');
  assert.equal($('save-import-recognized').hidden, true);
  assert.equal($('save-import-unresolved-details').hidden, true);
  assert.match($('save-import-notice').textContent, /choices could not be recovered/);
  $('save-import-name').value = 'My new history';
  $('review-remaining-after-import').checked = true;
  const firstToken = state.saveImport.import_id;
  await plan('target', 'missing');
  assert.equal($('review-remaining-after-import').checked, true, 'changing destination keeps the review preference');
  assert.notEqual(state.saveImport.import_id, firstToken);
  const request = calls.find(c => c[0].endsWith('/plan'))[1];
  assert.deepEqual(request, {import_id: firstToken, target_profile_id: 'target', target_revision: 7, policy: 'missing'});
  assert.equal($('save-import-name-field').hidden, true); assert.equal($('dao-import-review').hidden, false);
  assert.equal($('save-import-recognized').hidden, true);
  assert.match($('save-import-description').textContent, game === 'dao' ? /DA2 choices stay as they are/ : /DA2 choices and carried DAO history/);
  assert.equal($('dao-import-change-summary').textContent, '1 added · 0 replaced · 1 kept · 0 unchanged');
  assert.equal($('dao-import-changes').hidden, true);
  assert.match($('save-import-notice').textContent, /Existing answers are kept/);
  const mergeToken = state.saveImport.import_id, planCount = calls.length;
  $('show-import-review').onchange({target: {checked: true}});
  assert.equal($('show-save-import-review').checked, true);
  assert.equal($('dao-import-changes').hidden, false);
  assert.equal($('dao-import-changes').children.length, 2);
  assert.equal($('save-import-recognized').hidden, true, 'merge review uses changes rather than recovered list');
  assert.equal($('save-import-unresolved-details').hidden, false);
  assert.equal(state.saveImport.import_id, mergeToken);
  assert.equal(calls.length, planCount, 'showing review must not create a new merge plan');
  $('show-save-import-review').onchange({target: {checked: false}});
  assert.equal($('dao-import-changes').hidden, true);
  assert.equal($('dao-import-review').hidden, false, 'compact merge summary stays visible');
  await plan('target', 'replace');
  assert.match($('dao-import-change-summary').textContent, /1 replaced/);
  await plan('', 'missing');
  assert.equal($('save-import-name').value, 'My new history');
  assert.equal($('save-import-name-field').hidden, false);
  noChanges = true; await plan('target', 'missing');
  assert.equal($('confirm-save-import').disabled, true);
  const commits = () => calls.filter(c => c[0].endsWith('/commit')).length;
  await $('save-import-form').onsubmit({preventDefault() {}}); assert.equal(commits(), 0);
  noChanges = false; failPlan = true;
  await plan('target', 'replace');
  assert.equal($('save-import-error').hidden, false); assert.equal($('confirm-save-import').disabled, true);
  assert.equal(JSON.stringify(state.draft), original, 'failed review must preserve the open world state');
  const cancelToken = state.saveImport.import_id;
  $('save-import-dialog').close();
  assert.deepEqual(calls.find(c => c[0].endsWith('/cancel'))[1], {import_id: cancelToken});
  assert.equal(state.saveImport, null); assert.equal(commits(), 0);
  assert.equal(state.view, 'quick'); assert.equal($('enable-quick').checked, true);
  assert.equal(!!state.searchEnabled, false, 'canceling must not change the current filters');
  failPlan = false; await choose(); await plan('target', 'replace');
  assert.equal($('review-remaining-after-import').checked, false, 'a fresh import starts unchecked');
  const approvedToken = state.saveImport.import_id;
  $('save-import-name').value = 'Tampered hidden name';
  $('review-remaining-after-import').checked = true;
  await $('save-import-form').onsubmit({preventDefault() {}});
  assert.deepEqual(calls.find(c => c[0].endsWith('/commit'))[1], {import_id: approvedToken, name: 'Existing history'});
  assert.equal(loads, 1); assert.equal(state.game, game); assert.equal(state.category, null);
  assert.equal($('save-import-dialog').open, false);
  assert.equal(state.view, 'tapestry'); assert.equal($('enable-quick').checked, false);
  assert.equal(state.searchEnabled, true); assert.equal(state.unchosenOnly, true);
  assert.equal(state.reviewRemaining, true, 'remaining review combines both games');
  console.log('PASS: ' + game.toUpperCase() + ' new/merge review, both policies, explicit counts, name restoration, stale/no-op guards, cancel and existing-profile commit');
})().catch(error => { console.error(error); process.exitCode = 1; });
