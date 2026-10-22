/**
 * 浏览器 E2E（本地演示数据库）。
 *
 * 前置：
 *   - 已启动 uvicorn，APP_BASE_URL 与 APP_URL 一致；
 *   - 已运行 scripts/seed_demo.py；
 *   - Chrome 以 --remote-debugging-port=9222 启动。
 *
 * 运行：
 *   $env:APP_URL="http://127.0.0.1:8765"
 *   $env:DEMO_EMAIL="demo@example.com"
 *   $env:DEMO_PASSWORD="..."
 *   node scripts/e2e_frontend.mjs
 */
import fs from "node:fs";

const APP_URL = process.env.APP_URL || "http://127.0.0.1:8765";
const CDP_URL = process.env.CDP_URL || "http://127.0.0.1:9222";
const EMAIL = process.env.DEMO_EMAIL || "demo@example.com";
const PASSWORD = process.env.DEMO_PASSWORD || "";
if (!PASSWORD) throw new Error("set DEMO_PASSWORD for the demo database");
const SCREENSHOT = process.env.E2E_SCREENSHOT || "";

const targets = await (await fetch(`${CDP_URL}/json`)).json();
const page = targets.find((target) => target.type === "page" && target.url.startsWith(APP_URL));
if (!page) throw new Error("没有找到应用页面目标");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let commandId = 0;
const pending = new Map();
const exceptions = [];
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
    return;
  }
  if (message.method === "Runtime.exceptionThrown") {
    exceptions.push(
      message.params.exceptionDetails.exception?.description ||
        message.params.exceptionDetails.text,
    );
  }
};
await new Promise((resolve, reject) => {
  ws.onopen = resolve;
  ws.onerror = reject;
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++commandId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
const js = async (expression) => {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(
      result.exceptionDetails.exception?.description ||
        result.exceptionDetails.text ||
        "JS exception",
    );
  }
  return result.result?.value;
};
const waitFor = async (expression, timeout = 12000) => {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await js(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 120));
  }
  throw new Error(`等待超时：${expression}`);
};
const text = (selector) => js(`document.querySelector(${JSON.stringify(selector)})?.textContent || ""`);
const count = (selector) => js(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
const click = (selector) =>
  js(`document.querySelector(${JSON.stringify(selector)})?.click(); true`);
const fill = (selector, value) =>
  js(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) throw new Error('missing ${selector}');
    el.value = ${JSON.stringify(value)};
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);

await send("Runtime.enable");
await send("Page.enable");
await send("Network.enable");
await send("Network.clearBrowserCookies");
await send("Page.navigate", { url: `${APP_URL}/` });
await waitFor("document.readyState === 'complete'");
await waitFor("!!document.querySelector('#login-form')");

await fill("#login-email", EMAIL);
await fill("#login-password", PASSWORD);
await click("#login-form button[type=submit]");
await waitFor("document.querySelector('#app-view')?.hidden === false");
await waitFor("document.querySelectorAll('[data-testid=cell]').length > 0");

const initial = {
  cells: await count("[data-testid=cell]"),
  billTotals: await count("[data-testid=bill-total]"),
  personTotals: await count("[data-testid=person-total]"),
  grand: await text("[data-testid=grand-total]"),
  days: await count("[data-testid=days-input]"),
  amounts: await count("[data-testid=amount-input]"),
};
if (initial.cells !== 12 || initial.billTotals !== 4 || initial.personTotals !== 3) {
  throw new Error(`旧 DOM 契约不完整：${JSON.stringify(initial)}`);
}
if (!initial.grand.includes("493.05")) {
  throw new Error(`初始总账单异常：${initial.grand}`);
}

if (SCREENSHOT) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1365,
    height: 1200,
    deviceScaleFactor: 1,
    mobile: false,
  });
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(SCREENSHOT, Buffer.from(shot.data, "base64"));
}

await click("#main-nav button[data-view=rules]");
await waitFor("document.querySelector('#view-rules')?.hidden === false");
await fill("#rule-note", "E2E 规则草稿");
await click("#rule-save-draft");
await waitFor("document.querySelector('#rule-activate-btn')?.hidden === false");
await click("#rule-activate-btn");
await waitFor("document.querySelector('#rule-current')?.textContent.includes('版本 2')");
await click("#main-nav button[data-view=overview]");
const billsBefore = await count("#bills-table tr");
await click("#main-nav button[data-view=bills]");
await waitFor("document.querySelector('#view-bills')?.hidden === false");
await fill("#bill-name", "E2E 新增水费");
await fill("#bill-amount", "10.00");
await click("#bill-form button[type=submit]");
await waitFor(`document.querySelectorAll('#bills-table tr').length === ${billsBefore + 1}`);
await waitFor("document.querySelector('[data-testid=grand-total]')?.textContent.includes('503.05')");

const paymentsBefore = await count("#payments-table tr");
await click("#main-nav button[data-view=payments]");
await fill("#payment-amount", "50.00");
await click("#payment-form button[type=submit]");
await waitFor(`document.querySelectorAll('#payments-table tr').length === ${paymentsBefore + 1}`);

await click("#main-nav button[data-view=overview]");
await click("#period-lock-btn");
await waitFor("document.querySelector('#period-reopen-btn')?.disabled === false");

await click("#main-nav button[data-view=settlement]");
await waitFor("document.querySelector('#settlement-create-btn')?.disabled === false");
await click("#settlement-create-btn");
await waitFor("document.querySelectorAll('#settlement-table tr').length > 0");
await waitFor("!!document.querySelector('#settlement-table .badge.final')");

const settlementHref = await js(`(() => {
  const button = document.querySelector('[data-export-settlement]');
  return button ? button.dataset.exportSettlement : '';
})()`);
if (!settlementHref) throw new Error("没有结算导出按钮");
const csv = await js(`(async () => {
  const response = await fetch('/api/v1/households/' + document.querySelector('#household-select').value + '/settlements/${settlementHref}/export', { credentials: 'include' });
  return { status: response.status, text: await response.text() };
})()`);
if (csv.status !== 200 || !csv.text.includes("period")) {
  throw new Error(`CSV 导出失败：${JSON.stringify(csv)}`);
}

await click("#main-nav button[data-view=rules]");
await waitFor("document.querySelector('#view-rules')?.hidden === false");
if (!(await text("#rule-current")).includes("版本")) throw new Error("当前规则未显示");

await click("#main-nav button[data-view=audit]");
await waitFor("document.querySelector('#view-audit')?.hidden === false");
await waitFor("document.querySelectorAll('#audit-table tr').length > 0");

await click("#main-nav button[data-view=agent]");
await click("#new-conversation-btn");
await waitFor("document.querySelectorAll('#conversation-list .conversation-item').length > 0");
await fill("#agent-input", "帮我录入 100 元电费");
await click("#agent-form button[type=submit]");
await waitFor("document.querySelector('#global-error')?.hidden === false");
const agentError = await text("#global-error");
if (!agentError.includes("Agent")) throw new Error(`Agent 禁用提示异常：${agentError}`);

await click("#main-nav button[data-view=overview]");
const final = {
  grand: await text("[data-testid=grand-total]"),
  cells: await count("[data-testid=cell]"),
  status: await text("#status"),
  caption: await text("#household-caption"),
  error: await text("#global-error"),
};
console.log(
  JSON.stringify(
    {
      initial,
      final,
      csvBytes: csv.text.length,
      agentError,
      exceptions,
    },
    null,
    2,
  ),
);
if (final.error) throw new Error(`全局错误未清理：${final.error}`);
if (exceptions.length) throw new Error(`浏览器异常：${exceptions.join(" | ")}`);
ws.close();
