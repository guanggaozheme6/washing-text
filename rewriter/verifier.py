# -*- coding: utf-8 -*-
"""保义校验: SRL 谓词-论元 + 依存三元组 的包含率.

fidelity = 0.5 * SRL包含率 + 0.5 * 依存三元组包含率
  包含率 = |原结构 ∩ 新结构| / |原结构|  —— 度量"原意丢失了多少",
  比 Jaccard 更适合改写场景 (改写会增加代词/连接词, 但不该因此扣分).
关系标签先归一化 (nsubj/nsubjpass→subj, dobj/iobj/pobj→obj ...),
让"被字句→主动句"这类保义变换不被误杀.

只抓结构性偏差, 细微语气/范围变化兜不住 —— 终稿仍需人工通读.
"""
from .parser import Parsed

# 依存关系归一化: 同组关系在改写后会互换
_REL_GROUP = {
    'nsubj': 'subj', 'nsubjpass': 'subj', 'agent': 'subj',
    'dobj': 'obj', 'iobj': 'obj', 'lobj': 'obj', 'pobj': 'obj',
    'advmod': 'adv', 'tmod': 'adv',
    'amod': 'mod', 'assmod': 'mod', 'rcmod': 'mod', 'nn': 'mod', 'cpm': 'mod',
    'ccomp': 'comp', 'xcomp': 'comp', 'pccomp': 'comp',
}
_SKIP_RELS = {'punct', 'dep', 'assm', 'cc', 'conj', 'plmod', 'clf', 'etc', 'det', 'mmod', 'loc'}


def _norm_rel(rel: str) -> str:
    return _REL_GROUP.get(rel, rel)


def dep_triples(p: Parsed) -> set[tuple[str, str, str]]:
    """依存三元组 (中心词, 归一化关系, 依存词), 忽略标点."""
    out = set()
    for i in range(p.n):
        h, rel = p.dep[i]
        if h == 0 or rel in _SKIP_RELS:
            continue
        head = p.tokens[h - 1]
        dep = p.tokens[i]
        if head in '，。、；：！？' or dep in '，。、；：！？':
            continue
        out.add((head, _norm_rel(rel), dep))
    return out


def _norm_label(label: str) -> str:
    if label in ('A0', 'A1', 'A2'):
        return label
    if label.startswith('ARG'):
        n = label[3:]
        return n if n in ('0', '1', '2') else 'AM'
    return label


def srl_pairs(p: Parsed) -> set[tuple[str, str, str]]:
    """SRL 谓词-论元对 (谓词, 归一化标签, 论元)."""
    out = set()
    for pred in p.srl:
        try:
            pred_text = next((a[0] for a in pred if a[1] == 'PRED'), '')
            for arg in pred:
                text, label, _, _ = arg
                if label == 'PRED':
                    continue
                out.add((pred_text, _norm_label(label), text))
        except (ValueError, TypeError):
            continue
    return out


def _containment(orig: set, cand: set) -> float:
    """原结构在候选中的保留比例."""
    if not orig:
        return 1.0
    return len(orig & cand) / len(orig)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 实词词性: 名词/专名/动词/形容词. 这些词承载"信息", 修饰词与功能词不参与.
_LEX_POS = frozenset(('NN', 'NR', 'VV', 'VE', 'VA', 'VC', 'JJ'))


def lexical_containment(orig: Parsed, cand: Parsed) -> float:
    """原句实词(名/动/形)在候选中的覆盖率 —— 衡量信息有没有丢, 不苛求句式.

    与 fidelity 的分工:
      - fidelity 量的是"原句句法结构还剩多少", 适合规则算子的结构微调;
      - 生成式改写的目的就是换句法, 用 fidelity 衡量它等于让它起跑即出局,
        所以对它改用词汇口径: 只看原句实词还在不在.
    取原句 POS ∈ {NN, NR, VV, VE, VA, VC, JJ} 的 token 集合(重复词按集合算),
    算其中有多少在候选 token 里出现. 原句无实词时返回 1.0.
    """
    want = {t for t, p in zip(orig.tokens, orig.pos) if p in _LEX_POS}
    if not want:
        return 1.0
    have = set(cand.tokens)
    return round(len(want & have) / len(want), 4)


def fidelity(orig: Parsed, cand: Parsed) -> dict:
    """保义度: 0~1. 候选可为多句合并后的拼接文本."""
    st_o, st_c = srl_pairs(orig), srl_pairs(cand)
    dt_o, dt_c = dep_triples(orig), dep_triples(cand)
    s = _containment(st_o, st_c)
    d = _containment(dt_o, dt_c)
    return {
        'fidelity': round(0.5 * s + 0.5 * d, 4),
        'srl_contain': round(s, 4),
        'dep_contain': round(d, 4),
        'srl_jaccard': round(_jaccard(st_o, st_c), 4),
        'dep_jaccard': round(_jaccard(dt_o, dt_c), 4),
    }


def negation_words(p: Parsed) -> dict[str, int]:
    """否定词计数, 用于硬约束 (多一个少一个都是语义反转)."""
    negs = '不没未无莫别非'
    cnt: dict[str, int] = {}
    for t in p.tokens:
        if len(t) == 1 and t in negs:
            cnt[t] = cnt.get(t, 0) + 1
    return cnt


def numbers_of(p: Parsed) -> list[str]:
    import re
    return re.findall(r'[0-9]+(?:\.[0-9]+)?%?', p.join())
