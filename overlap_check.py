# -*- coding: utf-8 -*-
"""定向重合度自测（M1 的 overlap.py 雏形）

逐句检查文稿与 --corpus 语料的最长连续公共子串长度。
连续片段查重的判定基础就是这个长度：命中越长，计入重复的字数越多。

用法:
  .venv/Scripts/python.exe overlap_check.py 文稿.txt --corpus data/corpus --max-run 10
"""
import argparse
import os
import re

try:
    from hanlp.utils.rules import split_sentence
except Exception:
    def split_sentence(text):
        return [s for s in re.split(r'(?<=[。！？；!?;])', text) if s.strip()]


def normalize(s):
    return re.sub(r'[\s]+', '', s)


def longest_common_run(a, b):
    """返回 (最长连续公共子串长度, 该子串)"""
    if not a or not b:
        return 0, ''
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    best, end = 0, 0
    for i, ch in enumerate(a, 1):
        cur = [0] * (len(b) + 1)
        for j, cj in enumerate(b, 1):
            if ch == cj:
                v = prev[j - 1] + 1
                cur[j] = v
                if v > best:
                    best, end = v, i
        prev = cur
    return best, a[end - best:end]


def load_corpus(paths):
    docs = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(('.txt', '.md')):
                    fp = os.path.join(p, name)
                    with open(fp, encoding='utf-8') as f:
                        docs.append((fp, normalize(f.read())))
        else:
            with open(p, encoding='utf-8') as f:
                docs.append((p, normalize(f.read())))
    return docs


def main():
    ap = argparse.ArgumentParser(description='定向重合度自测')
    ap.add_argument('input', help='待检文稿')
    ap.add_argument('--corpus', nargs='+', required=True, help='比对语料：文件或目录')
    ap.add_argument('--max-run', type=int, default=10, help='超过该长度视为未达标')
    ap.add_argument('--top', type=int, default=15, help='列出前 N 个最危险的句子')
    ap.add_argument('--min-match', type=int, default=8,
                    help='计入重复字数估算的最小片段长度')
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    if not corpus:
        print('比对语料为空，退出')
        return
    print(f'比对语料: {len(corpus)} 份')
    for name, t in corpus:
        print(f'  - {os.path.basename(name)}  ({len(t)} 字)')

    with open(args.input, encoding='utf-8') as f:
        text = f.read()

    sents = [s.strip() for s in split_sentence(text) if len(normalize(s)) >= 4]
    total = sum(len(normalize(s)) for s in sents)
    print(f'\n待检文稿: {args.input}')
    print(f'共 {len(sents)} 句 / {total} 字\n')

    rows = []
    for i, s in enumerate(sents, 1):
        ns = normalize(s)
        best, frag, src = 0, '', ''
        for name, ctext in corpus:
            r, f = longest_common_run(ns, ctext)
            if r > best:
                best, frag, src = r, f, name
        rows.append({'run': best, 'idx': i, 'sent': s, 'frag': frag,
                     'src': os.path.basename(src) if src else '-',
                     'len': len(ns)})

    over = [r for r in rows if r['run'] > args.max_run]
    risky = sum(r['len'] for r in rows if r['run'] > 5)

    rows.sort(key=lambda r: -r['run'])
    print(f'{"重合":>4}  {"句":>3}  {"来源":<14} 命中片段')
    print('-' * 72)
    for r in rows[:args.top]:
        flag = '  <<< 超阈' if r['run'] > args.max_run else ''
        print(f'{r["run"]:>4}  {r["idx"]:>3}  {r["src"]:<14} {r["frag"][:34]}{flag}')

    print('\n--- 全文统计 ---')
    print(f'最长连续重合      : {rows[0]["run"]} 字')
    print(f'超过 {args.max_run} 字的句子  : {len(over)} / {len(rows)}')
    matched = sum(r['run'] for r in rows if r['run'] >= args.min_match)
    print(f'重合字数估算      : {matched} / {total}  ({matched / total * 100:.1f}%)'
          f'  ← 只计 ≥{args.min_match} 字的长片段, 对标平台的 30% 红线')
    print(f'高风险句字数(上限): {risky} / {total}  ({risky / total * 100:.1f}%)'
          f'  ← 最粗的上限: 只要有一处长片段, 整句都计入')


if __name__ == '__main__':
    main()
