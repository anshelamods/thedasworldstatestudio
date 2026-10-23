// Exercise the actual navigation setters/handlers, including persisted startup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/gui/app.js', 'utf8');
const html = fs.readFileSync(__dirname + '/gui/index.html', 'utf8');
const elements = new Map(), preferences = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {checked: false, hidden: false, focus() {}, setAttribute() {}});
  return elements.get(id);
};
const brand = {};
const state = {view: 'tapestry', activeChoice: null, draft: {name: 'A New Beginning'}, boot: {}};
const context = vm.createContext({$, state, localStorage: {
  setItem: (k, v) => preferences.set(k, v), getItem: k => preferences.get(k)
}, document: {querySelector: () => brand},
clearChoicePreview() { state.activeChoice = null; }, render() {},
setMenu() {}, navigateCategory(id) { state.category = id; },
window: {scrollTo() {}}, availableAnswers: () => [{id: 'answer'}], currentAnswer: () => 'answer'});
const run = code => vm.runInContext(code, context);
run(source.slice(source.indexOf('function setEditorView('), source.indexOf('function filteredChoices(')));
run(source.slice(source.indexOf("$('enable-quick').onchange"), source.indexOf("$('show-diagnostics').onchange")));
run(source.slice(source.indexOf("$('game-home').onclick"), source.indexOf('function setMenu(')));
run(source.slice(source.indexOf("$('drawer-tapestry').onclick"), source.indexOf("$('drawer-profiles').onclick")));
run(source.slice(source.indexOf("document.querySelector('.brand').onclick"), source.indexOf("document.querySelector('.brand').onclick") + source.slice(source.indexOf("document.querySelector('.brand').onclick")).indexOf('\n')));
run(source.slice(source.indexOf('function openChoice('), source.indexOf('function closeChoice(')));
function assertView(expected) {
  assert.equal(state.view, expected);
  assert.equal($('enable-quick').checked, expected === 'quick');
  assert.equal(preferences.get('the-studio-quick-editor'), String(expected === 'quick'));
}
for (const exit of ['game-home', 'drawer-tapestry', 'tapestry-view']) {
  $('enable-quick').onchange({target: {checked: true}}); assertView('quick');
  $(exit).onclick(); assertView('tapestry');
  $('enable-quick').onchange({target: {checked: true}}); assertView('quick');
}
$('enable-quick').onchange({target: {checked: true}});
brand.onclick({preventDefault() {}}); assertView('tapestry');
// Opening an illustrated answer also leaves the Quick Editor consistently.
run("openChoice({id: 'choice', answers: [{id: 'answer'}]})"); assertView('tapestry');
state.reviewRemaining = true;
run("openChoice({id: 'da2.choice', game: 'da2', answers: [{id: 'answer'}]})");
assert.equal(state.game, 'da2', 'a combined-review choice uses its own game context');
assert.equal(state.reviewRemaining, true, 'opening a choice keeps the combined review active');
preferences.set('the-studio-quick-editor', 'true');
run(source.slice(source.indexOf("    try { setEditorView(localStorage.getItem"), source.indexOf('    const mostRecent')));
assertView('quick');
// Stored preference errors must not prevent the visible view from switching.
run("localStorage.setItem = () => { throw Error('storage blocked'); }; setEditorView('tapestry')");
assert.equal(state.view, 'tapestry'); assert.equal($('enable-quick').checked, false);
assert.ok(html.includes('<title>Thedas World State Studio</title>'));
assert.ok(html.includes('Save changes to World State?'));
assert.ok(!html.includes('Keep this chapter?'));
const titleLine = source.split('\n').find(line => line.includes('document.title ='));
run(titleLine);
assert.equal(run('document.title'), 'A New Beginning · Thedas World State Studio');
state.draft.name = 'Renamed World State'; run(titleLine);
assert.equal(run('document.title'), 'Renamed World State · Thedas World State Studio');
// The global save shortcut must not change revisions underneath modal reviews.
let keyHandler, openDialog = null, saveCalls = 0;
const keyState = {busy: false, draft: {revision: 1}, menuOpen: false};
const keyContext = vm.createContext({state: keyState,
  document: {addEventListener(_name, handler) { keyHandler = handler; },
    querySelector(selector) { assert.equal(selector, 'dialog[open]'); return openDialog; }},
  save() { saveCalls++; keyState.draft.revision++; }});
vm.runInContext(source.slice(source.indexOf("document.addEventListener('keydown'"),
  source.indexOf("window.addEventListener('beforeunload'")), keyContext);
function saveShortcut(modifier = 'ctrlKey') {
  let prevented = false;
  keyHandler({key: 's', [modifier]: true, preventDefault() { prevented = true; }});
  assert.equal(prevented, true, 'the browser Save Page action stays suppressed');
}
openDialog = {id: 'story-change-dialog'};
saveShortcut(); assert.equal(saveCalls, 0, 'a story review must retain its original revision');
assert.equal(keyState.draft.revision, 1);
openDialog = {id: 'save-import-dialog'};
saveShortcut('metaKey'); assert.equal(saveCalls, 0, 'import review must not save the old World State');
openDialog = null;
saveShortcut(); assert.equal(saveCalls, 1, 'ordinary Ctrl+S still saves');
saveShortcut('metaKey'); assert.equal(saveCalls, 2);
keyState.busy = true;
saveShortcut(); assert.equal(saveCalls, 2);
keyState.busy = false; keyState.draft = null;
saveShortcut(); assert.equal(saveCalls, 2);
console.log('PASS: navigation/checkbox/preference synchronization, title, save prompt and modal-safe save shortcuts');
