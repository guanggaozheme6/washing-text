# -*- coding: utf-8 -*-
"""算子基类与句上下文.

算子契约:
  match(ctx) -> bool            该句是否可用此算子
  apply(ctx, rng) -> str | list[str] | None
      返回改写后的整句文本 (含句末标点);
      返回 list 表示拆成多句;
      返回 None 表示本次应用失败 (候选池丢弃)
"""
import random
from dataclasses import dataclass, field
from typing import Optional, Union

from ..parser import Parsed
from ..protect import Protection

Result = Optional[Union[str, list[str]]]


@dataclass
class SentenceCtx:
    text: str
    parsed: Parsed
    prot: Protection
    idx: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def tokens(self) -> list[str]:
        return self.parsed.tokens

    @property
    def pos(self) -> list[str]:
        return self.parsed.pos

    @property
    def n(self) -> int:
        return self.parsed.n

    def join(self) -> str:
        return self.parsed.join()

    def is_locked(self, i: int) -> bool:
        return i in self.prot.locked_tokens

    def locked_range(self, s: int, e: int) -> bool:
        return any(i in self.prot.locked_tokens for i in range(max(0, s), min(self.n, e)))

    def quote_in(self, s: int, e: int) -> bool:
        """[s, e) 与引号区是否有交叠 (引号区一律不动)."""
        return any(qs < e and qe > s for qs, qe in self.prot.quote_spans)

    def rebuild(self, tokens: list[str]) -> str:
        return ''.join(tokens)


class Operator:
    name = 'base'
    desc = ''

    def match(self, ctx: SentenceCtx) -> bool:
        return False

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Result:
        return None


def ensure_period(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    if s[-1] not in '。！？':
        s += '。'
    return s


def strip_tail_punct(tokens: list[str]) -> tuple[list[str], str]:
    """剥掉句末标点, 返回 (tokens, 尾标点)."""
    tail = ''
    while tokens and tokens[-1] in ('。', '！', '？', '…'):
        tail = tokens.pop() + tail
    return tokens, tail or '。'


def replace_span(tokens: list[str], s: int, e: int, new: list[str]) -> list[str]:
    return tokens[:s] + new + tokens[e:]
