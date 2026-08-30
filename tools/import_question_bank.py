"""Import a public QQSG question-bank JavaScript file into Search Cat."""

import argparse
import json
import re
from pathlib import Path


ITEM_PATTERN = re.compile(
    r'^\s*\{q:(?P<q>"(?:\\.|[^"\\])*")'
    r',a:(?P<a>"(?:\\.|[^"\\])*")'
    r',idx:(?P<idx>"(?:\\.|[^"\\])*")\},?\s*$'
)


def normalize_question(text: str) -> str:
    """Normalize a question for duplicate detection."""
    return re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]+', '', text).lower()


def parse_source(source_path: Path) -> list[dict]:
    """Parse q/a/idx records from the JavaScript data file."""
    records = []
    for line_number, line in enumerate(source_path.read_text(encoding='utf-8').splitlines(), 1):
        match = ITEM_PATTERN.match(line)
        if not match:
            continue
        try:
            records.append({
                'q': json.loads(match.group('q')),
                'ans': json.loads(match.group('a')),
                'idx': json.loads(match.group('idx')),
                'source': 'https://sg1.zhy1024.com/questionBank.js',
            })
        except json.JSONDecodeError as error:
            raise ValueError(f'Invalid JavaScript string at line {line_number}: {error}') from error
    return records


def load_existing_questions(data_directory: Path, excluded_path: Path) -> dict[str, str]:
    """Load existing q/ans pairs from JSON-array and JSON-lines files."""
    existing = {}
    for path in data_directory.rglob('*'):
        if path == excluded_path or path.suffix.lower() not in {'.txt', '.json'}:
            continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError):
            continue
        items = []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            for line in text.splitlines():
                line = line.strip().rstrip(',')
                if not line or line in {'[', ']'}:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    items.append(item)
        for item in items:
            if not isinstance(item, dict) or not item.get('q'):
                continue
            answer = item.get('ans', item.get('a', ''))
            existing.setdefault(normalize_question(str(item['q'])), str(answer))
    return existing


def import_bank(source_path: Path, output_path: Path) -> dict[str, int]:
    """Export the complete website bank, with website answers winning conflicts."""
    source_records = parse_source(source_path)
    existing = load_existing_questions(output_path.parent, output_path)
    website_records = {}
    website_duplicate_count = 0

    for record in source_records:
        key = normalize_question(record['q'])
        if not key:
            continue
        if key in website_records:
            website_duplicate_count += 1
        # A later duplicate in the website data is treated as the newer record.
        website_records[key] = record

    overlap_count = sum(key in existing for key in website_records)
    override_count = sum(
        bool(existing.get(key)) and existing[key] != record['ans']
        for key, record in website_records.items()
        if key in existing
    )

    output_path.write_text(
        json.dumps(list(website_records.values()), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return {
        'source': len(source_records),
        'exported': len(website_records),
        'overlaps': overlap_count,
        'website_overrides': override_count,
        'website_duplicates': website_duplicate_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/qqsg_public_question_bank.txt'))
    args = parser.parse_args()
    print(json.dumps(import_bank(args.source, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
