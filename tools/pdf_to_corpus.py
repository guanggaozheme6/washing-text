# -*- coding: utf-8 -*-
"""把课件 PDF (幻灯片/复习材料) 抽成 WashingText 可识别的 .txt 语料.

    .venv/Scripts/python.exe tools/pdf_to_corpus.py "源PDF目录" --prefix CCT011
    .venv/Scripts/python.exe tools/pdf_to_corpus.py "源PDF目录" --prefix CCT011 --dst data/corpus
    .venv/Scripts/python.exe tools/pdf_to_corpus.py "源PDF目录" --prefix CCT011 --dry-run

做的事:
  1. pdftotext -layout 抽文本 (Xpdf/poppler 均可);
  2. 丢页眉页脚残留: 空行标记、纯数字页码、◆/【知识点框架】这类空壳标题;
  3. 接回版面折行 (PDF 把一句话断成几行/几个文本框);
  4. 去掉中英混排的排版空格 ("1938 年" -> "1938年"), 保证字符级查重能命中;
  5. 按文件名里的专题号排序, 写成 <PREFIX>_L1.txt ... ; 内容完全相同的 PDF 只留一份。

输出路径: 默认写 本项目/data/corpus/ (由 overlap.load_corpus 自动扫 .txt/.md).
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DST = os.path.join(HERE, 'data', 'corpus')

END = tuple('。！？；：!?;:）)》」』】”’"\'')
DROP_LINE = re.compile(r'^\s*(?:【知识点框架】|【知识点与重点】|◆.*|…+|[.．]{3,}|[-—_=·\s]*)$')
NUM_ITEM = re.compile(
    r'^\s*(?:[（(]?\d{1,2}[）)．.、]|[一二三四五六七八九十]+、|[①-⑳]|[a-z][．.、]|第[一二三四五六七八九十]+[章节])')
PAGE_NO = re.compile(r'^\d{1,3}$')
HEAD_TAIL = re.compile(r'(知识点与重点|知识重难点|复习材料|知识点)\s*$')
CJK = r'\u4e00-\u9fff\u2013-\u201f\u2026\u3000-\u303f\uff00-\uffef'
CN_DIGIT = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def cn2int(s: str) -> int:
    """把 "九", "十", "十一", "四" 之类的专题号转成整数; 认不出就返回 99."""
    s = s.strip()
    if not s:
        return 99
    if s == '十':
        return 10
    if s.startswith('十'):
        return 10 + CN_DIGIT.get(s[1:2], 0)
    if '十' in s:
        a, _, b = s.partition('十')
        return CN_DIGIT.get(a, 0) * 10 + (CN_DIGIT.get(b, 0) if b else 0)
    return CN_DIGIT.get(s[:1], 99)


def topic_no(name: str) -> int:
    """从文件名里取专题序号: "5.专题五：..." -> 5, "9-10.专题九-十 ..." -> 9."""
    m = re.search(r'(\d{1,2})\s*[-—~]\s*\d{1,2}\s*[.、．:：]?\s*专题', name)
    if m:
        return int(m.group(1))
    m = re.search(r'专题\s*([一二三四五六七八九十]+)', name)
    if m:
        return cn2int(m.group(1))
    m = re.match(r'\s*(\d{1,2})\s*[.、．]', name)
    if m:
        return int(m.group(1))
    return 99


def raw_text(pdf: str) -> str:
    out = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-layout', pdf, '-'],
                         capture_output=True)
    if out.returncode != 0:
        raise SystemExit('pdftotext 失败: %s\n%s' % (pdf, out.stderr.decode('utf-8', 'replace')))
    return out.stdout.decode('utf-8')


def squeeze(s: str) -> str:
    """去掉排版空格: 中文与数字/字母相邻的空格一律删, 两侧都是西文才保留."""
    s = re.sub(r'[ \t\u3000]+', ' ', s).strip()
    s = re.sub(rf'(?<=[{CJK}]) (?=[{CJK}0-9A-Za-z])', '', s)
    s = re.sub(rf'(?<=[0-9A-Za-z]) (?=[{CJK}])', '', s)
    return s


def merge_lines(raw: str) -> list[str]:
    """版面折行合并: 上行未收尾且是"满行"就与下一行拼接."""
    raw = raw.replace('\f', '')
    lines = [squeeze(x) for x in raw.split('\n')]
    lines = [x for x in lines if x and not DROP_LINE.match(x) and not PAGE_NO.match(x)]
    if not lines:
        return []
    merged = [lines[0]]
    for cur in lines[1:]:
        prev = merged[-1]
        if prev.endswith('》') and cur.startswith('《'):   # 书名号连续列举
            merged[-1] = prev + cur
            continue
        join = (not prev.endswith(END)
                and len(prev) >= 25
                and not (NUM_ITEM.match(prev) and len(prev) <= 22
                         and not re.search(r'[。！？；，、]', prev))
                and not NUM_ITEM.match(cur)
                and not cur.startswith(('《', '【')))
        if join:
            merged[-1] = prev + cur
        else:
            merged.append(cur)
    return merged


def build(pdf: str, course: str) -> str:
    merged = merge_lines(raw_text(pdf))
    if not merged:
        return ''
    title = merged[0]
    body = [x for x in merged[1:] if not (HEAD_TAIL.search(x) and len(x) < 25)]
    return f'《{course}》{title}\n\n' + '\n\n'.join(body) + '\n'


def main():
    ap = argparse.ArgumentParser(description='课件 PDF -> WashingText 语料 txt')
    ap.add_argument('src', help='PDF 所在目录')
    ap.add_argument('--prefix', required=True, help='课程号, 如 CCT011 (输出 CCT011_L1.txt)')
    ap.add_argument('--dst', default=DEFAULT_DST, help='输出目录, 默认 data/corpus')
    ap.add_argument('--course', default='毛泽东思想和中国特色社会主义理论体系概论',
                    help='文件头里的课程全名')
    ap.add_argument('--dry-run', action='store_true', help='只报告不落盘')
    args = ap.parse_args()

    pdfs = [f for f in os.listdir(args.src) if f.lower().endswith('.pdf')]
    if not pdfs:
        raise SystemExit('目录里没有 PDF: ' + args.src)
    pdfs.sort(key=lambda n: (topic_no(n), n))

    seen, made = {}, []
    for name in pdfs:
        path = os.path.join(args.src, name)
        text = build(path, args.course)
        if not text.strip():
            print(f'抽取为空, 跳过: {name}')
            continue
        digest = hashlib.sha1(text.encode('utf-8')).hexdigest()
        if digest in seen:
            print(f'跳过重复内容: {name}  ==  {seen[digest]}')
            continue
        seen[digest] = name
        made.append((name, text))

    for i, (name, text) in enumerate(made, 1):
        out = os.path.join(args.dst, f'{args.prefix}_L{i}.txt')
        print(f'{os.path.basename(out)}  {len(text):5d} 字  <-  {name}')
        if not args.dry_run:
            os.makedirs(args.dst, exist_ok=True)
            with open(out, 'w', encoding='utf-8') as f:
                f.write(text)
    print(f'共 {len(made)} 份, {sum(len(t) for _, t in made)} 字'
          + ('  (dry-run 未落盘)' if args.dry_run else f'  -> {args.dst}'))


if __name__ == '__main__':
    main()
