// 用 CDP 驱动 Edge/Chrome 截图 (零依赖, Node 22 内置 WebSocket)
// 用法:
//   node tools/web_shot.mjs <url> <out.png> [actions]
//   actions: none (默认) | rewrite  → 载入示例 → 开始改写 → 等结果 → 截图
// 前置: Edge 已用 --remote-debugging-port=9222 启动
const [, , url = 'http://127.0.0.1:8777/', out = 'shot.png', actions = 'none'] = process.argv;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function findTarget() {
  for (let i = 0; i < 30; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
      const page = list.find((t) => t.type === 'page' && t.url.startsWith('http'));
      if (page) return page;
    } catch { /* daemon 未就绪, 重试 */ }
    await sleep(500);
  }
  throw new Error('找不到调试目标, 请确认 Edge 已带 --remote-debugging-port=9222 启动');
}

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const cdp = new Cdp(ws);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && cdp.pending.has(msg.id)) {
        const { resolve, reject } = cdp.pending.get(msg.id);
        cdp.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    };
    return cdp;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression, awaitPromise = false) {
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise, returnByValue: true,
    });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'eval 失败');
    return r.result && r.result.value;
  }
}

async function fullPageShot(cdp, path) {
  const metrics = await cdp.send('Page.getLayoutMetrics');
  const { width, height } = metrics.cssContentSize;
  const shot = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: Math.min(width, 1600), height: Math.min(height, 6000), scale: 1 },
  });
  const { writeFileSync } = await import('node:fs');
  writeFileSync(path, Buffer.from(shot.data, 'base64'));
  console.log(`saved ${path} (${Math.round(width)}x${Math.round(height)})`);
}

const target = await findTarget();
const cdp = await Cdp.connect(target.webSocketDebuggerUrl);
await cdp.send('Page.enable');
await cdp.send('Runtime.enable');

// 导航到目标 URL (若未在目标页)
const current = await cdp.eval('location.href');
if (!String(current).startsWith(url)) {
  await cdp.send('Page.navigate', { url });
  await sleep(1800);
}

if (actions === 'rewrite' || actions === 'evaluate') {
  // 等模型就绪 → 载入示例 → 触发对应动作 → 等结果渲染
  const btn = actions === 'rewrite' ? '#btnRewrite' : '#btnEvaluate';
  const panel = actions === 'rewrite' ? '#stateRewrite' : '#stateReport';
  await cdp.eval(`(async () => {
    const wait = (fn, timeout=90000) => new Promise((res, rej) => {
      const t0 = Date.now();
      const tick = () => {
        if (fn()) return res(true);
        if (Date.now() - t0 > timeout) return rej(new Error('timeout'));
        setTimeout(tick, 400);
      };
      tick();
    });
    await wait(() => !document.querySelector('#btnRewrite').disabled);
    document.querySelector('#btnLoadDemo').click();
    await new Promise(r => setTimeout(r, 300));
    document.querySelector('${btn}').click();
    await wait(() => !document.querySelector('${panel}').classList.contains('hidden'));
    return true;
  })()`, true);
  await sleep(600); // 让入场动画完成
}

await fullPageShot(cdp, out);
process.exit(0);
