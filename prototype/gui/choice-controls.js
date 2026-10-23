'use strict';

// Illustrated controls can compose existing semantic choices without changing
// historical catalogs or the independent controls in the quick editor.
const choiceControls = (() => {
  function rawAnswer(draft, preview, id) {
    return draft.choices[id] || preview?.resolved_choices[id]?.answer_id || null;
  }
  function members(choice) {
    return [...new Set([choice.id, ...choice.answers.flatMap(answer => Object.keys(answer.related_choices || {}))])];
  }
  function currentAnswer(draft, preview, choice, raw = false) {
    const selected = rawAnswer(draft, preview, choice.id);
    if (raw) return selected;
    const answer = choice.answers.find(item => item.id === selected);
    if (!answer) return null;
    return Object.entries(answer.related_choices || {}).every(([id, value]) => rawAnswer(draft, preview, id) === value)
      ? selected : null;
  }
  function explicit(draft, choice) {
    return members(choice).some(id => Object.hasOwn(draft.choices, id));
  }
  function apply(choices, choice, value) {
    const result = {...choices};
    if (value === null) {
      for (const id of members(choice)) delete result[id];
    } else {
      const answer = choice.answers.find(item => item.id === value);
      if (!answer) throw new Error('Unsupported illustrated answer');
      Object.assign(result, {[choice.id]: value}, answer.related_choices || {});
    }
    return result;
  }
  return Object.freeze({rawAnswer, members, currentAnswer, explicit, apply});
})();
if (typeof module !== 'undefined' && module.exports) module.exports = choiceControls;
