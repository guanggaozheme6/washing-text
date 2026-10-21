# -*- coding: utf-8 -*-
"""算子冒烟测试: 直接对样例句跑每个算子的 match/apply.

用法: .venv/Scripts/python.exe test_ops.py
"""
import random

from rewriter.config import load_config
from rewriter.parser import Parser
from rewriter.protect import load_whitelist, mark_protection
from rewriter.operators import (SentenceCtx, SplitOperator, ShiftOperator,
                                AttribOperator, ConnectorOperator, VoiceOperator)
from rewriter.scorer import hard_check, fluency_of, novelty_of

SENTS = [
    '自然语言处理是计算机科学领域与人工智能领域中的一个重要方向。',
    '它研究能实现人与计算机之间用自然语言进行有效通信的各种理论和方法。',
    '依存句法分析可以确定句子中词语之间的修饰关系，从而揭示句子的结构。',
    '句法分析被广泛应用于信息抽取、问答系统与机器翻译等任务中。',
    '生产资料被一部分人垄断，只有在一定的关系下，它才成为资本。',
    '因为机器大工业的发展，工人被集中在工厂里劳动，所以新的阶级形成了。',
    '工人创造的剩余价值被资本家占有。',
    '新的阶级形成了。',
    '实现分配是目标。',
]

OPS = [SplitOperator(), ShiftOperator(), AttribOperator(), ConnectorOperator(), VoiceOperator()]

def main():
    cfg = load_config()
    parser = Parser(tasks=cfg['parser']['tasks'])
    wl = load_whitelist('data/whitelist.txt')
    rng = random.Random(42)

    parsed = parser.parse_batch(SENTS)
    total_hits = 0
    for text, p in zip(SENTS, parsed):
        prot = mark_protection(p, wl)
        ctx = SentenceCtx(text=text, parsed=p, prot=prot)
        hits = []
        for op in OPS:
            if not op.match(ctx):
                continue
            # 每个算子最多试 3 次
            for _ in range(3):
                r = op.apply(ctx, rng)
                if r is None:
                    continue
                rs = r if isinstance(r, list) else [r]
                joined = ''.join(rs)
                ok, why = hard_check(text, joined, p, None, prot)
                hits.append(f'  [{op.name}] {" | ".join(rs)}   hard={ok}({why})')
                break
        n_locked = len(prot.locked_tokens)
        print(f'◆ {text}')
        print(f'  (locked={n_locked}, frozen={prot.frozen})')
        if hits:
            print('\n'.join(hits))
            total_hits += len(hits)
        else:
            print('  (无算子可用)')
    print(f'\n合计命中: {total_hits}')

if __name__ == '__main__':
    main()
