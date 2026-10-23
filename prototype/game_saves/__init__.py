"""Read-only source-game save import adapters."""
from fbmod_metadata import suggested_title


def suggested_import_name(character, game):
    suffix = ' - imported ' + game
    return suggested_title(character)[:120 - len(suffix)].rstrip() + suffix
