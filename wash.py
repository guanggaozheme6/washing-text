# -*- coding: utf-8 -*-
"""
批量文本分析 / 清洗
用法:
  .venv/Scripts/python.exe wash.py sample.txt
  .venv/Scripts/python.exe wash.py sample.txt --tasks tok,pos,dep --out out.json
  .venv/Scripts/python.exe wash.py sample.txt --sep "/"      # 分词结果用 / 连接
"""
import argparse
import json
import os

import hanlp
from hanlp.utils.rules import split_sentence

TASK_CHOICES = ['tok', 'pos', 'ner', 'dep', 'con', 'srl']


def main():
    ap = argparse.ArgumentParser(description='用 HanLP 批量分析文本')
    ap.add_argument('input', help='输入 .txt 文件')
    ap.add_argument('--tasks', default='tok,pos',
                    help='逗号分隔, 可选: ' + ','.join(TASK_CHOICES))
    ap.add_argument('--out', default=None, help='结果 json 路径, 默认与输入同名 .hanlp.json')
    ap.add_argument('--sep', default=' ', help='分词结果连接符, 默认空格')
    args = ap.parse_args()

    tasks = [t.strip() for t in args.tasks.split(',') if t.strip()]

    with open(args.input, encoding='utf-8') as f:
        text = f.read()

    sentences = [s for s in split_sentence(text) if s.strip()]
    if not sentences:
        print('没读到任何句子, 退出')
        return
    print(f'分句完成: {len(sentences)} 句')

    HanLP = hanlp.load(hanlp.pretrained.mtl.OPEN_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH)
    doc = HanLP(sentences, tasks=tasks)

    result = {'sentence': sentences}
    result.update({k: v for k, v in doc.items()})
    total_words = sum(len(t) for t in doc['tok'])
    print(f'分词完成: {total_words} 个词')

    out = args.out or os.path.splitext(args.input)[0] + '.hanlp.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'结果已写入: {out}')

    print('\n--- 分词预览 (前 5 句) ---')
    for s, tokens in list(zip(sentences, doc['tok']))[:5]:
        print(args.sep.join(tokens))


if __name__ == '__main__':
    main()
