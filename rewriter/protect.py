# -*- coding: utf-8 -*-
"""保护区: 术语白名单 / 引号内文本 / 数字与量词 / 命名实体.

三条铁律:
  术语不改 —— 白名单命中即锁定
  引文不动 —— 引号内容锁死, 引文占比过高的整句直接冻结
  数字不动 —— 数字/年份/百分比精确保留
"""
import re
from dataclasses import dataclass, field

from .parser import Parsed

_QUOTE_PAIRS = {'“': '”', '「': '」', '『': '』', '"': '"', "'": "'", '‘': '’'}
_QUOTE_OPEN = set('“「『‘')
_QUOTE_ALL = set('“”「」『』"\'')
_DIGIT_RE = re.compile(r'[0-9]+(?:\.[0-9]+)?%?|[一二三四五六七八九十百千万亿零两]+(?:年|月|日|个|种|部分|次|倍|%|％)?')
_PUNCT_SET = set('，。、；：！？""''（）《》〈〉【】…—·,.!?;:()[]{}"\'')


@dataclass
class Protection:
    """一句的保护信息."""
    locked_tokens: set[int] = field(default_factory=set)   # 不可改动的 token 下标 (0-based)
    quote_spans: list[tuple[int, int]] = field(default_factory=list)  # token 区间, 引号内容
    term_hits: dict[str, list[int]] = field(default_factory=dict)     # 命中术语 -> token 下标
    number_tokens: set[int] = field(default_factory=set)
    ner_tokens: set[int] = field(default_factory=set)
    frozen: bool = False          # 整句冻结 (引文占比高)
    frozen_reason: str = ''


def load_whitelist(path: str) -> list[str]:
    terms: list[str] = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    terms.append(line)
    except FileNotFoundError:
        pass
    # 长的优先, 保证最长匹配
    terms.sort(key=len, reverse=True)
    return terms


def _tokens_of(text: str) -> list[str]:
    """把术语串拍平成字符序列用于在 token 串中做最长匹配 (术语可能被分词器切开)."""
    return list(text)


def mark_protection(p: Parsed, whitelist: list[str],
                    keep_quotes: bool = True,
                    keep_numbers: bool = True,
                    keep_ner: bool = True) -> Protection:
    prot = Protection()
    n = p.n
    if n == 0:
        prot.frozen = True
        prot.frozen_reason = '空句'
        return prot

    # --- 白名单术语: 在 token 连接串上做最长匹配, 映射回 token 下标 ---
    joined = p.join()
    # 每个 token 的首字符偏移
    offsets = []
    off = 0
    for t in p.tokens:
        offsets.append(off)
        off += len(t)
    offsets.append(off)

    def char_span_to_tokens(cs: int, ce: int) -> list[int]:
        idxs = [i for i in range(n) if offsets[i] < ce and offsets[i + 1] > cs]
        return idxs

    for term in whitelist:
        start = 0
        while True:
            pos = joined.find(term, start)
            if pos < 0:
                break
            idxs = char_span_to_tokens(pos, pos + len(term))
            if idxs:
                prot.locked_tokens.update(idxs)
                prot.term_hits.setdefault(term, []).extend(idxs)
            start = pos + 1

    # --- 引号区 ---
    if keep_quotes:
        stack: list[int] = []
        i = 0
        while i < n:
            t = p.tokens[i]
            if len(t) == 1 and t in _QUOTE_ALL:
                if t in _QUOTE_OPEN:
                    stack.append(i)
                    prot.locked_tokens.add(i)
                elif stack:
                    st = stack.pop()
                    inner = set(range(st + 1, i))
                    prot.quote_spans.append((st, i + 1))
                    prot.locked_tokens.update(inner)
                    prot.locked_tokens.add(i)
                else:
                    prot.locked_tokens.add(i)
            i += 1
        # 未闭合引号: 引号后全部锁
        if stack:
            for st in stack:
                prot.locked_tokens.update(range(st, n))

    # --- 数字 ---
    if keep_numbers:
        for i, t in enumerate(p.tokens):
            if _DIGIT_RE.fullmatch(t):
                prot.number_tokens.add(i)
                prot.locked_tokens.add(i)
        # pos=CD 的数词也锁
        for i, tag in enumerate(p.pos):
            if tag in ('CD', 'OD', 'NT'):
                prot.number_tokens.add(i)
                prot.locked_tokens.add(i)

    # --- NER ---
    if keep_ner:
        for ent in p.ner:
            try:
                _, _, s, e = ent
                for i in range(int(s), min(int(e), n)):
                    prot.ner_tokens.add(i)
                    prot.locked_tokens.add(i)
            except (ValueError, TypeError):
                continue

    # --- 整句冻结判定: 引文内容占整句字符的一半以上 ---
    if prot.quote_spans:
        qlen = sum(sum(len(p.tokens[i]) for i in range(s, e)) for s, e in prot.quote_spans)
        if qlen >= max(8, int(len(joined) * 0.5)):
            prot.frozen = True
            prot.frozen_reason = '引文占比过高'
    return prot


def locked_in_range(prot: Protection, start: int, end: int) -> bool:
    """区间 [start, end) 内是否含锁定 token."""
    return any(i in prot.locked_tokens for i in range(start, end))
