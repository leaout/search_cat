"""Text normalization helpers for Windows integrations."""


def repair_utf8_gbk_mojibake(value: str) -> str:
    """Repair UTF-8 bytes that were decoded as Windows GBK.

    Some legacy Windows games expose titles through an ANSI path. Invalid GBK
    bytes are represented as low surrogates, so ``surrogateescape`` is needed
    to reconstruct the original UTF-8 byte sequence without data loss.
    """
    text = str(value or '')
    if not text:
        return text
    try:
        repaired = text.encode('gbk', errors='surrogateescape').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired
