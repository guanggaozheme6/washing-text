# -*- coding: utf-8 -*-
"""用户级设置: LLM 子算子的 API Key / 模型 / 开关.

为什么单独存一份, 而不是写在 config.yaml:
  config.yaml 跟着安装目录走, 装到 Program Files 之后普通用户没有写权限;
  API Key 又是"每台机器每个人不一样"的东西, 必须落在用户目录.

存放位置:
  Windows: %APPDATA%\\WashingText\\settings.json
  其他:    ~/.config/washing-text/settings.json

约定:
  - 纯标准库, 不引入第三方依赖;
  - 读带 mtime 缓存: 算子每句都会问一次 key, 不能每次都解析 JSON;
  - 落盘走"临时文件 + os.replace", 半路断电也不会留下坏 JSON;
  - 环境变量 WASHING_DEEPSEEK_KEY 优先级最高 (CI/临时覆盖用).
"""
import json
import os
import tempfile
import threading
from typing import Any

ENV_KEY = 'WASHING_DEEPSEEK_KEY'

DEFAULT_SETTINGS: dict[str, Any] = {
    'llm': {
        'enabled': True,
        'api_key': '',
        'provider': 'deepseek',   # deepseek | openai | claude
        'model': 'deepseek-chat',
        'timeout': 30,
    },
    'server': {
        # 所有页面关掉后自动退出, 把常驻的 HanLP 模型内存(约 1 GB)收回来
        'auto_stop': True,
    },
}

# 支持的服务商. 模型名不在白名单里硬卡 ——
# 各家中转/新模型层出不穷, 界面上给建议值(datalist), 允许手填.
PROVIDERS: dict[str, dict[str, Any]] = {
    'deepseek': {
        'label': 'DeepSeek',
        'models': ['deepseek-chat', 'deepseek-reasoner'],
    },
    'openai': {
        'label': 'OpenAI',
        'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-5-mini'],
    },
    'claude': {
        'label': 'Anthropic Claude',
        'models': ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-1'],
    },
}


def allowed_provider(name: str) -> bool:
    return name in PROVIDERS


def default_model(provider: str) -> str:
    info = PROVIDERS.get(provider) or PROVIDERS['deepseek']
    return info['models'][0]


def _settings_dir() -> str:
    appdata = os.environ.get('APPDATA')
    if appdata:
        return os.path.join(appdata, 'WashingText')
    return os.path.join(os.path.expanduser('~'), '.config', 'washing-text')


SETTINGS_DIR = _settings_dir()
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'settings.json')

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_mtime: float = -1.0


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_file() -> dict:
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load() -> dict:
    """读取设置 (带 mtime 缓存). 文件不存在时返回默认值."""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        mtime = -1.0
    with _lock:
        if _cache is not None and mtime == _cache_mtime:
            return _deep_merge(DEFAULT_SETTINGS, _cache)
        raw = _read_file()
        _cache, _cache_mtime = raw, mtime
        return _deep_merge(DEFAULT_SETTINGS, raw)


def save(patch: dict) -> dict:
    """把 patch 深合并进现有设置并落盘, 返回合并后的完整设置."""
    global _cache, _cache_mtime
    with _lock:
        merged = _deep_merge(_deep_merge(DEFAULT_SETTINGS, _read_file()), patch or {})
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=SETTINGS_DIR, prefix='.settings-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SETTINGS_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _cache, _cache_mtime = merged, os.path.getmtime(SETTINGS_FILE)
    return merged


def invalidate() -> None:
    """丢弃缓存, 下次 load() 重新读盘."""
    global _cache, _cache_mtime
    with _lock:
        _cache, _cache_mtime = None, -1.0


# ---------- API Key ----------

def key_source() -> str:
    """key 的来源: env / settings / none. 界面按它显示不同提示."""
    if os.environ.get(ENV_KEY, '').strip():
        return 'env'
    if str(load()['llm'].get('api_key', '')).strip():
        return 'settings'
    return 'none'


def get_api_key() -> str:
    """按优先级取 key: 环境变量 > 本地设置 > 空串."""
    env = os.environ.get(ENV_KEY, '').strip()
    if env:
        return env
    return str(load()['llm'].get('api_key', '')).strip()


def mask_key(key: str) -> str:
    """只露头尾, 供界面回显. 太短的 key 一律打码."""
    key = (key or '').strip()
    if not key:
        return ''
    if len(key) <= 10:
        return '*' * len(key)
    return f'{key[:4]}{"*" * (len(key) - 8)}{key[-4:]}'
