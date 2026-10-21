# -*- coding: utf-8 -*-
"""S9 整句生成式重写 —— 可选兜底, 默认关闭.

支持 backend:
  simbert        —— 需要本地 SimBERT/RoFormer 模型 (需自行准备)
  llm            —— 通过环境变量提供 API (OPENAI_API_KEY / OPENAI_BASE_URL / MODEL)
  backtranslate  —— 中→英→中 回译 (需外部 API, 失真风险高)

产出必须过 verifier 校验, 校验不过一律丢弃. 未配置时 match()=False.
"""
import json
import os
import random
import urllib.request
from typing import Optional

from .base import Operator, SentenceCtx


class GenerativeOperator(Operator):
    name = 'generative'
    desc = '生成式兜底: SimBERT / LLM / 回译 整句重写'

    def __init__(self, backend: str = 'simbert', enabled: bool = False):
        self.backend = backend
        self.enabled = enabled
        self._simbert = None

    # ---------- 各后端 ----------

    def _gen_llm(self, text: str) -> list[str]:
        api_key = os.environ.get('OPENAI_API_KEY')
        base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
        model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
        if not api_key:
            return []
        prompt = ('把下面这句话换一种句式重写，保持原意完全不变，'
                  '只做句法结构变换（如主动被动、状位移位、拆分合并），'
                  '不要增删信息。只输出改写结果，不要任何解释：\n' + text)
        body = json.dumps({
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.8,
            'n': 3,
        }).encode('utf-8')
        req = urllib.request.Request(
            base.rstrip('/') + '/chat/completions', data=body,
            headers={'Content-Type': 'application/json',
                     'Authorization': f'Bearer {api_key}'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return [c['message']['content'].strip() for c in data.get('choices', [])]
        except Exception:
            return []

    def _gen_simbert(self, text: str) -> list[str]:
        if self._simbert is None:
            try:
                from simbert_infer import SimBertInfer  # type: ignore
                self._simbert = SimBertInfer()
            except Exception:
                return []
        try:
            return list(self._simbert.generate(text, n=3))
        except Exception:
            return []

    def _gen_backtranslate(self, text: str) -> list[str]:
        return []  # 未配置外部 API, 占位

    # ---------- Operator 接口 ----------

    def match(self, ctx: SentenceCtx) -> bool:
        return self.enabled

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        if not self.enabled:
            return None
        if self.backend == 'llm':
            outs = self._gen_llm(ctx.text)
        elif self.backend == 'simbert':
            outs = self._gen_simbert(ctx.text)
        elif self.backend == 'backtranslate':
            outs = self._gen_backtranslate(ctx.text)
        else:
            outs = []
        outs = [o for o in outs if o and o != ctx.text]
        if not outs:
            return None
        return rng.choice(outs)
