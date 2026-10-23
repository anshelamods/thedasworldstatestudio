"""Frozen Keep dependency rules and transactional, bounded repair proposals.

Rules compare semantic Keep values; they never reinterpret export encodings.
A proposal is a new Profile value: no store, revision or game files are written.
"""
from collections import defaultdict
import heapq
from itertools import count

from .model import ProfileError


class RuleSet:
    def __init__(self, catalog):
        self.catalog = catalog
        self.assignments = {key: {answer: set(value['export_values']) for answer, value in definition['answers'].items()}
                            for key, definition in catalog.choices.items()}
        data = catalog.story_rules
        if not data:
            raise ProfileError('This catalog has no Keep dependency rules')
        self.normalizations = data['normalizations']
        self.profile_inputs = data.get('profile_inputs', {})
        self.groups = defaultdict(list)
        self.when_known = {}
        for rule in data['rules']:
            key = (rule.get('group', 'keep'), rule['target'], rule['value'])
            guard = rule.get('when_known')
            if key in self.when_known and self.when_known[key] != guard:
                raise ProfileError('Rule branches disagree about their known-answer guard')
            self.when_known[key] = guard
            self.groups[key].append(tuple((d['question'], d['min'], d['max']) for d in rule['dependencies']))

    def profile_values(self, choices):
        return {source['field']: source['answers'][choices[key]]
                for key, source in self.profile_inputs.items()
                if key in choices and choices[key] in source['answers']}

    def semantic(self, flags, choices=None):
        result = dict(flags)
        for field, mapping in self.normalizations.items():
            result[field] = mapping.get(str(flags.get(field)), flags.get(field))
        result.update(self.profile_values(choices or {}))
        return result

    @staticmethod
    def satisfies(flags, dependency):
        field, minimum, maximum = dependency
        value = flags.get(field)
        return type(value) is int and minimum <= value <= maximum

    def violations(self, flags, choices=None, *, preset_id=None):
        flags = self.semantic(flags, choices)
        exceptions = self.catalog.preset(preset_id).get('inherited_rule_exceptions', []) if preset_id else []
        explicit_fields = {field for key, answer in (choices or {}).items()
                           for field in self.assignments[key][answer]} if exceptions else set()

        def inherited_exception(key):
            # Preserve the original game's inconsistent, untouched Isabela
            # defaults. Editing either related control activates normal rules.
            return any(key[1:] == (entry['target'], entry['value'])
                       and not explicit_fields.intersection(entry['fields'])
                       and all(flags.get(field) == value for field, value in entry['fields'].items())
                       for entry in exceptions)

        return [(key, branches) for key, branches in self.groups.items()
                if (not self.when_known[key] or self.when_known[key] in flags)
                and flags.get(key[1]) == key[2]
                and not inherited_exception(key)
                and not any(all(self.satisfies(flags, dep) for dep in branch) for branch in branches)]

    def messages(self, flags, choices=None, *, preset_id=None):
        result = []
        for (_, target, value), branches in self.violations(flags, choices, preset_id=preset_id):
            alternatives = [' and '.join(f'{name}={lo}' if lo == hi else f'{name}={lo}–{hi}'
                                         for name, lo, hi in branch) for branch in branches]
            result.append(f'{target}={value} requires ' + ' OR '.join(alternatives))
        return result


def propose(profile, updates, *, mode, catalog, editable):
    """Retain every requested edit; propose dependent semantic answers atomically.

    A bounded best-first search repairs one violated dependency at a time. OR
    alternatives are explored separately; AND dependencies are repaired together.
    Ties favor fewer changed answers, preserve hero identity, then catalog order.
    Final technical and story validation uses the actual export compiler.
    """
    from .compiler import choice_assignments, compile_profile
    definitions = catalog.choices
    if not isinstance(updates, dict) or set(updates) - set(editable):
        raise ProfileError('Unsupported choice edit')
    for key, answer in updates.items():
        if answer is not None and answer not in definitions[key]['answers']:
            raise ProfileError('Unsupported answer for ' + key)
    desired = dict(profile.choices)
    for key, answer in updates.items():
        if answer is None:
            desired.pop(key, None)
        else:
            desired[key] = answer
    candidate = profile.edited(choices=desired, mode=mode)
    catalog.validate(candidate)
    if mode != 'keep':
        compile_profile(candidate, catalog=catalog)  # Technical validation still applies.
        return candidate

    if any(definitions[key]['answers'][answer].get('requires_unrestricted') for key, answer in desired.items()):
        raise ProfileError('Choose a standard sibling career or fate before turning off No Story Restrictions.')
    # Most edits need no repairs. Validate them with the actual compiler before
    # constructing the search state. Conflicts, including overlapping flag
    # assignments, still go through the existing bounded repair search.
    try:
        compile_profile(candidate, catalog=catalog)
        return candidate
    except ProfileError:
        pass
    # Import-only partial outcomes cannot serve as repairs for normal Keep rules.
    definitions = {key: dict(definition, answers={answer: data for answer, data in definition['answers'].items()
                    if not data.get('requires_unrestricted')}) for key, definition in definitions.items()}

    rules = RuleSet(catalog)
    base = compile_profile(profile.edited(choices={}, mode='experimental'), catalog=catalog)
    baseline = dict(base.effective_values)
    before = compile_profile(profile.edited(mode='experimental'), catalog=catalog)
    original = before.report['resolved_choices']
    locked = set(updates)
    editable = tuple(editable)
    field_owners = defaultdict(list)
    for key in editable:
        for field in {f for a in definitions[key]['answers'].values() for f in a['export_values']}:
            field_owners[field].append(key)
        if key in rules.profile_inputs:
            field_owners[rules.profile_inputs[key]['field']].append(key)

    def evaluate(choices):
        effective = dict(baseline)
        owners = {}
        collisions = []
        for key, answer in sorted(choices.items()):
            values = choice_assignments(catalog, choices, key, definitions[key]['answers'][answer])
            for field, value in values.items():
                if field in owners and effective[field] != value:
                    collisions.append((field, owners[field], key))
                effective[field], owners[field] = value, key
        # Local Keep-only questions participate in proposals, but never enter
        # the compiled game's effective values or the FBMOD writer.
        effective.update(rules.profile_values(choices))
        return effective, collisions, rules.violations(effective, choices, preset_id=profile.base_preset)

    def rank(choices, effective, problems):
        # Count semantic changes rather than making inherited answers expensive.
        changes = sum(key not in locked and answer != original[key]['answer_id'] for key, answer in choices.items())
        identity = sum(effective.get(f) != before.effective_values.get(f)
                       for f in ('dao_warden_mf', 'dao_warden_race', 'dao_warden_background',
                                 'dao_warden_class', 'da2_hawke_mf'))
        return changes * 10 + identity * 3 + problems * 18

    sequence = count()
    queue, visited = [], set()

    def enqueue(choices):
        signature = tuple(sorted(choices.items()))
        if signature in visited:
            return
        visited.add(signature)
        effective, collisions, violations = evaluate(choices)
        heapq.heappush(queue, (rank(choices, effective, len(collisions) + len(violations)),
                               next(sequence), choices, effective, collisions, violations))

    def set_field(choices, field, minimum, maximum):
        for owner in field_owners.get(field, ()):
            if owner in locked:
                continue
            for answer, definition in definitions[owner]['answers'].items():
                if choices.get(owner) == answer:
                    continue
                trial = dict(choices, **{owner: answer})
                effective, _, _ = evaluate(trial)
                if rules.satisfies(rules.semantic(effective), (field, minimum, maximum)):
                    yield trial

    enqueue(desired)
    examined = 0
    while queue and examined < 12000:
        _, _, choices, effective, collisions, violations = heapq.heappop(queue)
        examined += 1
        if not collisions and not violations:
            result = candidate.edited(choices=choices)
            try:
                compile_profile(result, catalog=catalog)
            except ProfileError:
                # Never offer an export that fails the compiler, even if the
                # semantic rule set alone can accept it.
                continue
            return result
        if collisions:
            field, first, second = collisions[0]
            for owner in (first, second):
                if owner in locked:
                    continue
                for answer in definitions[owner]['answers']:
                    if choices.get(owner) != answer:
                        trial = dict(choices, **{owner: answer})
                        _, new_collisions, _ = evaluate(trial)
                        if (field, first, second) not in new_collisions:
                            enqueue(trial)
            continue
        # Prefer a violation whose target was explicitly requested. This avoids
        # changing an unrelated choice before its downstream cause is repaired.
        violation = next((v for v in violations if set(field_owners[v[0][1]]) & locked), violations[0])
        (_, target, value), branches = violation
        for owner in field_owners.get(target, ()):
            if owner in locked:
                continue
            for answer in definitions[owner]['answers']:
                trial = dict(choices, **{owner: answer})
                flags, _, _ = evaluate(trial)
                if rules.semantic(flags).get(target) != value:
                    enqueue(trial)

        def repair_branch(trial, branch, seen):
            flags, _, _ = evaluate(trial)
            semantic = rules.semantic(flags)
            unmet = next((d for d in branch if not rules.satisfies(semantic, d)), None)
            if unmet is None:
                enqueue(trial)
                return
            signature = tuple(sorted(trial.items()))
            if signature in seen or len(seen) > 200:
                return
            seen = seen | {signature}
            for replacement in set_field(trial, *unmet):
                repair_branch(replacement, branch, seen)

        for branch in branches:
            repair_branch(choices, branch, set())
    raise ProfileError('No compatible set of related choices could be proposed for this answer. '
                       'Cancel the change, adjust related choices, or enable No Story Restrictions.')
