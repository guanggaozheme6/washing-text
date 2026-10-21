# -*- coding: utf-8 -*-
"""打分层: novelty / fidelity / fluency 三维 + 硬约束.

硬约束不过直接丢弃 (不进入打分):
  1. 否定词集合一致
  2. 数字原样保留
  3. 专名 / 白名单术语原样保留
  4. 句长在原文 0.6~1.8 倍
  5. 保护区内文本零改动
"""
import re

from . import verifier
from .overlap import max_run_against_corpus
from .parser import Parsed
from .protect import Protection

_GOOD_END = set('。！？')
_BAD_PAIRS = [('，', '，'), ('。', '，'), ('，', '。'),
              ('不存在', '，，'), ('；', '；')]

# --- 句法残缺检测用词表 ---
# 谓宾动词: 必须带宾语 (小句/名词短语) 才能成立, 直接收尾即为截断
_PRED_REQUIRES_OBJ = ('表明', '说明', '指出', '认为', '强调', '证明', '意味着',
                      '发现', '显示', '包括', '具有', '属于', '提出', '主张',
                      '使得')
# 不能作句尾的介词 / 连词 (悬空收尾)
_DANGLING_TAIL = ('在', '对', '把', '被', '由于', '因为', '通过', '根据',
                  '对于', '随着', '并且', '以及', '或者', '但是', '然而')

_ALT_PRED = '|'.join(_PRED_REQUIRES_OBJ)
# 句尾 = 谓宾动词 + 终止标点 → 宾语缺失 (硬伤)
_RE_PRED_END = re.compile(r'(?:%s)[着了过]?[。！？]$' % _ALT_PRED)
# 句中 = 谓宾动词 + 句号 + 后续内容 → 句子被截断后又接了新句
_RE_PRED_MID = re.compile(r'(?:%s)[着了过]?[。！？][^。！？]' % _ALT_PRED)
# 句尾 = 悬空介词 / 连词 + 终止标点
_RE_DANGLING_END = re.compile(
    r'(?:%s)[。！？]$' % '|'.join(sorted(_DANGLING_TAIL, key=len, reverse=True)))
# "是……的" 判断/强调句: 中间须为谓词性成分; 只剩光杆名词即残句
_RE_IS_DE_END = re.compile(r'是([^，。！？的是]{1,4})的[。！？]$')
# 谓词性线索字 (出现任一即视为成分成立, 不扣分)
_PRED_HINT = set('不很太更最都也才就又还再可应能会要须必得着过所被让给对从向往在是有无'
                 '来去说做行成现出到起想知觉认当同属包含具')
# 合法的"是……的"收尾 (代词 / 常见形容词)
_IS_DE_OK = frozenset(('我', '你', '他', '她', '它', '我们', '你们', '他们',
                       '自己', '大家', '别人', '这样', '那样',
                       '合理', '正确', '错误', '重要', '必要', '可能', '必然',
                       '有效', '客观', '主观', '真实', '具体', '抽象', '复杂',
                       '简单', '明显', '清楚', '一致', '相同', '不同', '唯一',
                       '相对', '绝对', '直接', '间接', '充分', '普遍', '特殊',
                       '独立', '自由', '平等', '科学', '系统', '完整', '稳定',
                       '可行', '准确', '严密', '深刻', '全面', '基本', '共同'))
# 句首悬空连接语 + 强及物动词: 主语被截掉 ("由此揭示句子的结构。")
_RE_SUBJLESS_HEAD = re.compile(
    r'^(?:由此|从而|进而|据此|就此)(?:揭示|阐明|阐述|解释|论证)')


def novelty_of(cand_text: str, corpus: list[str], orig_text: str) -> float:
    """新颖度 = 1 - max_run / len(cand). corpus 应包含比对库 + 原文."""
    if not cand_text:
        return 0.0
    pool = corpus
    if orig_text not in corpus:
        pool = corpus + [orig_text]
    run, _ = max_run_against_corpus(cand_text, pool)
    return max(0.0, 1.0 - run / len(cand_text))


def fluency_of(cand_text: str, orig_text: str,
               min_ratio: float = 0.6, max_ratio: float = 1.8) -> float:
    """通顺度: 句长合理性 + 标点合理性 + 连接词不打架 + 句法不残缺.

    权重: 句长 0.40 / 标点 0.20 / 赘余 0.15 / 句法完整 0.25.
    句尾是谓宾动词 (表明/说明/...) 属硬伤, 直接返回 0.0.
    """
    if not cand_text:
        return 0.0

    # 0) 句法硬伤: 谓宾动词收尾, 宾语 / 小句被截断
    if _RE_PRED_END.search(cand_text):
        return 0.0

    score = 0.0

    # 1) 长度比 (0.40)
    ratio = len(cand_text) / max(1, len(orig_text))
    if min_ratio <= ratio <= max_ratio:
        # 越接近 1 越自然, 允许范围内轻微扣分
        score += 0.40 * (1.0 - 0.15 * abs(ratio - 1.0))
    else:
        score += 0.0

    # 2) 标点 (0.20)
    p = 0.20
    if not re.search(r'[。！？]$', cand_text):
        p -= 0.10          # 句末必须有终止标点
    if re.search(r'[，、；：]{2,}', cand_text):
        p -= 0.06          # 连续标点
    for op, cl in [('“', '”'), ('（', '）'), ('「', '」')]:
        if cand_text.count(op) != cand_text.count(cl):
            p -= 0.10
    if re.search(r'。[^。！？]', cand_text):
        p -= 0.03          # 句中冒出句号 (拆句没接对)
    score += max(0.0, p)

    # 3) 重复连接词 / 赘余 (0.15)
    c = 0.15
    for w in ('因此', '所以', '但是', '然而', '因为', '由于', '而且', '并且'):
        if cand_text.count(w) > 1:
            c -= 0.05
    if re.search(r'(的的|了了|是是|和和|在在)', cand_text):
        c -= 0.07
    score += max(0.0, c)

    # 4) 句法完整 (0.25)
    g = 0.25
    if _RE_DANGLING_END.search(cand_text):
        g -= 0.20          # 介词 / 连词悬空收尾
    if _RE_PRED_MID.search(cand_text):
        g -= 0.20          # 谓宾动词处截断, 后接新句
    m = _RE_IS_DE_END.search(cand_text)
    if m:
        seg = m.group(1)
        if seg not in _IS_DE_OK and not (_PRED_HINT & set(seg)):
            g -= 0.15      # "是+光杆名词+的。" 判断句少谓语 ("它是真理的。")
    if _RE_SUBJLESS_HEAD.match(cand_text.strip()):
        g -= 0.10          # 句首连接语后直接挂及物动词, 主语悬空
    score += max(0.0, g)

    return round(score, 4)


def hard_check(orig_text: str, cand_text: str,
               orig_parsed: Parsed, cand_parsed: Parsed,
               prot: Protection,
               length_ratio: tuple[float, float] = (0.6, 1.8)) -> tuple[bool, str]:
    """硬约束. cand_parsed 为 None 时只做文本级检查 (粗筛用)."""
    if not cand_text or not cand_text.strip():
        return False, '空候选'

    # 1. 否定词一致
    o_neg = verifier.negation_words(orig_parsed)
    if cand_parsed is not None:
        c_neg = verifier.negation_words(cand_parsed)
        if o_neg != c_neg:
            return False, f'否定词不一致 {o_neg}->{c_neg}'
    else:
        for w, k in o_neg.items():
            if cand_text.count(w) != k:
                return False, f'否定词数量变化: {w}'

    # 2. 数字保留
    nums = verifier.numbers_of(orig_parsed)
    for x in nums:
        if x not in cand_text:
            return False, f'数字丢失: {x}'

    # 3. 白名单术语保留
    for term in prot.term_hits:
        if term not in cand_text:
            return False, f'术语丢失: {term}'

    # 4. NER 保留
    for ent in orig_parsed.ner:
        try:
            t = ent[0]
            if t and t not in cand_text:
                return False, f'专名丢失: {t}'
        except (ValueError, TypeError):
            continue

    # 5. 句长比
    lo, hi = length_ratio
    ratio = len(cand_text) / max(1, len(orig_text))
    if not (lo <= ratio <= hi):
        return False, f'句长比越界: {ratio:.2f}'

    # 6. 引号内容零改动
    if prot.quote_spans:
        for t in orig_parsed.tokens:
            pass
        joined = orig_parsed.join()
        for s, e in prot.quote_spans:
            inner = ''.join(orig_parsed.tokens[s:e])
            # 只校验引号内实体文本仍存在
            body = inner.strip('“”「」『』"\'')
            if body and body not in cand_text:
                return False, '引文被改动'
    return True, 'ok'


def total_score(novelty: float, fidelity: float, fluency: float,
                weights: dict[str, float]) -> float:
    w = weights
    return (w.get('novelty', 0.45) * novelty
            + w.get('fidelity', 0.30) * fidelity
            + w.get('fluency', 0.25) * fluency)
