// Real management handlers: selection, unsaved guard, recoverable delete/restore.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const elements = new Map();
function element() {
  return {value: '', hidden: false, open: false, children: [], events: {},
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
    setAttribute(key, value) { this[key] = value; },
    addEventListener(key, fn) { this.events[key] = fn; },
    focus() { this.focused = true; },
    showModal() { this.open = true; }, close() { this.open = false; this.events.close?.(); }};
}
const $ = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const a = {profile_id: 'a', revision: 2, name: 'Current'};
const b = {profile_id: 'b', revision: 1, name: 'Other'};
const state = {draft: a, profiles: [a, b], busy: false, deletingProfile: null};
let leave = true, deleted = [], calls = [], failure = false, resets = 0;
const context = vm.createContext({$, state, Option: function(text, value) { return {text, value}; },
  el: (_tag, _class, textContent) => Object.assign(element(), {textContent}),
  setMenu() {}, renderProfiles() {}, busy(v) { state.busy = v; },
  toast(...args) { calls.push(['toast', ...args]); }, ensureLeave: async () => leave,
  newDraft: async () => { resets++; state.draft = {profile_id: null}; },
  updateProfile(profile) { state.profiles.push(profile); },
  api: async (path, payload) => {
    calls.push([path, payload]);
    if (failure) throw new Error('World state changed; reopen it');
    if (path === '/api/deleted-profiles') return deleted;
    if (path === '/api/profile/delete') { deleted.push(state.profiles.find(p => p.profile_id === payload.profile_id)); return {deleted: true}; }
    if (path === '/api/profile/restore') { const restored = deleted.find(p => p.profile_id === payload.profile_id); deleted = []; return restored; }
    if (path === '/api/profiles/purge') {
      const ids = payload.profiles.map(p => p.profile_id);
      deleted = deleted.filter(p => !ids.includes(p.profile_id)); return {purged: ids};
    }
    throw new Error('Unexpected API ' + path);
  },
});
vm.runInContext(source.slice(source.indexOf('function renderManagement()'), source.indexOf("$('open-profile').onclick")), context);
(async () => {
  $('profile-menu').onclick();
  assert.equal($('open-profile-select').children.length, 2);
  assert.equal($('delete-profile').disabled, false);
  leave = false; await $('delete-profile').onclick();
  assert.equal($('delete-profile-dialog').open, false);
  assert.equal(calls.length, 0);
  leave = true; await $('delete-profile').onclick();
  assert.equal($('delete-profile-name').textContent, 'Current');
  $('delete-profile-dialog').close();
  assert.equal(state.deletingProfile, null);
  assert.equal(calls.length, 0, 'cancel must not delete');
  await $('delete-profile').onclick(); failure = true;
  await $('confirm-delete-profile').onclick();
  assert.equal(state.profiles.length, 2); assert.equal($('delete-profile-dialog').open, true);
  assert.equal($('delete-profile-error').hidden, false);
  failure = false; await $('confirm-delete-profile').onclick();
  assert.equal(state.profiles.length, 1); assert.equal(resets, 1);
  assert.equal($('delete-profile-dialog').open, false);
  await vm.runInContext('renderDeletedProfiles()', context);
  const restore = $('deleted-profiles-list').children[0].children[1].children[0];
  assert.equal(restore['aria-label'], 'Restore Current');
  await restore.onclick();
  assert.equal(state.profiles.length, 2); assert.equal(deleted.length, 0);
  assert.equal(state.draft.profile_id, null, 'restoring must not replace the active draft');
  assert.equal(state.profiles.find(p => p.profile_id === 'a').revision, 2);
  // Deleting a different selected history leaves the active draft alone.
  state.draft = a; $('profile-menu').onclick(); $('open-profile-select').value = 'b';
  leave = false; await $('delete-profile').onclick(); await $('confirm-delete-profile').onclick();
  assert.equal(state.draft, a); assert.equal(resets, 1);
  assert.deepEqual(state.profiles.map(p => p.profile_id), ['a']);
  // Permanent deletion is explicit, cancelable and limited to the reviewed list.
  deleted = [{...b, deletion_token: 'b'.repeat(64)}, {profile_id: 'c', revision: 4, name: 'Third', deletion_token: 'c'.repeat(64)}];
  await vm.runInContext('renderDeletedProfiles()', context);
  const remove = $('deleted-profiles-list').children[0].children[1].children[1];
  remove.onclick(); assert.equal($('purge-profiles-dialog').open, true);
  assert.equal($('purge-profile-names').children[0].textContent, 'Other');
  const purges = () => calls.filter(c => c[0] === '/api/profiles/purge');
  $('purge-profiles-dialog').close(); assert.equal(purges().length, 0);
  $('empty-deleted-profiles').onclick();
  assert.equal($('purge-profile-names').children.length, 2);
  assert.equal($('cancel-purge-profiles').focused, true);
  deleted.push({profile_id: 'd', revision: 1, name: 'New deletion', deletion_token: 'd'.repeat(64)});
  state.busy = true; let prevented = false;
  $('purge-profiles-dialog').events.cancel({preventDefault() { prevented = true; }});
  assert.equal(prevented, true); state.busy = false;
  await $('confirm-purge-profiles').onclick();
  assert.deepEqual(purges()[0][1].profiles.map(p => p.profile_id), ['b', 'c']);
  assert.deepEqual(deleted.map(p => p.profile_id), ['d']);
  assert.equal(state.draft, a, 'permanent deletion must not replace the active draft');
  assert.deepEqual(state.profiles.map(p => p.profile_id), ['a']);
  $('empty-deleted-profiles').onclick(); failure = true;
  await $('confirm-purge-profiles').onclick();
  assert.equal($('purge-profiles-error').hidden, false);
  assert.equal($('confirm-purge-profiles').disabled, true);
  $('purge-profiles-dialog').close(); failure = false;
  await vm.runInContext('renderDeletedProfiles()', context);
  $('empty-deleted-profiles').onclick(); await $('confirm-purge-profiles').onclick();
  assert.equal($('empty-deleted-profiles').disabled, true);
  assert.equal(deleted.length, 0);
  console.log('PASS: recoverable delete/restore, permanent-delete cancel, reviewed empty list, stale failure and active-draft preservation');
})().catch(error => { console.error(error); process.exitCode = 1; });
