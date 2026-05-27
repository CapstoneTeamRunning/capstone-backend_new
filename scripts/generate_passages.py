import json
import re
from pathlib import Path


def clean_text(text: str) -> str:
    if text is None:
        return ""
    # normalize newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # remove explicit labels
    text = re.sub(r"\[본문\]|\[제시문\]", "", text)
    # collapse multiple blank lines to one
    text = re.sub(r"\n{2,}", "\n\n", text)
    # strip leading/trailing whitespace
    text = text.strip()
    return text


def merge_labeled_fragments(text: str):
    # Replace lines that consist of (A) (B) ... with markers
    markered = re.sub(r'(?m)^\(([A-Z])\)\s*$', r'<<<\1>>>', text)
    if '<<<' not in markered:
        return None
    parts = []
    for chunk in markered.split('<<<'):
        if not chunk:
            continue
        if '>>>' in chunk:
            label, body = chunk.split('>>>', 1)
            parts.append((label.strip(), body.strip()))
        else:
            # leading text before first marker
            if chunk.strip():
                parts.append(('Z', chunk.strip()))
    if not parts:
        return None
    # sort by label except 'Z' which should stay first if present
    z_parts = [p for p in parts if p[0] == 'Z']
    ab_parts = sorted([p for p in parts if p[0] != 'Z'], key=lambda x: x[0])
    ordered = z_parts + ab_parts
    merged = '\n\n'.join(p[1] for p in ordered)
    return merged


def needs_manual(text: str) -> bool:
    if not text or text.strip() == "":
        return True
    low = text.lower()
    if '____' in text or '빈칸' in low or '___' in text:
        return True
    return False


def main():
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / 'test.json'
    out = repo_root / 'test_passages.json'
    manual_csv = repo_root / 'passages_needs_manual.csv'

    data = json.loads(src.read_text(encoding='utf-8'))
    result = []
    manual_rows = []

    for item in data:
        code = item.get('code')
        content = item.get('content', {}) or {}
        passage = content.get('passage') or ''
        cleaned = clean_text(passage)

        tag = 'rule'
        merged = None
        # try to merge labeled fragments when present
        merged = merge_labeled_fragments(cleaned)
        if merged:
            cleaned = merged
            tag = 'rule_merged_fragments'

        if needs_manual(cleaned):
            tag = 'manual'
            manual_rows.append({'code': code, 'reason': 'empty_or_placeholder'})

        new_item = {
            'code': code,
            'number': None,
            'category': {'code': 'PASSAGE', 'name': None},
            'content': {'instruction': None, 'passage': cleaned, 'choices': None},
            'answer': None
        }
        result.append(new_item)

    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    if manual_rows:
        import csv
        with manual_csv.open('w', encoding='utf-8', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['code', 'reason'])
            writer.writeheader()
            for r in manual_rows:
                writer.writerow(r)

    # print brief report
    total = len(data)
    manual_count = len(manual_rows)
    # recompute merged count by scanning original data for merged fragments
    merged_count = 0
    for item in data:
        content = item.get('content', {}) or {}
        passage = content.get('passage') or ''
        cleaned = clean_text(passage)
        if merge_labeled_fragments(cleaned):
            merged_count += 1
    rule_count = total - manual_count - merged_count
    print(f'Total: {total}, rule-cleaned: {rule_count}, merged-fragments: {merged_count}, manual: {manual_count}')
    print(f'Wrote: {out}\nManual CSV: {manual_csv} (if any)')


if __name__ == '__main__':
    main()
