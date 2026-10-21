# -*- coding: utf-8 -*-
"""S6 短句合并 —— 收益 ★★☆, pipeline 层应用.

"相邻句同主语" 时合并:
  S1: "工人创造了机器。工人占有了产品。"
  →   "工人创造了机器，并且占有了产品。"
合并后句子必须有完整主语, 两句都不含引文/数字锁定时才做.
"""
from .base import Operator, SentenceCtx  # noqa: F401  (接口占位)

_MERGE_CONN = ['并且', '而且', '同时', '也']


def try_merge(prev_text: str, prev_ctx, cur_text: str, cur_ctx,
              max_total: int = 56) -> str | None:
    """尝试合并相邻两句. prev_ctx / cur_ctx 为 SentenceCtx (可为 None)."""
    if prev_ctx is None or cur_ctx is None:
        return None
    if prev_ctx.prot.frozen or cur_ctx.prot.frozen:
        return None
    if prev_ctx.prot.quote_spans or cur_ctx.prot.quote_spans:
        return None
    total = len(prev_text) + len(cur_text)
    if total > max_total or len(prev_text) < 6 or len(cur_text) < 6:
        return None
    if any(ch.isdigit() for ch in cur_text):
        return None

    p = cur_ctx.parsed
    if p.n < 3:
        return None
    # 当前句主语必须在前 3 个 token 内且为 nsubj 子树起点
    subj_ids = [i for i in p.find('nsubj|nsubjpass') if i < 3]
    if not subj_ids:
        return None
    s0 = min(subj_ids)
    if s0 != 0 or not p.is_contiguous(s0):
        return None
    se = p.span_of(s0)[1]
    if se >= p.n - 1 or se >= 4:
        return None
    subj = ''.join(p.tokens[:se])
    rest = ''.join(p.tokens[se:]).rstrip('。！？')
    if not rest:
        return None

    # 前句末尾主语必须相同 (文本级判断, 保守: 前句非冻结且主语出现在前句)
    prev_body = prev_text.rstrip('。！？')
    if subj and subj not in prev_body:
        return None
    if prev_body.endswith(subj):
        return None

    conn = '，并且' if not prev_body.endswith(('，', '、')) else '并且'
    merged = prev_body + conn + rest + '。'
    return merged
