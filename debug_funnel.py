# -*- coding: utf-8 -*-
"""诊断: 单个句子的候选池漏斗."""
import sys
from rewriter.config import load_config
from rewriter.parser import Parser
from rewriter.protect import load_whitelist, mark_protection
from rewriter.operators import SentenceCtx, build_operators
from rewriter import overlap, scorer
from rewriter.verifier import fidelity as calc_fid

text = sys.argv[1] if len(sys.argv) > 1 else '依存句法分析可以确定句子中词语之间的修饰关系，从而揭示句子的结构。'

cfg = load_config()
cfg['overlap']['corpus_dir'] = 'data/corpus'
parser = Parser(tasks=cfg['parser']['tasks'])
wl = load_whitelist('data/whitelist.txt')
ops = build_operators(cfg, whitelist=wl)

corpus = overlap.load_corpus('data/corpus')
from rewriter.segmenter import split_text_to_sentences
corpus += [s for s in split_text_to_sentences(open('sample.txt', encoding='utf-8').read()) if s.strip()]

p = parser.parse_one(text)
prot = mark_protection(p, wl)
ctx = SentenceCtx(text=text, parsed=p, prot=prot)

cur_run, hit = overlap.max_run_against_corpus(text, corpus)
print(f'原句 max_run={cur_run} 命中={hit[:40]}')
print(f'可用算子: {[op.name for op in ops.values() if op.match(ctx)]}')

import random
rng = random.Random(42)
for op in ops.values():
    if not op.match(ctx):
        continue
    for t in range(5):
        r = op.apply(ctx, rng)
        if r is None:
            continue
        sents = r if isinstance(r, list) else [r]
        joined = ''.join(sents)
        ok, why = scorer.hard_check(text, joined, p, None, prot)
        nov = scorer.novelty_of(joined, corpus, text)
        flu = scorer.fluency_of(joined, text)
        run_after, h2 = overlap.max_run_against_corpus(joined, corpus)
        cp = parser.parse_one(joined)
        fid = calc_fid(p, cp)['fidelity']
        ok2, why2 = scorer.hard_check(text, joined, p, cp, prot)
        print(f'[{op.name}] run {cur_run}->{run_after} nov={nov:.2f} flu={flu:.2f} fid={fid:.2f} hard={ok}({why}) hard2={ok2}({why2})')
        print(f'   {joined}')
        break
