import json
from typing import Any


def sanitize_unicode(value: Any) -> Any:
    """Replace invalid Unicode surrogates before crossing process/file boundaries."""
    if isinstance(value, str):
        return value.encode('utf-8', errors='replace').decode('utf-8')
    if isinstance(value, dict):
        return {
            sanitize_unicode(key): sanitize_unicode(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_unicode(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_unicode(item) for item in value)
    return value


def encode_json_line(message: dict[str, Any]) -> bytes:
    """Serialize one safe UTF-8 JSON-lines protocol message."""
    safe_message = sanitize_unicode(message)
    return (json.dumps(safe_message, ensure_ascii=False) + '\n').encode('utf-8')
