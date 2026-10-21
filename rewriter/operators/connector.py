# -*- coding: utf-8 -*-
"""S5 逻辑连接词重写 —— 收益 ★★☆.

两种手法:
  1. 词面替换: 因此→由此可见 / 但是→然而 / 所以→因而 ...
  2. 句型重排:
     "因为X，所以Y" → "X，因此Y"  /  "之所以Y，是因为X"
     "虽然X，但是Y" → "尽管X，仍Y"
不跨句, 全部在单句内完成.
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx

# 词面替换表 (等价连接词)
_SWAP = {
    '因此': ['由此可见', '因而', '故', '这样一来'],
    '所以': ['因此', '因而', '于是'],
    '但是': ['然而', '不过', '可是'],
    '虽然': ['尽管', '固然'],
    '因为': ['由于', '鉴于'],
    '如果': ['倘若', '假如', '若'],
    '而且': ['并且', '况且'],
    '此外': ['另外', '除此之外'],
    '首先': ['其一', '第一'],
    '其次': ['其二', '第二'],
    '最后': ['最终', '末了'],
    '总之': ['总而言之', '概言之'],
    '例如': ['比如', '诸如'],
    '由于': ['鉴于', '因为'],
    '然而': ['但是', '不过'],
    '从而': ['进而', '由此', '继而'],
    '进而': ['从而', '由此'],
    '同时': ['与此同时', '并且'],
    '可见': ['由此可见', '足见'],
}


class ConnectorOperator(Operator):
    name = 'connector'
    desc = '逻辑连接词重写: 等价替换 + 因果/让步句型重排'

    def match(self, ctx: SentenceCtx) -> bool:
        return self._find_swap(ctx) is not None or self._causal_plan(ctx) is not None \
            or self._concessive_plan(ctx) is not None

    def _find_swap(self, ctx: SentenceCtx):
        toks = ctx.tokens
        for i, t in enumerate(toks):
            if t in _SWAP and not ctx.is_locked(i):
                return i
        return None

    def _causal_plan(self, ctx: SentenceCtx):
        """"因为X，所以Y" / "因为X，Y" 重排."""
        toks = ctx.tokens
        if not toks or toks[0] != '因为' or ctx.is_locked(0):
            return None
        try:
            c = toks.index('，')
        except ValueError:
            return None
        if not (2 < c < len(toks) - 2):
            return None
        has_so = '所以' in toks[c + 1:]
        return {'comma': c, 'has_so': has_so}

    def _concessive_plan(self, ctx: SentenceCtx):
        toks = ctx.tokens
        if not toks or toks[0] != '虽然' or ctx.is_locked(0):
            return None
        try:
            c = toks.index('，')
        except ValueError:
            return None
        if not (2 < c < len(toks) - 2):
            return None
        return {'comma': c}

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        actions = []
        if self._causal_plan(ctx):
            actions.append('causal')
        if self._concessive_plan(ctx):
            actions.append('concessive')
        if self._find_swap(ctx) is not None:
            actions.append('swap')
        if not actions:
            return None
        act = rng.choice(actions) if len(actions) > 1 else actions[0]
        toks = list(ctx.tokens)

        if act == 'causal':
            plan = self._causal_plan(ctx)
            c = plan['comma']
            mid = toks[1:c]                  # X
            tail = toks[c + 1:]
            if plan['has_so']:
                si = tail.index('所以')
                tail2 = tail[:si] + tail[si + 1:]
                variant = rng.choice(['因此', '于是', '由此可见'])
                new = mid + ['，'] + [variant] + tail2
            else:
                # 因为X，Y → 由于X，Y (安全) 或 X，因此Y
                if rng.random() < 0.5:
                    new = ['由于'] + toks[1:]
                else:
                    new = mid + ['，', '因此'] + tail
            return self._finish(new)

        if act == 'concessive':
            c = self._concessive_plan(ctx)['comma']
            mid = toks[1:c]
            tail = toks[c + 1:]
            if tail and tail[0] == '但是':
                tail = tail[1:]
                new = ['尽管'] + mid + ['，'] + tail
            elif tail and tail[0] == '但':
                tail = tail[1:]
                new = ['尽管'] + mid + ['，'] + tail
            else:
                new = ['尽管'] + mid + ['，'] + tail
            return self._finish(new)

        # swap: 词面替换
        i = self._find_swap(ctx)
        word = toks[i]
        repl = rng.choice([w for w in _SWAP[word] if w != word])
        # 替换后可能的赘余连接词检查由 scorer 负责
        toks[i] = repl
        return self._finish(toks)

    @staticmethod
    def _finish(tokens: list[str]) -> str:
        s = ''.join(tokens)
        if not s.endswith(('。', '！', '？')):
            s += '。'
        return s
