# -*- coding: utf-8 -*-
"""Web 服务层: 包装 rewriter 包. 本模块不含任何 HTTP 类型.

职责:
  - 模型预热 (后台线程, 一次加载常驻)
  - evaluate / rewrite 两个重型任务, 串行执行 (HanLP 模型非线程安全)
  - 类型化错误 (ServiceError) 与用户友好消息
"""
import logging
import os
import threading
import time
from dataclasses import dataclass, field

from rewriter import overlap
from rewriter.config import load_config, resolve_path
from rewriter.pipeline import Rewriter

log = logging.getLogger('washing.web.service')

KNOWN_OPS = ('split', 'shift', 'attrib', 'connector', 'voice', 'merge', 'synonym', 'generative', 'llm')


class ServiceError(Exception):
    """类型化错误: 携带机器可读 code 与用户友好 message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ModelState:
    ready: bool = False
    failed: bool = False
    message: str = '正在加载 HanLP 模型…'
    started_at: float = field(default_factory=time.time)


class RewriteService:
    """rewriter 包的服务门面."""

    def __init__(self):
        self._job_lock = threading.Lock()          # 重型任务串行
        self._state = ModelState()
        self._warmup = threading.Thread(target=self._warmup_model,
                                        name='hanlp-warmup', daemon=True)
        self._warmup.start()

    # ---------- 模型预热 ----------

    def _warmup_model(self):
        try:
            from rewriter.parser import Parser
            cfg = load_config()
            parser = Parser(tasks=cfg['parser'].get('tasks'),
                            model=cfg['parser'].get('model'))
            parser.parse_one('模型预热。')
            self._state.ready = True
            self._state.message = '模型就绪'
            log.info('HanLP 模型预热完成 (%.1fs)', time.time() - self._state.started_at)
        except Exception as exc:  # noqa: BLE001 - 预热失败要在 UI 上如实暴露
            self._state.failed = True
            self._state.message = f'模型加载失败: {exc}'
            log.exception('HanLP 模型预热失败')

    def status(self) -> dict:
        cfg = load_config()
        return {
            'model_ready': self._state.ready,
            'model_failed': self._state.failed,
            'message': self._state.message,
            'busy': self._job_lock.locked(),
            'defaults': {
                'rounds': cfg['rewrite']['rounds'],
                'seed': cfg['rewrite']['seed'],
                'max_run': cfg['overlap']['max_run_threshold'],
                'ops': cfg['rewrite']['ops_enabled']
                       + (['llm'] if cfg.get('llm', {}).get('enabled') else []),
                'all_ops': list(KNOWN_OPS),
                'corpus_dir': cfg['overlap']['corpus_dir'],
                'whitelist': cfg['protect']['whitelist'],
            },
        }

    # ---------- 配置组装 ----------

    def _build_config(self, params: dict) -> tuple[dict, str]:
        """把 Web 参数映射为 rewriter 配置; 返回 (cfg, corpus_dir)."""
        overrides: dict = {}
        if 'rounds' in params:
            overrides.setdefault('rewrite', {})['rounds'] = params['rounds']
        if 'seed' in params:
            overrides.setdefault('rewrite', {})['seed'] = params['seed']
        if 'ops' in params:
            ops = [o for o in params['ops'] if o in KNOWN_OPS]
            overrides.setdefault('rewrite', {})['ops_enabled'] = ops
            overrides['rewrite']['ops_disabled'] = []
            # llm 走独立开关(cfg.llm.enabled), 不读 ops_enabled, 这里显式同步
            overrides['llm'] = {'enabled': 'llm' in ops}
        if 'whitelist' in params:
            overrides.setdefault('protect', {})['whitelist'] = params['whitelist']
        if 'corpus_dir' in params:
            overrides.setdefault('overlap', {})['corpus_dir'] = params['corpus_dir']
        if 'max_run' in params:
            overrides.setdefault('overlap', {})['max_run_threshold'] = params['max_run']

        cfg = load_config(overrides=overrides)

        wl = resolve_path(cfg['protect']['whitelist'])
        if not os.path.isfile(wl):
            raise ServiceError('whitelist_not_found',
                               f'白名单文件不存在: {cfg["protect"]["whitelist"]}')
        corpus_dir = resolve_path(cfg['overlap']['corpus_dir'])
        if not os.path.isdir(corpus_dir):
            raise ServiceError('corpus_not_found',
                               f'比对语料目录不存在: {cfg["overlap"]["corpus_dir"]}')
        return cfg, corpus_dir

    # ---------- 两个重型任务 ----------

    def evaluate(self, text: str, params: dict) -> dict:
        self._require_ready()
        cfg, _ = self._build_config(params)
        with self._job_lock:
            rw = Rewriter(cfg)
            rep = rw.dry_run(text)
        return {
            'report': _report_payload(rep),
            'corpus_size': len(rw.corpus),
        }

    def rewrite(self, text: str, params: dict) -> dict:
        self._require_ready()
        cfg, _ = self._build_config(params)
        with self._job_lock:
            rw = Rewriter(cfg)
            result = rw.run(text)
        threshold = rw.max_run_threshold
        report_md = overlap.format_report_md(
            result.report_before, result.report_after,
            result.corpus_size, threshold)
        changed = [r for r in result.records if r.changed]
        return {
            'text': result.text,
            'rounds_run': result.rounds_run,
            'corpus_size': result.corpus_size,
            'threshold': threshold,
            'summary': {
                'sentences': len(result.records),
                'changed': len(changed),
                'frozen': sum(1 for r in result.records if r.frozen),
                'over_before': result.report_before['over_threshold'],
                'over_after': result.report_after['over_threshold'],
                'over_before_loose': result.report_before['over_threshold_loose'],
                'over_after_loose': result.report_after['over_threshold_loose'],
                'avg_before': result.report_before['avg_max_run'],
                'avg_after': result.report_after['avg_max_run'],
                'avg_before_loose': result.report_before['avg_max_run_loose'],
                'avg_after_loose': result.report_after['avg_max_run_loose'],
                'avg_fidelity': round(
                    sum(r.fidelity for r in changed) / len(changed), 4) if changed else 1.0,
            },
            'sentences': [
                {
                    'orig': r.orig, 'final': r.final, 'changed': r.changed,
                    'ops': r.ops, 'novelty': r.novelty, 'fidelity': r.fidelity,
                    'fluency': r.fluency, 'total': r.total,
                    'max_run_before': r.max_run_before,
                    'max_run_after': r.max_run_after,
                    'frozen': r.frozen, 'frozen_reason': r.frozen_reason,
                } for r in result.records
            ],
            'artifacts': {
                'report_md': report_md,
            },
        }

    def _require_ready(self):
        if self._state.failed:
            raise ServiceError('model_failed', self._state.message)
        if not self._state.ready:
            raise ServiceError('model_loading', '模型仍在加载中, 请稍候再试')


def _report_payload(rep: dict) -> dict:
    """report() 结果中挑出前端需要的字段 (details 里的 hit 不传, 省流量)."""
    return {
        'sentences': rep['sentences'],
        'over_threshold': rep['over_threshold'],
        'over_threshold_loose': rep['over_threshold_loose'],
        'avg_max_run': rep['avg_max_run'],
        'avg_max_run_loose': rep['avg_max_run_loose'],
        'max_run': rep['max_run'],
        'max_run_loose': rep['max_run_loose'],
        'top5': [
            {
                'sentence': s['sentence'], 'max_run': s['max_run'],
                'max_run_loose': s.get('max_run_loose', 0),
                'over': s['over'], 'hit': s['hit'],
            } for s in rep['top5']
        ],
    }
