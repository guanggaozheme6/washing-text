# -*- coding: utf-8 -*-
"""S2 状位移位 —— 收益 ★★★.

两个方向:
  A. 句首状语 → 主语后   "在一定的关系下，X才成为Y" → "X在一定的关系下才成为Y"
  B. 主语后状语 → 句首   "X在一定的关系下才成为Y" → "在一定的关系下，X才成为Y"
状语 span 通过 dep (advmod/tmod/prep 子树) 定位, 只处理介词/副词型状语,
不动因果/条件从句 (那些交给 connector 算子).
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx

# 句首状语允许的前导词 (介词结构)
_PREP_LEAD = ('在', '从', '对', '为', '随着', '通过', '根据', '按照', '经过',
              '沿着', '当着', '针对', '围绕', '以', '向', '于')
# 允许的前置副词 (可一起搬走)
_ADV_LEAD = ('只有', '就', '才', '都', '也', '又', '再', '则', '仍', '还')
# 条件是/因果从句开头 —— 不搬 (避免破坏主干)
_SUBORD = ('因为', '由于', '如果', '倘若', '若', '虽然', '尽管', '即使',
           '无论', '不管', '只要', '既然', '为了', '以免', '以便', '只有')
_ADPOS = ('AD',)


class ShiftOperator(Operator):
    name = 'shift'
    desc = '状位移位: 句首状语与主语后状语互换位置'

    def __init__(self, max_span: int = 12):
        self.max_span = max_span

    def match(self, ctx: SentenceCtx) -> bool:
        return self._find_a(ctx) is not None or self._find_b(ctx) is not None

    # ---------- 方向 A: 句首状语 → 主语后 ----------
    def _find_a(self, ctx: SentenceCtx):
        toks = ctx.tokens
        # 找第一个逗号, 其前为状语块
        try:
            c = toks.index('，')
        except ValueError:
            return None
        if c < 2 or c > self.max_span:
            return None
        if ctx.quote_in(0, c + 1):
            return None
        chunk = toks[:c]
        if chunk[0] in _SUBORD:
            return None
        body = chunk[1:] if chunk[0] in _ADV_LEAD else chunk
        if not body or body[0] not in _PREP_LEAD:
            return None
        # 状语块内不得有谓语动词
        if any(t in ('VV', 'VC', 'VE', 'VR') for t in ctx.pos[:c]):
            return None
        # 逗号后应是主语 + 谓语
        rest = toks[c + 1:]
        if not rest or ctx.quote_in(c + 1, min(c + 4, ctx.n)):
            return None
        p = ctx.parsed
        subj_end = None
        for i in range(c + 1, min(c + 5, ctx.n)):
            if p.rel_of(i) in ('nsubj', 'nsubjpass'):
                subj_end = max(p.span_of(i)[1], i + 1)
                break
        if subj_end is None:
            return None
        if not any(pp in ('VV', 'VA', 'VE', 'VR') for pp in ctx.pos[subj_end:]):
            return None
        return {'chunk': (0, c), 'subj': (c + 1, subj_end)}

    # ---------- 方向 B: 主语后状语 → 句首 ----------
    def _find_b(self, ctx: SentenceCtx):
        toks = ctx.tokens
        p = ctx.parsed
        if ctx.n < 6:
            return None
        # 主语必须是句首连续段
        subj_tokens = [i for i in range(min(4, ctx.n))
                       if p.rel_of(i) in ('nsubj', 'nsubjpass')]
        if not subj_tokens:
            return None
        ss = min(subj_tokens)
        se = max(p.span_of(subj_tokens[0])[1], max(subj_tokens) + 1)
        if ss != 0 or ctx.quote_in(0, se):
            return None
        # 主语后找介词状语
        as_, ae = None, None
        for j in range(se, min(se + 4, ctx.n)):
            if ctx.pos[j] == 'P' and toks[j] in _PREP_LEAD:
                if not p.is_contiguous(j):
                    return None
                as_, ae = p.span_of(j)
                break
        if as_ is None:
            return None
        # 左侧吸收副词 (只有/才...)
        while as_ - 1 >= se and ctx.pos[as_ - 1] in _ADPOS and toks[as_ - 1] in _ADV_LEAD:
            as_ -= 1
        if ae - as_ > self.max_span or ae <= as_:
            return None
        if ctx.quote_in(as_, ae):
            return None
        # 滑动窗口吸收 advmod 进 span 尾 (只有 ... 在 ... 下)
        while ae < ctx.n and ctx.pos[ae] in _ADPOS and toks[ae] in _ADV_LEAD and ae - as_ < self.max_span:
            ae += 1
        if ae >= ctx.n or not any(pp in ('VV', 'VA', 'VE', 'VR') for pp in ctx.pos[ae:]):
            return None
        return {'subj': (ss, se), 'adv': (as_, ae)}

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        plan_a = self._find_a(ctx)
        plan_b = self._find_b(ctx)
        options = []
        if plan_a:
            options.append('a')
        if plan_b:
            options.append('b')
        if not options:
            return None
        toks = ctx.tokens
        if rng.choice(options) == 'a':
            (cs, ce), (ss, se) = plan_a['chunk'], plan_a['subj']
            new = toks[ss:se] + toks[cs:ce] + toks[se:]
        else:
            ss, se = plan_b['subj']
            ass, aee = plan_b['adv']
            if se != ass:
                return None
            # 状语后若紧跟逗号, 跳过 (由移位重建的逗号替代)
            tail_start = aee + 1 if aee < ctx.n and toks[aee] in ('，', '；') else aee
            new = toks[ass:aee] + ['，'] + toks[ss:se] + toks[tail_start:]
        s = ''.join(new)
        if not s.endswith(('。', '！', '？')):
            s += '。'
        return s
