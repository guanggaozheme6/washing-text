# -*- coding: utf-8 -*-
"""S3 语态变换 —— 收益 ★★☆.

被字句 → 主动: "生产资料被一部分人垄断" → "一部分人垄断了生产资料"
主动 → 由字句: "资本家占有生产资料" → "生产资料由资本家占有"
只处理最简单的 NP被NP+V / NP+V+NP 框架, 成分不连续即放弃.
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx

_PASSIVE_MARKS = ('被', '由')


class VoiceOperator(Operator):
    name = 'voice'
    desc = '语态变换: 被字句 → 主动句 / 主动句 → 由字句'

    @staticmethod
    def _verb_of_mark(p, b: int):
        """取被动标记关联的谓语动词: 标记可能挂在动词下(pass), 也可能是动词的父节点."""
        h = p.head_of(b)
        if h >= 0 and p.is_verb(h):
            return h
        for c in p.children(b):
            if p.is_verb(c):
                return c
        return None

    def match(self, ctx: SentenceCtx) -> bool:
        return (self._passive_plan(ctx) is not None
                or self._active_plan(ctx) is not None
                or self._short_passive_plan(ctx) is not None)

    # ---------- 被字句 → 主动 ----------
    def _passive_plan(self, ctx: SentenceCtx):
        p = ctx.parsed
        toks = ctx.tokens
        marks = [i for i, t in enumerate(toks) if t == '被' and ctx.pos[i] in ('LB', 'SB', 'P')]
        if not marks or ctx.n < 7:
            return None
        b = marks[0]
        # 患者: 被 之前, 且是 nsubjpass 或其子树 (取子树并集, 要求连续)
        patient_ids = [i for i in range(b) if p.rel_of(i) in ('nsubjpass', 'nsubj')]
        if not patient_ids:
            return None
        pset: set[int] = set()
        for i in patient_ids:
            pset |= p.subtree(i)
        ps, pe = min(pset), max(pset) + 1
        if len(pset) != pe - ps or pe != b:
            return None
        # 谓语动词
        verb = self._verb_of_mark(p, b)
        if verb is None:
            return None
        # 施事: 动词的 nsubj 子树 (并集需连续)
        agent_ids = [i for i in p.find('nsubj') if p.head_of(i) == verb]
        if not agent_ids:
            return None
        aset: set[int] = set()
        for i in agent_ids:
            aset |= p.subtree(i)
        a0, ae = min(aset), max(aset) + 1
        if len(aset) != ae - a0:
            return None
        # 施事必须紧跟"被", 且整体位于动词之前
        if a0 != b + 1 or ae > verb:
            return None
        tail = toks[verb + 1:]
        return {'patient': (ps, pe), 'agent': (a0, ae), 'verb': verb,
                'tail': tail, 'head': toks[:ps], 'idx': (ps, pe, b, ae, verb)}

    # ---------- 主动 → 由字句 ----------
    def _active_plan(self, ctx: SentenceCtx):
        p = ctx.parsed
        toks = ctx.tokens
        if ctx.n < 6:
            return None
        verbs = p.main_verbs()
        if not verbs:
            return None
        v = verbs[0]
        if any(t in _PASSIVE_MARKS for t in toks):
            return None
        subj_ids = [i for i in p.find('nsubj') if p.head_of(i) == v]
        obj_ids = [i for i in p.find('dobj|iobj') if p.head_of(i) == v]
        if not subj_ids or not obj_ids:
            return None
        s0, o0 = min(subj_ids), min(obj_ids)
        if not (p.is_contiguous(s0) and p.is_contiguous(o0)):
            return None
        s_e = max(p.span_of(s0)[1], max(subj_ids) + 1)
        o_e = max(p.span_of(o0)[1], max(obj_ids) + 1)
        # 主语从句首开始, 宾语在动词右侧且基本收尾 (避免长距离错配)
        if s0 != 0 or o0 <= v or s_e > v:
            return None
        if o_e < ctx.n - 2:
            return None
        # 动词与宾语之间只允许体标记
        between = toks[v + 1:o0]
        if [x for x in between if x not in ('了', '着', '过')]:
            return None
        if v == s_e:
            mid = []
        elif toks[s_e:v] in ([], ['，']):
            mid = toks[s_e:v]
        else:
            return None
        return {'subj': (s0, s_e), 'obj': (o0, o_e), 'verb': v,
                'mid': mid, 'tail': toks[o_e:]}

    # ---------- 短被动: 删"被" (无施事时) ----------
    def _short_passive_plan(self, ctx: SentenceCtx):
        p = ctx.parsed
        toks = ctx.tokens
        marks = [i for i, t in enumerate(toks) if t == '被' and ctx.pos[i] in ('LB', 'SB', 'P')]
        if not marks:
            return None
        b = marks[0]
        # 必须有 nsubjpass 患者
        if not any(p.rel_of(i) == 'nsubjpass' for i in range(b)):
            return None
        # 施事不存在: 动词没有 nsubj/agent 子
        verb = self._verb_of_mark(p, b)
        if verb is None:
            return None
        if any(p.head_of(i) == verb and p.rel_of(i) in ('nsubj', 'agent') for i in range(ctx.n)):
            return None
        # 被 后紧跟动词或副词, 删除被不会产生断句
        if b + 1 >= ctx.n:
            return None
        return {'被': b, 'verb': verb}

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        pa = self._passive_plan(ctx)
        pb = self._active_plan(ctx)
        pc = self._short_passive_plan(ctx)
        opts = []
        if pa:
            opts.append('a')
        if pb:
            opts.append('b')
        if pc:
            opts.append('c')
        if not opts:
            return None
        toks = ctx.tokens
        act = rng.choice(opts)
        if act == 'a':
            ps, pe = pa['patient']
            ae = pa['agent'][1]
            verb = pa['verb']
            # 动词后已有体标记 (了/着/过) 则不再补 '了'
            nxt = toks[verb + 1] if verb + 1 < ctx.n else ''
            has_as = nxt in ('了', '着', '过') or (verb + 1 < ctx.n and ctx.pos[verb + 1] == 'AS')
            agent = toks[pa['agent'][0]:ae]
            patient = toks[ps:pe]
            verb_final = toks[verb] + '了' if not has_as else toks[verb]
            new = pa['head'] + agent + [verb_final] + patient + pa['tail']
            s = ''.join(new)
        elif act == 'b':
            s0, se = pb['subj']
            o0, oe = pb['obj']
            v = pb['verb']
            new = toks[o0:oe] + ['由'] + toks[s0:se] + pb['mid'] + [toks[v]] + pb['tail']
            s = ''.join(new)
        else:
            b = pc['被']
            new = toks[:b] + toks[b + 1:]
            s = ''.join(new)
        if not s.endswith(('。', '！', '？')):
            s += '。'
        return s
