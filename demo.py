# -*- coding: utf-8 -*-
"""
HanLP 快速上手示例
运行: .venv/Scripts/python.exe demo.py

输出三样东西:
  1. 分词 + 词性 + 依存关系 表格
  2. 依存句法树 (ASCII 画出来)
  3. 成分句法树 (主谓宾短语结构)
"""
import hanlp
from hanlp_common.visualization import pretty_tree_horizontal

# 开源多任务模型: 分词 + 词性 + 命名实体 + 语义角色 + 依存句法 + 语义依存 + 成分句法
# 首次运行会自动下载模型(约 90MB), 之后走缓存
HanLP = hanlp.load(hanlp.pretrained.mtl.OPEN_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH)

SENTENCES = [
    '2021年HanLPv2.1为生产环境带来次世代最先进的多语种NLP技术。',
    '阿婆主来到北京立方庭参观自然语义科技公司。',
    '我把冰箱里的西瓜吃掉了。',
]

# tasks 指定跑哪些任务, 越少越快
# tok=分词  pos=词性  ner=命名实体  dep=依存句法  con=成分句法  srl=语义角色标注
TASKS = ['tok', 'pos', 'dep', 'con']

doc = HanLP(SENTENCES, tasks=TASKS)

for idx, sentence in enumerate(SENTENCES):
    tokens = doc['tok'][idx]
    pos = doc['pos'][idx]
    dep = doc['dep'][idx]
    con = doc['con'][idx]

    print('=' * 62)
    print(f'句子 {idx + 1}: {sentence}')
    print('=' * 62)

    print('\n[1] 分词 / 词性 / 依存关系')
    print(f'{"#":<4}{"词":<12}{"词性":<8}{"中心词":<12}{"关系"}')
    print('-' * 62)
    for i, (word, tag, (head, rel)) in enumerate(zip(tokens, pos, dep), start=1):
        head_word = 'ROOT(根)' if head == 0 else tokens[head - 1]
        print(f'{i:<4}{word:<12}{tag:<8}{head_word:<12}{rel}')

    print('\n[2] 依存句法树')
    arrows = [{'from': head - 1, 'to': i} for i, (head, _) in enumerate(dep) if head != 0]
    for line, word in zip(pretty_tree_horizontal(arrows), tokens):
        print(f'{line}  {word}')

    print('\n[3] 成分句法树 (短语结构)')
    print(con)
    print()
