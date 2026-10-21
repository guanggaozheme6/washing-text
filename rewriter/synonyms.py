# -*- coding: utf-8 -*-
"""同义词资源加载与缓存.

优先级: synonyms 库 (若已安装) > data/synonyms.json > 内置小词表.
仅被 S8 同义替换算子使用 (默认关闭).
"""
import json
import os

from .config import resolve_path

# 内置极简词表 (无外部依赖时的兜底)
_BUILTIN = {
    '重要': ['关键', '要紧'],
    '方法': ['办法', '途径'],
    '研究': ['探讨', '考察'],
    '发展': ['演进', '推进'],
    '提高': ['提升', '增强'],
    '许多': ['不少', '诸多'],
    '因此': ['由此可见', '因而'],
    '但是': ['然而', '不过'],
    '开始': ['着手', '起步'],
    '最后': ['最终'],
    '主要': ['首要', '核心'],
    '明显': ['显著', '突出'],
    '巨大': ['庞大', '可观'],
    '表明': ['显示', '说明'],
    '具有': ['拥有', '具备'],
    '不断': ['持续', '日益'],
    '能够': ['可以', '足以'],
    '由于': ['因为', '鉴于'],
    '可以': ['能够', '可'],
    '确定': ['明确', '厘定'],
    '提供': ['给出', '供给'],
    '分析': ['剖析', '解析'],
    '包括': ['涵盖', '包含'],
}

_TABLE_CACHE: dict | None = None


def _load_json_table(path: str) -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    if path and os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            for k, v in data.items():
                if isinstance(v, list):
                    table[k] = [x for x in v if isinstance(x, str) and x != k]
        except (json.JSONDecodeError, OSError):
            pass
    return table


def _load_synonyms_lib() -> dict[str, list[str]]:
    """可选: 使用 huyingxi/Synonyms 词表 (pip install synonyms)."""
    try:
        import synonyms  # noqa: F401
    except ImportError:
        return {}
    # Synonyms 库按需查询 (无全量导出接口), 这里只做探活;
    # 实际替换时走 synonyms.nearby(word) 动态查询.
    return {'__lib__': ['synonyms']}


def load_synonym_table(extra_path: str | None = None, use_cache: bool = True) -> dict[str, list[str]]:
    """加载同义词表: 内置 + synonyms.json 补充 (+ synonyms 库探活)."""
    global _TABLE_CACHE
    if use_cache and _TABLE_CACHE is not None and extra_path is None:
        return _TABLE_CACHE
    if extra_path is None:
        extra_path = resolve_path('data/synonyms.json')

    table = {k: list(v) for k, v in _BUILTIN.items()}
    for k, v in _load_json_table(extra_path).items():
        merged = table.setdefault(k, [])
        for w in v:
            if w not in merged:
                merged.append(w)
    table.update(_load_synonyms_lib())
    if use_cache and extra_path is not None:
        _TABLE_CACHE = table
    return table


def nearby(word: str, table: dict[str, list[str]] | None = None,
           topn: int = 5) -> list[str]:
    """取某个词的同义候选: 先查表, 表没有再走 synonyms 库."""
    table = table or load_synonym_table()
    if word in table:
        return list(table[word])
    try:
        import synonyms
        words, scores = synonyms.nearby(word, topn)
        return [w for w, s in zip(words, scores) if w != word and s > 0.7][:topn]
    except Exception:
        return []
