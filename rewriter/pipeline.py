# -*- coding: utf-8 -*-
"""管线编排: [1]预处理 → [2]分析 → [3]保护区 → [4]算子 → [5]打分 → [6]组装 → [7]报告.

内层循环在 [4]→[5] (单句候选池选优), 外层全篇循环控制轮次与早停.
"""
import json
import os
import random
from dataclasses import dataclass, field

from . import overlap, scorer
from .config import resolve_path
from .operators import SentenceCtx, build_operators, try_merge
from .parser import Parser
from .protect import load_whitelist, mark_protection
from .segmenter import segment, unwrap_hard_breaks
from .verifier import lexical_containment
from .verifier import fidelity as calc_fidelity


# 子句收尾的终结标点 (校验前先剥掉, 只检查其内侧字符)
_TERMINALS = '。！？!?…；;'
# 不允许出现在子句结尾的悬垂标点 / 连字符
_DANGLING = '，、；：,;:—–-_'


def _clauses_intact(sents: list[str]) -> bool:
    """子句完整性兜底: 多子句候选(即 split 产物)的每个子句必须能独立成句.

    取消 split 保义度后门后, 用它代替"降门槛"来保住拆分覆盖率:
      - 每个子句(含终结标点)不短于 7 字符, 避免拆出"它。"这类残片;
      - 剥掉终结标点后, 内侧末字不能是逗号/顿号/冒号/连字符等悬垂符号,
        避免拆出半截成分(如"……包括：")后又被 ensure_period 补成句号.
    """
    for s in sents:
        body = s.strip()
        if len(body) < 7:
            return False
        core = body.rstrip(_TERMINALS)
        if not core or core[-1] in _DANGLING:
            return False
    return True


@dataclass
class SentenceRecord:
    orig: str
    final: str
    ops: list[str] = field(default_factory=list)
    novelty: float = 0.0
    fidelity: float = 1.0
    fidelity_mode: str = 'struct'   # struct=依存/SRL 结构包含率; lexical=实词覆盖率(LLM 句)
    fluency: float = 1.0
    total: float = 0.0
    max_run_before: int = 0
    max_run_after: int = 0
    frozen: bool = False
    frozen_reason: str = ''
    rounds_used: int = 0

    @property
    def changed(self) -> bool:
        return self.final != self.orig


@dataclass
class RewriteResult:
    text: str
    records: list[SentenceRecord] = field(default_factory=list)
    report_before: dict = field(default_factory=dict)
    report_after: dict = field(default_factory=dict)
    corpus_size: int = 0
    rounds_run: int = 0


class Rewriter:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        rw = cfg['rewrite']
        self.rng = random.Random(rw.get('seed', 42))
        self.parser = Parser(tasks=cfg['parser'].get('tasks'),
                             model=cfg['parser'].get('model'),
                             cache=cfg['parser'].get('cache', True))
        protect_cfg = cfg['protect']
        self.whitelist = load_whitelist(resolve_path(protect_cfg['whitelist']))
        self.ops = build_operators(cfg, whitelist=self.whitelist)
        self.max_run_threshold = cfg['overlap'].get('max_run_threshold', 10)
        self.corpus: list[str] = []

    # ---------- 构建上下文 ----------

    def _ctx(self, text: str, idx: int) -> SentenceCtx:
        parsed = self.parser.parse_one(text)
        prot = mark_protection(
            parsed, self.whitelist,
            keep_quotes=self.cfg['protect'].get('keep_quotes', True),
            keep_numbers=self.cfg['protect'].get('keep_numbers', True),
            keep_ner=self.cfg['protect'].get('keep_ner', True))
        return SentenceCtx(text=text, parsed=parsed, prot=prot, idx=idx)

    def _load_corpus(self, text: str) -> list[str]:
        corpus_dir = resolve_path(self.cfg['overlap'].get('corpus_dir', 'data/corpus'))
        corpus = overlap.load_corpus(corpus_dir)
        # 原文自身也是比对源 (novelty 对照)
        from .segmenter import split_text_to_sentences
        corpus += [s for s in split_text_to_sentences(text) if s.strip()]
        return corpus

    # ---------- 候选生成 (§6.1) ----------

    def _run_ops_on(self, ctx: SentenceCtx, chosen) -> tuple[list[str], list[str]] | None:
        """顺序应用算子. 拆分后对每个子句接力应用剩余算子.

        返回 (句子列表, 生效算子名).
        """
        cur = ctx
        used: list[str] = []
        for oi, op in enumerate(chosen):
            r = op.apply(cur, self.rng)
            if r is None:
                continue
            used.append(op.name)
            if isinstance(r, list):
                # 拆分: 对子句接力 (每子句最多再接 1 个算子, 控制语义漂移)
                rest = chosen[oi + 1:]
                out_sents = []
                for sub in r:
                    sc = self._ctx(sub, ctx.idx)
                    for op2 in rest:
                        if not op2.match(sc):
                            continue
                        r2 = op2.apply(sc, self.rng)
                        if r2 and not isinstance(r2, list) and r2 != sub:
                            sub, sc = r2, self._ctx(r2, ctx.idx)
                            used.append(op2.name)
                            break
                    out_sents.append(sub)
                return out_sents, used
            if r != cur.text:
                cur = self._ctx(r, ctx.idx)
        if used and cur.text != ctx.text:
            return [cur.text], used
        return None

    def _candidates(self, ctx: SentenceCtx) -> list[tuple[list[str], list[str], bool]]:
        """返回 [(句子列表, 生效算子名, 是否 LLM 来源)].

        来源标记必须带出去: LLM 候选改动大, novelty 天然高 (0.85 上下), 若与规则
        候选同池粗排, 它会稳定挤进 coarse[:3], 却在精排被结构保义度 (fidelity) 刷掉 —
        既占了名额又交了白卷, 还连带挤掉本该入选的规则候选. 故由调用方分开排队.
        """
        n_cand = self.cfg['rewrite'].get('candidates_per_sentence', 8)
        max_ops = self.cfg['rewrite'].get('max_ops_per_candidate', 3)
        out: list[tuple[list[str], list[str], bool]] = []
        usable = [op for op in self.ops.values() if op.match(ctx)]
        if not usable:
            return out
        # LLM 算子独立出候选: 它一次调用就是一次完整重写, 混进随机抽样会
        # 让同一句反复请求 API (8 个候选里大半是无效调用), 也挤占规则候选名额.
        llm_op = self.ops.get('llm')
        if llm_op is not None and any(op is llm_op for op in usable):
            usable = [op for op in usable if op is not llm_op]
            # 温度 0.9 下每次措辞不同, 取两条能显著提高过阈值 (词汇保义) 的概率
            for _ in range(2):
                r = llm_op.apply(ctx, self.rng)
                if r and r != ctx.text:
                    out.append(([r], ['llm'], True))
            if not usable:
                return out
        for _ in range(n_cand):
            k = self.rng.choices([1, 2, max_ops], weights=[6, 3, 1])[0]
            k = min(k, len(usable))
            chosen = self.rng.sample(usable, k)
            res = self._run_ops_on(ctx, chosen)
            if res:
                out.append((res[0], res[1], False))
        return out

    # ---------- 单句选优 ----------

    def _best_for(self, ctx: SentenceCtx, cur_run: int):
        rw = self.cfg['rewrite']
        sc = self.cfg['scorer']
        weights = sc.get('weights', {})
        min_fid = sc.get('min_fidelity', 0.65)
        # LLM 候选的保义门槛 (词汇口径: 实词覆盖率), 与规则候选的 min_fid 互不影响
        min_lex = sc.get('min_lexical_containment', 0.55)
        ratio = tuple(sc.get('length_ratio', (0.6, 1.8)))
        cur_run_loose = overlap.max_run_against_corpus(ctx.text, self.corpus, loose=True)[0]

        cands = self._candidates(ctx)
        if not cands:
            return None

        # 粗排: 硬约束(文本级) + novelty + fluency. 规则 / LLM 分两池, 互不抢名次.
        coarse: list[tuple] = []
        coarse_llm: list[tuple] = []
        seen = set()
        for sents, used, is_llm in cands:
            text = ''.join(sents)
            if text in seen or text == ctx.text:
                continue
            seen.add(text)
            # 拆分候选先过子句完整性校验, 不完整直接丢 (替代原先的保义度降门槛)
            if len(sents) > 1 and not _clauses_intact(sents):
                continue
            ok, _why = scorer.hard_check(ctx.text, text, ctx.parsed, None,
                                         ctx.prot, ratio)
            if not ok:
                continue
            nov = scorer.novelty_of(text, self.corpus, ctx.text)
            flu = scorer.fluency_of(text, ctx.text, *ratio)
            item = (0.6 * nov + 0.4 * flu, text, sents, used, nov, flu, is_llm)
            (coarse_llm if is_llm else coarse).append(item)
        if not coarse and not coarse_llm:
            return None
        coarse.sort(key=lambda x: -x[0])
        coarse_llm.sort(key=lambda x: -x[0])
        # 精排池 = 规则前 3 + LLM 最好的 1 条 (LLM 单占名额, 不挤占规则名额;
        # 没有规则候选时它就独占精排池).
        top = coarse[:3] + coarse_llm[:1]

        # 精排: 解析候选 → 保义度 + 完整硬约束
        texts = [x[1] for x in top]
        parsed_list = self.parser.parse_batch(texts)
        best = None
        for (_, text, sents, used, nov, flu, is_llm), cand_parsed in zip(top, parsed_list):
            ok, _why = scorer.hard_check(ctx.text, text, ctx.parsed, cand_parsed,
                                         ctx.prot, ratio)
            if not ok:
                continue
            fid = calc_fidelity(ctx.parsed, cand_parsed)['fidelity']
            if is_llm:
                # 生成式改写的任务就是换句法, 用结构保义度卡它等于让它起跑即出局;
                # 改用词汇口径卡"信息有没有丢". 术语/数字/NER/否定词仍由 hard_check 统一把关.
                keep = lexical_containment(ctx.parsed, cand_parsed)
                if keep < min_lex:
                    continue
            else:
                # 规则候选门槛不变: 仍是 config 里的 min_fidelity (0.65)
                keep = fid
                if keep < min_fid:
                    continue
            run_after = max(overlap.max_run_against_corpus(s, self.corpus)[0]
                            for s in sents)
            run_loose_after = max(overlap.max_run_against_corpus(s, self.corpus, loose=True)[0]
                                  for s in sents)
            if run_after >= cur_run:
                continue  # 含标点口径没有改善, 不要
            if run_loose_after > cur_run_loose:
                continue  # 忽略标点口径变差, 不要
            total = scorer.total_score(nov, keep, flu, weights)
            cand = (total, nov, keep, flu, run_after, text, sents, used, is_llm)
            if best is None or cand > best:
                best = cand
        return best

    # ---------- 全篇主流程 ----------

    def run(self, text: str) -> RewriteResult:
        # 先合并 PDF/Word 复制带来的硬换行, 否则改前指标与分段口径不一致
        text = unwrap_hard_breaks(text)
        corpus = self._load_corpus(text)
        self.corpus = corpus
        # 段落分隔风格: 原稿有空行用空行, 否则单换行 (回填时保持一致)
        self._para_sep = '\n\n' if '\n\n' in text.replace('\r\n', '\n') else '\n'
        paras = segment(text)
        # 构建上下文 (含保护标记)
        para_ctxs: list[list[SentenceCtx]] = []
        flat: list[SentenceCtx] = []
        for pi, para in enumerate(paras):
            row = []
            for si, sent in enumerate(para):
                ctx = self._ctx(sent, len(flat))
                row.append(ctx)
                flat.append(ctx)
            para_ctxs.append(row)

        rep_before = overlap.report(text, corpus, self.max_run_threshold)
        records: dict[int, SentenceRecord] = {}
        for ctx in flat:
            run_now, _ = overlap.max_run_against_corpus(ctx.text, corpus)
            records[ctx.idx] = SentenceRecord(
                orig=ctx.text, final=ctx.text, max_run_before=run_now,
                max_run_after=run_now, frozen=ctx.prot.frozen,
                frozen_reason=ctx.prot.frozen_reason)

        rounds = self.cfg['rewrite'].get('rounds', 2)
        prev_metric = rep_before['avg_max_run'] * 0.5 + rep_before['avg_max_run_loose'] * 0.5
        rounds_run = 0

        for rnd in range(1, rounds + 1):
            rounds_run = rnd
            improved = 0
            for pi, row in enumerate(para_ctxs):
                i = 0
                while i < len(row):
                    ctx = row[i]
                    if ctx.prot.frozen:
                        i += 1
                        continue
                    cur_run, _ = overlap.max_run_against_corpus(ctx.text, corpus)
                    if cur_run < self.max_run_threshold:
                        i += 1  # 已达标, 冻结
                        continue
                    best = self._best_for(ctx, cur_run)
                    if best is None:
                        i += 1
                        continue
                    total, nov, fid, flu, run_after, new_text, sents, used, is_llm = best
                    rec = ctx.meta.get('rec') or records.get(ctx.idx)
                    # 替换 (拆分产生多句时插入); 记录回溯到原始句
                    new_ctxs = []
                    for k, s in enumerate(sents):
                        nc = self._ctx(s, ctx.idx + 10000 * rnd + k)
                        nc.meta['rec'] = rec
                        new_ctxs.append(nc)
                    row[i:i + 1] = new_ctxs
                    if rec is not None:
                        rec.final = ''.join(sents)
                        rec.ops = list(dict.fromkeys(rec.ops + used))
                        rec.novelty = round(nov, 4)
                        rec.fidelity = round(fid, 4)
                        rec.fidelity_mode = 'lexical' if is_llm else 'struct'
                        rec.fluency = round(flu, 4)
                        rec.total = round(total, 4)
                        rec.max_run_after = run_after
                        rec.rounds_used = rnd
                    improved += 1
                    i += len(new_ctxs)

            # 早停: 本轮重合度改善太小 (双口径均值, 比超阈句数更敏感)
            final_text = self._assemble(para_ctxs)
            rep_now = overlap.report(final_text, corpus, self.max_run_threshold)
            now_metric = rep_now['avg_max_run'] * 0.5 + rep_now['avg_max_run_loose'] * 0.5
            gain = (prev_metric - now_metric) / max(0.1, prev_metric)
            prev_metric = now_metric
            if gain < 0.05 or improved == 0:
                break

        # ---- 组装 (含 S6 合并) ----
        # 终态回填: 改写过的句子按记录聚合成最终文本 (拆分句拼接还原)
        final_parts: dict[int, list[str]] = {}
        for row in para_ctxs:
            for ctx in row:
                rec = ctx.meta.get('rec')
                if rec is not None:
                    final_parts.setdefault(id(rec), []).append(ctx.text)
        recs = [records[k] for k in sorted(records)]
        for rec in recs:
            parts = final_parts.get(id(rec))
            if parts:
                rec.final = ''.join(parts)

        final_text = self._assemble(para_ctxs, allow_merge=True)
        rep_after = overlap.report(final_text, corpus, self.max_run_threshold)

        return RewriteResult(
            text=final_text, records=recs,
            report_before=rep_before, report_after=rep_after,
            corpus_size=len(corpus), rounds_run=rounds_run)

    def _assemble(self, para_ctxs: list[list[SentenceCtx]],
                  allow_merge: bool = False) -> str:
        do_merge = allow_merge and 'merge' in self.cfg['rewrite'].get('ops_enabled', [])
        sep = getattr(self, '_para_sep', '\n\n')
        out_paras = []
        for row in para_ctxs:
            texts = [c.text for c in row]
            ctxs = list(row)
            if do_merge and len(texts) >= 2:
                merged_texts: list[str] = []
                merged_ctxs: list = []
                i = 0
                while i < len(texts):
                    if i + 1 < len(texts):
                        m = try_merge(texts[i], ctxs[i], texts[i + 1], ctxs[i + 1])
                        if m:
                            merged_texts.append(m)
                            merged_ctxs.append(None)
                            i += 2
                            continue
                    merged_texts.append(texts[i])
                    merged_ctxs.append(ctxs[i])
                    i += 1
                texts = merged_texts
            out_paras.append(texts)
        return sep.join(''.join(p) for p in out_paras) + '\n'

    # ---------- 输出 ----------

    def write_outputs(self, result: RewriteResult, input_path: str, out_dir: str) -> dict:
        os.makedirs(out_dir, exist_ok=True)
        name = os.path.splitext(os.path.basename(input_path))[0]

        txt_path = os.path.join(out_dir, f'{name}.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(result.text)

        json_path = os.path.join(out_dir, f'{name}.json')
        detail = {
            'input': os.path.abspath(input_path),
            'rounds_run': result.rounds_run,
            'corpus_size': result.corpus_size,
            'summary': {
                'sentences': len(result.records),
                'changed': sum(1 for r in result.records if r.changed),
                'frozen': sum(1 for r in result.records if r.frozen),
                'over_before': result.report_before['over_threshold'],
                'over_after': result.report_after['over_threshold'],
                'avg_fidelity': round(
                    sum(r.fidelity for r in result.records if r.changed)
                    / max(1, sum(1 for r in result.records if r.changed)), 4),
            },
            'sentences': [
                {
                    'orig': r.orig, 'final': r.final, 'changed': r.changed,
                    'ops': r.ops, 'novelty': r.novelty, 'fidelity': r.fidelity,
                    'fidelity_mode': r.fidelity_mode,
                    'fluency': r.fluency, 'total': r.total,
                    'max_run_before': r.max_run_before,
                    'max_run_after': r.max_run_after,
                    'frozen': r.frozen, 'frozen_reason': r.frozen_reason,
                    'rounds_used': r.rounds_used,
                } for r in result.records
            ],
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

        report_path = os.path.join(out_dir, 'report.md')
        md = overlap.format_report_md(result.report_before, result.report_after,
                                      result.corpus_size, self.max_run_threshold)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(md + '\n')
        return {'txt': txt_path, 'json': json_path, 'report': report_path}

    def dry_run(self, text: str) -> dict:
        text = unwrap_hard_breaks(text)
        corpus = self._load_corpus(text)
        self.corpus = corpus
        return overlap.report(text, corpus, self.max_run_threshold)
