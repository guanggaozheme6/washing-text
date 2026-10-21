# -*- coding: utf-8 -*-
"""Web 控制器: 路由 + 输入校验 + 错误映射. 业务逻辑全部在 service 层.

启动:
  .venv/Scripts/python.exe web/app.py
  # 打开 http://127.0.0.1:8777
"""
import logging
import os
import signal
import sys
import time
import uuid

from flask import Flask, jsonify, render_template, request, g

# 允许直接以脚本运行 (python web/app.py) 时找到项目包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.service import KNOWN_OPS, RewriteService, ServiceError  # noqa: E402

HOST = os.environ.get('WASHING_HOST', '127.0.0.1')
PORT = int(os.environ.get('WASHING_PORT', '8777'))
MAX_TEXT_CHARS = 100000
MAX_BODY_BYTES = 2 * 1024 * 1024

log = logging.getLogger('washing.web')


class _RidFilter(logging.Filter):
    """给每条日志记录补 request_id (挂在 handler 上, 覆盖 werkzeug 的传播日志)."""

    def filter(self, record):
        if not hasattr(record, 'request_id'):
            rid = '-'
            try:
                from flask import g, has_request_context
                if has_request_context():
                    rid = getattr(g, 'rid', '-')
            except Exception:  # noqa: BLE001
                rid = '-'
            record.request_id = rid
        return True


def _setup_logging():
    """统一日志: 自定义 handler + handler 级过滤器 (logger 级过滤器不作用于传播记录)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s rid=%(request_id)s %(name)s %(message)s'))
    handler.addFilter(_RidFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


_setup_logging()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_BODY_BYTES
service = RewriteService()


# ---------- 请求钩子与错误处理 ----------

@app.before_request
def _assign_rid():
    g.rid = uuid.uuid4().hex[:8]
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = (time.time() - getattr(g, 't0', time.time())) * 1000
    if request.path.startswith('/api/'):
        log.info('%s %s -> %s (%.0fms)', request.method, request.path,
                 resp.status_code, dur)
    return resp


@app.errorhandler(ServiceError)
def _service_error(exc: ServiceError):
    return jsonify({'ok': False, 'error': {'code': exc.code, 'message': exc.message}}), 400


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({'ok': False,
                    'error': {'code': 'body_too_large',
                              'message': '请求体过大 (上限 2MB)'}}), 413


@app.errorhandler(404)
def _not_found(e):
    if request.path == '/favicon.ico':
        return '', 204
    return jsonify({'ok': False,
                    'error': {'code': 'not_found', 'message': '接口不存在'}}), 404


@app.errorhandler(Exception)
def _unhandled(exc: Exception):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return jsonify({'ok': False,
                        'error': {'code': 'http_error',
                                  'message': f'{exc.code} {exc.name}'}}), exc.code
    log.exception('未处理异常: %s', exc)
    return jsonify({'ok': False,
                    'error': {'code': 'internal',
                              'message': '服务器内部错误, 请查看终端日志'}}), 500


# ---------- 输入校验 (边界处) ----------

def _text_from_upload(body: dict) -> str:
    """取上传稿件的正文: multipart 文件 (docx/txt) 或 JSON 里的 docx_b64."""
    from rewriter.docx_io import read_docx

    upload = next((f for f in request.files.values() if f and f.filename), None)
    if upload is not None:
        data = upload.read()
        if not upload.filename.lower().endswith('.docx'):
            return data.decode('utf-8-sig', errors='replace')
        try:
            return read_docx(data)
        except Exception:  # noqa: BLE001 - 损坏 / 加密 / 非 docx
            raise ServiceError('bad_docx', f'无法解析 .docx: {upload.filename}') from None

    b64 = body.get('docx_b64')
    if isinstance(b64, str) and b64.strip():
        import base64
        try:
            return read_docx(base64.b64decode(b64))
        except Exception:  # noqa: BLE001 - base64 非法或 docx 损坏
            raise ServiceError('bad_docx', '.docx 内容解析失败') from None
    return ''


def _validated_params() -> tuple[str, dict]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        if request.files:
            body = {}
        else:
            raise ServiceError('bad_json', '请求体必须是 JSON 对象')
    text = body.get('text')
    if not isinstance(text, str) or not text.strip():
        text = _text_from_upload(body)
    if not text or not text.strip():
        raise ServiceError('empty_text', '文稿内容不能为空')
    if len(text) > MAX_TEXT_CHARS:
        raise ServiceError('text_too_long', f'文稿过长 (上限 {MAX_TEXT_CHARS} 字)')

    params: dict = {}
    if 'rounds' in body and body['rounds'] is not None:
        try:
            rounds = int(body['rounds'])
        except (TypeError, ValueError):
            raise ServiceError('bad_rounds', '轮数必须是整数') from None
        if not 1 <= rounds <= 3:
            raise ServiceError('bad_rounds', '轮数范围 1~3')
        params['rounds'] = rounds
    if 'seed' in body and body['seed'] is not None:
        try:
            params['seed'] = int(body['seed'])
        except (TypeError, ValueError):
            raise ServiceError('bad_seed', '随机种子必须是整数') from None
    if 'max_run' in body and body['max_run'] is not None:
        try:
            mr = int(body['max_run'])
        except (TypeError, ValueError):
            raise ServiceError('bad_max_run', '重合阈值必须是整数') from None
        if not 3 <= mr <= 100:
            raise ServiceError('bad_max_run', '重合阈值范围 3~100')
        params['max_run'] = mr
    if 'ops' in body and body['ops'] is not None:
        ops = body['ops']
        if not isinstance(ops, list) or not all(isinstance(o, str) for o in ops):
            raise ServiceError('bad_ops', '算子列表格式不正确')
        unknown = [o for o in ops if o not in KNOWN_OPS]
        if unknown:
            raise ServiceError('bad_ops', f'未知算子: {", ".join(unknown)}')
        if not ops:
            raise ServiceError('bad_ops', '至少启用一个算子')
        params['ops'] = ops
    for key, label in (('corpus_dir', '语料目录'), ('whitelist', '白名单路径')):
        if key in body and body[key]:
            v = body[key]
            if not isinstance(v, str) or '..' in v:
                raise ServiceError('bad_path', f'{label}路径不合法')
            params[key] = v.strip()
    return text, params


# ---------- 路由 ----------

@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/health')
def health():
    return jsonify({'ok': True, 'time': time.time()})


@app.get('/api/status')
def status():
    st = service.status()
    return jsonify({'ok': True, **st})


@app.post('/api/evaluate')
def evaluate():
    text, params = _validated_params()
    return jsonify({'ok': True, **service.evaluate(text, params)})


@app.post('/api/rewrite')
def rewrite():
    text, params = _validated_params()
    return jsonify({'ok': True, **service.rewrite(text, params)})


@app.post('/api/parse')
def parse_upload():
    """把上传的 .docx / .txt 解析成纯文本, 供前端载入编辑框 (不走改写)."""
    body = request.get_json(silent=True) or {}
    text = _text_from_upload(body)
    if not text.strip():
        raise ServiceError('empty_text', '文件里没有可用文字')
    return jsonify({'ok': True, 'text': text, 'chars': len(text)})


def _graceful(signum, _frame):
    log.info('收到信号 %s, 退出', signum)
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, _graceful)
    signal.signal(signal.SIGTERM, _graceful)
    log.info('启动 http://%s:%s  (模型后台预热中)', HOST, PORT)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
