// Exercise the app's actual search logic, including composed illustrated choices.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'gui/app.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'gui/choice-controls.js'), 'utf8'), context);
vm.runInContext(`
  const state = {searchEnabled: false, searchQuery: '', unchosenOnly: false,
    draft: {choices: {'dao.dagna_study': 'helped'}},
    boot: {categories: [{id: 'dao.paragon', title: 'Paragon of Her Kind'}]}};
  const choices = [
    {id: 'dao.dagna', category_id: 'dao.paragon', title: 'Dagna', question: "How did the Warden deal with Dagna’s request?",
      answers: [{id: 'helped', title: 'Helped Dagna study', related_choices: {'dao.dagna_study': 'helped'}}]},
    {id: 'dao.throne', category_id: 'dao.paragon', title: 'The throne of Orzammar', answers: [{id: 'b', title: 'King Bhelen'}]}
  ];
  function choiceExplicit(choice) { return choiceControls.explicit(state.draft, choice); }
`, context);
vm.runInContext(source.slice(source.indexOf('function filteredChoices('), source.indexOf('function renderSearch(')), context);
const run = code => vm.runInContext(code, context);
assert.equal(run("state.searchQuery = 'nothing'; filteredChoices(choices).length"), 2, 'disabled tools cannot hide choices');
assert.equal(run("state.searchEnabled = true; filteredChoices(choices).length"), 0);
assert.equal(run("state.searchQuery = 'PARAGON dagna'; filteredChoices(choices)[0].id"), 'dao.dagna');
assert.equal(run('state.searchQuery = "Dagna\'s request"; filteredChoices(choices).length'), 1);
assert.equal(run("state.searchQuery = 'king'; filteredChoices(choices)[0].id"), 'dao.throne');
assert.equal(run("state.searchQuery = '   '; filteringChoices()"), false);
assert.equal(run("state.unchosenOnly = true; filteredChoices(choices)[0].id"), 'dao.throne', 'related choices count as explicit and are excluded');
assert.equal(run('filteredChoices(choices).length'), 1);
assert.equal(run("state.searchQuery = 'dagna'; filteredChoices(choices).length"), 0, 'query and unchosen filter intersect');
assert.equal(run("state.searchEnabled = false; filteringChoices()"), false);
assert.equal(run('filteredChoices(choices).length'), 2);

// Render the combined review with both games, then leave it through normal
// navigation. Explicit selections must disappear as the user completes them.
const nodes = new Map();
function node(text) {
  return {textContent: text, children: [], hidden: false, value: '', checked: false,
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
    setAttribute() {}, focus() {}};
}
context.$ = id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); };
context.el = (_tag, _class, text) => node(text);
context.icon = () => node();
context.gameNames = {dao: 'Dragon Age: Origins', da2: 'Dragon Age II'};
context.window = {scrollTo() {}};
context.setGameMenu = () => {};
context.clearChoicePreview = () => {};
context.answerFor = () => null;
context.otherAnswerLabel = () => 'Inherited';
context.decisionCount = count => count + ' decisions';
run(`
  state.game = 'dao'; state.category = null; state.view = 'tapestry';
  state.boot.categories[0].game = 'dao';
  state.boot.categories.push({id:'da2.hero', game:'da2', title:'Hero'});
  state.boot.choices = [...choices, {id:'da2.personality', game:'da2', category_id:'da2.hero',
    title:'Hawke personality', answers:[]}];
  choices.forEach(c => c.game = 'dao');
  function gameCategories() { return state.boot.categories.filter(c => c.game === state.game); }
  function selectedCategory() { return null; }
`);
run(source.slice(source.indexOf('function setEditorView('), source.indexOf('function filteredChoices(')));
run(source.slice(source.indexOf('function renderTapestry('), source.indexOf('function renderCategorySettings(')));
run(source.slice(source.indexOf('function navigateCategory('), source.indexOf('function renderNavigation(')));
run('function render() { renderTapestry(); }');
run("state.reviewRemaining = true; state.searchEnabled = true; state.unchosenOnly = true; state.searchQuery = ''; renderTapestry()");
assert.deepEqual(nodes.get('tapestry').children.map(n => n.id), ['tile-dao-throne', 'tile-da2-personality']);
assert.match(nodes.get('tapestry').children[0].children[0].textContent, /Dragon Age: Origins/);
assert.match(nodes.get('tapestry').children[1].children[0].textContent, /Dragon Age II/);
run("state.draft.choices['da2.personality'] = 'diplomatic'; renderTapestry()");
assert.deepEqual(nodes.get('tapestry').children.map(n => n.id), ['tile-dao-throne']);
run('navigateCategory(null)');
assert.equal(run('state.reviewRemaining'), false);
assert.equal(run('state.searchEnabled'), false);
assert.equal(run('state.unchosenOnly'), false);
assert.deepEqual(nodes.get('tapestry').children.map(n => n.id), ['category-dao-paragon']);
console.log('PASS: default visibility, multi-term search, category/answer text, punctuation and composed-choice filtering');
