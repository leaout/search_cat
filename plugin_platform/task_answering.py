"""Pure helpers for scripted QQSG question answering."""

import re
from difflib import SequenceMatcher


OPTION_RE = re.compile(r'^\s*([A-DＡ-Ｄ])\s*[、.．:：]?\s*(.+?)\s*$')
FEEDBACK_RE = re.compile(r'(?:正确答案|答案是|正确选项)\s*[：:、]?\s*([A-DＡ-Ｄ])', re.IGNORECASE)


def normalize_text(value: str) -> str:
    """Normalize OCR text for matching while retaining Chinese characters."""
    text = str(value or '').strip().upper()
    return re.sub(r'[\s，。！？、：:；;,.!?()（）【】\[\]「」“”\"\']+', '', text)


def parse_options(lines: list[str]) -> list[dict]:
    """Extract A-D options from OCR lines, accepting Chinese punctuation."""
    options = []
    full_width = dict(zip('ＡＢＣＤ', 'ABCD'))
    for line in lines or []:
        match = OPTION_RE.match(str(line or ''))
        if not match:
            continue
        letter = full_width.get(match.group(1), match.group(1)).upper()
        options.append({'letter': letter, 'text': match.group(2).strip()})
    return options


def match_question(question: str, records: list[dict], threshold: float = 0.72) -> dict | None:
    """Return the best local answer record, if similarity reaches threshold."""
    query = normalize_text(question)
    if not query:
        return None
    best = None
    for record in records or []:
        candidate = normalize_text(record.get('q', record.get('question', '')))
        if not candidate:
            continue
        score = SequenceMatcher(None, query, candidate).ratio()
        if best is None or score > best['_score']:
            best = {**record, '_score': score}
    return best if best and best['_score'] >= threshold else None


def anti_fraud_answer(question: str, options: list[dict]) -> tuple[str | None, float]:
    """Infer the safe option for common account/security questions."""
    text = normalize_text(question)
    markers = ('骗子', '诈骗', '骗', '盗号', '账号安全', '陌生链接', '验证码')
    if not any(marker in text for marker in markers):
        return None, 0.0
    safe = ('不要', '拒绝', '官方', '核实', '举报', '保护', '不透露', '不点击', '不转账')
    unsafe = ('提供密码', '告诉密码', '点击链接', '转账', '验证码', '私下交易', '借给')
    scored = []
    for option in options or []:
        value = normalize_text(option.get('text', ''))
        score = sum(2 for marker in safe if marker in value)
        score -= sum(2 for marker in unsafe if marker in value)
        scored.append((score, option.get('letter')))
    if not scored:
        return None, 0.0
    scored.sort(reverse=True)
    if scored[0][0] <= 0:
        return None, 0.0
    return scored[0][1], min(0.98, 0.72 + scored[0][0] * 0.05)


def parse_feedback_answer(text: str) -> str | None:
    """Extract the letter revealed by the game's wrong-answer feedback."""
    match = FEEDBACK_RE.search(str(text or ''))
    if not match:
        return None
    return dict(zip('ＡＢＣＤ', 'ABCD')).get(match.group(1).upper(), match.group(1).upper())
