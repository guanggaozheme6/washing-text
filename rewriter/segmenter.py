# -*- coding: utf-8 -*-
"""预处理: 分句 + 段落结构保持 + 标点归一化.

分句复用 HanLP 的 split_sentence (wash.py 已在用, 不重写).
段落结构以 "\n\n+" 切段, 每段内部再分句, 保证回填时能还原段落布局.
"""
import re

from hanlp.utils.rules import split_sentence

_WS_RE = re.compile(r'[ \t\u3000]+')

# 行尾已是句末/收尾符号 → 说明这句完整, 不与下一行合并
# 英文句点 / 右方括号 / 右圆括号 / 冒号 同样算收尾: 参考文献、公式编号、
# 条款编号 ("[1] …2020." "式(3)" "第4条:") 都以它们结尾, 合并会毁掉列表结构
_NO_MERGE_TAIL = set('。！？；：\u201c\u201d\u2018\u2019）》」』】…"\'') | set('.]):')
# 行尾是数字/字母 → 多为编号、公式、参考文献, 保持原样
_LATIN_TAIL_RE = re.compile(r'[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]$')
# 标题行: #、第X章/节、一、、（一）、1.、（1）
_HEADING_RE = re.compile(
    r'^\s*(?:'
    r'#{1,6}\s*'
    r'|第[一二三四五六七八九十百千零〇0-9]+[章节篇部]'
    r'|[一二三四五六七八九十]+、'
    r'|[（(][一二三四五六七八九十]+[）)]'
    r'|\d+[.．](?!\d)'
    r'|[（(]\d+[）)]'
    r')'
)

# 结构标签行: 整行命中才生效 (允许前后空白), 该行自身闭合, 不与下一行合并
# 这些行是论文骨架, 一旦被并进正文就成了内容损坏
_LABEL_LINES = {
    '摘要', 'Abstract', 'ABSTRACT', '关键词', '关键字',
    'Key words', 'Keywords', '目录', '参考文献', 'References',
    '致谢', '附录', '引言', '绪论', '结论',
}
_LABEL_CASEFOLD = {s.casefold() for s in _LABEL_LINES}

# 标题行的第二形态: 数字 + 空格 + 标题文字 ("1 引言" "3 实验")
# 限制数字 1-2 位/整行 ≤20 字, 且后续文字不是量词单位, 避免误判 "2023 年" "12 月"
_NUM_SPACE_HEADING_RE = re.compile(r'^(\d{1,2})[ \t\u3000]+(\S.*)$')
_UNIT_START = set('年月日时分秒个次种位篇页条项名人元％%多天周届版号')


# 孤立页码行: 整行仅 1-4 位数字 (PDF 分页残留)
_PAGE_NO_RE = re.compile(r'\d{1,4}')
# 句末标点 (判页码行时用来确认上一行是完整句)
_SENT_END = set('。！？；：.!?;:')
_CJK_START_RE = re.compile(r'^[\u4e00-\u9fff]')


def _is_label(line: str) -> bool:
    return line.strip().casefold() in _LABEL_CASEFOLD


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if _HEADING_RE.match(s):
        return True
    if len(s) <= 20:
        m = _NUM_SPACE_HEADING_RE.match(s)
        if m and len(m.group(2)) >= 2 and m.group(2)[0] not in _UNIT_START:
            return True
    return False


def _is_page_number(lines: list[str], i: int) -> bool:
    """判断 lines[i] 是否为 PDF 分页残留的孤立页码.

    必须同时满足: 整行 1-4 位数字 / 上一行为空或以句末标点结尾 /
    下一行为空或以中文起首 / 且紧邻空行 (页码必然孤立在段落边界上).
    任一不满足就保持原样, 避免把正文里的 "2023"、表格数字当噪声删掉.
    """
    if not _PAGE_NO_RE.fullmatch(lines[i].strip()):
        return False
    prev = lines[i - 1].strip() if i > 0 else ''
    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
    if not (prev == '' or prev[-1] in _SENT_END):
        return False
    if not (nxt == '' or _CJK_START_RE.match(nxt)):
        return False
    return prev == '' or nxt == ''


def _can_continue(line: str) -> bool:
    """该行是否愿意接续下一行 (行尾无句末标点且不是数字/字母)."""
    s = line.rstrip()
    if not s:
        return False
    return not (s[-1] in _NO_MERGE_TAIL or _LATIN_TAIL_RE.search(s))


def unwrap_hard_breaks(text: str) -> str:
    """合并 PDF / 知网复制带来的硬换行.

    若上一行未以句末标点或数字/字母结尾, 且下一行不是标题行 / 结构标签行,
    则把下一行直接拼上去 (中文不加空格). 循环累积即可处理连续多行被切断.
    空行视为段落边界, 原样保留.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [ln.strip() for ln in text.split('\n')]
    out: list[str] = []
    buf = ''
    buf_is_heading = False

    def flush():
        nonlocal buf, buf_is_heading
        if buf:
            out.append(buf)
            buf = ''
        buf_is_heading = False

    for i, line in enumerate(lines):
        if not line:
            flush()
            if out and out[-1] != '':
                out.append('')
            continue
        # 孤立页码 (PDF 分页残留的 "1" "23"): 丢弃, 不要并进正文句子,
        # 否则会被当成正文数字, 改写时丢失后触发"数字丢失"硬约束.
        # 判定从严 (见 _is_page_number), 拿不准就保留原文.
        if _is_page_number(lines, i):
            continue
        if not buf:
            buf = line
            buf_is_heading = _is_label(line) or _is_heading(line)
            continue
        if (buf_is_heading or _is_label(line) or _is_heading(line)
                or not _can_continue(buf)):
            flush()
            buf = line
            buf_is_heading = _is_label(line) or _is_heading(line)
        else:
            buf += line
    flush()
    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out)


def normalize_punct(text: str) -> str:
    """统一标点: 英文标点 → 中文标点 (保守处理, 不动数字与变量)."""
    trans = str.maketrans({
        ',': '，', ';': '；', ':': '：', '?': '？', '!': '！',
        '(': '（', ')': '）',
    })
    # 只在中文上下文中替换半角逗号/冒号等
    out = []
    for i, ch in enumerate(text):
        if ch in trans:
            prev = text[i - 1] if i > 0 else ''
            nxt = text[i + 1] if i + 1 < len(text) else ''
            if re.match(r'[\u4e00-\u9fff]', prev or '') or re.match(r'[\u4e00-\u9fff]', nxt or ''):
                out.append(trans[ch])
                continue
        out.append(ch)
    return ''.join(out)


def split_text_to_sentences(text: str) -> list[str]:
    """全篇 → 句子列表 (不含空句), 段落信息忽略."""
    sents: list[str] = []
    for para in split_paragraphs(text):
        sents.extend([s for s in split_sentence(para) if s.strip()])
    return sents


def split_paragraphs(text: str) -> list[str]:
    """按空行切段; 无空行的长文本按行切段."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paras = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
    if len(paras) <= 1:
        paras = [p for p in text.split('\n') if p.strip()]
    return paras


def segment(text: str) -> list[list[str]]:
    """段落结构保持的分句: 返回 [[句1, 句2], [句1, ...]], 外层=段落."""
    result: list[list[str]] = []
    for para in split_paragraphs(unwrap_hard_breaks(text)):
        para = normalize_punct(para)
        sents = [_WS_RE.sub('', s).strip() for s in split_sentence(para)]
        sents = [s for s in sents if s]
        if sents:
            result.append(sents)
    return result


def flatten(paras: list[list[str]]) -> list[str]:
    return [s for p in paras for s in p]


def reassemble(paras: list[list[str]], sep: str = '') -> str:
    """回填: 段落内句子用 sep 连接 (中文默认无空格), 段间空行."""
    return '\n\n'.join(sep.join(p) for p in paras) + '\n'
