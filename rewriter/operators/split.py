# -*- coding: utf-8 -*-
"""S1 长句拆分 —— 收益 ★★★ (最高).

信号: 句长 > 阈值 / 逗号分句处存在完整小句
变换: 一句长句 → 2 个小句, 拆分点选在连接词或并列谓词边界
收益: 最长连续公共子串被打断, 拆点两侧片段各自缩短
风险: 补错主语 (本实现仅在拆分点两侧都成句时动手, 不自动补主语)
"""
import random
from typing import Optional

from .base import Operator, SentenceCtx, ensure_period

# 独立成句时语义仍自洽的句首词
_LEAD_OK = ('因此', '所以', '但是', '然而', '而且', '并且', '此外', '同时',
            '由此', '从而', '进而', '只有', '如果', '由于', '因为', '尽管', '虽然',
            '于是', '可见', '反之', '否则', '总之', '换言之', '也就是说')
# 上述词条中以承接前文为主的连接词: 右半必须自带主语, 否则是残句
_LEAD_NEED_SUBJECT = frozenset(('由此', '从而', '因此', '所以', '可见', '于是',
                                '并且', '而且', '同时', '进而'))
# 长词优先, 避免短词抢占长词 (如「因此」不会被「因」类短词截断)
_LEAD_SORTED = tuple(sorted(_LEAD_OK, key=len, reverse=True))
# 分词器会把「由此」「由于」「从而」切成两个 token (由+此), 跨 token 匹配的最多 token 数
_LEAD_MAX_TOKENS = 3
# 情态/助动词: 定位「首个谓词」时跳过, 让真正的主谓语浮出来
_AUX_MODAL = frozenset(('会', '能', '能够', '可以', '可', '将', '要', '应',
                        '应该', '可能', '须', '需', '必须', '得以'))
# 指示/回指代词: 不能充当独立小句的主语 (「由此揭示…」里的「此」不是主语)
_DEMONSTRATIVE = frozenset(('此', '这', '那', '其', '该', '本', '上述',
                            '前者', '后者', '它', '它们', '之'))
_NOUN_POS = ('NN', 'NR', 'NS', 'NT', 'NX', 'PN')
# 谓宾动词: 后面必须带宾语或宾语从句, 在其后断句会拦腰砍断动宾结构
_PRED_TAKING_CLAUSE = frozenset((
    '表明', '说明', '指出', '认为', '强调', '证明', '意味着', '发现',
    '显示', '包括', '具有', '属于', '提出', '主张', '要求', '使得',
))
_SUBJ_RELS = ('nsubj', 'nsubjpass')     # 主语类依存关系
_VERB_POS = ('VV', 'VE', 'VA', 'VC', 'VR')
_PUNCT = ('，', '；', '、', '。', '：', '！', '？', '…')
_COMMA = ('，', '；')


def _lead_span(right: list[str]) -> tuple[str, int]:
    """右半句首的连接词及其占用的 token 数 (无则 ('', 0)).

    HanLP 会把多字连接词切开 (如「由此」→ 由/此, 「由于」→ 由/于,
    「从而」→ 从/而), 因此除单 token 前缀匹配外, 还要把前 k 个 token
    拼起来再匹配一次, 否则跨 token 的连接词永远识别不到.
    """
    if not right:
        return '', 0
    for w in _LEAD_SORTED:
        if right[0].startswith(w):        # 连接词粘在首个 token 上
            return w, 1
    for k in range(2, min(_LEAD_MAX_TOKENS, len(right)) + 1):
        joined = ''.join(right[:k])
        for w in _LEAD_SORTED:
            if joined.startswith(w):
                return w, k
    return '', 0


def _last_content_idx(ctx: SentenceCtx, end: int) -> int:
    """[0, end) 内最后一个实词下标; -1 表示取不到."""
    for i in range(end - 1, -1, -1):
        if ctx.tokens[i] in _PUNCT:
            continue
        if i < len(ctx.pos) and ctx.pos[i] == 'PU':
            continue
        return i
    return -1


def _is_pred_taking_clause(ctx: SentenceCtx, i: int) -> bool:
    """i 处是否为谓宾动词 (词表 + 动词性词性, 避免把同形名词误判)."""
    if i < 0 or ctx.tokens[i] not in _PRED_TAKING_CLAUSE:
        return False
    # 词性缺失时退化为纯词表判定
    if i < len(ctx.pos) and ctx.pos[i]:
        return ctx.pos[i] in _VERB_POS
    return True


def _first_pred(ctx: SentenceCtx, start: int) -> int:
    """右半 [start, n) 的首个主要谓词下标; -1 表示没有谓词."""
    for j in range(start, ctx.n):
        if j >= len(ctx.pos) or ctx.pos[j] not in _VERB_POS:
            continue
        if ctx.tokens[j] in _AUX_MODAL:
            continue
        return j
    return -1


def _has_subject(ctx: SentenceCtx, start: int) -> bool:
    """右半 [start, n) 的首个谓词是否自带主语.

    只认右半首个谓词的主语 —— 扫描整个右半会把从句主语误当主句主语
    (如「从而证明了该方法…具有…」里的「方法」是「具有」的主语, 不是「证明」的).
    指示代词 (此/这/其) 不算主语, 它们只是回指前文.
    """
    if start >= ctx.n:
        return False
    pred = _first_pred(ctx, start)
    if pred < 0:
        return False                        # 无谓词, 不是完整小句
    dep = ctx.parsed.dep
    # 1) 依存证据: 主语必须挂在首个谓词上 (head 落在 [start, pred]), 不能早于拆分点
    for j in range(start, ctx.n):
        if j >= len(dep) or dep[j][1] not in _SUBJ_RELS:
            continue
        head = dep[j][0] - 1
        if start <= head <= pred and ctx.tokens[j] not in _DEMONSTRATIVE:
            return True
    # 2) 兜底: 连接词之后紧邻的名词性成分作主语
    #    HanLP 常把「由此模型…」解析成 由+此模型 的介宾结构, 拿不到 nsubj
    for j in range(start, ctx.n):
        if ctx.tokens[j] in _PUNCT:
            continue
        if j < len(ctx.pos) and ctx.pos[j] == 'PU':
            continue
        if ctx.tokens[j] in _DEMONSTRATIVE:
            return False
        if j >= len(ctx.pos) or ctx.pos[j] not in _NOUN_POS:
            return False                    # 句首就是谓词 -> 缺主语
        return j < pred                     # 名词性成分在谓词之前 -> 作主语
    return False


class SplitOperator(Operator):
    name = 'split'
    desc = '长句拆分: 在分句边界把长句切成两小句'

    def __init__(self, min_len: int = 28, min_half: int = 7):
        self.min_len = min_len      # 整句最小字符数
        self.min_half = min_half    # 每半最小字符数

    def match(self, ctx: SentenceCtx) -> bool:
        return len(ctx.text) >= self.min_len and self._split_points(ctx)

    def _split_points(self, ctx: SentenceCtx) -> list[int]:
        """收集合法的拆分点 (逗号 token 下标)."""
        pts: list[int] = []
        toks = ctx.tokens
        for i, t in enumerate(toks):
            if t not in _COMMA:
                continue
            if ctx.is_locked(i):
                continue
            # 引号内不做拆分点
            if any(s <= i < e for s, e in ctx.prot.quote_spans):
                continue
            left_len = sum(len(x) for x in toks[:i])
            right_len = sum(len(x) for x in toks[i + 1:])
            if left_len < self.min_half or right_len < self.min_half:
                continue
            right = toks[i + 1:]
            # 左半以谓宾动词收尾: 断句会把动宾结构拦腰砍断, 直接拒绝
            if _is_pred_taking_clause(ctx, _last_content_idx(ctx, i)):
                continue
            # 右侧必须是完整小句
            has_verb = any(pp in _VERB_POS for pp in ctx.pos[i + 1:])
            lead, lead_n = _lead_span(right)
            if lead in _LEAD_NEED_SUBJECT:
                # 承接型连接词: 右半首个谓词无主语即为残句, 拒绝
                ok = _has_subject(ctx, i + 1 + lead_n)
            elif lead:
                # 让步/转折/递进类连接词: 自带分句能力
                ok = True
            else:
                # 无连接词: 必须自身含谓语
                ok = has_verb
            if ok:
                pts.append(i)
        return pts

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[list[str]]:
        pts = self._split_points(ctx)
        if not pts:
            return None
        rng.shuffle(pts)
        # 优先选右侧以连接词开头的拆分点 (最安全)
        connector_pts = [p for p in pts if _lead_span(ctx.tokens[p + 1:])[0]]
        pool = connector_pts or pts
        pt = rng.choice(pool)

        left = ctx.tokens[:pt]
        right = ctx.tokens[pt + 1:]
        if not left or not right:
            return None

        # 左半收尾: 剥掉其原有逗号类的悬垂标点, 补句号
        while left and left[-1] in ('，', '；', '、'):
            left.pop()
        left_s = ''.join(left)
        left_s = ensure_period(left_s)
        right_s = ensure_period(''.join(right))

        # 半句太短则放弃
        if len(left_s) < self.min_half or len(right_s) < self.min_half:
            return None
        return [left_s, right_s]
