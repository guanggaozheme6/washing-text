# -*- coding: utf-8 -*-
"""配置加载: config.yaml + 代码默认值合并."""
import copy
import os

import yaml

DEFAULTS = {
    'parser': {
        'tasks': ['tok', 'pos', 'dep', 'srl', 'ner'],
        'model': 'OPEN_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH',
        'cache': True,
    },
    'rewrite': {
        'rounds': 2,
        'candidates_per_sentence': 8,
        'max_ops_per_candidate': 3,
        'ops_enabled': ['split', 'shift', 'attrib', 'connector', 'voice', 'merge'],
        'ops_disabled': ['synonym'],
        'seed': 42,
    },
    'scorer': {
        'weights': {'novelty': 0.45, 'fidelity': 0.30, 'fluency': 0.25},
        'min_fidelity': 0.65,
        'length_ratio': [0.6, 1.8],
    },
    'overlap': {
        'max_run_threshold': 10,
        'corpus_dir': 'data/corpus',
    },
    'protect': {
        'whitelist': 'data/whitelist.txt',
        'keep_quotes': True,
        'keep_numbers': True,
        'keep_ner': True,
    },
    'generative': {
        'enabled': False,
        'backend': 'simbert',
    },
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | None = None, overrides: dict | None = None) -> dict:
    """加载 config.yaml, 缺省项用内置默认补齐."""
    cfg = copy.deepcopy(DEFAULTS)
    if path is None:
        path = os.path.join(PROJECT_ROOT, 'config.yaml')
    if path and os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    return cfg


def resolve_path(path: str) -> str:
    """相对路径按项目根目录解析."""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)
