/** 金额/日期/标签格式化。所有金额输入输出都以整数分为边界。 */

const CATEGORY_LABELS = {
  electricity: "电费",
  water: "水费",
  internet: "宽带费",
  trash: "垃圾清运费",
  other: "其他",
};

const LEGACY_BILL_IDS = {
  electricity: "electric",
  water: "water",
  internet: "internet",
  trash: "trash",
  other: "other",
};

const METHOD_LABELS = {
  cash: "现金",
  bank: "银行",
  wechat: "微信",
  alipay: "支付宝",
  other: "其他",
};

const STATUS_LABELS = {
  open: "开放",
  locked: "已锁定",
  settled: "已结算",
  active: "生效",
  draft: "草稿",
  archived: "已归档",
  final: "正式",
  superseded: "已替代",
  voided: "已作废",
  pending: "待确认",
  confirmed: "已确认",
  cancelled: "已取消",
  expired: "已过期",
};

export function formatCents(cents) {
  const value = Number.isFinite(Number(cents)) ? Math.trunc(Number(cents)) : 0;
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const yuan = Math.floor(abs / 100);
  const fen = String(abs % 100).padStart(2, "0");
  const grouped = String(yuan).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}¥${grouped}.${fen}`;
}

export function parseYuanToCents(value) {
  const text = String(value ?? "").trim();
  if (!/^[+-]?\d+(\.\d{1,2})?$/.test(text)) {
    throw new Error("金额格式必须是最多两位小数");
  }
  const negative = text.startsWith("-");
  const unsigned = text.replace(/^[+-]/, "");
  const [yuanPart, fenPart = ""] = unsigned.split(".");
  const yuan = Number(yuanPart);
  const fen = Number(fenPart.padEnd(2, "0"));
  if (!Number.isSafeInteger(yuan) || !Number.isSafeInteger(fen)) {
    throw new Error("金额过大");
  }
  const cents = yuan * 100 + fen;
  if (!Number.isSafeInteger(cents)) throw new Error("金额过大");
  return negative ? -cents : cents;
}

export function centsToInput(cents) {
  const value = Number(cents) || 0;
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

export function formatDate(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function todayISO() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category || "其他";
}

export function legacyBillId(category) {
  return LEGACY_BILL_IDS[category] || category || "other";
}

export function methodLabel(method) {
  return METHOD_LABELS[method] || method || "其他";
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}

export function balanceClass(cents) {
  if (cents > 0) return "positive";
  if (cents < 0) return "negative";
  return "zero";
}

export function balanceLabel(cents) {
  if (cents > 0) return "需补缴";
  if (cents < 0) return "应退款";
  return "无需调整";
}

export function splitMethodLabel(method) {
  return method === "days" ? "按入住天数" : "按户均摊";
}

export function shortId(value, length = 8) {
  return value ? String(value).slice(0, length) : "—";
}

export function sumBy(items, key) {
  return (items || []).reduce((total, item) => total + (Number(item[key]) || 0), 0);
}
