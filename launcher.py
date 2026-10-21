# -*- coding: utf-8 -*-
"""桌面启动器: 无控制台启动 Web 工作台, 并自动打开浏览器.

为什么不让快捷方式直接指向 pythonw.exe web/app.py:
  pythonw 下 sys.stdout / sys.stderr 是 None, HanLP 打进度条时会抛
  "'NoneType' object has no attribute 'write'", 模型直接加载失败;
  所以这里先接管输出, 把日志写到 %APPDATA%\\WashingText\\logs\\web.log,
  再导入应用.

端口策略:
  8777 被本应用(同版本)占着  → 认为已经在跑, 只开浏览器;
  8777 被别的程序/旧版本占着 → 依次试 8778..8788, 找到空位再启动,
                                绝不把浏览器指向别人的服务.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ID = 'washing-text'
APP_VERSION = '1.0.1'          # 必须与 web/app.py 的 APP_VERSION 一致
BASE_PORT = int(os.environ.get('WASHING_PORT', '8777'))
PORT_TRIES = 12
TITLE = '文本改写降重工作台'


def _data_dir() -> str:
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'WashingText')
    os.makedirs(path, exist_ok=True)
    return path


def _alert(message: str) -> None:
    """没有控制台时只能弹窗, 否则用户看到的就是"双击没反应"."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x40)
    except Exception:  # noqa: BLE001 - 弹窗失败就算了, 不能盖住真正的错误
        pass


def port_open(port: int, timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def probe_app(port: int) -> dict | None:
    """问一下端口上跑的是不是本应用; 是就返回 health 信息, 否则 None."""
    try:
        url = f'http://127.0.0.1:{port}/api/health'
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception:  # noqa: BLE001 - 连不上/不是 JSON 都算"不是我们"
        return None
    return data if isinstance(data, dict) and data.get('app') == APP_ID else None


def pick_port(start: int) -> int | None:
    """返回可用端口; 全被占则 None."""
    for port in range(start, start + PORT_TRIES):
        if not port_open(port):
            return port
    return None


def _open_when_ready(port: int, stop: threading.Event) -> None:
    for _ in range(720):            # 最多等 180 秒 (首次要加载模型)
        if stop.is_set():
            return
        if port_open(port):
            webbrowser.open(f'http://127.0.0.1:{port}/')
            return
        time.sleep(0.25)


def main() -> int:
    # 装到 Program Files 后目录只读: 不写 .pyc 就不会反复撞权限失败;
    # 同时屏蔽用户级 site-packages, 避免机器上别的 Python 包串进来.
    sys.dont_write_bytecode = True
    os.environ.setdefault('PYTHONNOUSERSITE', '1')

    # 安装包把 HanLP 模型放在程序目录 models/ 下(与 app/ 同级), 跟程序一起卸载;
    # 开发环境没有这个目录, 不动 HANLP_HOME, 继续用 %APPDATA%\hanlp.
    models = os.path.join(os.path.dirname(APP_DIR), 'models')
    if os.path.isdir(models):
        os.environ.setdefault('HANLP_HOME', models)

    # 端口上已经有本应用(同版本)在跑: 直接开页面, 不重复起进程
    running = probe_app(BASE_PORT) if port_open(BASE_PORT) else None
    if running and running.get('version') == APP_VERSION:
        webbrowser.open(f'http://127.0.0.1:{BASE_PORT}/')
        return 0

    port = BASE_PORT
    if port_open(port):
        # 被别的程序或旧版本占着, 换端口启动, 别让浏览器开到别人家去
        spare = pick_port(BASE_PORT + 1)
        if spare is None:
            _alert(f'{BASE_PORT}-{BASE_PORT + PORT_TRIES - 1} 端口都被占用, 无法启动。\n'
                   f'请关掉占用端口的程序后重试。')
            return 1
        port = spare

    logs = os.path.join(_data_dir(), 'logs')
    os.makedirs(logs, exist_ok=True)
    log_path = os.path.join(logs, 'web.log')
    # line_buffering: 日志实时落盘, 用户排查问题时不会看到半截
    stream = open(log_path, 'a', encoding='utf-8', buffering=1)
    sys.stdout = stream
    sys.stderr = stream

    stop = threading.Event()
    threading.Thread(target=_open_when_ready, args=(port, stop), daemon=True).start()

    os.chdir(APP_DIR)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    os.environ.setdefault('WASHING_PORT', str(port))

    try:
        from web.app import app
        app.run(host='127.0.0.1', port=port, threaded=True, debug=False)
    except Exception as exc:  # noqa: BLE001 - 启动失败必须让用户看见
        import traceback
        traceback.print_exc()
        stream.write(f'\n[启动失败] {exc}\n')
        stream.flush()
        _alert(f'工作台启动失败: {exc}\n\n详细日志:\n{log_path}')
        return 1
    finally:
        stop.set()
    return 0


if __name__ == '__main__':
    sys.exit(main())
