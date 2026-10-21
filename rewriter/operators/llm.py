# -*- coding: utf-8 -*-
"""LLM 整句重写算子 —— 基于 DeepSeek 的生成式兜底.

定位: 规则算子 (split/shift/attrib/connector/voice) 只改句法骨架, 覆盖面有限;
本算子对整句做"语义不变、句法重构"的重写, 用于补齐规则算子打不动的句子.

约定:
  apply() 只返回单个字符串 (整句, 含句末标点), 不返回 list —— list 是 split 的约定.
  任何异常 (网络/超时/JSON/key 缺失/输出不合规) 一律返回 None, 绝不让管线崩.

安全:
  key 只从环境变量 WASHING_DEEPSEEK_KEY 或本地文件读取, 源码内不含明文 key.
"""
import json
import os
import random
import re
import urllib.request
from typing import Optional

from .base import Operator, SentenceCtx

ENDPOINT = 'https://api.deepseek.com/chat/completions'
KEY_ENV = 'WASHING_DEEPSEEK_KEY'
# 分发场景可用 WASHING_DEEPSEEK_KEY_FILE 指定 key 文件位置
KEY_FILE = (os.environ.get('WASHING_DEEPSEEK_KEY_FILE')
            or os.path.join(os.path.expanduser('~'), 'Desktop', 'WASHING.txt'))

SYSTEM_PROMPT = (
    '你是中文论文改写助手。你的任务是在完全保持原意的前提下，改变句子的句法结构，'
    '让表达与原句明显不同。\n'
    '必须遵守：\n'
    '1. 只改动句法结构，可采用的手段包括：长句拆分、主被动转换、状语位移、定语后置、'
    '语序调整、成分合并。\n'
    '2. 专业术语、概念名称、数据、年份、百分比、人名、机构名必须原样保留，不得替换、'
    '不得增删。\n'
    '3. 不得增删任何事实、观点、因果关系和限定条件，不得改变论述的肯定或否定语气，'
    '不得强化或弱化论断，不得把原文的推测、评价或个别观点升级为普遍共识。\n'
    '4. 不得使用"首先/其次/然后/总之/综上所述"这类衔接套话。\n'
    '5. 只输出改写后的这一个句子，不要解释、不要加引号、不要输出多句、不要换行。\n'
    '6. 改写结果与原文的用词应有明显差异，但语义必须完全等价。'
)

# 拒答痕迹. 只匹配成句的拒答短语: "无法""语言模型"在学术句里是正常用词
# (如"该方法无法处理长文本""预训练语言模型"), 单独出现不能判为拒答.
REFUSAL_MARKS = (
    '抱歉', '对不起', '作为AI', '作为 AI', '作为一个AI', '作为一个 AI',
    '作为一个语言模型', '作为语言模型', '我是一个AI', '我是一个 AI',
    '我无法', '无法提供', '无法完成', '无法回答', '无法改写', '无法协助',
    '无法为您', '不能提供', '建议您',
)

# 模型偶尔会加的中文标签前缀, 如 "改写：xxx"
_LABEL_RE = re.compile(r'^(?:改写后的句子|改写结果|改写后|改写|重写结果|重写|结果|句子)\s*[:：]\s*')

# 成对引号, 模型有时会把整句包起来
_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’'), ('「', '」'), ('『', '』'))

_END_PUNCT = '。！？!?'
_BAD_END = '，、；：,;:'


class LLMOperator(Operator):
    name = 'llm'
    desc = '大模型整句重写 (DeepSeek): 保持原意, 重构句法'

    # 同一句最多真实调用几次 (管线每句会抽样多条候选, 不限制会重复烧 API)
    MAX_CALLS_PER_TEXT = 2

    def __init__(self, enabled: bool = True, model: str = 'deepseek-chat',
                 timeout: float = 30.0, max_fail_streak: int = 3,
                 key_file: str = KEY_FILE):
        self.enabled = enabled
        self.model = model
        self.timeout = timeout
        self.max_fail_streak = max(1, int(max_fail_streak))
        self.key_file = key_file
        self._key: Optional[str] = None
        self._key_loaded = False
        self._fail_streak = 0
        self._dead = False          # 熔断标志, 进程内生效
        self._calls: dict[str, int] = {}

    # ---------- key ----------

    def _get_key(self) -> str:
        if self._key_loaded:
            return self._key or ''
        self._key_loaded = True
        key = os.environ.get(KEY_ENV, '').strip()
        if not key:
            try:
                with open(self.key_file, encoding='utf-8') as f:
                    key = f.read().strip()
            except OSError:
                key = ''
        self._key = key or None
        return key

    # ---------- API ----------

    def _request(self, text: str) -> Optional[str]:
        key = self._get_key()
        if not key:
            return None
        body = json.dumps({
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': text},
            ],
            'temperature': 0.9,
            'max_tokens': len(text) * 3 + 100,
            'stream': False,
        }, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + key})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']

    # ---------- 输出清洗与校验 ----------

    @staticmethod
    def _clean(raw: str) -> str:
        """取首个非空行, 去标签/引号, 补句末标点; 明显不合规返回空串."""
        lines = [ln.strip() for ln in (raw or '').splitlines() if ln.strip()]
        if not lines:
            return ''
        s = lines[0]
        s = _LABEL_RE.sub('', s).strip()
        for lo, hi in _QUOTE_PAIRS:
            if len(s) >= 2 and s.startswith(lo) and s.endswith(hi):
                s = s[len(lo):-len(hi)].strip()
                break
        if not s:
            return ''
        if s[-1] == '.':
            s = s[:-1] + '。'
        elif s[-1] == '!':
            s = s[:-1] + '！'
        elif s[-1] == '?':
            s = s[:-1] + '？'
        if s[-1] in _BAD_END:
            return ''
        if s[-1] not in '。！？':
            s += '。'
        return s

    @staticmethod
    def _valid(orig: str, out: str) -> bool:
        if not out:
            return False
        if any(m in out for m in REFUSAL_MARKS):
            return False
        ratio = len(out) / max(1, len(orig))
        if ratio < 0.6 or ratio > 1.8:
            return False
        core = out.rstrip('。！？')
        if not core:
            return False
        # 只允许一个句子: 句中去掉句末标点后不应再有句末符号
        if any(p in core for p in '。！？'):
            return False
        # 与原句完全一致 (仅差标点) 视为没改
        if core == orig.strip().rstrip('。！？'):
            return False
        return True

    # ---------- Operator 接口 ----------

    def match(self, ctx: SentenceCtx) -> bool:
        if not self.enabled or self._dead:
            return False
        text = (ctx.text or '').strip()
        if len(text) < 12:
            return False
        if ctx.prot.frozen:
            return False
        return bool(ctx.parsed.main_verbs())

    def apply(self, ctx: SentenceCtx, rng: random.Random) -> Optional[str]:
        if not self.enabled or self._dead:
            return None
        text = (ctx.text or '').strip()
        if not text:
            return None
        n_called = self._calls.get(text, 0)
        if n_called >= self.MAX_CALLS_PER_TEXT:
            return None
        self._calls[text] = n_called + 1
        try:
            raw = self._request(text)
            out = self._clean(raw or '')
            if not self._valid(text, out):
                self._on_fail()
                return None
        except Exception:
            # 网络/超时/解析/鉴权等全部吞掉, 只做熔断计数
            self._on_fail()
            return None
        self._fail_streak = 0
        return out

    def _on_fail(self) -> None:
        self._fail_streak += 1
        if self._fail_streak >= self.max_fail_streak:
            self._dead = True
