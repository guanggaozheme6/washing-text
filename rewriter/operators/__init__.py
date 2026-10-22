# -*- coding: utf-8 -*-
"""算子注册表.

ops_enabled 顺序即建议实施顺序: split → shift → attrib → connector → voice → merge
"""
from .base import Operator, SentenceCtx
from .split import SplitOperator
from .shift import ShiftOperator
from .attrib import AttribOperator
from .connector import ConnectorOperator
from .voice import VoiceOperator
from .synonym import SynonymOperator
from ..synonyms import load_synonym_table
from .generative import GenerativeOperator
from .llm import LLMOperator
from .merge import try_merge

__all__ = [
    'Operator', 'SentenceCtx', 'SplitOperator', 'ShiftOperator', 'AttribOperator',
    'ConnectorOperator', 'VoiceOperator', 'SynonymOperator', 'GenerativeOperator',
    'LLMOperator', 'load_synonym_table', 'try_merge', 'build_operators',
]


def build_operators(cfg: dict, whitelist: list[str] | None = None) -> dict[str, Operator]:
    """按配置构造算子实例 (不含 merge, merge 在 pipeline 层调用)."""
    rw = cfg.get('rewrite', {})
    enabled = set(rw.get('ops_enabled', []))
    disabled = set(rw.get('ops_disabled', []))
    ops: dict[str, Operator] = {}
    if 'split' in enabled and 'split' not in disabled:
        ops['split'] = SplitOperator()
    if 'shift' in enabled and 'shift' not in disabled:
        ops['shift'] = ShiftOperator()
    if 'attrib' in enabled and 'attrib' not in disabled:
        ops['attrib'] = AttribOperator()
    if 'connector' in enabled and 'connector' not in disabled:
        ops['connector'] = ConnectorOperator()
    if 'voice' in enabled and 'voice' not in disabled:
        ops['voice'] = VoiceOperator()
    if 'synonym' in enabled and 'synonym' not in disabled:
        ops['synonym'] = SynonymOperator(whitelist=whitelist or [])
    gen_cfg = cfg.get('generative', {})
    if gen_cfg.get('enabled'):
        ops['generative'] = GenerativeOperator(
            backend=gen_cfg.get('backend', 'simbert'), enabled=True)
    # LLM 算子: 独立开关 (llm.enabled), 默认关闭, 需显式开启并配置 key
    llm_cfg = cfg.get('llm', {})
    if llm_cfg.get('enabled') and 'llm' not in disabled:
        ops['llm'] = LLMOperator(
            enabled=True,
            provider=llm_cfg.get('provider', 'deepseek'),
            model=llm_cfg.get('model', 'deepseek-chat'),
            timeout=llm_cfg.get('timeout', 30),
            max_fail_streak=llm_cfg.get('max_fail_streak', 3))
    return ops
