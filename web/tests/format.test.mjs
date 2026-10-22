import assert from "node:assert/strict";
import test from "node:test";

import {
  balanceClass,
  balanceLabel,
  categoryLabel,
  centsToInput,
  formatCents,
  legacyBillId,
  parseYuanToCents,
  splitMethodLabel,
  statusLabel,
} from "../assets/js/format.js";

test("formatCents uses integer cents and groups thousands", () => {
  assert.equal(formatCents(0), "¥0.00");
  assert.equal(formatCents(1), "¥0.01");
  assert.equal(formatCents(12494), "¥124.94");
  assert.equal(formatCents(123456789), "¥1,234,567.89");
  assert.equal(formatCents(-562), "-¥5.62");
});

test("parseYuanToCents is strict about two decimals", () => {
  assert.equal(parseYuanToCents("287.65"), 28765);
  assert.equal(parseYuanToCents("0"), 0);
  assert.equal(parseYuanToCents("89.0"), 8900);
  assert.equal(parseYuanToCents("-5.62"), -562);
  for (const bad of ["", "1.234", "abc", "1,000", ".5", "1."]) {
    assert.throws(() => parseYuanToCents(bad), bad);
  }
});

test("centsToInput round-trips display values", () => {
  assert.equal(centsToInput(28765), "287.65");
  assert.equal(centsToInput(1), "0.01");
  assert.equal(centsToInput(-1), "-0.01");
});

test("category and legacy ids preserve old DOM contract", () => {
  assert.equal(categoryLabel("electricity"), "电费");
  assert.equal(legacyBillId("electricity"), "electric");
  assert.equal(legacyBillId("water"), "water");
  assert.equal(legacyBillId("internet"), "internet");
  assert.equal(legacyBillId("trash"), "trash");
  assert.equal(splitMethodLabel("days"), "按入住天数");
  assert.equal(splitMethodLabel("equal_household"), "按户均摊");
  assert.equal(statusLabel("locked"), "已锁定");
});

test("balance labels and classes", () => {
  assert.equal(balanceClass(1), "positive");
  assert.equal(balanceClass(-1), "negative");
  assert.equal(balanceClass(0), "zero");
  assert.equal(balanceLabel(1), "需补缴");
  assert.equal(balanceLabel(-1), "应退款");
  assert.equal(balanceLabel(0), "无需调整");
});
