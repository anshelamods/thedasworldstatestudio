"""Reviewed, expiring DAO/DA2 save imports and merge plans. No saves retained."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import secrets
import threading
import time

from world_profiles.compiler import StoryConflict, compile_profile
from world_profiles.model import ProfileError
from world_profiles.storage import RevisionConflict
from .da2 import import_save as import_da2
from .dao import import_save as import_dao


@dataclass(frozen=True)
class PendingImport:
    source: dict
    original: object
    profile: object
    target: object = None
    policy: str = 'missing'


class SaveImports:
    def __init__(self, catalog, store, presentation):
        self.catalog, self.store, self.presentation = catalog, store, presentation
        self.lock = threading.Lock()
        self.pending = {}

    def _expire(self):
        for key, (deadline, _) in list(self.pending.items()):
            if deadline <= time.monotonic():
                del self.pending[key]

    def _restrictions(self, profile):
        reasons = []
        try:
            compile_profile(profile, catalog=self.catalog)
        except StoryConflict as error:
            profile = profile.edited(mode='experimental')
            reasons = compile_profile(profile, catalog=self.catalog).report['story_conflicts'] or [str(error)]
        return profile, reasons

    def _review(self, item):
        result = deepcopy(item.source)
        profile, reasons = self._restrictions(item.profile)
        result['mode'] = profile.mode
        result['restriction_reasons'] = reasons
        result['restriction_message'] = ('No Story Restrictions will be enabled for this imported World State because its recovered choices conflict with normal story rules or inherited defaults. Your choices will be preserved.'
                                        if reasons else 'No Story Restrictions is already enabled for this World State.'
                                        if profile.mode in ('experimental', 'ordinary') else 'Normal story restrictions will remain enabled for this imported World State.')
        for entry in result['recognized'] + result['unresolved']:
            entry['title'] = self.presentation[entry['choice_id']]['title']
        result.update(target_profile_id=item.target.profile_id if item.target else None,
                      target_revision=item.target.revision if item.target else 0,
                      target_name=item.target.name if item.target else None,
                      policy=item.policy, profile_name=profile.name,
                      has_changes=item.target is None or profile.to_dict() != item.target.to_dict())
        result['changes'] = []
        if item.target is not None:
            current = self.catalog.upgrade(item.target)
            before = compile_profile(current.edited(mode='experimental'), catalog=self.catalog)
            definitions = self.catalog.choices
            for key, answer in item.source['choices'].items():
                explicit = key in current.choices
                kept = explicit and item.policy == 'missing'
                after_answer = profile.choices[key]
                status = ('kept' if kept and after_answer != answer else 'unchanged'
                          if explicit and after_answer == current.choices.get(key) else 'replaced' if explicit else 'added')
                result['changes'].append(dict(choice_id=key, title=self.presentation[key]['title'], status=status,
                    before_label=before.report['resolved_choices'][key]['label'] or 'Other inherited outcome',
                    incoming_label=definitions[key]['answers'][answer]['label'],
                    after_label=definitions[key]['answers'][after_answer]['label'], before_explicit=explicit))
        return PendingImport(item.source, item.original, profile, item.target, item.policy), result

    def _cache(self, item, result, deadline=None):
        self._expire()
        while len(self.pending) >= 4:
            del self.pending[next(iter(self.pending))]
        import_id = secrets.token_urlsafe(24)
        self.pending[import_id] = (time.monotonic() + 600 if deadline is None else deadline, item)
        return dict(result, import_id=import_id)

    def preview(self, raw, *, game='da2'):
        if game not in ('dao', 'da2'):
            raise ProfileError('Unsupported save game.')
        result = (import_dao if game == 'dao' else import_da2)(raw, self.catalog)
        result['game'] = game
        original = self.catalog.create(result['suggested_name'], base_preset=self.catalog.default_preset,
                                       mode='keep', choices=result['choices'])
        item, result = self._review(PendingImport(deepcopy(result), original, original))
        with self.lock:
            # Cache only immutable semantic profiles and bounded review data.
            return self._cache(item, result)

    def plan(self, data):
        expected = {'import_id', 'target_profile_id', 'target_revision', 'policy'}
        if (not isinstance(data, dict) or set(data) != expected or not isinstance(data['import_id'], str)
                or data['policy'] not in ('missing', 'replace')):
            raise ProfileError('Invalid save import plan.')
        with self.lock:
            self._expire()
            cached = self.pending.get(data['import_id'])
            if cached is None:
                raise ProfileError('This import preview expired or was already used. Choose the save again.')
            deadline, previous = cached
            game = previous.source['game']
            allowed = ('dao.',) if game == 'dao' else ('dao.', 'da2.') if game == 'da2' else ()
            if not allowed or any(not key.startswith(allowed) for key in previous.source['choices']):
                raise ProfileError('The imported choices do not belong to the source game history.')
            target = None
            if data['target_profile_id'] is not None:
                target = self.store.load(data['target_profile_id'])
                if type(data['target_revision']) is not int or target.revision != data['target_revision']:
                    raise RevisionConflict('The destination World State changed. Reopen it before importing.')
                current = self.catalog.upgrade(target)
                choices = dict(current.choices)
                for key, answer in previous.source['choices'].items():
                    if data['policy'] == 'replace' or key not in choices:
                        choices[key] = answer
                profile = current.edited(choices=choices)
            else:
                if type(data['target_revision']) is not int or data['target_revision'] != 0:
                    raise ProfileError('A new import destination must have revision zero.')
                profile = previous.original
            item, result = self._review(PendingImport(previous.source, previous.original, profile, target, data['policy']))
            # A reviewed plan gets a new single-use ID; an older plan can never
            # be submitted after the user changes destination or merge policy.
            del self.pending[data['import_id']]
            return self._cache(item, result, deadline)

    def commit(self, data):
        if not isinstance(data, dict) or set(data) != {'import_id', 'name'}:
            raise ProfileError('Invalid save import confirmation.')
        if not isinstance(data['import_id'], str):
            raise ProfileError('Invalid save import preview.')
        with self.lock:
            self._expire()
            cached = self.pending.get(data['import_id'])
            if cached is None:
                raise ProfileError('This import preview expired or was already used. Choose the save again.')
            item = cached[1]
            if item.target is not None and data['name'] != item.target.name:
                raise ProfileError('Importing into an existing World State cannot rename it.')
            profile = item.profile.edited(name=data['name'])
            compile_profile(profile, catalog=self.catalog)
            if item.target is None:
                saved = self.store.create(profile.name, base_preset=profile.base_preset,
                                          mode=profile.mode, choices=dict(profile.choices))
            else:
                saved = self.store.save(profile)
            del self.pending[data['import_id']]
            return saved

    def cancel(self, data):
        if not isinstance(data, dict) or set(data) != {'import_id'} or not isinstance(data['import_id'], str):
            raise ProfileError('Invalid save import cancellation.')
        with self.lock:
            self.pending.pop(data['import_id'], None)
        return {'cancelled': True}
