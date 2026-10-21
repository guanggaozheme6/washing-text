# -*- coding: utf-8 -*-
"""HanLP 封装: 一次加载, 批量解析, 带缓存.

输出统一为 Parsed 对象, 算子只依赖:
  tokens / pos / dep / srl / ner
不再使用 con 树 (算子全部可以基于 dep+srl 实现, 更快更稳).
"""
from dataclasses import dataclass, field
from typing import Optional

_MODEL = None
_MODEL_NAME = None
_CACHE: dict[tuple, 'Parsed'] = {}

ALL_TASKS = ['tok', 'pos', 'ner', 'dep', 'con', 'srl']
DEFAULT_TASKS = ['tok', 'pos', 'dep', 'srl', 'ner']


@dataclass
class Parsed:
    text: str
    tokens: list[str] = field(default_factory=list)
    pos: list[str] = field(default_factory=list)
    dep: list[tuple[int, str]] = field(default_factory=list)   # (head_1based, rel); 0=root
    srl: list = field(default_factory=list)                    # [[text, label, start, end], ...]
    ner: list = field(default_factory=list)                    # [[text, type, start, end], ...]

    @property
    def n(self) -> int:
        return len(self.tokens)

    def join(self) -> str:
        return ''.join(self.tokens)

    # ---------- dep 辅助 ----------

    def head_of(self, i: int) -> int:
        """token i (0-based) 的中心词下标 (0-based), -1 表示 root."""
        h = self.dep[i][0]
        return h - 1 if h > 0 else -1

    def rel_of(self, i: int) -> str:
        return self.dep[i][1]

    def root_idx(self) -> int:
        for i, (h, _) in enumerate(self.dep):
            if h == 0:
                return i
        return -1

    def children(self, i: int) -> list[int]:
        """token i 的依存孩子 (0-based)."""
        return [j for j in range(self.n) if self.dep[j][0] == i + 1]

    def find(self, rel: str) -> list[int]:
        """按关系找 token: rel 可为 'nsubj' 或 'nsubj|nsubjpass'."""
        rels = set(rel.split('|'))
        return [i for i in range(self.n) if self.dep[i][1] in rels]

    def subtree(self, i: int) -> set[int]:
        """token i 的完整依存子树 (含自身)."""
        out = {i}
        stack = [i]
        while stack:
            cur = stack.pop()
            for ch in self.children(cur):
                if ch not in out:
                    out.add(ch)
                    stack.append(ch)
        return out

    def span_of(self, i: int) -> tuple[int, int]:
        """token i 子树的最小区间 [start, end) —— 仅当子树连续时严格有效."""
        st = self.subtree(i)
        return min(st), max(st) + 1

    def is_contiguous(self, i: int) -> bool:
        st = self.subtree(i)
        return max(st) - min(st) + 1 == len(st)

    def subtree_text(self, i: int) -> str:
        st, en = self.span_of(i)
        return ''.join(self.tokens[st:en])

    def is_verb(self, i: int) -> bool:
        return self.pos[i] in ('VV', 'VA', 'VE', 'VC', 'VR')

    def main_verbs(self) -> list[int]:
        """句内主要动词 (root 或与 root 并列的谓词)."""
        r = self.root_idx()
        verbs = []
        if r >= 0 and (self.is_verb(r) or self.pos[r] in ('NN', 'JJ', 'PN', 'CD')):
            # root 是动词直接用; root 是名词/形容词时向下找动词
            if self.is_verb(r):
                verbs.append(r)
            else:
                cand = [c for c in self.children(r) if self.is_verb(c)]
                verbs.extend(cand)
        for i in range(self.n):
            if self.is_verb(i) and i not in verbs and self.head_of(i) == r and self.rel_of(i) in ('conj', 'ccomp', 'xcomp'):
                verbs.append(i)
        return verbs or [i for i in range(self.n) if self.is_verb(i)][:1]


def load_model(name: str = 'OPEN_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH'):
    """加载多任务模型 (进程级单例)."""
    global _MODEL, _MODEL_NAME
    if _MODEL is None or _MODEL_NAME != name:
        import hanlp
        _MODEL = hanlp.load(getattr(hanlp.pretrained.mtl, name))
        _MODEL_NAME = name
    return _MODEL


class Parser:
    """批量解析器. 相同文本命中缓存, 跨轮次复用."""

    def __init__(self, tasks: Optional[list[str]] = None,
                 model: str = 'OPEN_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH',
                 cache: bool = True):
        self.tasks = [t for t in (tasks or DEFAULT_TASKS) if t in ALL_TASKS]
        self.model_name = model
        self.cache_on = cache

    def parse_one(self, text: str) -> Parsed:
        return self.parse_batch([text])[0]

    def parse_batch(self, texts: list[str]) -> list[Parsed]:
        if not texts:
            return []
        results: list[Optional[Parsed]] = [None] * len(texts)
        todo: list[tuple[int, str]] = []
        for idx, t in enumerate(texts):
            key = (self.model_name, tuple(self.tasks), t)
            if self.cache_on and key in _CACHE:
                results[idx] = _CACHE[key]
            else:
                todo.append((idx, t))

        if todo:
            model = load_model(self.model_name)
            inputs = [t for _, t in todo]
            doc = model(inputs, tasks=self.tasks)
            for k, (idx, text) in enumerate(todo):
                p = Parsed(text=text)
                if 'tok' in self.tasks:
                    p.tokens = list(doc['tok'][k])
                if 'pos' in self.tasks:
                    p.pos = list(doc['pos'][k])
                if 'dep' in self.tasks:
                    p.dep = [tuple(x) for x in doc['dep'][k]]
                if 'srl' in self.tasks:
                    p.srl = [list(x) for x in doc['srl'][k]]
                if 'ner' in self.tasks:
                    p.ner = [list(x) for x in doc['ner'][k]] if doc.get('ner') else []
                if self.cache_on:
                    _CACHE[(self.model_name, tuple(self.tasks), text)] = p
                results[idx] = p
        return [r for r in results if r is not None]

    def clear_cache(self):
        _CACHE.clear()
