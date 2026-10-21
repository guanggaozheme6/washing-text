# -*- coding: utf-8 -*-
"""重合度评估: 最长连续公共子串 / 与语料库比对 / 全篇报告.

这是优化目标的可计算版本 —— 没有评估器, 改写就是盲改.
"""
import os

# 参与比对时剔除的标点 (查重系统通常忽略标点, 字符级比对提供两档:
# strict=保留标点, loose=剔除标点后再比)
_PUNCT_CHARS = """，。、；：！？（）《》〈〉【】…—·,.!?;:()[]{}"'`~“”‘’「」『』 \t\u3000\n\r"""
_PUNCT_TRANS = {ord(c): None for c in _PUNCT_CHARS}


def _strip_punct(s: str) -> str:
    return s.translate(_PUNCT_TRANS)


def max_common_substring(a: str, b: str, loose: bool = False) -> int:
    """最长连续公共子串长度 (字符级).

    loose=True 时先剔除标点与空白再比 —— 更接近查重系统的口径.
    """
    if not a or not b:
        return 0
    if loose:
        a = _strip_punct(a)
        b = _strip_punct(b)
    if not a or not b:
        return 0
    # DP 滚动数组, O(len(a)*len(b)); 句子级文本足够
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                v = prev[j - 1] + 1
                cur[j] = v
                if v > best:
                    best = v
        prev = cur
    return best


def max_run_against_corpus(sent: str, corpus: list[str], loose: bool = False) -> tuple[int, str]:
    """与整个语料库比对, 返回 (最大连续重合长度, 命中的语料句).

    loose=False (默认): 字符级比对, 标点计入 —— 与 PLAN §8 口径一致.
    loose=True: 忽略标点 —— 模拟查重系统的常见口径, 供参考.
    """
    best, hit = 0, ''
    for c in corpus:
        if not c.strip():
            continue
        v = max_common_substring(sent, c, loose=loose)
        if v > best:
            best, hit = v, c
    return best, hit


def load_corpus(corpus_dir: str) -> list[str]:
    """加载目录下所有 .txt, 按句拆开作为比对语料."""
    from .segmenter import split_text_to_sentences

    corpus: list[str] = []
    if not os.path.isdir(corpus_dir):
        return corpus
    for name in sorted(os.listdir(corpus_dir)):
        if not name.lower().endswith(('.txt', '.md')):
            continue
        path = os.path.join(corpus_dir, name)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        corpus.extend(split_text_to_sentences(text))
    return [s for s in corpus if s.strip()]


def sentence_stats(sent: str, corpus: list[str], threshold: int = 10) -> dict:
    """单句统计 (strict=标点计入 / loose=忽略标点)."""
    run, hit = max_run_against_corpus(sent, corpus)
    run_loose, _ = max_run_against_corpus(sent, corpus, loose=True)
    return {
        'sentence': sent,
        'max_run': run,
        'max_run_loose': run_loose,
        'threshold': threshold,
        'over': run >= threshold,
        'over_loose': run_loose >= threshold,
        'hit': hit,
    }


def report(text: str, corpus: list[str], threshold: int = 10) -> dict:
    """全篇统计: 超阈句数 / 平均最长重合 / 最危险 TOP5 句."""
    from .segmenter import split_text_to_sentences

    sents = [s for s in split_text_to_sentences(text) if s.strip()]
    stats = [sentence_stats(s, corpus, threshold) for s in sents]
    over = [s for s in stats if s['over']]
    avg = sum(s['max_run'] for s in stats) / len(stats) if stats else 0.0
    avg_loose = sum(s['max_run_loose'] for s in stats) / len(stats) if stats else 0.0
    top5 = sorted(stats, key=lambda s: -s['max_run'])[:5]
    return {
        'sentences': len(stats),
        'over_threshold': len(over),
        'avg_max_run': round(avg, 2),
        'max_run': max((s['max_run'] for s in stats), default=0),
        'over_threshold_loose': sum(1 for s in stats if s['over_loose']),
        'avg_max_run_loose': round(avg_loose, 2),
        'max_run_loose': max((s['max_run_loose'] for s in stats), default=0),
        'top5': top5,
        'details': stats,
    }


def format_report_md(before: dict, after: dict | None, corpus_size: int,
                     threshold: int) -> str:
    """把 report() 结果渲染成 markdown (前后对比)."""
    lines = ['# 评估报告', '']
    lines.append(f'- 比对语料: {corpus_size} 句')
    lines.append(f'- 重合阈值: 最长连续公共子串 ≥ {threshold} 字符视为未达标')
    lines.append('- 口径: **含标点**为主指标 (PLAN §8); 忽略标点为参考 (模拟查重后台)')
    lines.append('')

    def _summary(r: dict, label: str):
        return [
            f'### {label}',
            f'- 句数: {r["sentences"]}',
            f'- 超阈句数 (含标点): **{r["over_threshold"]}**  |  忽略标点: {r["over_threshold_loose"]}',
            f'- 平均最长重合 (含标点): {r["avg_max_run"]} 字符  |  忽略标点: {r["avg_max_run_loose"]}',
            f'- 全篇最长重合 (含标点): {r["max_run"]} 字符  |  忽略标点: {r["max_run_loose"]}',
            '',
        ]

    if after is None:
        lines += _summary(before, '当前状态')
        lines.append('## 最危险 TOP5 句')
        lines.append('')
        for i, s in enumerate(before['top5'], 1):
            flag = '⚠️' if s['over'] else '✅'
            lines.append(f'{i}. {flag} 重合{s["max_run"]}字(忽略标点{s.get("max_run_loose", "-")}字) | {s["sentence"]}')
            if s['hit']:
                lines.append(f'   - 命中语料: {s["hit"]}')
        return '\n'.join(lines)

    lines += ['## 前后对比', '',
              '| 指标 | 改写前 | 改写后 |',
              '|---|---|---|',
              f'| 超阈句数 (含标点) | {before["over_threshold"]} | {after["over_threshold"]} |',
              f'| 超阈句数 (忽略标点) | {before["over_threshold_loose"]} | {after["over_threshold_loose"]} |',
              f'| 平均最长重合 (含标点) | {before["avg_max_run"]} | {after["avg_max_run"]} |',
              f'| 平均最长重合 (忽略标点) | {before["avg_max_run_loose"]} | {after["avg_max_run_loose"]} |',
              f'| 全篇最长重合 (含标点) | {before["max_run"]} | {after["max_run"]} |',
              f'| 全篇最长重合 (忽略标点) | {before["max_run_loose"]} | {after["max_run_loose"]} |',
              '']
    if before['over_threshold']:
        drop = 1 - after['over_threshold'] / before['over_threshold']
        lines.append(f'超阈句数下降 (含标点): **{drop:.0%}**')
    lines.append('')
    lines.append('## 改写后最危险 TOP5 句')
    lines.append('')
    for i, s in enumerate(after['top5'], 1):
        flag = '⚠️' if s['over'] else '✅'
        lines.append(f'{i}. {flag} 重合{s["max_run"]}字(忽略标点{s.get("max_run_loose", "-")}字) | {s["sentence"]}')
        if s['hit']:
            lines.append(f'   - 命中语料: {s["hit"]}')
    return '\n'.join(lines)
