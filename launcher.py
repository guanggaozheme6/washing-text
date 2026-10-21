# -*- coding: utf-8 -*-
"""桌面启动器: 无控制台启动 Web 工作台, 并自动打开浏览器.

为什么不让快捷方式直接指向 pythonw.exe web/app.py:
  pythonw 下 sys.stdout / sys.stderr 是 None, HanLP 打进度条时会抛
  "'NoneType' object has no attribute 'write'"; 所以这里先接管输出,
  把日志写到 %APPDATA%\\WashingText\\logs\\web.log, 再导入应用.

行为:
  - 端口已在监听: 说明服务本来就在跑, 直接开浏览器, 不重复起进程;
  - 否则拉起 Flask, 后台线程等端口通了再开浏览器.
"""
import os
import socket
import sys
import threading
import time
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('WASHING_PORT', '8777'))
URL = f'http://127.0.0.1:{PORT}/'
TITLE = '文本改写降重工作台'


def _data_dir() -> str:
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'WashingText')
    os.makedirs(path, exist_ok=True)
    return path


def port_open(port: int, timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def _open_when_ready(stop: threading.Event) -> None:
    for _ in range(600):            # 最多等 150 秒 (首次要下/载模型)
        if stop.is_set():
            return
        if port_open(PORT):
            webbrowser.open(URL)
            return
        time.sleep(0.25)


def main() -> None:
    # 装到 Program Files 后目录只读: 不写 .pyc 就不会反复撞权限失败;
    # 同时屏蔽用户级 site-packages, 避免机器上别的 Python 包串进来.
    sys.dont_write_bytecode = True
    os.environ.setdefault('PYTHONNOUSERSITE', '1')

    # 安装包把 HanLP 模型放在程序目录 models/ 下(与 app/ 同级), 跟程序一起卸载;
    # 开发环境没有这个目录, 不动 HANLP_HOME, 继续用 %APPDATA%\hanlp.
    models = os.path.join(os.path.dirname(APP_DIR), 'models')
    if os.path.isdir(models):
        os.environ.setdefault('HANLP_HOME', models)

    if port_open(PORT):
        webbrowser.open(URL)
        return

    logs = os.path.join(_data_dir(), 'logs')
    os.makedirs(logs, exist_ok=True)
    # line_buffering: 日志实时落盘, 用户排查问题时不会看到半截
    stream = open(os.path.join(logs, 'web.log'), 'a', encoding='utf-8', buffering=1)
    sys.stdout = stream
    sys.stderr = stream

    stop = threading.Event()
    threading.Thread(target=_open_when_ready, args=(stop,), daemon=True).start()

    os.chdir(APP_DIR)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    os.environ.setdefault('WASHING_PORT', str(PORT))

    try:
        from web.app import app
        app.run(host='127.0.0.1', port=PORT, threaded=True, debug=False)
    except Exception as exc:  # noqa: BLE001 - 启动失败必须留下痕迹
        import traceback
        traceback.print_exc()
        stream.write(f'\n[启动失败] {exc}\n')
        stream.flush()
        raise
    finally:
        stop.set()


if __name__ == '__main__':
    main()
