# -*- coding: utf-8 -*-
"""S8 同义替换 —— 收益 ★☆☆ (但全覆盖), 默认关闭.

资源层在 rewriter/synonyms.py (synonyms 库 / data/synonyms.json / 内置词表).
逐 token 替换, 锁定词/术语/数字一律跳过; 每句最多替换 max_repl 处,
避免堆砌同义词的"AI 味".
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx
from ..synonyms import load_synonym_table, nearby

_SKIP_POS = {'CD', 'OD', 'NT', 'PU', 'NR', 'NN'}


class SynonymOperator(Operator):
    name = 'synonym'
    desc = '同义替换: 词级替换, 仅作兜底点缀'

    def __init__(self, table: dict[str, list[str]] | None = None,
                 whitelist: list[str] | None = None,
                 max_repl: int = 2):
        self.table = table or load_synonym_table()
        self.whitelist = set(whitelist or [])
        self.max_repl = max_repl

    def match(self, ctx: SentenceCtx) -> bool:
        return bool(self._candidates(ctx))

    def _candidates(self, ctx: SentenceCtx) -> list[int]:
        out = []
        for i, t in enumerate(ctx.tokens):
            if t in self.table and not ctx.is_locked(i):
                if ctx.pos and ctx.pos[i] in _SKIP_POS and t not in ('发展', '提高'):
                    continue
                if t in self.whitelist:
                    continue
                out.append(i)
        return out

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        cands = self._candidates(ctx)
        if not cands:
            return None
        rng.shuffle(cands)
        toks = list(ctx.tokens)
        n = 0
        for i in cands:
            if n >= self.max_repl:
                break
            opts = [w for w in nearby(toks[i], self.table) if w != toks[i]]
            if not opts:
                continue
            toks[i] = rng.choice(opts)
            n += 1
        if n == 0:
            return None
        s = ''.join(toks)
        if not s.endswith(('。', '！', '？')):
            s += '。'
        return s
