"""Window-title classifiers used by desktop automation features."""

import re

from core.text import repair_utf8_gbk_mojibake


def is_qqsg_game_window_title(title: str) -> bool:
    """Return whether a title belongs to the QQSG game client.

    Real clients currently begin with ``QQ三国`` followed by a numeric
    version. Requiring the version excludes browser pages and helper tools
    whose titles merely contain the game name.
    """
    normalized = repair_utf8_gbk_mojibake(str(title or '')).strip()
    return bool(re.match(r'^QQ三国\s*\d', normalized, flags=re.IGNORECASE))
