#!/usr/bin/env node
/**
 * 阶段 0 审计脚本（只读）：
 * 1. 从旧版单文件 HTML 中原样抽取 split()，验证分摊守恒和边界行为；
 * 2. 用一个最小 DOM 桩执行页面内嵌 IIFE，复现初始页面显示结果；
 * 3. 验证“修改账单金额后，差额合计仍应为 0”这一界面声明是否成立。
 *
 * 用法：
 *   node docs/audits/legacy-split-audit.mjs [html路径]
 *
 * 本脚本不会写入旧版 HTML，也不会访问网络。
 */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultHtml = path.resolve(here, '../../legacy/合租账单分摊器.html');
const htmlPath = process.argv[2] ? path.resolve(process.argv[2]) : defaultHtml;

if (!fs.existsSync(htmlPath)) {
  console.error(`找不到旧版 HTML：${htmlPath}`);
  process.exit(2);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
assert(scriptMatch, '未找到内嵌 <script>');

const pageScript = scriptMatch[1];
const functionStart = pageScript.indexOf('function split(');
const functionEnd = pageScript.indexOf('window.__split = split;');
assert(functionStart >= 0 && functionEnd > functionStart, '未找到 split() 源码边界');

// 在宿主环境执行旧版纯函数，避免依赖浏览器。
const split = new Function(`${pageScript.slice(functionStart, functionEnd)}\nreturn split;`)();

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push({ name, status: 'PASS' });
  } catch (error) {
    results.push({ name, status: 'FAIL', error: error.message });
  }
}
function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}
function assertConservation(name, total, values, expectedLength) {
  assert.equal(values.length, expectedLength ?? values.length, `${name}: 返回长度`);
  assert.equal(sum(values), total, `${name}: 分摊总和应等于账单总额`);
  for (const value of values) {
    assert.ok(Number.isInteger(value), `${name}: 每一项必须是整数分，实际为 ${value}`);
  }
}

// 1. 固定样例：89.00 元按户平摊，零头归小周。
check('89.00 元按户平摊，零头归小周', () => {
  const values = split(8900, [1, 1, 1], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [2966, 2966, 2968]);
  assertConservation('89.00 元按户平摊', 8900, values, 3);
});

// 2. 固定样例：287.65 元按 18/30/30 天分摊。
check('287.65 元按 18/30/30 天分摊', () => {
  const values = split(28765, [18, 30, 30], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [6638, 11063, 11064]);
  assertConservation('287.65 元按天分摊', 28765, values, 3);
});

// 3. 旧规则基线：四笔均按天数，零头分散。验证迁移前余额。
check('旧规则四笔基线合计', () => {
  const days = [18, 30, 30];
  const oldBills = [28765, 9640, 8900, 2000];
  const totals = [0, 0, 0];
  for (const amount of oldBills) {
    const shares = split(amount, days, days, 'spread', 2);
    assertConservation(`旧规则 ${amount}`, amount, shares, 3);
    shares.forEach((value, index) => { totals[index] += value; });
  }
  // 旧页面把电费、水费、宽带费、垃圾清运费全部按入住天数重算；
  // 由于逐笔取整后再求和，结果与“先合计 493.05 元再按天分摊”等价。
  assert.deepEqual(totals, [11378, 18964, 18963]);
});

// 4. 边界：零金额、全零权重、非法权重、备用权重、负金额、单人。
check('零金额仍返回全零且长度正确', () => {
  const values = split(0, [18, 30, 30], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [0, 0, 0]);
  assertConservation('零金额', 0, values, 3);
});

check('权重全零且无备用权重时按人数均分', () => {
  const values = split(2000, [0, 0, 0], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [666, 666, 668]);
  assertConservation('全零权重', 2000, values, 3);
});

check('无效/负数权重被归零，再触发均分备用规则', () => {
  const values = split(1000, [NaN, -5, 'x'], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [333, 333, 334]);
  assertConservation('非法权重', 1000, values, 3);
});

check('主权重全零时使用备用权重', () => {
  const values = split(1000, [0, 0, 0], [1, 1, 2], 'owner', 2);
  assert.deepEqual(Array.from(values), [250, 250, 500]);
  assertConservation('备用权重', 1000, values, 3);
});

check('负金额保持符号且分摊守恒', () => {
  const values = split(-8900, [1, 1, 1], undefined, 'owner', 2);
  assert.deepEqual(Array.from(values), [-2966, -2966, -2968]);
  assertConservation('负金额', -8900, values, 3);
});

check('单人分摊返回全额', () => {
  const values = split(12345, [7], undefined, 'owner', 0);
  assert.deepEqual(Array.from(values), [12345]);
  assertConservation('单人分摊', 12345, values, 1);
});

check('非法零头归属下标回退到最后一人', () => {
  const values = split(100, [1, 1, 1], undefined, 'owner', 99);
  assert.deepEqual(Array.from(values), [33, 33, 34]);
  assertConservation('非法零头下标', 100, values, 3);
});

// 5. 随机性质测试（固定种子，可复现）：整数分、守恒、长度、非 NaN、确定性。
check('固定种子随机输入 5000 组：守恒/整数/确定性', () => {
  let seed = 0x5eed1234;
  function random() {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 0x100000000;
  }
  for (let caseIndex = 0; caseIndex < 5000; caseIndex += 1) {
    const n = 1 + Math.floor(random() * 8);
    const total = Math.floor(random() * 1_000_000_000) - 500_000_000;
    const weights = Array.from({ length: n }, () => {
      const mode = Math.floor(random() * 5);
      if (mode === 0) return 0;
      if (mode === 1) return -random() * 10;
      if (mode === 2) return Number.NaN;
      if (mode === 3) return random();
      return Math.floor(random() * 100);
    });
    const fallback = random() > 0.5
      ? Array.from({ length: n }, () => Math.floor(random() * 10))
      : undefined;
    const remainderMode = random() > 0.5 ? 'owner' : 'spread';
    const owner = Math.floor(random() * (n + 2)) - 1;
    const values = split(total, weights, fallback, remainderMode, owner);
    assert.equal(values.length, n, `case ${caseIndex}: 长度`);
    assert.equal(sum(values), total, `case ${caseIndex}: 守恒`);
    assert.ok(values.every(Number.isInteger), `case ${caseIndex}: 整数`);
    const values2 = split(total, weights, fallback, remainderMode, owner);
    assert.deepEqual(Array.from(values2), Array.from(values), `case ${caseIndex}: 确定性`);
  }
});

// 6. 最小 DOM 桩：执行完整页面脚本，读取初始渲染结果。
function attrsOf(tag) {
  const attrs = {};
  for (const match of tag.matchAll(/([A-Za-z_:][\w:-]*)="([^"]*)"/g)) {
    attrs[match[1]] = match[2];
  }
  return attrs;
}

const elements = [];
const byTestId = new Map();
const byId = new Map();
const inputs = [];

function makeElement(attrs) {
  const element = {
    attrs,
    textContent: '',
    className: '',
    style: {},
    value: attrs.value,
    listeners: [],
    setAttribute(name, value) { this.attrs[name] = String(value); },
    addEventListener(type, handler) { this.listeners.push({ type, handler }); },
  };
  if (attrs['data-testid']) {
    const list = byTestId.get(attrs['data-testid']) ?? [];
    list.push(element);
    byTestId.set(attrs['data-testid'], list);
  }
  if (attrs.id) byId.set(attrs.id, element);
  if (attrs.tag === 'input') inputs.push(element);
  elements.push(element);
  return element;
}

const markup = html.split('<script>')[0];
for (const match of markup.matchAll(/<(input|span|strong|time|div)\b[^>]*>/g)) {
  const attrs = attrsOf(match[0]);
  if (!attrs['data-testid'] && !attrs.id) continue;
  attrs.tag = match[1];
  makeElement(attrs);
}

function querySelector(selector) {
  if (selector.startsWith('#')) return byId.get(selector.slice(1)) ?? null;
  const tokens = [...selector.matchAll(/\[data-testid="([^"]+)"\]|\[data-person="([^"]+)"\]|\[data-bill="([^"]+)"\]/g)];
  const testid = tokens.find((token) => token[1])?.[1];
  if (!testid) return null;
  const person = tokens.find((token) => token[2])?.[2];
  const bill = tokens.find((token) => token[3])?.[3];
  const candidates = byTestId.get(testid) ?? [];
  return candidates.find((element) =>
    (person === undefined || element.attrs['data-person'] === person) &&
    (bill === undefined || element.attrs['data-bill'] === bill)
  ) ?? null;
}

const documentStub = {
  querySelector,
  querySelectorAll(selector) {
    if (selector.includes('[data-testid="days-input"]')) {
      return inputs.filter((element) =>
        ['days-input', 'amount-input'].includes(element.attrs['data-testid']));
    }
    return [];
  },
};

const sandbox = { window: {}, document: documentStub, console };
vm.createContext(sandbox);
vm.runInContext(pageScript, sandbox, { filename: 'legacy-inline.js' });

function text(testid, filters = {}) {
  const found = (byTestId.get(testid) ?? []).find((element) =>
    Object.entries(filters).every(([key, value]) => element.attrs[key] === value));
  return found ? found.textContent : undefined;
}
function cents(testid, filters = {}) {
  const found = (byTestId.get(testid) ?? []).find((element) =>
    Object.entries(filters).every(([key, value]) => element.attrs[key] === value));
  return found ? Number(found.attrs['data-cents']) : undefined;
}
function allCents(testid) {
  return (byTestId.get(testid) ?? []).map((element) => Number(element.attrs['data-cents']));
}

const initial = {
  newTotals: allCents('new-total'),
  paidTotals: allCents('paid-total'),
  balances: allCents('balance'),
  grandTotal: cents('grand-total'),
  balanceCheck: byId.get('balance-check')?.textContent,
  status: byId.get('status')?.textContent,
  cells: {},
};
for (const bill of ['electric', 'water', 'internet', 'trash']) {
  initial.cells[bill] = ['lin', 'zhe', 'zhou'].map((person) =>
    cents('cell', { 'data-bill': bill, 'data-person': person }));
}

check('完整页面脚本可执行并完成初始渲染', () => {
  assert.deepEqual(initial.newTotals, [12494, 18402, 18409]);
  assert.deepEqual(initial.paidTotals, [11378, 18964, 18963]);
  assert.deepEqual(initial.balances, [1116, -562, -554]);
  assert.equal(initial.grandTotal, 49305);
  assert.equal(initial.balanceCheck, '¥0.00');
  assert.match(initial.status, /核对通过/);
});

check('初始四笔账单逐项分摊结果', () => {
  assert.deepEqual(initial.cells.electric, [6638, 11063, 11064]);
  assert.deepEqual(initial.cells.water, [2224, 3707, 3709]);
  assert.deepEqual(initial.cells.internet, [2966, 2966, 2968]);
  assert.deepEqual(initial.cells.trash, [666, 666, 668]);
});

// 7. 修改电费金额后，页面仍显示“差额合计应为 0”的静态声明，但实际不再为 0。
let balanceCheckAfterAmountChange;
check('修改电费后差额合计不为 0（界面声明与实际不一致）', () => {
  const electricInput = inputs.find((element) =>
    element.attrs['data-testid'] === 'amount-input' &&
    element.attrs['data-bill'] === 'electric');
  assert.ok(electricInput, '找到电费输入框');
  electricInput.value = '300.00';
  const handler = electricInput.listeners.find((listener) => listener.type === 'input');
  assert.ok(handler, '找到 input 事件处理器');
  handler.handler();
  balanceCheckAfterAmountChange = byId.get('balance-check')?.textContent;
  assert.notEqual(balanceCheckAfterAmountChange, '¥0.00', '实际差额合计应不再是 0');
});

// 8. 金额解析与边界输入（记录现状，不要求页面通过）。
const observations = [];
const decimalCents = (() => {
  const input = inputs.find((element) =>
    element.attrs['data-testid'] === 'amount-input' &&
    element.attrs['data-bill'] === 'electric');
  input.value = '1.005';
  const handler = input.listeners.find((listener) => listener.type === 'input');
  handler.handler();
  return cents('bill-total', { 'data-bill': 'electric' });
})();
observations.push({
  id: 'decimal-rounding-1.005',
  observed: decimalCents,
  note: '输入 1.005 元时，Math.round(Number(value) * 100) 实际得到 100 分，不是常见的四舍五入 101 分；且三位小数未被拒绝。',
});

const negativeInput = (() => {
  const input = inputs.find((element) =>
    element.attrs['data-testid'] === 'amount-input' &&
    element.attrs['data-bill'] === 'electric');
  input.value = '-10.00';
  const handler = input.listeners.find((listener) => listener.type === 'input');
  handler.handler();
  return {
    billTotalCents: cents('bill-total', { 'data-bill': 'electric' }),
    status: byId.get('status')?.textContent,
    balanceCheck: byId.get('balance-check')?.textContent,
  };
})();
observations.push({
  id: 'negative-amount-not-rejected',
  observed: negativeInput,
  note: '虽然 input 上有 min="0"，但 input 事件处理器没有校验；程序化输入 -10.00 后页面仍显示负账单并提示“核对通过”。',
});

// 9. 大额整数分的浮点精度边界：旧 split() 不是全整数运算。
const largeNumberProbe = (() => {
  const total = 7347996544991231;
  const weights = [574135598, 292763212];
  const shares = split(total, weights, undefined, 'owner', 2);
  return {
    total,
    weights,
    shares: Array.from(shares),
    sum: sum(shares),
    delta: sum(shares) - total,
  };
})();
observations.push({
  id: 'large-number-conservation',
  observed: largeNumberProbe,
  note: '在接近但未超过 Number.MAX_SAFE_INTEGER 的整数分区间，比例计算使用浮点数，分摊合计比总额多 1 分。正常账单范围内未复现，但不满足“整数分运算”的严格约束。',
});

const report = {
  htmlPath: path.relative(process.cwd(), htmlPath) || path.basename(htmlPath),
  htmlSha256: (await import('node:crypto')).createHash('sha256').update(fs.readFileSync(htmlPath)).digest('hex'),
  splitFunctionPresent: true,
  initial,
  balanceCheckAfterAmountChange,
  checks: results,
  observations,
  defects: [
    {
      id: 'D01',
      severity: 'blocker',
      area: '历史实收',
      summary: '页面没有真实历史收款录入能力，所谓“冻结基线”只是首次打开页面时按旧规则自动估算的示例。',
    },
    {
      id: 'D02',
      severity: 'blocker',
      area: '持久化',
      summary: 'frozenPaid 只存在于内存；刷新、换浏览器或重新打开页面后，历史基线和所有编辑都会消失，无法承担正式账目。',
    },
    {
      id: 'D03',
      severity: 'blocker',
      area: '数据模型',
      summary: '没有账期、账本、用户、规则版本、付款流水、结算快照和审计日志；无法支持多用户、多账本或历史追溯。',
    },
    {
      id: 'D04',
      severity: 'major',
      area: '结算校验',
      summary: '“三人差额合计应为 ¥0.00”的静态声明只在历史已收总额等于新账单总额时成立；修改任一账单金额后该合计立即非零，页面只变红而不解释原因。',
    },
    {
      id: 'D05',
      severity: 'major',
      area: '输入校验',
      summary: '负数、三位小数、非整数天数、空值等没有业务校验；金额按浮点元数相乘后取整，1.005 元会被解析为 1.00 元。',
    },
    {
      id: 'D06',
      severity: 'major',
      area: '迁移差异',
      summary: '旧基线把四笔账单全部按入住天数分摊，且逐笔使用 spread 零头；新规则对宽带和垃圾清运费按户平摊、零头归小周。迁移时必须保留旧基线作为“示例/待核对”而不是真实收款。',
    },
    {
      id: 'D07',
      severity: 'major',
      area: '算法实现',
      summary: '小额账单守恒测试通过，但比例金额使用 Number 浮点运算；接近 MAX_SAFE_INTEGER 时出现 1 分误差，不符合严格的整数分算法要求。',
    },
    {
      id: 'D08',
      severity: 'major',
      area: '审计与权限',
      summary: '任何修改都无版本、无操作者、无审计；页面对所有人开放，没有登录、权限或账本隔离。',
    },
  ],
  summary: {
    passed: results.filter((result) => result.status === 'PASS').length,
    failed: results.filter((result) => result.status === 'FAIL').length,
    total: results.length,
    defects: 8,
  },
};

console.log(JSON.stringify(report, null, 2));
if (report.summary.failed > 0) process.exit(1);
