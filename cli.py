# -*- coding: utf-8 -*-
"""文本结构改写降重系统 · 主入口

用法:
  .venv/Scripts/python.exe cli.py input.txt --out out/ --rounds 2 --seed 42
  .venv/Scripts/python.exe cli.py input.txt --ops split,shift,attrib,connector,voice \
      --protect data/whitelist.txt --corpus data/corpus/ --report --max-run 10
  .venv/Scripts/python.exe cli.py input.txt --dry-run --corpus data/corpus/
"""
import argparse
import os
import sys

from rewriter.config import load_config
from rewriter.pipeline import Rewriter


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='文本结构改写降重: 分句 → 句法结构变换 → 迭代选优')
    ap.add_argument('input', help='输入 .txt 文件')
    ap.add_argument('--out', default='out', help='输出目录, 默认 out/')
    ap.add_argument('--config', default=None, help='config.yaml 路径')
    ap.add_argument('--rounds', type=int, default=None, help='迭代轮数 (默认 2, 上限 3)')
    ap.add_argument('--seed', type=int, default=None, help='随机种子')
    ap.add_argument('--ops', default=None,
                    help='启用的算子, 逗号分隔: split,shift,attrib,connector,voice,merge,synonym')
    ap.add_argument('--protect', default=None, help='术语白名单文件路径')
    ap.add_argument('--corpus', default=None, help='比对语料目录')
    ap.add_argument('--max-run', type=int, default=None, help='最长连续重合阈值, 默认 10')
    ap.add_argument('--report', action='store_true', help='输出 evaluate report.md')
    ap.add_argument('--dry-run', action='store_true', help='只评估不改写')
    return ap


def main():
    args = build_argparser().parse_args()

    overrides: dict = {}
    if args.rounds is not None:
        overrides.setdefault('rewrite', {})['rounds'] = min(args.rounds, 3)
    if args.seed is not None:
        overrides.setdefault('rewrite', {})['seed'] = args.seed
    if args.ops:
        ops = [o.strip() for o in args.ops.split(',') if o.strip()]
        # merge 走 pipeline 层, 同样登记在 ops_enabled
        overrides.setdefault('rewrite', {})['ops_enabled'] = ops
        overrides['rewrite']['ops_disabled'] = []
    if args.protect:
        overrides.setdefault('protect', {})['whitelist'] = args.protect
    if args.corpus:
        overrides.setdefault('overlap', {})['corpus_dir'] = args.corpus
    if args.max_run is not None:
        overrides.setdefault('overlap', {})['max_run_threshold'] = args.max_run

    cfg = load_config(args.config, overrides)

    if not os.path.isfile(args.input):
        print(f'找不到输入文件: {args.input}')
        sys.exit(1)
    with open(args.input, encoding='utf-8') as f:
        text = f.read()
    if not text.strip():
        print('输入文件为空')
        sys.exit(1)

    print(f'加载模型与配置... (rounds={cfg["rewrite"]["rounds"]}, '
          f'ops={",".join(cfg["rewrite"]["ops_enabled"])})')
    rw = Rewriter(cfg)

    if args.dry_run:
        print('--- DRY RUN: 只评估, 不改写 ---')
        rep = rw.dry_run(text)
        print(f'句数: {rep["sentences"]}')
        print(f'超阈句数 (≥{rw.max_run_threshold}字): {rep["over_threshold"]}'
              f'  (忽略标点口径: {rep["over_threshold_loose"]})')
        print(f'平均最长重合: {rep["avg_max_run"]} 字符'
              f'  (忽略标点: {rep["avg_max_run_loose"]})')
        print(f'全篇最长重合: {rep["max_run"]} 字符')
        print('\n最危险 TOP5:')
        for i, s in enumerate(rep['top5'], 1):
            flag = '⚠️' if s['over'] else '✅'
            print(f'  {i}. {flag} 重合{s["max_run"]}字 | {s["sentence"]}')
            if s['hit']:
                print(f'      命中: {s["hit"]}')
        return

    print('开始改写 (首次会加载 HanLP 模型, 约 20 秒)...')
    result = rw.run(text)
    paths = rw.write_outputs(result, args.input, args.out)

    s = {'before': result.report_before, 'after': result.report_after}
    print('\n' + '=' * 56)
    print('改写完成')
    print('=' * 56)
    print(f'句数: {len(result.records)}  |  改动: '
          f'{sum(1 for r in result.records if r.changed)}  |  冻结: '
          f'{sum(1 for r in result.records if r.frozen)}')
    print(f'超阈句数: {s["before"]["over_threshold"]} → {s["after"]["over_threshold"]}'
          f'  (忽略标点口径: {s["before"]["over_threshold_loose"]} → {s["after"]["over_threshold_loose"]})')
    print(f'平均最长重合: {s["before"]["avg_max_run"]} → {s["after"]["avg_max_run"]} 字符'
          f'  (忽略标点: {s["before"]["avg_max_run_loose"]} → {s["after"]["avg_max_run_loose"]})')
    print(f'全篇最长重合: {s["before"]["max_run"]} → {s["after"]["max_run"]} 字符')
    changed = [r for r in result.records if r.changed]
    if changed:
        avg_fid = sum(r.fidelity for r in changed) / len(changed)
        print(f'改动句平均保义度: {avg_fid:.0%}')
    print(f'\n输出:\n  {paths["txt"]}\n  {paths["json"]}')
    if args.report:
        print(f'  {paths["report"]}')


if __name__ == '__main__':
    main()
