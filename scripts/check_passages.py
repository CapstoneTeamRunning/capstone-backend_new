import json
import re
from pathlib import Path


def scan():
    p = Path(__file__).resolve().parents[1] / 'test_passages.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    total = len(data)

    underscore_re = re.compile(r'_{3,}')
    parenthesis_label_re = re.compile(r'\([A-Z]\)')
    lowercase_label_re = re.compile(r'\([a-z]\)')
    numbered_label_re = re.compile(r'\([0-9]+\)')

    underscores = []
    labels = []
    manual_like = []

    for item in data:
        code = item.get('code')
        passage = (item.get('content') or {}).get('passage') or ''
        if underscore_re.search(passage):
            underscores.append(code)
        if parenthesis_label_re.search(passage) or lowercase_label_re.search(passage):
            labels.append(code)
        # heuristics for 'manual' clues
        if '____' in passage or '빈칸' in passage or passage.strip() == '':
            manual_like.append(code)

    print('Total passages:', total)
    print('Underscore placeholders:', len(underscores))
    print('Parenthesis labels (A/B...):', len(labels))
    print('Manual-like (empty/placeholder):', len(manual_like))
    print()
    print('Sample underscores (max 10):', underscores[:10])
    print('Sample labels (max 10):', labels[:10])
    print('Sample manual-like (max 10):', manual_like[:10])


if __name__ == '__main__':
    scan()
