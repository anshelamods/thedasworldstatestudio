'use strict';

const $ = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
const svgNS = 'http://www.w3.org/2000/svg';
const gameNames = {dao: 'Dragon Age: Origins', da2: 'Dragon Age II'};
const state = {boot: null, profiles: [], draft: null, saved: null, preview: null,
  game: 'dao', category: null, view: 'tapestry', busy: false, touched: false, menuOpen: false,
  previewPending: true, previewError: null, activeChoice: null, candidateAnswer: null, nameAction: 'new',
  fbmodIcon: null, presetIcon: null, iconLoading: false, showDiagnostics: false, showImportReview: false,
  searchEnabled: false, searchQuery: '', unchosenOnly: false, reviewRemaining: false,
  saveImport: null, saveImportNewName: null, deletingProfile: null,
  deletedProfiles: [], purgeProfiles: null};
let previewSequence = 0, previewTimer, toastTimer;

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function icon(name) {
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(svgNS, 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}
async function api(path, body) {
  const options = {};
  if (body !== undefined) Object.assign(options, {method: 'POST', body: JSON.stringify(body),
    headers: {'Content-Type': 'application/json'}});
  let response;
  try { response = await backend.fetch(path, options); }
  catch (_) { throw new Error('The editor has stopped responding. Your unsaved choices are still in this window. Export them as World State JSON or reload the page.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The action could not be completed.');
  return result;
}
function toDraft(profile) {
  return {profile_id: profile.profile_id, revision: profile.revision, name: profile.name,
    base_preset: profile.base_preset, mode: profile.mode === 'ordinary' ? 'experimental' : profile.mode,
    choices: {...(profile.editor_choices || profile.choices)}};
}
function dirty() { return state.draft && (!state.saved || JSON.stringify(state.draft) !== JSON.stringify(state.saved)); }
function updateProfile(profile) {
  const index = state.profiles.findIndex(item => item.profile_id === profile.profile_id);
  if (index < 0) state.profiles.push(profile); else state.profiles[index] = profile;
}
async function loadProfile(profile) {
  clearChoicePreview();
  state.draft = toDraft(profile);
  state.saved = clone(state.draft);
  state.preview = null;
  state.touched = false;
  render();
  await preview();
}
async function newDraft(name = 'A New Beginning', presetId = state.boot.default_preset) {
  clearChoicePreview();
  const preset = state.boot.presets.find(item => item.id === presetId);
  state.draft = {profile_id: null, revision: 0, name, base_preset: presetId, mode: preset.mode, choices: {}};
  state.saved = null;
  state.preview = null;
  state.touched = false;
  render();
  await preview();
}
function presetName() {
  const label = state.boot.presets.find(item => item.id === state.draft.base_preset)?.label ||
    state.boot.preset_labels[state.draft.base_preset] || 'Base World State';
  return label.replace(/\bworldstate(s?)\b/gi, (_, plural) => 'World State' + (plural ? 's' : ''));
}
function currentAnswer(choice, raw = false) {
  return choiceControls.currentAnswer(state.draft, state.preview, choice, raw);
}
function answerFor(choice, raw = false) { return choice.answers.find(answer => answer.id === currentAnswer(choice, raw)); }
function availableAnswers(choice) {
  return choice.answers.filter(answer => !answer.unrestricted_only || state.draft.mode === 'experimental');
}
function choiceExplicit(choice) { return choiceControls.explicit(state.draft, choice); }
function otherAnswerLabel(choice) { return choice.custom_answer_label || 'Other inherited outcome'; }
function answerArt(choice, answer) {
  const appearance = state.preview?.hero_appearance?.[choice.game] || {};
  if (answer?.art_variant_context === 'class') return answer.art_variants?.[appearance.class] || answer.art;
  return answer?.art_variants?.[appearance.race + '_' + appearance.gender]
    || answer?.art_variants?.[appearance.gender] || answer?.art;
}
function gameCategories() { return state.boot.categories.filter(category => category.game === state.game); }
function selectedCategory() { return gameCategories().find(category => category.id === state.category); }
function decisionCount(count) { return count + (count === 1 ? ' decision' : ' decisions'); }
function clearChoicePreview() { state.activeChoice = null; state.candidateAnswer = null; }

function setEditorView(view) {
  state.view = view;
  $('enable-quick').checked = view === 'quick';
  try { localStorage.setItem('the-studio-quick-editor', String(view === 'quick')); } catch (_) {}
}

function stopRemainingReview() {
  if (!state.reviewRemaining) return;
  state.reviewRemaining = false; state.searchEnabled = false;
  state.searchQuery = ''; state.unchosenOnly = false;
  $('choice-search').value = ''; $('unchosen-choices-only').checked = false;
}

function filteredChoices(choices) {
  if (!state.searchEnabled) return choices;
  const normalize = text => text.toLocaleLowerCase().replace(/[’‘]/g, "'");
  const terms = normalize(state.searchQuery).trim().split(/\s+/).filter(Boolean);
  return choices.filter(choice => {
    if (state.unchosenOnly && choiceExplicit(choice)) return false;
    const category = state.boot.categories.find(item => item.id === choice.category_id);
    const text = normalize([choice.title, choice.question, category?.title,
      ...choice.answers.flatMap(answer => [answer.title, answer.tile_caption])].filter(Boolean).join(' '));
    return terms.every(term => text.includes(term));
  });
}
function filteringChoices() { return state.searchEnabled && (!!state.searchQuery.trim() || state.unchosenOnly); }
function renderSearch() {
  $('enable-search').checked = state.searchEnabled;
  $('unchosen-choices-only').checked = state.unchosenOnly;
  $('leave-remaining-review').hidden = !state.reviewRemaining;
  $('choice-tools').hidden = !state.searchEnabled || !!state.activeChoice;
  $('choice-search').placeholder = state.reviewRemaining ? 'Search remaining choices across both games'
    : state.view === 'tapestry' && selectedCategory() ? 'Search this category' : 'Search this game';
  $('clear-choice-search').disabled = !state.searchQuery && !state.unchosenOnly;
  const source = state.boot.choices.filter(choice => (state.reviewRemaining || choice.game === state.game) &&
    (state.view === 'quick' || (!['context', 'quick-only'].includes(choice.display) &&
      (!state.category || choice.category_id === state.category))));
  const count = filteredChoices(source).length;
  $('choice-results-count').textContent = filteringChoices() ? `${count} ${count === 1 ? 'choice' : 'choices'} found` : '';
}

function navigateCategory(id, focusId) {
  stopRemainingReview();
  setGameMenu(false);
  clearChoicePreview();
  state.category = gameCategories().some(category => category.id === id) ? id : null;
  render();
  window.scrollTo({top: 0, behavior: 'instant'});
  (focusId && $(focusId) || $('view-title')).focus({preventScroll: true});
}

function renderNavigation() {
  const category = selectedCategory(), crumbs = $('breadcrumbs');
  crumbs.replaceChildren();
  if (category && state.view === 'tapestry') {
    const parent = el('button', 'trail-step', category.title);
    parent.id = 'category-crumb'; parent.onclick = () => navigateCategory(category.id);
    crumbs.append(parent);
  }
  const current = el('span', 'trail-current', state.activeChoice?.title || (state.reviewRemaining ? 'Remaining choices' : state.view === 'quick' ? 'Quick editor' : category ? 'Choices' : 'Categories'));
  current.setAttribute('aria-current', 'page'); crumbs.append(current);
}

function renderHeader() {
  if (!state.draft) return;
  document.body.classList.toggle('show-diagnostics', state.showDiagnostics);
  $('show-diagnostics').checked = state.showDiagnostics;
  $('show-import-review').checked = state.showImportReview;
  for (const item of gameMenuItems()) item.setAttribute('aria-checked', String(item.dataset.game === state.game));
  $('game-home').textContent = state.reviewRemaining && !state.activeChoice ? 'All games' : gameNames[state.game];
  $('game-home').setAttribute('aria-label', 'Back to ' + gameNames[state.game] + ' tapestry');
  document.body.dataset.game = state.game;
  if ($('profile-name').value !== state.draft.name) $('profile-name').value = state.draft.name;
  $('revision-label').textContent = state.draft.profile_id ? 'Revision ' + state.draft.revision + (dirty() ? ' · Editing' : state.preview?.mapping_upgrade_pending ? ' · Update available' : ' · Saved') : 'Unsaved World State';
  $('preset-label').textContent = presetName().replace('Custom World State - ', '');
  $('preset-label').title = presetName();
  $('save-profile').textContent = state.busy ? 'Working…' : state.draft.profile_id ? 'Save changes' : 'Save World State';
  $('save-profile').disabled = state.busy || (!dirty() && !state.preview?.mapping_upgrade_pending);
  if (!dirty() && state.preview?.mapping_upgrade_pending) $('save-profile').textContent = 'Update World State';
  $('export-mod').disabled = state.busy || state.previewPending || !!state.previewError || !state.preview?.can_export;
  $('profile-menu').disabled = state.busy;
  $('import-save').disabled = state.busy;
  $('enable-quick').checked = state.view === 'quick';
  $('mode-switch').hidden = state.view !== 'quick';
  $('tapestry-view').classList.toggle('selected', state.view === 'tapestry');
  $('quick-view').classList.toggle('selected', state.view === 'quick');
  $('tapestry-view').setAttribute('aria-pressed', String(state.view === 'tapestry'));
  $('quick-view').setAttribute('aria-pressed', String(state.view === 'quick'));
  $('tapestry').hidden = state.view !== 'tapestry' || !!state.activeChoice;
  $('quick-editor').hidden = state.view !== 'quick' || !!state.activeChoice;
  $('view-title').hidden = !!state.activeChoice;
  $('choice-view').hidden = !state.activeChoice;
  document.body.classList.toggle('browsing-choice', !!state.activeChoice);
  const category = selectedCategory();
  $('view-title').textContent = state.reviewRemaining ? 'Remaining choices' : state.view === 'quick' ? 'Quick editor' : category?.title || 'The tapestry';
  document.title = (state.draft.name || 'Untitled') + ' · ' + (state.boot.app_name || 'Thedas World State Studio');
  const errors = state.previewError ? [state.previewError] : state.preview?.errors || [];
  $('review-story').hidden = state.draft.mode !== 'keep' || !errors.length || !!state.previewError;
  $('review-story').disabled = state.busy || state.previewPending;
  $('story-unrestricted').checked = state.draft.mode !== 'keep';
  const experimental = state.preview?.experimental_conflicts || [];
  $('validation').hidden = !errors.length && !experimental.length;
  $('validation').classList.toggle('diagnostic', !errors.length);
  $('validation').replaceChildren();
  if (errors.length || experimental.length) {
    $('validation').append(el('strong', '', errors.length ? 'These choices need attention before export' : 'No Story Restrictions'));
    for (const message of errors.length ? errors : experimental) $('validation').append(el('div', '', readableConflict(message)));
  }
}
function readableConflict(message) {
  if (message.includes('da2_hawke_class_mage=1')) return 'This outcome requires a mage Hawke. Change Hawke’s class in Hero, or enable No Story Restrictions.';
  if (message.includes('da2_hawke_class_mage=0')) return 'This outcome requires a warrior or rogue Hawke. Change Hawke’s class in Hero, or enable No Story Restrictions.';
  if (message.includes('da2_bethany_career=0') || message.includes('da2_bethany_alive=0')) return 'For this Carver history, choose Bethany’s death while escaping Lothering.';
  if (message.includes('da2_carver_alive')) return 'This Bethany outcome conflicts with Carver surviving in the base World State.';
  if (message.includes('Recruited Loghain')) return 'Alistair cannot normally remain a Grey Warden after Loghain is recruited.' + (state.draft.mode === 'ordinary' ? ' Change their outcomes or enable No Story Restrictions.' : '');
  return message;
}
function renderProfiles() {
  const list = $('profile-list');
  list.replaceChildren();
  if (!state.profiles.length) list.append(el('p', 'side-hint', 'Your saved histories will appear here.'));
  for (const profile of [...state.profiles].sort((a, b) => b.updated_at.localeCompare(a.updated_at))) {
    const button = el('button', 'profile-item' + (profile.profile_id === state.draft?.profile_id ? ' current' : ''));
    const copy = el('div');
    copy.append(el('span', '', profile.name), el('small', '', 'Revision ' + profile.revision));
    button.append(copy);
    button.title = 'Open ' + profile.name;
    button.setAttribute('aria-label', 'Open World State: ' + profile.name);
    button.onclick = async () => {
      setMenu(false);
      if (!(await ensureLeave())) return;
      try {
        const latest = await api('/api/profile/' + profile.profile_id);
        updateProfile(latest); await loadProfile(latest);
      } catch (error) { toast('Could not open this World State', error.message, true); }
    };
    list.append(button);
  }
}
function renderTapestry() {
  const grid = $('tapestry');
  grid.replaceChildren();
  const category = selectedCategory();
  grid.className = 'tapestry ' + (category ? 'decision-grid' : 'category-grid');
  grid.setAttribute('aria-label', state.reviewRemaining ? 'Remaining choices across Origins and Dragon Age II'
    : category ? category.title + ' decisions' : gameNames[state.game] + ' categories');
  const gameChoices = state.boot.choices.filter(choice => (state.reviewRemaining || choice.game === state.game) && !['context', 'quick-only'].includes(choice.display));
  const choices = category ? gameChoices.filter(choice => choice.category_id === category.id) : gameChoices;
  if (filteringChoices()) {
    grid.className = 'tapestry search-results';
    const matches = filteredChoices(choices);
    if (!matches.length) grid.append(el('p', 'search-empty', state.reviewRemaining && !state.searchQuery.trim()
      ? 'No remaining choices to review. Return to the tapestry when you’re ready.'
      : 'No choices match. Try another search or clear the filter.'));
    for (const choice of matches) {
      const button = el('button', 'search-result');
      button.id = 'tile-' + choice.id.replaceAll('.', '-');
      const categoryTitle = state.boot.categories.find(item => item.id === choice.category_id)?.title;
      button.append(el('small', '', state.reviewRemaining ? gameNames[choice.game] + ' · ' + categoryTitle : categoryTitle), el('strong', '', choice.title),
        el('span', '', answerFor(choice)?.tile_caption || answerFor(choice)?.title || otherAnswerLabel(choice)), icon('arrow'));
      button.onclick = () => openChoice(choice); grid.append(button);
    }
    return;
  }
  if (!category) {
    const pairHosts = new Map(), renderedBlocks = new Set(), overviewHosts = new Map();
    const categories = gameCategories();
    const makeCategory = item => {
      const button = el('button', 'story-tile category-tile ' + item.layout);
      const supported = gameChoices.filter(choice => choice.category_id === item.id);
      button.id = 'category-' + item.id.replaceAll('.', '-');
      button.setAttribute('aria-label', 'Open ' + item.title + ': ' + decisionCount(supported.length) + ' available');
      const image = el('img'); image.src = state.preview?.category_art?.[item.id] || item.art; image.alt = ''; button.append(image);
      const copy = el('div', 'tile-copy');
      copy.append(el('h2', '', item.title), icon('arrow'));
      button.append(copy); button.onclick = () => navigateCategory(item.id);
      return button;
    };
    for (const item of categories) {
      if (item.overview_tile) {
        const tile = item.overview_tile;
        if (!overviewHosts.has(tile.block)) {
          const block = el('div', 'category-block');
          overviewHosts.set(tile.block, block); grid.append(block);
        }
        const button = makeCategory(item);
        button.style.gridColumn = (tile.x + 1) + ' / span ' + tile.width;
        button.style.gridRow = (tile.y + 1) + ' / span ' + tile.height;
        overviewHosts.get(tile.block).append(button);
        continue;
      }
      if (item.overview_block) {
        if (renderedBlocks.has(item.overview_block)) continue;
        renderedBlocks.add(item.overview_block);
        const block = el('div', 'category-chapters');
        const order = ['nature', 'paragon', 'circle'];
        for (const member of categories.filter(value => value.overview_block === item.overview_block)
            .sort((a, b) => order.indexOf(a.overview_slot) - order.indexOf(b.overview_slot))) {
          const button = makeCategory(member); button.dataset.slot = member.overview_slot; block.append(button);
        }
        grid.append(block); continue;
      }
      let host = grid;
      if (item.overview_pair) {
        if (!pairHosts.has(item.overview_pair)) {
          const pair = el('div', 'category-pair');
          pairHosts.set(item.overview_pair, pair); grid.append(pair);
        }
        host = pairHosts.get(item.overview_pair);
      }
      host.append(makeCategory(item));
    }
    return;
  }
  const hosts = new Map();
  let orderedChoices = choices;
  if (category.tile_blocks) {
    grid.classList.add('mosaic-grid');
    const byId = new Map(choices.map(choice => [choice.id, choice]));
    const blocks = category.tile_blocks.map(block => block.filter(tile => byId.has(tile.choice_id))).filter(block => block.length);
    const listed = new Set(blocks.flat().map(tile => tile.choice_id));
    for (const choice of choices) if (!listed.has(choice.id)) blocks.push([{choice_id: choice.id, x: 0, y: 0, width: 2, height: 2}]);
    orderedChoices = blocks.flat().map(tile => byId.get(tile.choice_id));
    for (const block of blocks) {
      const landscapeStack = block.every(tile => tile.width === 2 && tile.height === 1);
      const wrapper = el('div', 'tapestry-block' + (landscapeStack ? ' landscape-stack' : '')); grid.append(wrapper);
      for (const tile of block) hosts.set(tile.choice_id, {wrapper, tile});
    }
  }
  const classes = {'da2.bethany_fate': 'bethany', 'da2.carver_fate': 'carver', 'da2.anders_fate': 'anders', 'dao.ferelden_leadership': 'ferelden', 'dao.loghain_fate': 'loghain'};
  for (const choice of orderedChoices) {
    const answer = answerFor(choice);
    const button = el('button', 'story-tile ' + (classes[choice.id] || ''));
    button.id = 'tile-' + choice.id.replaceAll('.', '-');
      button.setAttribute('aria-label', choice.title + ': ' + (answer?.title || otherAnswerLabel(choice)) +
        (state.showDiagnostics && choice.export_note ? '. ' + choice.export_note : '') + '. Edit choice');
      const art = answerArt(choice, answer || answerFor(choice, true) ||
        choice.answers.find(item => item.id === choice.placeholder_answer));
    if (art) {
      const image = el('img');
      image.onload = () => { button.dataset.shape = image.naturalWidth / image.naturalHeight > 1.55 ? 'landscape' : 'portrait'; };
      image.src = art; image.alt = ''; button.append(image);
    } else {
      const placeholder = el('div', 'empty-art'); placeholder.append(icon('diamond')); button.append(placeholder);
    }
    button.append(el('span', 'image-shade'));
    const top = el('span', 'tile-topline');
    top.append(el('span', '', choice.game === 'dao' ? 'ORIGINS' : 'DRAGON AGE II'));
    if (choiceExplicit(choice)) {
      const edited = el('span', 'tile-edited'); edited.title = 'Chosen for this World State'; edited.append(icon('check')); top.append(edited);
    }
    const copy = el('div', 'tile-copy');
    copy.append(el('p', 'tile-answer', answer?.tile_caption || answer?.title || otherAnswerLabel(choice)));
      if (choice.export_note) copy.append(el('small', 'profile-only-note', choice.export_note));
    button.append(top, copy);
    button.onclick = () => openChoice(choice);
    const host = hosts.get(choice.id);
    if (host) {
      button.style.gridColumn = (host.tile.x + 1) + ' / span ' + host.tile.width;
      button.style.gridRow = (host.tile.y + 1) + ' / span ' + host.tile.height;
      host.wrapper.append(button);
    } else grid.append(button);
  }
}
function renderCategorySettings() {
  const container = $('category-settings'); container.replaceChildren();
  const contexts = state.boot.choices.filter(choice => choice.display === 'context' && choice.category_id === state.category && choice.game === state.game);
  container.hidden = !contexts.length || state.view !== 'tapestry' || !!state.activeChoice || filteringChoices();
  for (const choice of contexts) {
    const label = el('label', '', choice.title), select = el('select', 'text-input');
    select.id = 'context-' + choice.id.replaceAll('.', '-'); label.htmlFor = select.id;
    const explicit = Object.hasOwn(state.draft.choices, choice.id);
    select.append(new Option('Use base · ' + (explicit ? 'reset this choice' : answerFor(choice)?.title || 'Other inherited class'), ''));
    for (const answer of availableAnswers(choice)) select.append(new Option(answer.title, answer.id));
    select.value = explicit ? state.draft.choices[choice.id] : '';
    select.onchange = () => changeChoice(choice.id, select.value || null, select.id);
    container.append(label, select);
  }
}
function renderQuick() {
  const rows = $('quick-rows'); rows.replaceChildren();
  const choices = filteredChoices(state.boot.choices.filter(item => state.reviewRemaining || item.game === state.game));
  if (!choices.length) rows.append(el('p', 'search-empty', 'No choices match. Try another search or clear the filter.'));
  for (const choice of choices) {
    const answer = answerFor(choice, true), explicit = Object.hasOwn(state.draft.choices, choice.id);
      const profileOnly = choice.export_behavior === 'profile-only';
    const row = el('div', 'quick-row'), label = el('div');
    label.append(el('h3', '', choice.title),
        el('small', 'diagnostic', explicit ? 'Chosen for this World State' : profileOnly ? 'Not selected' : 'Inherited from base World State'));
    if (choice.verification_note) label.append(el('small', 'mapping-note', choice.verification_note));
    const controlId = 'quick-' + choice.id.replaceAll('.', '-');
    let control;
    if (choice.quick_kind === 'checkbox') {
      control = el('label', 'toggle-label');
      const input = el('input'); input.type = 'checkbox'; input.id = controlId;
      input.checked = currentAnswer(choice, true) === choice.checked_answer; input.indeterminate = !answer;
      input.onchange = () => changeChoice(choice.id, input.checked ? choice.checked_answer : choice.unchecked_answer, controlId);
      const text = el('span', '', choice.checkbox_label);
      text.append(el('small', '', answer?.title || 'Other inherited outcome; choose explicitly to replace it'));
      control.append(input, text);
    } else {
      control = el('select', 'text-input'); control.id = controlId; control.setAttribute('aria-label', choice.title);
        control.append(new Option(profileOnly ? 'Not selected' : 'Use base · ' + (explicit ? 'reset this choice' : answer?.title || 'Other outcome'), ''));
      for (const item of availableAnswers(choice)) control.append(new Option(item.title, item.id));
      control.value = explicit ? state.draft.choices[choice.id] : '';
      control.onchange = () => changeChoice(choice.id, control.value || null, controlId);
    }
      const reset = el('button', 'text-button', profileOnly ? 'Clear choice' : 'Use base'); reset.disabled = !explicit;
      reset.setAttribute('aria-label', profileOnly ? 'Clear ' + choice.title : 'Reset ' + choice.title + ' to base World State');
    reset.onclick = () => changeChoice(choice.id, null, controlId);
    row.append(label, control, reset); rows.append(row);
  }
}
function render() {
  if (!state.boot || !state.draft) return;
  const focus = document.activeElement?.id;
  renderHeader(); renderNavigation(); renderProfiles(); renderSearch(); renderTapestry(); renderCategorySettings(); renderQuick(); renderAnswerCarousel();
  if (focus && $(focus) && document.activeElement?.id !== focus) $(focus).focus({preventScroll: true});
}
async function preview() {
  clearTimeout(previewTimer);
  const sequence = ++previewSequence;
  state.previewPending = true; renderHeader();
  try {
    const result = await api('/api/preview', clone(state.draft));
    if (sequence !== previewSequence) return;
    state.preview = result; state.previewError = null;
  } catch (error) {
    if (sequence !== previewSequence) return;
    state.previewError = error.message;
  }
  state.previewPending = false;
  render();
}
async function changeChoice(id, value, focusId) {
  if (state.busy) return;
  await requestStoryChange({[id]: value});
  if (focusId && $(focusId)) $(focusId).focus({preventScroll: true});
}
async function changeIllustratedChoice(choice, value) {
  if (state.busy) return;
  const next = choiceControls.apply(state.draft.choices, choice, value);
  const updates = Object.fromEntries(choiceControls.members(choice).map(id => [id, next[id] || null]));
  const applied = await requestStoryChange(updates);
  if (applied) closeChoice();
}

async function requestStoryChange(updates, mode = state.draft.mode) {
  if (state.busy) return false;
  // Draft, dirty state and illustrated preview stay untouched until acceptance.
  const original = clone(state.draft);
  ++previewSequence; clearTimeout(previewTimer); state.previewPending = false;
  busy(true);
  let proposal;
  try { proposal = await api('/api/propose', {draft: original, updates, mode}); }
  catch (error) {
    toast('Could not apply this answer', error.message, true);
    return false;
  } finally { busy(false); render(); }
  if (proposal.changes.length) {
    const list = $('story-change-list'); list.replaceChildren();
    for (const change of proposal.changes) {
      const choice = state.boot.choices.find(item => item.id === change.choice_id);
      const row = el('section', 'story-change-row'); row.append(el('h3', '', change.title));
      const comparison = el('div', 'story-change-comparison');
      for (const side of ['before', 'after']) {
        if (side === 'after') { const arrow = el('span', 'story-change-arrow', '→'); arrow.setAttribute('aria-hidden', 'true'); comparison.append(arrow); }
        const panel = el('div', 'story-change-answer');
        panel.append(el('span', 'eyebrow', side === 'before' ? 'Original choice' : 'New choice'));
        const answer = choice?.answers.find(item => item.id === change[side]);
        // Show the answer's own gender/race variant in each comparison panel.
        const art = answer?.art_variants?.[change[side]?.startsWith('female_') ? 'female' : 'male'] || answer?.art;
        if (art) { const image = el('img'); image.src = art; image.alt = ''; panel.append(image); }
        panel.append(el('p', '', answer?.title || change[side + '_label'])); comparison.append(panel);
      }
      row.append(comparison); list.append(row);
    }
    const dialog = $('story-change-dialog'); dialog.returnValue = '';
    const accepted = await new Promise(resolve => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'apply'), {once: true});
      dialog.showModal(); $('cancel-story-change').focus();
    });
    if (!accepted) { render(); return false; }
  }
  state.draft = proposal.draft; state.touched = true;
  await preview();
  return true;
}
function openChoice(choice) {
  if (choice.game) state.game = choice.game;
  state.activeChoice = choice;
  setEditorView('tapestry');
  const answers = availableAnswers(choice);
  state.candidateAnswer = answers.find(answer => answer.id === currentAnswer(choice))?.id || answers[0].id;
  render(); window.scrollTo({top: 0, behavior: 'instant'});
  $('choice-question').focus({preventScroll: true});
}
function closeChoice() {
  const choice = state.activeChoice;
  clearChoicePreview(); render();
  window.scrollTo({top: 0, behavior: 'instant'});
  (choice && $('tile-' + choice.id.replaceAll('.', '-')) || $('view-title')).focus({preventScroll: true});
}
function browseAnswer(id, focus = false) {
  if (!state.activeChoice || !availableAnswers(state.activeChoice).some(answer => answer.id === id)) return;
  state.candidateAnswer = id;
  renderAnswerCarousel();
  if (focus) $('answer-' + id).focus({preventScroll: true});
}
function stepAnswer(direction) {
  const answers = state.activeChoice && availableAnswers(state.activeChoice);
  if (!answers) return;
  const index = answers.findIndex(answer => answer.id === state.candidateAnswer);
  const next = Math.max(0, Math.min(answers.length - 1, index + direction));
  browseAnswer(answers[next].id, true);
}
function renderAnswerCarousel() {
  const choice = state.activeChoice;
  if (!choice) return;
  const answers = availableAnswers(choice);
  const candidateIndex = Math.max(0, answers.findIndex(answer => answer.id === state.candidateAnswer));
  const candidate = answers[candidateIndex];
  $('choice-question').textContent = choice.question;
  $('choice-description').textContent = candidate.description;
  const customNote = !currentAnswer(choice) ? choice.custom_answer_note : '';
  $('choice-verification').hidden = !choice.verification_note && !customNote;
  $('choice-verification').textContent = [customNote, choice.verification_note].filter(Boolean).join(' ');
  const profileOnly = choice.export_behavior === 'profile-only';
  $('choice-origin').textContent = choiceExplicit(choice) ? 'Chosen for this World State' : profileOnly ? 'Not selected' : 'Inherited from your base World State';
  $('choice-current').textContent = 'Current answer: ' + (answerFor(choice)?.title || otherAnswerLabel(choice));
  $('inherit-choice').disabled = !choiceExplicit(choice);
  $('inherit-choice').textContent = profileOnly ? 'Clear choice' : 'Use base World State';
  $('answer-position').textContent = 'Answer ' + (candidateIndex + 1) + ' of ' + answers.length;
  $('previous-answer').disabled = candidateIndex === 0;
  $('next-answer').disabled = candidateIndex === answers.length - 1;
  $('approve-answer').disabled = state.busy || state.previewPending;
  const cards = $('answer-cards'); cards.replaceChildren();
  answers.forEach((answer, index) => {
    const offset = index - candidateIndex, current = currentAnswer(choice) === answer.id;
    const slot = offset === 0 ? 'is-active' : (Math.abs(offset) > 1 ? 'far-' : '') + (offset < 0 ? 'left' : 'right');
    const card = el('button', 'carousel-card ' + slot);
    card.id = 'answer-' + answer.id;
    card.hidden = Math.abs(offset) > 2;
    card.setAttribute('aria-pressed', String(offset === 0));
    card.setAttribute('aria-label', 'Preview ' + answer.title + (current ? ' · Current answer' : ''));
    const art = answerArt(choice, answer);
    if (art) {
      const image = el('img');
      image.onload = () => {
        const ratio = image.naturalWidth / image.naturalHeight;
        card.dataset.shape = ratio > 1.55 ? 'landscape' : ratio < .75 ? 'portrait' : 'square';
      };
      image.src = art; image.alt = ''; card.append(image);
    }
    card.append(el('span', 'carousel-caption', answer.title));
    for (const corner of ['top-left', 'top-right', 'bottom-left', 'bottom-right']) {
      const ornament = el('span', 'card-corner ' + corner); ornament.setAttribute('aria-hidden', 'true'); card.append(ornament);
    }
    if (current) { const marker = el('span', 'answer-marker'); marker.title = 'Current World State answer'; marker.append(icon('check')); card.append(marker); }
    card.onclick = () => browseAnswer(answer.id, true);
    cards.append(card);
  });
}
function busy(value) {
  state.busy = value;
  document.querySelector('.app-shell').inert = value;
  document.querySelectorAll('dialog').forEach(dialog => { dialog.inert = value; });
  document.querySelector('main').setAttribute('aria-busy', String(value));
  renderHeader();
}
function toast(title, detail = '', error = false, actions = []) {
  clearTimeout(toastTimer);
  $('toast').classList.toggle('error', error);
  $('toast-title').textContent = title; $('toast-detail').textContent = detail;
  $('toast-actions').replaceChildren();
  for (const action of actions) {
    const button = el('button', 'text-button', action.label);
    button.onclick = async () => { try { await action.run(); } catch (failure) { toast('Could not complete action', failure.message, true); } };
    $('toast-actions').append(button);
  }
  $('toast').hidden = false;
  if (!error && !actions.length) toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
async function save() {
  if (state.busy) return false;
  if (!dirty() && !state.preview?.mapping_upgrade_pending) return true;
  busy(true); ++previewSequence;
  try {
    state.draft.name = state.draft.name.trim();
    const {storage_warning, ...profile} = await api('/api/save', state.draft);
    updateProfile(profile);
    state.draft = toDraft(profile); state.saved = clone(state.draft); state.touched = false;
    toast('World State saved', storage_warning || profile.name + ' · Revision ' + profile.revision, Boolean(storage_warning));
    return true;
  } catch (error) { toast('Could not save your World State', error.message, true); return false; }
  finally { busy(false); render(); await preview(); }
}
async function ensureLeave() {
  if (!dirty() || (!state.saved && !state.touched)) return true;
  const dialog = $('unsaved-dialog'); dialog.returnValue = '';
  const answer = await new Promise(resolve => { dialog.addEventListener('close', () => resolve(dialog.returnValue), {once: true}); dialog.showModal(); });
  if (answer === 'discard') return true;
  if (answer === 'save') return save();
  return false;
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob), anchor = el('a'); anchor.href = url; anchor.download = name;
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
}
function openExportDialog() {
  if (state.busy) return;
  $('fbmod-title').value = state.draft.name;
  let filename = state.draft.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '-').replace(/[. ]+$/g, '').trim().slice(0, 120) || 'World State';
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(filename)) filename = 'World State - ' + filename;
  $('fbmod-filename').value = /\.fbmod$/i.test(filename) ? filename : filename + '.fbmod';
  $('fbmod-export-error').hidden = true;
  $('fbmod-export-dialog').showModal(); $('fbmod-title').focus();
}
async function exportMod() {
  $('fbmod-export-error').hidden = true;
  if (!(await save())) {
    $('fbmod-export-error').textContent = $('toast-detail').textContent;
    $('fbmod-export-error').hidden = false; return;
  }
  if (!state.preview?.can_export) {
    $('fbmod-export-error').textContent = 'Resolve the highlighted story conflict before exporting.';
    $('fbmod-export-error').hidden = false; return;
  }
  busy(true);
  try {
    const result = await api('/api/export', {profile_id: state.draft.profile_id, revision: state.draft.revision,
      title: $('fbmod-title').value.trim(), filename: $('fbmod-filename').value.trim()});
    const file = data => new Blob([Uint8Array.from(atob(data), character => character.charCodeAt(0))],
      {type: 'application/octet-stream'});
    downloadBlob(file(result.files.mod), result.name);
    $('fbmod-export-dialog').close();
    toast('FBMOD downloaded · Revision ' + result.revision,
      result.name + (state.showDiagnostics ? '\nSHA-256: ' + result.sha256 : '') +
        (result.warnings?.length ? '\n' + result.warnings.join('\n') : ''), false,
      [{label: 'Download report', run: () => downloadBlob(file(result.files.report), result.report_name)}]);
  } catch (error) { $('fbmod-export-error').textContent = error.message; $('fbmod-export-error').hidden = false; }
  finally { busy(false); }
}
function renderFbmodIcon() {
  const source = state.fbmodIcon || state.presetIcon;
  $('fbmod-icon-preview').hidden = !source;
  if (source) $('fbmod-icon-preview').src = source;
  else $('fbmod-icon-preview').removeAttribute('src');
  $('fbmod-icon-label').textContent = state.fbmodIcon ? 'Custom icon' : 'Preset icon';
  $('reset-fbmod-icon').disabled = !state.fbmodIcon;
}
async function openFbmodSettings() {
  if (state.busy) return;
  setMenu(false); busy(true);
  try {
    const result = await api('/api/export-settings?base_preset=' + encodeURIComponent(state.draft.base_preset));
    $('fbmod-author').value = result.settings.author;
    $('fbmod-description').value = result.settings.description;
    $('fbmod-category').value = result.category;
    state.fbmodIcon = result.settings.icon_data_url; state.presetIcon = result.preset_icon_data_url;
    state.iconLoading = false; $('save-fbmod-settings').disabled = false;
    $('fbmod-icon-file').value = ''; $('fbmod-settings-error').hidden = true; renderFbmodIcon();
    $('fbmod-settings-dialog').showModal();
  } catch (error) { toast('Could not open FBMOD settings', error.message, true); }
  finally { busy(false); }
  if ($('fbmod-settings-dialog').open) $('fbmod-author').focus();
}
function renderNewSource() {
  const creating = state.nameAction === 'new', source = $('new-source').value;
  const importing = creating && source !== 'preset';
  $('new-source-field').hidden = !creating;
  $('new-name-field').hidden = importing;
  $('new-name').required = !importing;
  $('new-name').disabled = importing;
  $('preset-field').hidden = !creating || importing;
  $('new-save-hint').hidden = !importing;
  $('name-submit').textContent = !creating ? 'Duplicate World State' : importing
    ? 'Choose ' + source.toUpperCase() + ' save' : 'Create World State';
}
async function nameDialog(action) {
  setMenu(false);
  $('profile-dialog').close();
  if (action === 'new' && !(await ensureLeave())) return;
  if (action === 'duplicate' && !(await save())) return;
  state.nameAction = action;
  $('name-title').textContent = action === 'new' ? 'New World State' : 'Duplicate World State';
  $('name-eyebrow').textContent = action === 'new' ? 'NEW WORLD STATE' : 'DUPLICATE WORLD STATE';
  $('new-name').value = action === 'new' ? '' : state.draft.name + ' — Copy';
  $('new-source').value = 'preset';
  $('new-source-error').hidden = true;
  renderNewSource();
  $('new-preset').replaceChildren();
  const presets = [...state.boot.presets].sort((a, b) => a.id === state.boot.default_preset ? -1 : b.id === state.boot.default_preset ? 1 : a.label.localeCompare(b.label));
  for (const preset of presets) $('new-preset').append(new Option(preset.label, preset.id));
  $('name-dialog').showModal(); $('new-name').focus();
}

async function init() {
  try {
    state.boot = await api('/api/bootstrap'); state.profiles = state.boot.profiles;
    document.querySelector('.build-tag').textContent = state.boot.app_version || 'PREVIEW';
    try { setEditorView(localStorage.getItem('the-studio-quick-editor') === 'true' ? 'quick' : 'tapestry'); } catch (_) {}
    const mostRecent = [...state.profiles].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (mostRecent) await loadProfile(mostRecent); else await newDraft();
    $('loading').hidden = true;
    if (state.boot.storage_warnings?.length) toast('Some World State folders could not be reorganized', state.boot.storage_warnings.join('\n'), true);
  } catch (error) {
    $('loading').querySelector('p').textContent = error.message;
    $('loading').classList.add('failed');
  }
}

$('profile-name').oninput = event => {
  if (state.busy) return;
  state.draft.name = event.target.value; state.touched = true;
  ++previewSequence;
  state.previewPending = true; renderHeader();
  clearTimeout(previewTimer); previewTimer = setTimeout(preview, 400);
};
$('save-profile').onclick = save;
$('export-mod').onclick = openExportDialog;
$('fbmod-export-form').onsubmit = event => { event.preventDefault(); exportMod(); };
$('drawer-fbmod-settings').onclick = openFbmodSettings;
$('export-settings-link').onclick = openFbmodSettings;
function cancelIconRead() {
  state.iconReadSequence = (state.iconReadSequence || 0) + 1;
  state.iconLoading = false;
  $('save-fbmod-settings').disabled = false;
  $('fbmod-icon-file').value = '';
}
$('choose-fbmod-icon').onclick = () => $('fbmod-icon-file').click();
$('fbmod-settings-dialog').addEventListener('close', cancelIconRead);
$('reset-fbmod-icon').onclick = () => { cancelIconRead(); state.fbmodIcon = null; renderFbmodIcon(); };
$('fbmod-icon-file').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  cancelIconRead(); const sequence = state.iconReadSequence;
  state.iconLoading = true; $('save-fbmod-settings').disabled = true; $('fbmod-settings-error').hidden = true;
  try {
    if (file.size > 512 * 1024) throw new Error('Choose a PNG or JPEG icon no larger than 512 KB.');
    if (!['image/png', 'image/jpeg'].includes(file.type)) throw new Error('Choose a PNG or JPEG icon.');
    const url = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('This image could not be read.')); reader.readAsDataURL(file);
    });
    const image = new Image(); image.src = url; await image.decode();
    if (sequence !== state.iconReadSequence) return;
    if (image.naturalWidth > 2048 || image.naturalHeight > 2048) throw new Error('Icon dimensions must be at most 2048 pixels.');
    state.fbmodIcon = url; renderFbmodIcon();
  } catch (error) {
    if (sequence === state.iconReadSequence) { $('fbmod-settings-error').textContent = error.message; $('fbmod-settings-error').hidden = false; }
  } finally {
    if (sequence === state.iconReadSequence) { state.iconLoading = false; $('save-fbmod-settings').disabled = false; event.target.value = ''; }
  }
};
$('fbmod-settings-form').onsubmit = async event => {
  event.preventDefault(); if (state.busy || state.iconLoading) return;
  $('fbmod-settings-error').hidden = true; busy(true);
  try {
    await api('/api/export-settings', {author: $('fbmod-author').value.trim(),
      description: $('fbmod-description').value, icon_data_url: state.fbmodIcon});
    $('fbmod-settings-dialog').close(); toast('FBMOD settings saved');
  } catch (error) { $('fbmod-settings-error').textContent = error.message; $('fbmod-settings-error').hidden = false; }
  finally { busy(false); }
};
$('dismiss-toast').onclick = () => { $('toast').hidden = true; };
function renderManagement() {
  $('show-history').disabled = !state.draft.profile_id;
  const select = $('open-profile-select'); select.replaceChildren();
  for (const profile of [...state.profiles].sort((a, b) => a.name.localeCompare(b.name))) select.append(new Option(profile.name, profile.profile_id));
  if (state.draft.profile_id) select.value = state.draft.profile_id;
  $('open-profile').disabled = !state.profiles.length;
  $('delete-profile').disabled = !state.profiles.length;
  select.disabled = !state.profiles.length;
  if (!state.profiles.length) select.append(new Option('No saved World States yet', ''));
}
$('profile-menu').onclick = () => {
  setMenu(false);
  renderManagement();
  $('deleted-profiles-details').open = false;
  $('profile-dialog').showModal();
};
async function renderDeletedProfiles() {
  const list = $('deleted-profiles-list'); list.replaceChildren();
  const sequence = state.deletedListSequence = (state.deletedListSequence || 0) + 1;
  state.deletedProfiles = []; $('empty-deleted-profiles').disabled = true;
  try {
    const profiles = await api('/api/deleted-profiles');
    if (sequence !== state.deletedListSequence) return;
    state.deletedProfiles = profiles;
    $('empty-deleted-profiles').disabled = !profiles.length;
    if (!profiles.length) list.append(el('p', 'form-hint', 'No deleted World States.'));
    for (const profile of profiles) {
      const row = el('div', 'deleted-profile-row');
      const restore = el('button', 'button secondary', 'Restore');
      restore.setAttribute('aria-label', 'Restore ' + profile.name);
      restore.disabled = !!profile.purge_incomplete;
      restore.onclick = async () => {
        if (state.busy) return;
        busy(true);
        try {
          const restored = await api('/api/profile/restore', {profile_id: profile.profile_id, revision: profile.revision});
          updateProfile(restored); renderProfiles(); renderManagement();
          await renderDeletedProfiles();
          toast('World State restored', restored.name);
        } catch (error) { toast('Could not restore this World State', error.message, true); }
        finally { busy(false); }
      };
      const remove = el('button', 'button secondary danger', 'Delete permanently');
      remove.setAttribute('aria-label', 'Delete ' + profile.name + ' permanently');
      remove.onclick = () => confirmPurge([profile]);
      const actions = el('div', 'deleted-profile-actions'); actions.append(restore, remove);
      row.append(el('span', '', profile.name + (profile.purge_incomplete ? ' · Deletion incomplete; retry cleanup' : '')), actions);
      list.append(row);
    }
  } catch (error) { if (sequence === state.deletedListSequence) list.append(el('p', 'form-hint', error.message)); }
}
function confirmPurge(profiles) {
  if (state.busy || !profiles.length) return;
  state.purgeProfiles = profiles.map(profile => ({...profile}));
  $('purge-profiles-title').textContent = profiles.length === 1 ? 'Delete this World State permanently?' : 'Empty deleted World States?';
  const names = $('purge-profile-names'); names.replaceChildren();
  for (const profile of profiles) names.append(el('li', '', profile.name));
  $('purge-profiles-count').textContent = profiles.length + (profiles.length === 1 ? ' World State' : ' World States');
  $('confirm-purge-profiles').disabled = false;
  $('purge-profiles-error').hidden = true;
  $('purge-profiles-dialog').showModal(); $('cancel-purge-profiles').focus();
}
$('empty-deleted-profiles').onclick = () => confirmPurge(state.deletedProfiles || []);
$('purge-profiles-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('purge-profiles-dialog').addEventListener('close', () => { state.purgeProfiles = null; });
$('confirm-purge-profiles').onclick = async () => {
  if (state.busy || !state.purgeProfiles || $('confirm-purge-profiles').disabled) return;
  const profiles = state.purgeProfiles.map(({profile_id, revision, deletion_token}) => ({profile_id, revision, deletion_token}));
  busy(true); $('purge-profiles-error').hidden = true;
  try {
    const result = await api('/api/profiles/purge', {profiles});
    $('purge-profiles-dialog').close();
    await renderDeletedProfiles();
    toast('Permanently deleted', result.purged.length + (result.purged.length === 1 ? ' World State and its saved revisions removed.' : ' World States and their saved revisions removed.'));
  } catch (error) {
    $('confirm-purge-profiles').disabled = true;
    $('purge-profiles-error').textContent = error.message + ' Close this dialog and review the remaining deleted World States before trying again.';
    $('purge-profiles-error').hidden = false;
    await renderDeletedProfiles();
  } finally { busy(false); }
};
$('deleted-profiles-details').addEventListener('toggle', () => {
  if ($('deleted-profiles-details').open) renderDeletedProfiles();
});
$('delete-profile').onclick = async () => {
  if (state.busy) return;
  const profile = state.profiles.find(item => item.profile_id === $('open-profile-select').value);
  if (!profile) return;
  $('profile-dialog').close();
  if (profile.profile_id === state.draft.profile_id && !(await ensureLeave())) return;
  // ensureLeave may have saved another revision; capture that version for deletion.
  state.deletingProfile = state.profiles.find(item => item.profile_id === profile.profile_id);
  $('delete-profile-name').textContent = state.deletingProfile.name;
  $('delete-profile-error').hidden = true;
  $('delete-profile-dialog').showModal();
};
$('delete-profile-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('delete-profile-dialog').addEventListener('close', () => { state.deletingProfile = null; });
$('confirm-delete-profile').onclick = async () => {
  const profile = state.deletingProfile;
  if (!profile || state.busy) return;
  busy(true); $('delete-profile-error').hidden = true;
  try {
    await api('/api/profile/delete', {profile_id: profile.profile_id, revision: profile.revision});
    state.profiles = state.profiles.filter(item => item.profile_id !== profile.profile_id);
    $('delete-profile-dialog').close();
    if (state.draft.profile_id === profile.profile_id) {
      await newDraft();
    } else renderProfiles();
    toast('World State deleted', profile.name + ' can be restored from Manage World States.');
  } catch (error) { $('delete-profile-error').textContent = error.message; $('delete-profile-error').hidden = false; }
  finally { busy(false); }
};
$('open-profile').onclick = async () => {
  const id = $('open-profile-select').value; $('profile-dialog').close();
  if (!(await ensureLeave())) return;
  try { const profile = await api('/api/profile/' + id); updateProfile(profile); await loadProfile(profile); }
  catch (error) { toast('Could not open this World State', error.message, true); }
};
$('import-from-manage').onclick = async () => {
  $('profile-dialog').close(); if (await ensureLeave()) $('import-file').click();
};
$('import-save-from-manage').onclick = () => {
  $('profile-dialog').close(); $('save-import-file').click();
};
$('import-dao-save-from-manage').onclick = () => {
  $('profile-dialog').close(); $('dao-save-import-file').click();
};
$('import-save').onclick = () => {
  if (!state.busy) $('import-save-game-dialog').showModal();
};
$('import-dao-save').onclick = () => {
  if (state.busy) return;
  $('import-save-game-dialog').close(); $('dao-save-import-file').click();
};
$('import-da2-save').onclick = () => {
  if (state.busy) return;
  $('import-save-game-dialog').close(); $('save-import-file').click();
};
function renderSaveImportReview(result = state.saveImport) {
  $('show-import-review').checked = !!state.showImportReview;
  $('show-save-import-review').checked = !!state.showImportReview;
  if (!result) return;
  const merging = !!result.target_profile_id;
  $('save-import-recognized').hidden = merging || !state.showImportReview;
  $('save-import-recognized-title').hidden = merging || !state.showImportReview;
  $('dao-import-changes').hidden = !state.showImportReview;
  $('save-import-unresolved-details').hidden = !state.showImportReview;
  $('save-import-diagnostics').hidden = !state.showImportReview;
}
function setImportReview(event) {
  state.showImportReview = event.target.checked;
  renderSaveImportReview();
}
function renderSaveImport(result) {
  const dao = result.game === 'dao', merging = !!result.target_profile_id;
  $('save-import-game').textContent = dao ? 'IMPORT DAO SAVE' : 'IMPORT DA2 SAVE';
  $('dao-import-options').hidden = false;
  $('dao-import-policy-field').hidden = !merging;
  $('dao-import-target').value = result.target_profile_id || '';
  $('dao-import-policy').value = result.policy || 'missing';
  $('save-import-name-field').hidden = merging;
  $('save-import-name').disabled = merging;
  $('save-import-name').value = merging ? result.target_name : state.saveImportNewName || result.suggested_name;
  $('save-import-title').textContent = merging ? 'Update ' + result.target_name : 'Import a World State';
  $('save-import-summary').textContent = result.character + ' · ' + result.stage + ' · ' +
    (dao ? result.counts.dao.recovered + ' DAO choices recovered' : result.counts.da2.recovered + ' DA2 choices + ' + result.counts.dao.recovered + ' DAO choices recovered');
  $('save-import-description').textContent = merging
    ? (dao ? 'Only recovered DAO outcomes can change. DA2 choices stay as they are.' : 'Recovered DA2 choices and carried DAO history can change.') + ' Outcomes missing from this save retain the World State’s existing answers or inherited values.'
    : dao ? 'This creates a new World State from this save’s recovered DAO choices. Other choices use the default World State until you fill them in.'
    : 'This creates a new World State from this save’s DA2 choices and carried DAO history. Choices that cannot be recovered use the default World State until you fill them in.';
  $('save-import-restrictions').textContent = result.restriction_message;
  const recognized = $('save-import-recognized'); recognized.replaceChildren();
  for (const entry of result.recognized) {
    const row = el('li'); row.append(el('strong', '', (entry.choice_id.startsWith('dao.') ? 'DAO · ' : 'DA2 · ') + entry.title), el('span', '', entry.label));
    row.append(el('small', 'diagnostic', entry.evidence)); recognized.append(row);
  }
  $('dao-import-review').hidden = !merging;
  const changes = $('dao-import-changes'); changes.replaceChildren();
  if (merging) {
    const counts = {added: 0, replaced: 0, kept: 0, unchanged: 0};
    for (const entry of result.changes) {
      counts[entry.status]++;
      const copy = entry.status === 'kept' ? 'Keep existing: ' + entry.before_label + ' · Save contains: ' + entry.incoming_label
        : entry.status === 'unchanged' ? 'Unchanged: ' + entry.before_label
        : (entry.status === 'added' ? 'Add: ' : 'Replace: ') + entry.before_label + ' → ' + entry.after_label;
      const row = el('li'); row.append(el('strong', '', entry.title), el('span', '', copy)); changes.append(row);
    }
    $('dao-import-change-summary').textContent = counts.added + ' added · ' + counts.replaced + ' replaced · ' + counts.kept + ' kept · ' + counts.unchanged + ' unchanged' + (result.has_changes ? '' : '. No changes to apply.');
  }
  $('save-import-unresolved-title').textContent = dao ? result.counts.dao.unresolved + ' DAO choices still need review'
    : result.counts.da2.unresolved + ' DA2 + ' + result.counts.dao.unresolved + ' DAO choices still need review';
  const missing = result.counts.dao.unresolved + (dao ? 0 : result.counts.da2.unresolved);
  $('save-import-notice').hidden = !missing;
  $('save-import-notice').textContent = missing + (missing === 1 ? ' choice could not' : ' choices could not') +
    ' be recovered from this save. ' + (merging ? 'Existing answers are kept; fill in any missing choices manually.'
      : 'Choose those answers manually; default answers are used until then.') + ' Enable Show import review to see the list.';
  const unresolved = $('save-import-unresolved'); unresolved.replaceChildren();
  for (const entry of result.unresolved) {
    const row = el('li'); row.append(el('strong', '', (entry.choice_id.startsWith('dao.') ? 'DAO · ' : 'DA2 · ') + entry.title), el('span', '', entry.reason)); unresolved.append(row);
  }
  $('save-import-unresolved-details').open = false;
  $('save-import-diagnostics').textContent = 'Save SHA-256: ' + result.save_sha256 + '\n' + result.restriction_reasons.join('\n');
  renderSaveImportReview(result);
  $('confirm-save-import').textContent = merging ? 'Apply choices' : 'Create World State';
  $('confirm-save-import').disabled = merging && !result.has_changes;
  $('save-import-error').hidden = true;
}
async function chooseSaveImport(event, game, {leaveChecked = false, errorId = null} = {}) {
  const file = event.target.files[0]; event.target.value = '';
  if (!file || (!leaveChecked && !(await ensureLeave()))) return false;
  const failed = error => {
    if (errorId) { $(errorId).textContent = error.message; $(errorId).hidden = false; }
    else toast('Could not import save', error.message, true);
  };
  if (file.size > 32 * 1024 * 1024) {
    failed(new Error('Choose a ' + game.toUpperCase() + ' .das save no larger than 32 MB.')); return false;
  }
  busy(true);
  try {
    const response = await backend.fetch(game === 'dao' ? '/api/dao-save-import/preview' : '/api/save-import/preview', {method: 'POST',
      headers: {'Content-Type': 'application/octet-stream'}, body: file});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The save could not be read.');
    state.saveImport = result; state.saveImportNewName = result.suggested_name;
    $('review-remaining-after-import').checked = false;
    const targets = $('dao-import-target'); targets.replaceChildren();
    targets.append(new Option('Create a new World State', ''));
    for (const profile of [...state.profiles].sort((a, b) => a.name.localeCompare(b.name)))
      targets.append(new Option('Update: ' + profile.name, profile.profile_id));
    renderSaveImport(result); $('save-import-dialog').showModal();
    return true;
  } catch (error) { failed(error); return false; }
  finally { busy(false); if ($('save-import-dialog').open) $('save-import-name').focus(); }
}
$('save-import-file').onchange = event => chooseSaveImport(event, 'da2');
$('dao-save-import-file').onchange = event => chooseSaveImport(event, 'dao');
async function planSaveImport() {
  if (!state.saveImport || state.busy) return;
  if (!state.saveImport.target_profile_id) state.saveImportNewName = $('save-import-name').value;
  const id = $('dao-import-target').value, target = state.profiles.find(p => p.profile_id === id);
  if (id && !target) return;
  busy(true); $('confirm-save-import').disabled = true;
  try {
    const result = await api('/api/save-import/plan', {import_id: state.saveImport.import_id,
      target_profile_id: target?.profile_id || null, target_revision: target?.revision || 0,
      policy: $('dao-import-policy').value});
    state.saveImport = result; renderSaveImport(result);
  } catch (error) { $('save-import-error').textContent = error.message; $('save-import-error').hidden = false; }
  finally { busy(false); }
}
$('dao-import-target').onchange = planSaveImport;
$('dao-import-policy').onchange = planSaveImport;
$('save-import-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('save-import-dialog').addEventListener('close', () => {
  if (!state.saveImport) return;
  const import_id = state.saveImport.import_id; state.saveImport = null;
  api('/api/save-import/cancel', {import_id}).catch(() => {});
});
$('save-import-form').onsubmit = async event => {
  event.preventDefault();
  if (!state.saveImport || state.busy || $('confirm-save-import').disabled) return;
  const review = state.saveImport, game = review.game || 'da2', merging = !!review.target_profile_id;
  const reviewRemaining = $('review-remaining-after-import').checked;
  busy(true); $('save-import-error').hidden = true;
  try {
    const profile = await api('/api/save-import/commit', {import_id: review.import_id,
      name: merging ? review.target_name : $('save-import-name').value.trim()});
    state.saveImport = null; $('save-import-dialog').close();
    state.game = game; state.category = null; setEditorView('tapestry');
    state.reviewRemaining = reviewRemaining;
    if (reviewRemaining) {
      state.searchEnabled = true; state.searchQuery = ''; state.unchosenOnly = true;
      $('choice-search').value = ''; $('unchosen-choices-only').checked = true;
    }
    updateProfile(profile); await loadProfile(profile);
    toast(game.toUpperCase() + (merging ? ' choices imported' : ' save imported'),
      (merging ? 'Updated ' : 'Created ') + profile.name + '. Review the remaining choices before exporting.');
  } catch (error) { $('save-import-error').textContent = error.message; $('save-import-error').hidden = false; }
  finally { busy(false); }
};
$('new-sidebar').onclick = () => nameDialog('new');
$('new-profile').onclick = () => nameDialog('new');
$('duplicate-profile').onclick = () => nameDialog('duplicate');
$('new-source').onchange = () => { $('new-source-error').hidden = true; renderNewSource(); };
$('new-save-import-file').onchange = async event => {
  if (!event.target.files[0]) { event.target.value = ''; return; }
  const game = state.newSaveGame; state.newSaveGame = null;
  if (state.nameAction !== 'new' || !['dao', 'da2'].includes(game)) { event.target.value = ''; return; }
  $('name-dialog').close();
  // The creation dialog already passed the unsaved-changes guard. Its modal
  // file picker cannot edit the underlying draft; do not ask a second time.
  const opened = await chooseSaveImport(event, game, {leaveChecked: true, errorId: 'new-source-error'});
  if (!opened) { $('name-dialog').showModal(); $('name-submit').focus(); }
};
$('name-form').onsubmit = async event => {
  event.preventDefault();
  if (state.busy) return;
  if (state.nameAction === 'new' && ['dao', 'da2'].includes($('new-source').value)) {
    state.newSaveGame = $('new-source').value;
    $('new-source-error').hidden = true; $('new-save-import-file').click(); return;
  }
  const name = $('new-name').value.trim(); if (!name) return;
  if (state.nameAction === 'new') {
    $('name-dialog').close(); await newDraft(name, $('new-preset').value); state.touched = true;
  } else {
    busy(true);
    try {
      const profile = await api('/api/duplicate', {profile_id: state.draft.profile_id, revision: state.draft.revision, name});
      updateProfile(profile); $('name-dialog').close(); await loadProfile(profile);
      toast('World State duplicated', profile.name);
    } catch (error) { toast('Could not duplicate this World State', error.message, true); }
    finally { busy(false); }
  }
};
$('inherit-choice').onclick = async () => {
  const choice = state.activeChoice;
  await changeIllustratedChoice(choice, null);
};
$('approve-answer').onclick = async () => {
  const choice = state.activeChoice, answer = state.candidateAnswer;
  if (!choice || !choice.answers.some(item => item.id === answer) || state.busy || state.previewPending) return;
  await changeIllustratedChoice(choice, answer);
};
$('previous-answer').onclick = () => stepAnswer(-1);
$('next-answer').onclick = () => stepAnswer(1);
$('cancel-choice').onclick = closeChoice;
$('answer-cards').onkeydown = event => {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); stepAnswer(event.key === 'ArrowLeft' ? -1 : 1); }
};
for (const [id, value] of [['unsaved-cancel', 'cancel'], ['unsaved-discard', 'discard'], ['unsaved-save', 'save']]) {
  $(id).onclick = () => $('unsaved-dialog').close(value);
}
document.querySelectorAll('[data-close]').forEach(button => { button.onclick = () => $(button.dataset.close).close(); });
function gameMenuItems() { return [...$('game-menu').querySelectorAll('[data-game]')]; }
function setGameMenu(open, focus = false) {
  $('game-menu').hidden = !open;
  $('game-select').setAttribute('aria-expanded', String(open));
  for (const item of gameMenuItems()) item.tabIndex = -1;
  if (open) {
    const selected = gameMenuItems().find(item => item.dataset.game === state.game);
    selected.tabIndex = 0;
    selected.focus({preventScroll: true});
  } else if (focus) $('game-select').focus({preventScroll: true});
}
$('game-select').onpointerdown = event => { if (!$('game-menu').hidden) event.preventDefault(); };
$('game-select').onclick = () => setGameMenu($('game-menu').hidden, true);
$('game-select').onkeydown = event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setGameMenu(true); }
};
for (const item of gameMenuItems()) item.onclick = () => {
  setGameMenu(false, true);
  if (item.dataset.game === state.game && !state.reviewRemaining) return;
  stopRemainingReview();
  clearChoicePreview(); state.game = item.dataset.game; state.category = null; render();
  window.scrollTo({top: 0, behavior: 'instant'});
};
$('game-menu').onkeydown = event => {
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const items = gameMenuItems(), current = items.indexOf(document.activeElement);
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
    : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
  for (const item of items) item.tabIndex = -1;
  items[index].tabIndex = 0; items[index].focus();
};
$('game-menu').addEventListener('focusout', event => {
  if (!$('game-menu').contains(event.relatedTarget)) setGameMenu(false);
});
$('game-home').onclick = () => { setEditorView('tapestry'); navigateCategory(null); };
function setMenu(open) {
  if (state.busy && open) return;
  if (open) setGameMenu(false);
  state.menuOpen = open;
  $('side-menu').hidden = !open;
  $('side-menu').inert = !open;
  $('menu-backdrop').hidden = !open;
  $('menu-toggle').setAttribute('aria-expanded', String(open));
  $('studio-main').inert = open;
  document.body.classList.toggle('menu-open', open);
  if (open) $('close-menu').focus();
  else $('menu-toggle').focus({preventScroll: true});
}
$('menu-toggle').onclick = () => setMenu(!state.menuOpen);
$('close-menu').onclick = () => setMenu(false);
$('menu-backdrop').onclick = () => setMenu(false);
$('drawer-tapestry').onclick = () => { setMenu(false); setEditorView('tapestry'); navigateCategory(null); };
$('drawer-profiles').onclick = () => $('profile-menu').click();
$('view-options').onclick = () => {
  setGameMenu(false);
  const open = $('options-panel').hidden;
  $('options-panel').hidden = !open; $('view-options').setAttribute('aria-expanded', String(open));
};
document.addEventListener('click', event => {
  if (!event.target.closest('#game-menu, #game-select')) setGameMenu(false);
  if (!event.target.closest('.view-options')) { $('options-panel').hidden = true; $('view-options').setAttribute('aria-expanded', 'false'); }
});
$('enable-quick').onchange = event => {
  clearChoicePreview();
  setEditorView(event.target.checked ? 'quick' : 'tapestry');
  $('options-panel').hidden = true; $('view-options').setAttribute('aria-expanded', 'false'); render();
  $('view-title').focus({preventScroll: true});
};
function switchEditorView(view) {
  clearChoicePreview(); setEditorView(view);
  $('options-panel').hidden = true; $('view-options').setAttribute('aria-expanded', 'false');
  render(); $('view-title').focus({preventScroll: true});
}
$('tapestry-view').onclick = () => switchEditorView('tapestry');
$('quick-view').onclick = () => switchEditorView('quick');
$('show-diagnostics').onchange = event => { state.showDiagnostics = event.target.checked; render(); };
$('show-import-review').onchange = setImportReview;
$('show-save-import-review').onchange = setImportReview;
$('enable-search').onchange = event => {
  state.searchEnabled = event.target.checked;
  if (!state.searchEnabled) {
    state.reviewRemaining = false;
    state.searchQuery = ''; state.unchosenOnly = false;
    $('choice-search').value = ''; $('unchosen-choices-only').checked = false;
  }
  $('options-panel').hidden = true; $('view-options').setAttribute('aria-expanded', 'false');
  render();
  if (state.searchEnabled && !state.activeChoice) $('choice-search').focus();
};
$('choice-search').oninput = event => { state.searchQuery = event.target.value; render(); };
$('unchosen-choices-only').onchange = event => {
  state.unchosenOnly = event.target.checked;
  if (!state.unchosenOnly) state.reviewRemaining = false;
  render();
};
$('leave-remaining-review').onclick = () => { setEditorView('tapestry'); navigateCategory(null); };
$('clear-choice-search').onclick = () => {
  const reviewing = state.reviewRemaining;
  stopRemainingReview();
  state.searchQuery = ''; state.unchosenOnly = false;
  $('choice-search').value = ''; $('unchosen-choices-only').checked = false;
  render(); (reviewing ? $('view-title') : $('choice-search')).focus();
};
$('story-unrestricted').onchange = async event => {
  const mode = event.target.checked ? 'experimental' : 'keep';
  await requestStoryChange({}, mode);
};
$('review-story').onclick = () => requestStoryChange({}, 'keep');
$('cancel-story-change').onclick = () => $('story-change-dialog').close('cancel');
$('apply-story-change').onclick = () => $('story-change-dialog').close('apply');
$('import-profile').onclick = async () => { setMenu(false); if (await ensureLeave()) $('import-file').click(); };
$('import-file').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 1048576) { toast('Could not import World State', 'World State documents must be smaller than 1 MiB.', true); event.target.value = ''; return; }
  busy(true);
  try {
    const document = JSON.parse(await file.text());
    const profile = await api('/api/import', {document}); updateProfile(profile); await loadProfile(profile);
    toast('World State imported', 'Created an independent copy of ' + profile.name);
  } catch (error) { toast('Could not import World State', error.message, true); }
  finally { busy(false); event.target.value = ''; }
};
$('export-json').onclick = async () => {
  $('profile-dialog').close(); if (!(await save())) return;
  const profile = state.profiles.find(item => item.profile_id === state.draft.profile_id);
  const {editor_choices, ...portable} = profile;
  const name = profile.name.replace(/[^\p{L}\p{N}._-]+/gu, '-') + '.profile.json';
  downloadBlob(new Blob([JSON.stringify(portable, null, 2) + '\n'], {type: 'application/json'}), name);
};
async function showHistory() {
  if (state.busy || !state.draft.profile_id) return;
  $('profile-dialog').close(); busy(true);
  try {
    const profiles = await api('/api/history/' + state.draft.profile_id), list = $('history-list'); list.replaceChildren();
    state.historyProfile = profiles[0];
    $('clear-history').disabled = profiles.length < 2;
    for (const profile of profiles) {
      const row = el('div', 'history-item');
      row.append(el('strong', '', 'Revision ' + profile.revision), el('span', '', profile.name),
        el('small', '', new Date(profile.updated_at).toLocaleString() + ' · ' + Object.keys(profile.choices).length + ' explicit choices'));
      list.append(row);
    }
    $('history-dialog').showModal();
  } catch (error) { toast('Could not load revisions', error.message, true); }
  finally { busy(false); }
}
$('show-history').onclick = showHistory;
$('clear-history').onclick = () => {
  if (state.busy || !state.historyProfile || $('clear-history').disabled) return;
  $('history-dialog').close();
  state.clearingHistory = {...state.historyProfile};
  $('clear-history-name').textContent = state.clearingHistory.name;
  $('clear-history-error').hidden = true;
  $('confirm-clear-history').disabled = false;
  $('clear-history-dialog').showModal(); $('cancel-clear-history').focus();
};
$('clear-history-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('clear-history-dialog').addEventListener('close', () => { state.clearingHistory = null; });
$('confirm-clear-history').onclick = async () => {
  if (state.busy || !state.clearingHistory || $('confirm-clear-history').disabled) return;
  const {profile_id, revision} = state.clearingHistory;
  busy(true); $('clear-history-error').hidden = true;
  try {
    const result = await api('/api/profile/clear-history', {profile_id, revision});
    $('clear-history-dialog').close();
    toast('Saved revisions cleared', result.storage_warning || 'Your current World State has been kept.', Boolean(result.storage_warning));
  } catch (error) {
    $('confirm-clear-history').disabled = true;
    $('clear-history-error').textContent = error.message + ' Close this dialog and reopen Saved revisions before trying again.';
    $('clear-history-error').hidden = false;
  } finally { busy(false); }
};
document.querySelector('.brand').onclick = event => { event.preventDefault(); setMenu(false); setEditorView('tapestry'); navigateCategory(null); };
document.addEventListener('keydown', event => {
  if (state.menuOpen && event.key === 'Tab') {
    const items = [...$('side-menu').querySelectorAll('button:not(:disabled), a[href], input:not([hidden])')].filter(item => item.getClientRects().length);
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault();
    if (!state.busy && state.draft && !document.querySelector('dialog[open]')) save();
  }
  if (event.key === 'Escape') {
    if (!$('game-menu').hidden) { event.preventDefault(); setGameMenu(false, true); return; }
    if (state.menuOpen) setMenu(false);
    else if ($('options-panel').hidden && state.activeChoice && !document.querySelector('dialog[open]')) closeChoice();
    $('options-panel').hidden = true; $('view-options').setAttribute('aria-expanded', 'false');
  }
});
window.addEventListener('beforeunload', event => { if (dirty() && state.touched) { event.preventDefault(); event.returnValue = ''; } });
init();
