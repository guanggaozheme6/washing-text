/* ============================================================
   文本改写降重工作台 · 交互层 (无框架, 离线可用)
   ============================================================ */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const DEMO_TEXT = `自然语言处理（NLP）是计算机科学领域与人工智能领域中的一个重要方向。
它研究能实现人与计算机之间用自然语言进行有效通信的各种理论和方法。
依存句法分析可以确定句子中词语之间的修饰关系，从而揭示句子的结构。
句法分析被广泛应用于信息抽取、问答系统等任务中。`;

  const OP_LABELS = {
    split: '长句拆分', shift: '状位移位', attrib: '定语展开', connector: '连接词重写',
    voice: '语态变换', merge: '短句合并', synonym: '同义替换', generative: '生成式兜底',
  };
  const RISKY_OPS = new Set(['synonym', 'generative']);

  const state = {
    modelReady: false, modelFailed: false, busy: false,
    lastResult: null, pollTimer: null,
  };

  /* ---------- 通用工具 ---------- */

  const esc = (s) => String(s).replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function toast(message, kind = 'error', ttl = 5200) {
    const wrap = $('#toastWrap');
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => {
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 260);
    }, ttl);
  }

  async function api(path, payload) {
    let resp;
    try {
      resp = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new Error('无法连接本地服务，请确认服务仍在运行');
    }
    let data;
    try { data = await resp.json(); } catch { data = null; }
    if (!data || data.ok !== true) {
      const code = data && data.error ? data.error.code : 'unknown';
      const msg = data && data.error ? data.error.message : `请求失败 (HTTP ${resp.status})`;
      const e = new Error(friendlyError(code, msg));
      e.code = code;
      throw e;
    }
    return data;
  }

  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = String(r.result || '');
        resolve(s.includes(',') ? s.split(',')[1] : s);
      };
      r.onerror = () => reject(new Error('读取文件失败'));
      r.readAsDataURL(file);
    });
  }

  function friendlyError(code, fallback) {
    const map = {
      empty_text: '文稿内容不能为空',
      text_too_long: '文稿过长，请分段处理（上限 2 万字）',
      model_loading: 'HanLP 模型仍在加载中，请稍候再试',
      model_failed: 'HanLP 模型加载失败，请查看终端日志',
      corpus_not_found: '比对语料目录不存在，请检查路径',
      whitelist_not_found: '白名单文件不存在，请检查路径',
      body_too_large: '请求体过大',
      bad_path: '路径不合法',
    };
    return map[code] || fallback;
  }

  function download(filename, content, mime = 'text/plain') {
    const blob = new Blob([content], { type: `${mime};charset=utf-8` });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
  }

  const stamp = () => {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
  };

  /* ---------- 状态机 ---------- */

  function showState(name) {
    for (const s of ['Empty', 'Loading', 'Report', 'Rewrite']) {
      $(`#state${s}`).classList.toggle('hidden', s.toLowerCase() !== name);
    }
  }

  function setActionsEnabled(enabled) {
    $('#btnEvaluate').disabled = !enabled;
    $('#btnRewrite').disabled = !enabled;
  }

  function applyModelState(data) {
    state.modelReady = !!data.model_ready;
    state.modelFailed = !!data.model_failed;
    const pill = $('#modelStatus');
    const text = $('#modelStatusText');
    if (data.model_failed) {
      pill.dataset.state = 'error';
      text.textContent = '模型加载失败';
      setActionsEnabled(false);
    } else if (data.model_ready) {
      pill.dataset.state = 'ready';
      text.textContent = '模型就绪';
      setActionsEnabled(!state.busy);
    } else {
      pill.dataset.state = 'loading';
      text.textContent = '模型加载中…';
      setActionsEnabled(false);
    }
  }

  async function pollStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      applyModelState(data);
      if (data.model_ready || data.model_failed) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        if (data.model_failed) toast(data.message, 'error', 8000);
      }
      if (data.defaults && !state.defaultsApplied) {
        applyDefaults(data.defaults);
        state.defaultsApplied = true;
      }
    } catch {
      $('#modelStatus').dataset.state = 'error';
      $('#modelStatusText').textContent = '服务未连接';
    }
  }

  function applyDefaults(defaults) {
    $('#optRounds').value = defaults.rounds;
    $('#optRoundsOut').textContent = `${defaults.rounds} 轮`;
    $('#optSeed').value = defaults.seed;
    $('#optMaxRun').value = defaults.max_run;
    $('#optCorpus').value = defaults.corpus_dir;
    $('#optWhitelist').value = defaults.whitelist;
    buildOps(defaults.all_ops, new Set(defaults.ops));
  }

  function buildOps(allOps, enabledSet) {
    const grid = $('#opsGrid');
    grid.innerHTML = '';
    for (const op of allOps) {
      const label = document.createElement('label');
      label.className = 'op-chip' + (RISKY_OPS.has(op) ? ' risky' : '') + (enabledSet.has(op) ? ' on' : '');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = op;
      cb.checked = enabledSet.has(op);
      cb.addEventListener('change', () => {
        label.classList.toggle('on', cb.checked);
        updateParamsHint();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(OP_LABELS[op] || op));
      grid.appendChild(label);
    }
    updateParamsHint();
  }

  function collectParams() {
    const ops = $$('#opsGrid input:checked').map((el) => el.value);
    return {
      rounds: parseInt($('#optRounds').value, 10),
      seed: parseInt($('#optSeed').value, 10) || 0,
      max_run: parseInt($('#optMaxRun').value, 10) || 10,
      ops,
      corpus_dir: $('#optCorpus').value.trim(),
      whitelist: $('#optWhitelist').value.trim(),
    };
  }

  function updateParamsHint() {
    const n = $$('#opsGrid input:checked').length;
    $('#paramsHint').textContent =
      `${$('#optRounds').value} 轮 · 阈值 ${$('#optMaxRun').value} · ${n} 个算子`;
  }

  /* ---------- 加载动画 ---------- */

  const STAGES = {
    rewrite: ['分句与句法分析…', '构建候选池…', '打分与保义校验…', '多轮迭代选优…', '组装与评估报告…'],
    evaluate: ['分句与句法分析…', '与语料库比对…', '统计危险指数…'],
  };
  let stageTimer = null;

  function startLoading(mode) {
    $('#loadingTitle').textContent = mode === 'rewrite' ? '正在改写…' : '正在评估…';
    const stages = STAGES[mode];
    let i = 0;
    $('#loadingStage').textContent = stages[0];
    clearInterval(stageTimer);
    stageTimer = setInterval(() => {
      i = Math.min(i + 1, stages.length - 1);
      $('#loadingStage').textContent = stages[i];
    }, 5000);
  }

  function stopLoading() { clearInterval(stageTimer); stageTimer = null; }

  /* ---------- 动作 ---------- */

  async function withBusy(mode, fn) {
    if (state.busy) return;
    const text = $('#sourceText').value.trim();
    if (!text) {
      toast('文稿内容不能为空', 'warn');
      $('#sourceText').focus();
      return;
    }
    state.busy = true;
    setActionsEnabled(false);
    showState('loading');
    startLoading(mode);
    try {
      await fn(text);
    } catch (e) {
      showState(state.lastResult && state.lastResult.view === 'rewrite' ? 'rewrite' : 'empty');
      toast(e.message || '请求失败', 'error', 7000);
    } finally {
      state.busy = false;
      stopLoading();
      setActionsEnabled(state.modelReady);
    }
  }

  async function doEvaluate() {
    await withBusy('evaluate', async (text) => {
      const data = await api('/api/evaluate', { text, ...collectParams() });
      state.lastResult = { view: 'report', data };
      renderReport(data);
      showState('report');
    });
  }

  async function doRewrite() {
    await withBusy('rewrite', async (text) => {
      const data = await api('/api/rewrite', { text, ...collectParams() });
      state.lastResult = { view: 'rewrite', data };
      renderRewrite(data);
      showState('rewrite');
    });
  }

  /* ---------- 渲染: 指标 ---------- */

  function metricHtml({ label, valueHtml, deltaHtml, sub }) {
    return `<div class="metric">
      <div class="metric-label">${esc(label)}</div>
      <div class="metric-value">${valueHtml}</div>
      <div class="metric-delta ${deltaHtml ? deltaHtml.cls : 'flat'}">${deltaHtml ? deltaHtml.text : '&nbsp;'}</div>
      <div class="metric-sub">${sub ? esc(sub) : '&nbsp;'}</div>
    </div>`;
  }

  function deltaFor(before, after, lowerIsBetter = true) {
    const d = after - before;
    if (Math.abs(d) < 1e-9) return { cls: 'flat', text: '持平' };
    const good = lowerIsBetter ? d < 0 : d > 0;
    const pct = before !== 0 ? ` (${d > 0 ? '+' : ''}${((d / before) * 100).toFixed(0)}%)` : '';
    return { cls: good ? 'good' : 'bad', text: `${d > 0 ? '↑' : '↓'}${Math.abs(d).toFixed(d % 1 ? 1 : 0)}${pct}` };
  }

  function renderReport(data) {
    const r = data.report;
    $('#reportTitle').textContent = `危险指数评估 · ${r.sentences} 句`;
    $('#reportMetrics').innerHTML = [
      metricHtml({
        label: '超阈句数', valueHtml: `<span${r.over_threshold ? ' style="color:var(--warn)"' : ''}>${r.over_threshold}</span>`,
        deltaHtml: null, sub: `忽略标点口径: ${r.over_threshold_loose}`,
      }),
      metricHtml({
        label: '平均最长重合', valueHtml: `${r.avg_max_run}<span style="font-size:12px;font-weight:500;color:var(--ink-3)"> 字符</span>`,
        deltaHtml: null, sub: `忽略标点: ${r.avg_max_run_loose}`,
      }),
      metricHtml({
        label: '全篇最长重合', valueHtml: `${r.max_run}<span style="font-size:12px;font-weight:500;color:var(--ink-3)"> 字符</span>`,
        deltaHtml: null, sub: `忽略标点: ${r.max_run_loose}`,
      }),
      metricHtml({
        label: '比对语料', valueHtml: `${data.corpus_size}<span style="font-size:12px;font-weight:500;color:var(--ink-3)"> 句</span>`,
        deltaHtml: null, sub: 'data/corpus 目录',
      }),
    ].join('');
    renderDangerList(r.top5);
  }

  function renderDangerList(top5) {
    $('#dangerList').innerHTML = top5.map((s, i) => `
      <li class="${s.over ? 'hot' : 'cool'}">
        <span class="danger-rank">${i + 1}</span>
        <span class="danger-body">
          <span class="danger-badge">重合 ${s.max_run} 字</span>${esc(s.sentence)}
          ${s.hit ? `<span class="danger-hit">命中语料: <em>${esc(s.hit)}</em></span>` : ''}
        </span>
      </li>`).join('');
  }

  function renderRewrite(data) {
    const m = data.summary;
    $('#roundsBadge').textContent = `${data.rounds_run} 轮 · 语料 ${data.corpus_size} 句`;

    const overDelta = deltaFor(m.over_before, m.over_after);
    const avgDelta = deltaFor(m.avg_before, m.avg_after);
    $('#rewriteMetrics').innerHTML = [
      metricHtml({
        label: '超阈句数',
        valueHtml: `<span class="from">${m.over_before}</span><span class="arrow">→</span>${m.over_after}`,
        deltaHtml: overDelta, sub: `忽略标点: ${m.over_before_loose} → ${m.over_after_loose}`,
      }),
      metricHtml({
        label: '平均最长重合',
        valueHtml: `<span class="from">${m.avg_before}</span><span class="arrow">→</span>${m.avg_after}`,
        deltaHtml: avgDelta, sub: `忽略标点: ${m.avg_before_loose} → ${m.avg_after_loose}`,
      }),
      metricHtml({
        label: '改动句保义度',
        valueHtml: `${Math.round(m.avg_fidelity * 100)}<span style="font-size:13px;font-weight:500;color:var(--ink-3)">%</span>`,
        deltaHtml: null, sub: `SRL + 依存包含率`,
      }),
      metricHtml({
        label: '改动 / 冻结',
        valueHtml: `${m.changed}<span class="from"> / ${m.frozen}</span>`,
        deltaHtml: null, sub: `共 ${m.sentences} 句 · 冻结为引文保护`,
      }),
    ].join('');

    $('#finalText').textContent = data.text;
    renderSentenceList(data.sentences);
  }

  function renderSentenceList(sentences) {
    const list = $('#sentenceList');
    list.innerHTML = sentences.map((s, i) => {
      const chips = s.frozen
        ? `<span class="chip frozen">引文冻结</span>`
        : (s.changed
          ? s.ops.map((op) => `<span class="chip">${esc(OP_LABELS[op] || op)}</span>`).join('')
          : `<span class="chip unchanged">未改动</span>`);
      const scores = s.changed
        ? `<span class="sent-scores">
             <span>新 <b>${s.novelty.toFixed(2)}</b></span>
             <span>义 <b>${s.fidelity.toFixed(2)}</b></span>
             <span>顺 <b>${s.fluency.toFixed(2)}</b></span>
             <span>重合 <b>${s.max_run_before}</b>→<b>${s.max_run_after}</b></span>
           </span>`
        : `<span class="sent-scores"><span>重合 <b>${s.max_run_before}</b></span></span>`;
      let origHtml, finalHtml;
      if (s.changed) {
        [origHtml, finalHtml] = diffHighlight(s.orig, s.final);
      } else {
        origHtml = esc(s.orig);
        finalHtml = esc(s.orig);
      }
      return `<div class="sent-row" style="--i:${Math.min(i, 14)}">
        <div class="sent-meta">
          <span class="sent-no">#${i + 1}</span>${chips}${scores}
        </div>
        <div class="sent-line sent-orig"><span class="tag">原</span><span>${origHtml}</span></div>
        <div class="sent-line sent-final"><span class="tag">新</span><span>${finalHtml}</span></div>
      </div>`;
    }).join('');
  }

  /* 字符级差异高亮: 掐头去尾, 中间标差异 */
  function diffHighlight(orig, final) {
    const minLen = Math.min(orig.length, final.length);
    let p = 0;
    while (p < minLen && orig[p] === final[p]) p++;
    let s = 0;
    while (s < minLen - p && orig[orig.length - 1 - s] === final[final.length - 1 - s]) s++;
    const aMid = orig.slice(p, orig.length - s);
    const bMid = final.slice(p, final.length - s);
    const tail = s ? orig.slice(orig.length - s) : '';
    const aHtml = esc(orig.slice(0, p))
      + (aMid ? `<mark class="del">${esc(aMid)}</mark>` : '')
      + esc(tail);
    const bHtml = esc(final.slice(0, p))
      + (bMid ? `<mark class="add">${esc(bMid)}</mark>` : '')
      + esc(tail);
    return [aHtml, bHtml];
  }

  /* ---------- 事件绑定 ---------- */

  function bind() {
    const src = $('#sourceText');

    src.addEventListener('input', () => {
      $('#charCount').textContent = `${src.value.length} 字`;
    });

    $('#btnLoadDemo').addEventListener('click', () => {
      src.value = DEMO_TEXT;
      src.dispatchEvent(new Event('input'));
    });

    $('#btnClear').addEventListener('click', () => {
      src.value = '';
      src.dispatchEvent(new Event('input'));
      src.focus();
    });

    $('#btnEvaluate').addEventListener('click', doEvaluate);
    $('#btnRewrite').addEventListener('click', doRewrite);

    $('#btnBackToEdit').addEventListener('click', () => showState('empty'));

    $('#btnNewRun').addEventListener('click', () => {
      const seedEl = $('#optSeed');
      seedEl.value = (parseInt(seedEl.value, 10) || 0) + 1;
      toast(`换一版：种子已调整为 ${seedEl.value}`, 'ok', 2600);
      doRewrite();
    });

    $('#btnCopyText').addEventListener('click', async () => {
      if (!state.lastResult) return;
      try {
        await navigator.clipboard.writeText(state.lastResult.data.text);
        toast('改写稿已复制到剪贴板', 'ok', 2400);
      } catch {
        toast('复制失败，请手动选择文本复制', 'warn');
      }
    });

    $('#btnDownloadTxt').addEventListener('click', () => {
      if (!state.lastResult) return;
      download(`改写稿-${stamp()}.txt`, state.lastResult.data.text);
    });

    $('#btnDownloadJson').addEventListener('click', () => {
      if (!state.lastResult) return;
      const data = { ...state.lastResult.data };
      data.artifacts && delete data.artifacts.report_md;
      download(`改写明细-${stamp()}.json`, JSON.stringify(data, null, 2), 'application/json');
    });

    $('#btnDownloadMd').addEventListener('click', () => {
      if (!state.lastResult || !state.lastResult.data.artifacts) return;
      download(`评估报告-${stamp()}.md`, state.lastResult.data.artifacts.report_md, 'text/markdown');
    });

    // 参数联动
    $('#optRounds').addEventListener('input', (e) => {
      $('#optRoundsOut').textContent = `${e.target.value} 轮`;
      updateParamsHint();
    });
    $('#optMaxRun').addEventListener('input', updateParamsHint);

    // 拖拽 .txt / .md / .docx
    const dz = $('#dropZone');
    ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add('dragover');
    }));
    ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.remove('dragover');
    }));
    dz.addEventListener('drop', async (e) => {
      const file = e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      if (!/\.(txt|md|docx)$/i.test(file.name)) {
        toast('只支持 .txt / .md / .docx 文件', 'warn');
        return;
      }
      if (/\.docx$/i.test(file.name)) {
        // docx 是二进制, 交给后端解析 (前端读不出正文)
        try {
          const b64 = await readAsBase64(file);
          const res = await api('/api/parse', { docx_b64: b64 });
          src.value = res.text;
          src.dispatchEvent(new Event('input'));
          toast(`已载入 ${file.name}（${res.chars} 字）`, 'ok', 2400);
        } catch (err) {
          toast(`docx 解析失败：${err.message}`, 'warn');
        }
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        src.value = String(reader.result || '');
        src.dispatchEvent(new Event('input'));
        toast(`已载入 ${file.name}`, 'ok', 2400);
      };
      reader.readAsText(file, 'utf-8');
    });

    // 快捷键: Ctrl/Cmd + Enter 开始改写
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !state.busy) doRewrite();
    });
  }

  /* ---------- 启动 ---------- */

  bind();
  showState('empty');
  pollStatus();
  state.pollTimer = setInterval(pollStatus, 2500);
})();
