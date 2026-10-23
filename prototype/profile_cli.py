"""Development interface for the profile system, without a GUI or Keep connection."""
import argparse
import json
from pathlib import Path

from world_profiles import Catalog, ProfileError, ProfileStore
from world_profiles.compiler import compile_profile, export_profile_mod


def _selections(items):
    result = {}
    for item in items:
        if '=' not in item:
            raise ProfileError('Selections must use choice.id=answer_id')
        key, value = item.split('=', 1)
        if key in result:
            raise ProfileError('A choice was specified more than once: ' + key)
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=Path(__file__).parent / 'profile-data',
                        help='Local profile directory (default: prototype/profile-data)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('catalog', help='Show supported presets and semantic choices')
    commands.add_parser('list', help='List saved profiles')
    create = commands.add_parser('create')
    create.add_argument('--name', required=True)
    create.add_argument('--preset', help='Starting preset; defaults to original game values with DAO and DA2 played')
    create.add_argument('--mode', choices=['ordinary', 'experimental'])
    create.add_argument('--choice', action='append', default=[])
    for name in ('show', 'history', 'edit', 'duplicate', 'export-json', 'export-fbmod', 'check'):
        command = commands.add_parser(name)
        command.add_argument('profile_id')
        if name in ('show', 'export-json', 'export-fbmod', 'check'):
            command.add_argument('--revision', type=int)
        if name in ('edit', 'duplicate'):
            command.add_argument('--name', required=name == 'duplicate')
        if name == 'edit':
            command.add_argument('--expected-revision', type=int, required=True,
                                 help='Revision you inspected; prevents stale CLI edits')
            command.add_argument('--mode', choices=['ordinary', 'experimental'])
            command.add_argument('--choice', action='append', default=[])
            command.add_argument('--inherit', action='append', default=[], help='Remove an override and inherit the preset value')
        if name in ('export-json', 'export-fbmod'):
            command.add_argument('--output', type=Path, required=True)
    importing = commands.add_parser('import-json')
    importing.add_argument('input', type=Path)
    importing.add_argument('--name')
    args = parser.parse_args(argv)
    try:
        catalog = Catalog()
        store = ProfileStore(args.store, catalog=catalog)
        if args.command == 'catalog':
            result = dict(mapping_version=catalog.version, mapping_sha256=catalog.sha256,
                          presets=catalog.presets, choices=catalog.choices)
        elif args.command == 'list':
            result = [profile.to_dict() for profile in store.list()]
        elif args.command == 'create':
            result = store.create(args.name, base_preset=args.preset, mode=args.mode,
                                  choices=_selections(args.choice)).to_dict()
        elif args.command == 'import-json':
            result = store.import_profile(args.input, name=args.name).to_dict()
        elif args.command == 'history':
            result = [profile.to_dict() for profile in store.history(args.profile_id)]
        elif args.command == 'duplicate':
            result = store.duplicate(args.profile_id, args.name).to_dict()
        else:
            profile = store.load(args.profile_id, revision=getattr(args, 'revision', None))
            if args.command == 'show':
                result = profile.to_dict()
            elif args.command == 'edit':
                if profile.revision != args.expected_revision:
                    raise ProfileError('Expected revision differs from the saved head; inspect/reload before editing')
                selections = _selections(args.choice)
                if set(args.inherit) & selections.keys():
                    raise ProfileError('A choice cannot be both selected and inherited')
                choices = dict(profile.choices)
                for key in args.inherit:
                    if key not in catalog.choices:
                        raise ProfileError('Unknown inherited choice: ' + key)
                    choices.pop(key, None)
                choices.update(selections)
                result = store.save(profile.edited(name=args.name, mode=args.mode, choices=choices)).to_dict()
            elif args.command == 'export-json':
                result = store.export_json(profile.profile_id, args.output, revision=profile.revision).to_dict()
            elif args.command == 'export-fbmod':
                result = export_profile_mod(profile, args.output, catalog=catalog)
            elif args.command == 'check':
                compiled = compile_profile(profile, catalog=catalog)
                result = dict(report=compiled.report, values=dict(compiled.values),
                              max_value_overrides=dict(compiled.max_overrides))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, AssertionError) as error:
        parser.exit(1, f'Profile operation failed: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
