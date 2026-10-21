#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""组装可分发目录 build/stage —— Inno Setup 的输入.

产物结构:
  build/stage/
    python/   嵌入式 CPython 3.13 + 全部三方依赖(含 torch)
    app/      项目代码、配置、语料、启动器

为什么用嵌入式解释器而不是 PyInstaller:
  torch 2.x 走 PyInstaller 需要大量 --collect-all 补丁, 且 onefile 解包到临时目录
  会让 800MB 依赖每次启动都复制一遍; 嵌入式解释器 + 目录安装装完即用, 启动稳定.

用法:
  .venv/Scripts/python.exe build/package.py
"""
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build')
CACHE = os.path.join(BUILD, 'cache')
STAGE = os.path.join(BUILD, 'stage')

PY_VER = '3.13.14'
PY_TAG = '313'
PY_URL = f'https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip'
PY_ZIP = os.path.join(CACHE, f'python-{PY_VER}-embed-amd64.zip')

VENV_SP = os.path.join(ROOT, '.venv', 'Lib', 'site-packages')

# 不需要进安装包的: pip 是开发期工具; 两个 editable 文件指向开发机绝对路径, 必须去掉
SKIP_TOP = {'pip', '__pycache__'}
SKIP_FILES = {'__editable__.hanlp-2.1.5.pth', '__editable___hanlp_2_1_5_finder.py'}
# torch 里只有 import 时用不到的两块: C++ 头文件、自带测试
TORCH_SKIP = {'include', 'test'}

VC_DLLS = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
           'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')

APP_ITEMS = ('config.yaml', 'launcher.py', 'README.md', 'data', 'rewriter', 'web')


# ---------- 长路径安全的文件操作 (torch 目录很深, Windows 260 上限会炸) ----------

def _lp(path: str) -> str:
    if os.name != 'nt':
        return path
    path = os.path.abspath(path)
    if path.startswith('\\\\?\\'):
        return path
    if path.startswith('\\\\'):
        return '\\\\?\\UNC' + path[1:]
    return '\\\\?\\' + path


def rmtree(path: str) -> None:
    if os.path.exists(_lp(path)):
        shutil.rmtree(_lp(path))


def copy_tree(src: str, dst: str, skip_dirs=frozenset(), skip_files=frozenset()) -> int:
    """递归复制, 返回复制的文件数. 跳过 __pycache__ / *.pyc."""
    copied = 0
    os.makedirs(_lp(dst), exist_ok=True)
    with os.scandir(_lp(src)) as entries:
        for entry in entries:
            name = entry.name
            s = os.path.join(src, name)
            d = os.path.join(dst, name)
            if entry.is_dir(follow_symlinks=False):
                if name in skip_dirs or name == '__pycache__':
                    continue
                copied += copy_tree(s, d, skip_dirs, skip_files)
            elif entry.is_file(follow_symlinks=False):
                if name in skip_files or name.endswith('.pyc'):
                    continue
                shutil.copy2(_lp(s), _lp(d))
                copied += 1
    return copied


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(_lp(path)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def mb(n: int) -> str:
    return f'{n / 1048576:.1f} MB'


def step(msg: str) -> None:
    print(f'\n== {msg}')


# ---------- 各步骤 ----------

def fetch_python() -> None:
    os.makedirs(CACHE, exist_ok=True)
    if os.path.isfile(PY_ZIP) and os.path.getsize(PY_ZIP) > 5 * 1048576:
        print(f'复用缓存: {PY_ZIP}')
        return
    print(f'下载 {PY_URL}')
    with urllib.request.urlopen(PY_URL, timeout=180) as resp, open(PY_ZIP, 'wb') as f:
        shutil.copyfileobj(resp, f)
    print(f'完成 {mb(os.path.getsize(PY_ZIP))}')


def unpack_python() -> str:
    pydir = os.path.join(STAGE, 'python')
    os.makedirs(pydir, exist_ok=True)
    with zipfile.ZipFile(PY_ZIP) as z:
        z.extractall(pydir)
    print(f'解压到 {pydir}')
    return pydir


def install_deps(pydir: str) -> None:
    dst = os.path.join(pydir, 'Lib', 'site-packages')
    os.makedirs(dst, exist_ok=True)
    total = 0
    for name in sorted(os.listdir(VENV_SP)):
        src = os.path.join(VENV_SP, name)
        if name in SKIP_TOP or name in SKIP_FILES:
            continue
        if os.path.isdir(src):
            skip = TORCH_SKIP if name.lower() == 'torch' else frozenset()
            n = copy_tree(src, os.path.join(dst, name), skip_dirs=skip)
            total += n
            if name.lower() in {'torch', 'transformers'}:
                print(f'  {name}: {n} 个文件')
        elif os.path.isfile(src) and not name.endswith('.pyc'):
            shutil.copy2(_lp(src), _lp(os.path.join(dst, name)))
            total += 1

    # HanLP 在开发机是 editable 安装(指向 D:\AI\program\washing-text\HanLP),
    # 装到用户机器上路径不存在, 这里落成实体包.
    hanlp_src = os.path.join(ROOT, 'HanLP', 'hanlp')
    n = copy_tree(hanlp_src, os.path.join(dst, 'hanlp'))
    total += n
    print(f'  hanlp(实体化): {n} 个文件')
    print(f'  合计 {total} 个文件, {mb(dir_size(dst))}')


def copy_app() -> None:
    dst = os.path.join(STAGE, 'app')
    os.makedirs(dst, exist_ok=True)
    total = 0
    for item in APP_ITEMS:
        src = os.path.join(ROOT, item)
        target = os.path.join(dst, item)
        if os.path.isdir(src):
            total += copy_tree(src, target)
        elif os.path.isfile(src):
            shutil.copy2(_lp(src), _lp(target))
            total += 1
        else:
            print(f'  ! 缺少 {item}, 已跳过')
    print(f'{total} 个文件, {mb(dir_size(dst))}')


def copy_vc_runtime(pydir: str) -> None:
    sys32 = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
    got = []
    for dll in VC_DLLS:
        src = os.path.join(sys32, dll)
        if os.path.isfile(src):
            shutil.copy2(_lp(src), _lp(os.path.join(pydir, dll)))
            got.append(dll)
    print(f'VC 运行时: {", ".join(got) or "无（目标机需自带 VC++ 2015-2022）"}')


def write_pth(pydir: str) -> None:
    """嵌入式解释器靠 ._pth 决定搜索路径; 不写就 import 不到 site-packages."""
    pth = os.path.join(pydir, f'python{PY_TAG}._pth')
    with open(pth, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(f'python{PY_TAG}.zip\n')
        f.write('.\n')
        f.write('Lib\\site-packages\n')
        f.write('import site\n')
    print(f'搜索路径: {pth}')


def main() -> int:
    print(f'项目根: {ROOT}')
    step('清理 build/stage')
    rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)

    step('准备 Python 运行时')
    fetch_python()
    pydir = unpack_python()
    copy_vc_runtime(pydir)
    write_pth(pydir)

    step('安装三方依赖')
    install_deps(pydir)

    step('复制应用代码')
    copy_app()

    step('完成')
    print(f'stage 总大小: {mb(dir_size(STAGE))}')
    print(f'输出目录: {STAGE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
