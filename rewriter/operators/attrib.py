# -*- coding: utf-8 -*-
"""S4 定语展开 + S7 名词化切换.

S4: "[M]的[N] + 谓语P" → "[N] + P，[代词] + [M的复现]"
    例: "工人创造的剩余价值被资本家占有。" → "剩余价值被资本家占有，它由工人创造。"
S7: "V + Obj + 是/成为 X" → "Obj + 的 + V + 是 X"
    例: "实现分配是目标。" → "分配的实现是目标。"
两句都做保守匹配, 不满足条件即放弃.
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx

_COPULA = ('是', '成为', '构成', '属于', '标志', '体现', '意味着', '被称为')
_VERB_POS = ('VV', 'VA', 'VE', 'VC', 'VR')


class AttribOperator(Operator):
    name = 'attrib'
    desc = '定语展开 / 名词化: 前置长定语转为后置小句'

    def match(self, ctx: SentenceCtx) -> bool:
        return (self._attrib_plan(ctx) is not None
                or self._nominal_plan(ctx) is not None
                or self._postpose_plan(ctx) is not None)

    # ---------- S4: [M]的[N] 主语前置定语 ----------
    def _attrib_plan(self, ctx: SentenceCtx):
        p = ctx.parsed
        toks = ctx.tokens
        if ctx.n < 5 or toks[0] == '的':
            return None
        try:
            d = toks.index('的')
        except ValueError:
            return None
        if d == 0 or d + 1 >= ctx.n:
            return None
        # 引号区不做定语展开 (锁定词允许, 因为原文整体保留、仅换序)
        if ctx.quote_in(0, d + 2):
            return None
        m = toks[:d]                      # 定语
        n_idx = d + 1                     # 中心名词
        if ctx.pos[n_idx] not in ('NN', 'NR', 'PN') and toks[n_idx] not in ('阶级', '社会', '价值', '资本'):
            return None
        if len(m) > 8 or any(t in '，。、；：！？' for t in m):
            return None
        # [M]的[N] 必须是主语 (nsubj), 且谓词在 N 之后
        subj_ids = [i for i in p.find('nsubj|nsubjpass') if p.head_of(i) >= 0]
        if n_idx not in subj_ids:
            return None
        # 谓语部分: N 之后
        rest = toks[n_idx + 1:]
        if not rest or not any(pp in _VERB_POS for pp in ctx.pos[n_idx + 1:]):
            return None
        # 小句复现: 依定语构成选择句式
        has_v = any(pp in ('VV', 'VE', 'VC', 'VR') for pp in ctx.pos[:d])
        noun_lead = ctx.pos[0] in ('NN', 'NR', 'PN', 'JJ') if m else False
        if m and m[0] in ('被', '由', '以', '为'):
            clause = '它' + ''.join(m)
        elif has_v and noun_lead:
            clause = '它由' + ''.join(m)
        elif has_v:
            clause = '它被' + ''.join(m)
        else:
            # "X的Y" 多为领属关系, 只有定语整体是形容词性修饰 (JJ/VA/DT)
            # 时 "它是X的" 才成立; 否则放弃展开, 避免 "它是真理的" 这类荒谬句.
            if len(m) > 4 or any(pp not in ('JJ', 'VA', 'DT') for pp in ctx.pos[:d]):
                return None
            clause = '它是' + ''.join(m) + '的'
        return {'head': toks[n_idx:n_idx + 1], 'rest': rest, 'clause': clause}

    # ---------- S7: 动宾名词化 ----------
    def _nominal_plan(self, ctx: SentenceCtx):
        p = ctx.parsed
        toks = ctx.tokens
        if ctx.n < 4 or ctx.pos[0] not in _VERB_POS:
            return None
        if ctx.quote_in(0, 4):
            return None
        v = 0
        obj_ids = [i for i in p.find('dobj|iobj') if p.head_of(i) == v]
        if not obj_ids:
            return None
        o0 = min(obj_ids)
        if not p.is_contiguous(o0):
            return None
        oe = max(p.span_of(o0)[1], max(obj_ids) + 1)
        if o0 != 1 or oe > 4:
            return None
        # 后面必须还有主谓结构 (是/成为...)
        if not any(toks[i] in _COPULA or ctx.pos[i] in _VERB_POS
                   for i in range(oe, min(ctx.n, oe + 3))):
            return None
        return {'verb': toks[v], 'obj': toks[o0:oe], 'rest': toks[oe:]}

    # ---------- S4b: 宾语位长定语后置成句 ----------
    def _postpose_plan(self, ctx: SentenceCtx):
        """[prefix V ...] [Mod(含动词)的 Head] 。 → prefix + Head，[pron] + Mod + 。"""
        p = ctx.parsed
        toks = ctx.tokens
        if ctx.n < 9:
            return None
        tail = toks[-1]
        if tail not in ('。', '！', '？'):
            return None
        head_end = ctx.n - 1            # 句号之前
        # 从右往左吃名词性 head (NN/NR/CC/JJ/DT/CD/M)
        hs = head_end
        while hs - 1 >= 0 and ctx.pos[hs - 1] in ('NN', 'NR', 'CC', 'JJ', 'DT', 'CD', 'M') \
                and toks[hs - 1] != '的':
            hs -= 1
        if hs >= head_end or toks[hs - 1] != '的':
            return None
        d = hs - 1                       # 定语标记"的"
        # 定语从句起点: 句内第一个动词之后
        v0 = None
        for i in range(d):
            if ctx.pos[i] in ('VV', 'VE', 'VC', 'VR'):
                v0 = i
                break
        if v0 is None:
            return None
        m_start = v0 + 1
        m = toks[m_start:d]
        if not (4 <= len(m) <= 14):
            return None
        if not any(pp in ('VV', 'VE', 'VC', 'VR') for pp in ctx.pos[m_start:d]):
            return None               # 定语从句必须含谓语, 否则后置句不成句
        if any(t in '，。、；：！？' for t in m):
            return None
        if any(t in '，。、；：！？' for t in toks[:hs]):
            return None
        if ctx.quote_in(m_start, head_end + 1):
            return None
        head = toks[hs:head_end]
        pron = '它们' if any(t in ('和', '等', '们', '各种', '这些', '那些') for t in head) else '它'
        return {'prefix': toks[:m_start], 'head': head, 'mod': m, 'pron': pron}

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        pa = self._attrib_plan(ctx)
        pb = self._nominal_plan(ctx)
        pc = self._postpose_plan(ctx)
        opts = []
        if pa:
            opts.append('a')
        if pb:
            opts.append('b')
        if pc:
            opts.append('c')
        if not opts:
            return None
        act = rng.choice(opts)
        if act == 'a':
            s = ''.join(pa['head']) + ''.join(pa['rest']).rstrip('。！？') \
                + '，' + pa['clause'] + '。'
        elif act == 'b':
            s = ''.join(pb['obj']) + '的' + pb['verb'] + ''.join(pb['rest'])
            if not s.endswith(('。', '！', '？')):
                s += '。'
        else:
            s = ''.join(pc['prefix']) + ''.join(pc['head']) + '，' \
                + pc['pron'] + ''.join(pc['mod']) + '。'
        return s
