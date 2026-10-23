"""Portable profile documents. This module has no game, UI, or filesystem dependency."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
import unicodedata
from uuid import UUID, uuid4

SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 1_048_576


class ProfileError(ValueError):
    pass


class UnsupportedVersion(ProfileError):
    pass


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


def fingerprint(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ProfileError('JSON document exceeds the 1 MiB limit')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError('Invalid UTF-8 JSON document') from error


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def check_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as error:
        raise ProfileError('Profile ID must be a canonical UUID') from error
    return value


def _timestamp(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ProfileError('Profile timestamps must be UTC ISO dates ending in Z')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as error:
        raise ProfileError('Invalid profile timestamp') from error


@dataclass(frozen=True)
class Profile:
    schema_version: int
    profile_id: str
    revision: int
    name: str
    created_at: str
    updated_at: str
    mapping_version: int
    mapping_sha256: str
    base_preset: str
    mode: str
    choices: Mapping[str, str]

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise UnsupportedVersion('Unsupported profile schema; no automatic migration is available')
        check_id(self.profile_id)
        if type(self.revision) is not int or not 1 <= self.revision <= 99_999_999:
            raise ProfileError('Revision must be an integer between 1 and 99999999')
        if (not isinstance(self.name, str) or self.name != self.name.strip() or not 1 <= len(self.name) <= 120
                or any(unicodedata.category(char).startswith('C') for char in self.name)):
            raise ProfileError('Profile name must be 1–120 characters without control characters or outer spaces')
        if _timestamp(self.updated_at) < _timestamp(self.created_at):
            raise ProfileError('Updated timestamp precedes creation')
        if type(self.mapping_version) is not int or self.mapping_version < 1:
            raise ProfileError('Invalid mapping version')
        if not isinstance(self.mapping_sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.mapping_sha256):
            raise ProfileError('Invalid mapping fingerprint')
        if not isinstance(self.base_preset, str) or not re.fullmatch('[a-z0-9._-]{1,100}', self.base_preset):
            raise ProfileError('Invalid base preset ID')
        if self.mode not in ('ordinary', 'experimental', 'keep'):
            raise ProfileError('Mode must be ordinary, experimental or keep')
        if (not isinstance(self.choices, Mapping) or len(self.choices) > 1000
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.choices.items())):
            raise ProfileError('Choices must map story identifiers to answer identifiers')
        object.__setattr__(self, 'choices', MappingProxyType(dict(self.choices)))

    def to_dict(self):
        return {key: dict(value) if key == 'choices' else value for key, value in self.__dict__.items()}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ProfileError('Profile document must be a JSON object')
        if type(value.get('schema_version')) is not int or value['schema_version'] != SCHEMA_VERSION:
            raise UnsupportedVersion('Unsupported or missing profile schema; no automatic migration is available')
        if set(value) != set(cls.__dataclass_fields__):
            raise ProfileError('Unexpected or missing profile fields')
        return cls(**value)

    @classmethod
    def load(cls, path):
        return cls.from_dict(read_json(path))

    @property
    def sha256(self):
        return fingerprint(self.to_dict())

    def edited(self, *, name=None, choices=None, mode=None):
        """Unsaved replacement of this revision. Store.save performs the revision increment."""
        return replace(self, name=self.name if name is None else name,
                       choices=self.choices if choices is None else choices,
                       mode=self.mode if mode is None else mode)


def new_profile(name, base_preset, mapping_version, mapping_sha256, *, choices=None, mode='ordinary'):
    timestamp = now()
    return Profile(SCHEMA_VERSION, str(uuid4()), 1, name, timestamp, timestamp,
                   mapping_version, mapping_sha256, base_preset, mode, {} if choices is None else choices)
