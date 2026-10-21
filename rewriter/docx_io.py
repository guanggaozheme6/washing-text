# -*- coding: utf-8 -*-
"""docx 读写: 只处理正文段落.

读: 段落之间用 "\\n\\n" 连接; 表格 / 页眉页脚 / 脚注不取 (第一版只要正文).
写: 纯文本按空行分段写入新 docx, 字体使用模板默认.

优先用 python-docx; 未安装或导入失败时降级为 zipfile + xml.etree 解析
word/document.xml, 只取 <w:t> 文本节点, 按 <w:p> 分段.
"""
import os
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

try:  # pragma: no cover - 取决于环境
    import docx  # type: ignore
    _HAS_DOCX = True
except Exception:  # noqa: BLE001
    docx = None
    _HAS_DOCX = False

_W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_W = '{%s}' % _W_NS

_PARA_SPLIT_RE = re.compile(r'\n\s*\n')


def _open_stream(source):
    """把 path / bytes / 文件对象统一成 python-docx 与 zipfile 都能吃的形态."""
    if isinstance(source, (bytes, bytearray)):
        return BytesIO(bytes(source))
    if hasattr(source, 'read'):
        return source
    return os.fspath(source)


def _read_with_docx(source) -> str:
    document = docx.Document(_open_stream(source))
    paras = [p.text.strip() for p in document.paragraphs]
    return '\n\n'.join(p for p in paras if p)


def _read_with_zipfile(source) -> str:
    stream = _open_stream(source)
    with zipfile.ZipFile(stream) as zf:
        xml = zf.read('word/document.xml')
    root = ET.fromstring(xml)
    body = root.find(_W + 'body')
    if body is None:
        return ''
    paras: list[str] = []
    for node in body:  # 只遍历 body 直接子节点 → 自然跳过 w:tbl / w:sectPr
        if node.tag != _W + 'p':
            continue
        texts = [t.text or '' for t in node.iter(_W + 't')]
        text = ''.join(texts).strip()
        if text:
            paras.append(text)
    return '\n\n'.join(paras)


def read_docx(source) -> str:
    """读取 docx 正文, 返回按空行分隔的纯文本.

    source 可以是路径, 也可以是 bytes / 文件对象 (供上传场景直接传入).
    """
    if _HAS_DOCX:
        try:
            return _read_with_docx(source)
        except Exception:  # noqa: BLE001 - 损坏文件等, 退回裸解析
            pass
    return _read_with_zipfile(source)


def _split_paragraphs(text: str) -> list[str]:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paras = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    if len(paras) <= 1:  # 没有空行 → 每行一段
        paras = [p.strip() for p in text.split('\n') if p.strip()]
    return paras


def _write_with_docx(text: str, path: str) -> None:
    document = docx.Document()
    for para in _split_paragraphs(text):
        document.add_paragraph(para)
    document.save(os.fspath(path))


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _escape(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def _write_with_zipfile(text: str, path: str) -> None:
    body = ''.join(
        '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % _escape(p)
        for p in _split_paragraphs(text)
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (_W_NS, body)
    )
    with zipfile.ZipFile(os.fspath(path), 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES)
        zf.writestr('_rels/.rels', _RELS)
        zf.writestr('word/document.xml', document)


def write_docx(text: str, path: str) -> None:
    """把纯文本按段落写入新 docx (空行分段; 无空行则每行一段)."""
    target_dir = os.path.dirname(os.path.abspath(os.fspath(path)))
    os.makedirs(target_dir, exist_ok=True)
    if _HAS_DOCX:
        try:
            _write_with_docx(text, path)
            return
        except Exception:  # noqa: BLE001
            pass
    _write_with_zipfile(text, path)
