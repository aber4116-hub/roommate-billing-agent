import { api, ApiError, setHouseholdId } from "./api.js";
import { h, append, clear, $, $$, showError, showLoginError, setStatus, toast, badge, option } from "./dom.js";
import {
  balanceClass,
  balanceLabel,
  categoryLabel,
  centsToInput,
  currentMonth,
  formatCents,
  formatDate,
  formatDateTime,
  legacyBillId,
  methodLabel,
  parseYuanToCents,
  shortId,
  splitMethodLabel,
  statusLabel,
  todayISO,
} from "./format.js";
import { state, resetHouseholdState } from "./store.js";

const CATEGORIES = ["electricity", "water", "internet", "trash", "other"];
const CATEGORY_NAMES = {
  electricity: "电费",
  water: "水费",
  internet: "宽带费",
  trash: "垃圾清运费",
  other: "其他",
};
const ROLE_NAMES = { owner: "owner", admin: "admin", member: "member" };
const VIEW_NAMES = [
  "overview",
  "bills",
  "occupancy",
  "rules",
  "payments",
  "settlement",
  "members",
  "audit",
  "agent",
];

let loadSequence = 0;
let bound = false;

function isAdmin() {
  return state.role === "owner" || state.role === "admin";
}

function isOwner() {
  return state.role === "owner";
}

function householdId() {
  return state.householdId;
}

function periodOpen() {
  return state.period?.status === "open";
}

function people() {
  return state.people || [];
}

function personById(id) {
  return people().find((person) => person.id === id) || null;
}

function personName(id) {
  return personById(id)?.display_name || shortId(id);
}

function currentRule() {
  return state.currentRule || state.rules.find((rule) => rule.status === "active") || null;
}

function payableBills() {
  return (state.bills || []).filter((bill) => bill.status === "active");
}

function preview() {
  return state.preview;
}

function previewLine(personId) {
  return preview()?.lines?.find((line) => line.person_id === personId) || null;
}

function previewTotal(key) {
  return Number(preview()?.[key] || 0);
}

function setBusy(button, busy, text = "处理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = text;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function viewButton(name) {
  return $(`#main-nav button[data-view="${name}"]`);
}

function showView(name) {
  if (!VIEW_NAMES.includes(name)) name = "overview";
  showError("");
  state.currentView = name;
  for (const panel of $$("[data-view-panel]")) {
    panel.hidden = panel.dataset.viewPanel !== name;
  }
  for (const button of $$("#main-nav button[data-view]")) {
    button.classList.toggle("active", button.dataset.view === name);
  }
  if (name === "audit" && isAdmin()) loadAudit();
  if (name === "agent") loadConversations(true);
  if (name === "members") {
    renderMembers();
    renderInvites();
  }
}

function showLogin() {
  state.user = null;
  resetHouseholdState();
  setHouseholdId(null);
  $("#login-view").hidden = false;
  $("#app-view").hidden = true;
  showError("");
  showLoginError("");
  $("#login-email")?.focus();
}

function showApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#user-chip").textContent = state.user
    ? `${state.user.display_name} · ${state.user.email}`
    : "";
}

function populateHouseholdSelect() {
  const select = $("#household-select");
  clear(select);
  for (const household of state.households) {
    const role = household.role ? ` · ${ROLE_NAMES[household.role] || household.role}` : "";
    append(select, option(household.id, `${household.name}${role}`, household.id === state.householdId));
  }
  if (!state.households.length) {
    append(select, option("", "还没有账本", true));
  }
  select.disabled = !state.households.length;
}

function hydrateMe(data) {
  state.user = data.user;
  state.households = data.households || [];
  const stored = localStorage.getItem("rba_household");
  const preferred = stored && state.households.some((row) => row.id === stored)
    ? stored
    : state.households[0]?.id || null;
  state.householdId = preferred;
  setHouseholdId(preferred);
  populateHouseholdSelect();
  showApp();
}

async function boot() {
  bindEvents();
  $("#generated-at").textContent = formatDateTime(new Date());
  try {
    const me = await api.me();
    hydrateMe(me.data);
    await selectHousehold(state.householdId, { force: true });
  } catch {
    showLogin();
  }
}

/* ---------------- household loading ---------------- */

async function selectHousehold(id, { force = false } = {}) {
  if (!id) {
    resetHouseholdState();
    state.householdId = null;
    setHouseholdId(null);
    populateHouseholdSelect();
    $("#household-caption").textContent = "还没有账本；请先新建账本并添加人员。";
    renderAll();
    return;
  }
  if (!force && state.householdId === id && state.period) {
    renderAll();
    return;
  }
  const sequence = ++loadSequence;
  state.householdId = id;
  setHouseholdId(id);
  localStorage.setItem("rba_household", id);
  state.period = null;
  state.bills = [];
  state.occupancies = [];
  state.payments = [];
  state.preview = null;
  state.settlements = [];
  state.conversations = [];
  state.activeConversationId = null;
  state.messages = [];
  state.pendingActions = [];
  state.ruleDraft = null;
  state.rulePreview = null;
  const selected = state.households.find((row) => row.id === id);
  state.role = selected?.role || null;
  state.personId = selected?.person_id || null;
  state.households = state.households.map((row) =>
    row.id === id ? { ...row, role: row.role || state.role } : row,
  );
  populateHouseholdSelect();
  try {
    const household = await api.household(id);
    if (sequence !== loadSequence) return;
    state.household = household.data;
    $("#household-caption").textContent = `${state.household.name} · 当前角色 ${ROLE_NAMES[state.role] || state.role || "—"}`;
    await Promise.all([loadPeople(), loadMembers(), loadRules(), loadPeriods()]);
    if (sequence !== loadSequence) return;
    await loadPeriod();
    await loadConversations(true);
    if (isAdmin()) {
      await Promise.all([loadInvites(), loadAudit()]);
    } else {
      state.invites = [];
      state.audit = [];
    }
    if (sequence !== loadSequence) return;
    renderAll();
    setStatus("已加载");
  } catch (error) {
    if (sequence !== loadSequence) return;
    showError(error.message || "加载账本失败");
    setStatus("加载失败", true);
  }
}

async function loadPeople() {
  const data = await api.people(householdId());
  state.people = data.data.items || [];
}

async function loadMembers() {
  const data = await api.members(householdId());
  state.members = data.data.items || [];
}

async function loadRules() {
  const data = await api.rules(householdId());
  state.rules = data.data.items || [];
  state.currentRule = state.rules.find((rule) => rule.status === "active") || null;
  if (state.ruleDraft && !state.rules.some((rule) => rule.id === state.ruleDraft.id)) {
    state.ruleDraft = null;
    state.rulePreview = null;
  }
}

async function loadPeriods() {
  const data = await api.periods(householdId());
  state.periods = data.data.items || [];
  let currentId = null;
  try {
    const ledger = await api.request(`/api/v1/households/${householdId()}/ledger/current`);
    currentId = ledger.data?.period?.id || null;
  } catch {
    currentId = null;
  }
  const previousId = state.period?.id;
  const keep = previousId && state.periods.some((period) => period.id === previousId);
  const selectedId = keep
    ? previousId
    : currentId && state.periods.some((period) => period.id === currentId)
      ? currentId
      : state.periods[0]?.id || null;
  state.period = state.periods.find((period) => period.id === selectedId) || null;
  const select = $("#period-select");
  clear(select);
  for (const period of state.periods) {
    append(
      select,
      option(
        period.id,
        `${period.period_key} · ${statusLabel(period.status)}`,
        period.id === selectedId,
      ),
    );
  }
  if (!state.periods.length) append(select, option("", "没有账期", true));
}

async function loadPeriod() {
  if (!state.period?.id) {
    state.period = null;
    state.bills = [];
    state.occupancies = [];
    state.payments = [];
    state.preview = null;
    state.settlements = [];
    renderAll();
    return;
  }
  const id = state.period.id;
  const [period, occupancies, bills, payments, settlements] = await Promise.all([
    api.period(householdId(), id),
    api.occupancies(householdId(), id),
    api.bills(householdId(), id),
    api.payments(householdId(), id),
    api.settlements(householdId(), id),
  ]);
  state.period = period.data;
  state.occupancies = occupancies.data.items || [];
  state.bills = bills.data.items || [];
  state.payments = payments.data.items || [];
  state.settlements = settlements.data.items || [];
  try {
    const result = await api.settlementPreview(householdId(), id);
    state.preview = result.data;
  } catch (error) {
    state.preview = null;
    if (![404, 409].includes(error.status)) showError(error.message || "结算预览失败");
  }
  state.rulePreview = null;
  renderAll();
}

async function refreshPeriod() {
  await loadPeriod();
  renderAll();
}

async function refreshAll() {
  await Promise.all([loadPeople(), loadMembers(), loadRules()]);
  await loadPeriod();
  if (isAdmin()) {
    await Promise.all([loadInvites(), loadAudit()]);
  }
  renderAll();
}

async function loadAudit() {
  if (!isAdmin() || !householdId()) {
    state.audit = [];
    return;
  }
  try {
    const data = await api.audit(householdId());
    state.audit = data.data.items || [];
    renderAudit();
  } catch (error) {
    state.audit = [];
    if (error.status !== 403) showError(error.message || "审计加载失败");
  }
}

async function loadInvites() {
  if (!isAdmin() || !householdId()) {
    state.invites = [];
    return;
  }
  try {
    const data = await api.invites(householdId());
    state.invites = data.data.items || [];
    renderInvites();
  } catch (error) {
    state.invites = [];
    if (error.status !== 403) showError(error.message || "邀请加载失败");
  }
}

async function loadConversations(openFirst = false) {
  if (!householdId()) {
    state.conversations = [];
    return;
  }
  try {
    const data = await api.conversations(householdId());
    state.conversations = data.data.items || [];
    const active = state.conversations.find((row) => row.id === state.activeConversationId);
    if (!active) state.activeConversationId = state.conversations[0]?.id || null;
    if (openFirst && state.activeConversationId) await openConversation(state.activeConversationId);
    else renderAgent();
  } catch (error) {
    state.conversations = [];
    if (error.status !== 503) showError(error.message || "Agent 会话加载失败");
    renderAgent();
  }
}

/* ---------------- rendering ---------------- */

function renderAll() {
  renderHouseholdHeader();
  renderSetup();
  renderOverview();
  renderBills();
  renderOccupancy();
  renderRules();
  renderPayments();
  renderSettlement();
  renderMembers();
  renderInvites();
  renderAudit();
  renderAgent();
  $("#generated-at").textContent = formatDateTime(new Date());
}

function renderHouseholdHeader() {
  if (!state.householdId) {
    $("#household-caption").textContent = "还没有账本；请先新建账本并添加人员。";
    return;
  }
  $("#household-caption").textContent = state.household
    ? `${state.household.name} · 当前角色 ${ROLE_NAMES[state.role] || state.role || "—"}`
    : "正在加载账本…";
}

function renderSetup() {
  const panel = $("#setup-panel");
  const hasPeople = people().length > 0;
  const hasPeriod = Boolean(state.period);
  const needs = state.householdId && (!hasPeople || !hasPeriod);
  panel.hidden = !needs;
  $("#quick-person-form").hidden = !(needs && !hasPeople && isAdmin());
  $("#period-empty").hidden = !(needs && hasPeople && !hasPeriod && isAdmin());
  const message = !state.householdId
    ? "请先新建账本。"
    : !hasPeople
      ? "这个账本还没有人员；先添加人员，再创建规则和账期。"
      : !hasPeriod
        ? "已有人员；创建账期后即可录入账单。首次使用还需要在“规则”页创建并激活一条规则。"
        : "";
  $("#setup-message").textContent = message;
  $("#period-key").value = $("#period-key").value || currentMonth();
}

function renderOverview() {
  renderStats();
  renderOccupancyInputs();
  renderBillInputs();
  renderLiabilityTable();
  renderBalanceTable();
  renderNotes();
  const canEdit = isAdmin() && periodOpen();
  $("#save-occupancy-btn").disabled = !canEdit;
  $("#period-lock-btn").disabled = !isAdmin() || state.period?.status !== "open";
  $("#period-reopen-btn").disabled = !isAdmin() || state.period?.status !== "locked";
  $("#period-hint").textContent = state.period
    ? `账期 ${state.period.period_key} · 状态 ${statusLabel(state.period.status)} · 版本 ${state.period.version}`
    : "尚无账期。";
}

function renderStats() {
  $("#stat-period").textContent = state.period?.period_key || "—";
  $("#stat-period-status").textContent = state.period
    ? statusLabel(state.period.status)
    : "尚无账期";
  $("#stat-bills").textContent = formatCents(previewTotal("bills_total_cents"));
  $("#stat-paid").textContent = formatCents(previewTotal("payments_total_cents"));
  const balance = previewTotal("balance_total_cents");
  const stat = $("#stat-balance");
  stat.textContent = formatCents(balance);
  stat.className = balanceClass(balance);
}

function renderOccupancyInputs() {
  const grid = $("#occupancy-grid");
  clear(grid);
  if (!state.period) {
    append(grid, h("p", { class: "empty", text: "创建账期后填写入住天数。" }));
    return;
  }
  const byPerson = new Map((state.occupancies || []).map((row) => [row.person_id, row.days]));
  for (const person of people()) {
    const input = h("input", {
      id: `days-${person.slug}`,
      type: "number",
      min: "0",
      max: "31",
      step: "1",
      value: String(byPerson.get(person.id) ?? 0),
      dataset: { testid: "days-input", person: person.slug, personId: person.id },
      disabled: !isAdmin() || !periodOpen(),
    });
    append(
      grid,
      h(
        "div",
        { class: "person" },
        h("h3", { text: person.display_name }),
        h("label", { class: "field-label", for: `days-${person.slug}`, text: "在住天数" }),
        h("div", { class: "input-wrap" }, input, h("span", { class: "unit", text: "天" })),
      ),
    );
  }
}

function renderBillInputs() {
  const grid = $("#bill-input-grid");
  clear(grid);
  const seen = new Set();
  const candidates = payableBills();
  if (!candidates.length) {
    append(grid, h("p", { class: "empty", text: "本账期还没有账单。" }));
    return;
  }
  for (const bill of candidates) {
    if (seen.has(bill.category)) continue;
    seen.add(bill.category);
    const legacy = legacyBillId(bill.category);
    const input = h("input", {
      id: `amount-${legacy}`,
      inputmode: "decimal",
      value: centsToInput(bill.amount_cents),
      dataset: {
        testid: "amount-input",
        bill: legacy,
        billId: bill.id,
        version: bill.version,
        category: bill.category,
      },
      disabled: !isAdmin() || !periodOpen(),
    });
    append(
      grid,
      h(
        "div",
        { class: "person" },
        h(
          "h3",
          {},
          categoryLabel(bill.category),
          bill.name && bill.name !== categoryLabel(bill.category)
            ? h("span", { class: "pill", text: bill.name })
            : null,
        ),
        h("label", { class: "field-label", for: `amount-${legacy}`, text: "账单金额（元）" }),
        h("div", { class: "input-wrap" }, input, h("span", { class: "unit", text: "元" })),
        h(
          "button",
          {
            class: "btn small mt-10",
            type: "button",
            dataset: { saveBill: bill.id, version: bill.version },
            disabled: !isAdmin() || !periodOpen(),
            text: "保存金额",
          },
        ),
      ),
    );
  }
}

function renderLiabilityTable() {
  const head = $("#liability-head");
  const body = $("#liability-body");
  clear(head);
  clear(body);
  const headRow = h("tr", {}, h("th", { text: "账单项目" }));
  for (const person of people()) append(headRow, h("th", { text: person.display_name }));
  append(headRow, h("th", { text: "账单合计" }));
  append(head, headRow);
  const personTotals = new Map(people().map((person) => [person.id, 0]));
  const active = payableBills();
  for (const bill of active) {
    const legacy = legacyBillId(bill.category);
    const row = h(
      "tr",
      {},
      h(
        "td",
        { class: "bill-name" },
        categoryLabel(bill.category),
        h("span", { class: "hint", text: bill.name || "" }),
      ),
    );
    let total = 0;
    for (const person of people()) {
      const allocation = (bill.allocations || []).find(
        (row) => row.person_id === person.id,
      );
      const cents = allocation?.amount_cents || 0;
      total += cents;
      personTotals.set(person.id, (personTotals.get(person.id) || 0) + cents);
      append(
        row,
        h(
          "td",
          {},
          h("span", {
            dataset: { testid: "cell", bill: legacy, person: person.slug, cents: String(cents) },
            text: formatCents(cents),
          }),
        ),
      );
    }
    append(
      row,
      h(
        "td",
        {},
        h("span", {
          dataset: { testid: "bill-total", bill: legacy, cents: String(total) },
          text: formatCents(total),
        }),
      ),
    );
    append(body, row);
  }
  if (!active.length) {
    append(body, h("tr", {}, h("td", { colspan: String(people().length + 2), class: "empty", text: "暂无账单" })));
  }
  const totalRow = h("tr", { class: "total-row" }, h("td", { text: "个人合计" }));
  for (const person of people()) {
    const cents = personTotals.get(person.id) || 0;
    append(
      totalRow,
      h(
        "td",
        {},
        h("span", {
          dataset: { testid: "person-total", person: person.slug, cents: String(cents) },
          text: formatCents(cents),
        }),
      ),
    );
  }
  append(totalRow, h("td", { text: "—" }));
  append(body, totalRow);
  const grand = previewTotal("bills_total_cents") || [...personTotals.values()].reduce((a, b) => a + b, 0);
  const grandNode = $('[data-testid="grand-total"]');
  grandNode.dataset.cents = String(grand);
  grandNode.textContent = formatCents(grand);
}

function renderBalanceTable() {
  const body = $("#balance-body");
  clear(body);
  let sum = 0;
  for (const person of people()) {
    const line = previewLine(person.id);
    const paid = line?.paid_cents || 0;
    const allocated = line?.allocated_cents || 0;
    const balance = line?.balance_cents ?? allocated - paid;
    sum += balance;
    append(
      body,
      h(
        "tr",
        {},
        h("td", { class: "bill-name", text: person.display_name }),
        h(
          "td",
          {},
          h("span", {
            dataset: { testid: "paid-total", person: person.slug, cents: String(paid) },
            text: formatCents(paid),
          }),
        ),
        h(
          "td",
          {},
          h("span", {
            dataset: { testid: "new-total", person: person.slug, cents: String(allocated) },
            text: formatCents(allocated),
          }),
        ),
        h(
          "td",
          {},
          h("span", {
            class: balanceClass(balance),
            dataset: { testid: "balance", person: person.slug, cents: String(balance) },
            text: formatCents(balance),
          }),
        ),
        h(
          "td",
          {},
          h("span", {
            class: balanceClass(balance),
            dataset: { testid: "balance-label", person: person.slug },
            text: balanceLabel(balance),
          }),
        ),
      ),
    );
  }
  if (!people().length) {
    append(body, h("tr", {}, h("td", { colspan: "5", class: "empty", text: "暂无人员" })));
  }
  const node = $("#balance-check");
  node.textContent = formatCents(sum);
  node.className = balanceClass(sum);
}

function renderNotes() {
  const list = $('[data-testid="notes"]');
  clear(list);
  const active = currentRule();
  const owner = active ? personName(active.owner_person_id) : "未设置";
  const methods = active
    ? [...active.items]
        .sort((a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category))
        .map((item) => `${categoryLabel(item.category)}：${splitMethodLabel(item.split_method)}`)
        .join("；")
    : "尚未激活规则";
  append(list, h("li", { text: `当前规则：${methods || "尚未激活"}。零头归属：${owner}。` }));
  append(list, h("li", { text: "金额使用整数分；每笔账单先按权重向下取整，剩余分全部记入零头归属人，逐笔守恒。" }));
  append(list, h("li", { text: "实际已收来自付款记录；规则变更不覆盖历史付款，正式结算保存当时的规则与金额快照。" }));
}

function renderBills() {
  const body = $("#bills-table");
  clear(body);
  if (!state.bills.length) {
    append(body, h("tr", {}, h("td", { colspan: "4", class: "empty", text: "暂无账单" })));
    return;
  }
  for (const bill of state.bills) {
    const editable = isAdmin() && periodOpen() && bill.status === "active";
    const row = h(
      "tr",
      {},
      h(
        "td",
        {},
        h("span", { class: "bill-name", text: bill.name }),
        h("span", { class: "hint", text: `${categoryLabel(bill.category)} · ${shortId(bill.id)}` }),
      ),
      h("td", { text: formatCents(bill.amount_cents) }),
      h("td", {}, badge(bill.status, statusLabel(bill.status))),
    );
    if (!editable) {
      append(row, h("td", { text: bill.status === "active" ? "—" : "不可编辑" }));
    } else {
      const amount = h("input", {
        inputmode: "decimal",
        value: centsToInput(bill.amount_cents),
        dataset: { billAmountFor: bill.id },
        "aria-label": "账单金额",
      });
      const name = h("input", {
        value: bill.name,
        dataset: { billNameFor: bill.id },
        "aria-label": "账单名称",
      });
      append(
        row,
        h(
          "td",
          {},
          h(
            "div",
            { class: "inline-form" },
            name,
            amount,
            h("button", {
              class: "btn small",
              type: "button",
              dataset: { editBill: bill.id, version: bill.version },
              text: "保存",
            }),
            h("button", {
              class: "btn small danger",
              type: "button",
              dataset: { voidBill: bill.id, version: bill.version },
              text: "作废",
            }),
          ),
        ),
      );
    }
    append(body, row);
  }
}

function renderOccupancy() {
  const body = $("#occupancy-table");
  clear(body);
  if (!people().length) {
    append(body, h("tr", {}, h("td", { colspan: "3", class: "empty", text: "暂无人员" })));
    return;
  }
  const byPerson = new Map((state.occupancies || []).map((row) => [row.person_id, row.days]));
  for (const person of people()) {
    append(
      body,
      h(
        "tr",
        {},
        h("td", { class: "bill-name", text: person.display_name }),
        h("td", { text: `${byPerson.get(person.id) ?? 0} 天` }),
        h("td", { text: String(state.period?.version ?? "—") }),
      ),
    );
  }
}

function ruleMethods(rule) {
  const map = {};
  for (const item of rule?.items || []) map[item.category] = item.split_method;
  return map;
}

function renderRules() {
  const current = currentRule();
  const currentBox = $("#rule-current");
  clear(currentBox);
  if (current) {
    append(
      currentBox,
      h(
        "div",
        { class: "grid2" },
        h(
          "div",
          { class: "mini-card" },
          h("h3", { text: `版本 ${current.version_no} · 生效` }),
          h("p", { class: "muted small", text: current.note || "无备注" }),
          h("p", { class: "small", text: `零头归属：${personName(current.owner_person_id)}` }),
        ),
        h(
          "div",
          { class: "mini-card" },
          ...CATEGORIES.map((category) =>
            h("div", {
              class: "kv",
              text: `${categoryLabel(category)}：${splitMethodLabel(ruleMethods(current)[category])}`,
            }),
          ),
        ),
      ),
    );
  } else {
    append(currentBox, h("p", { class: "empty", text: "尚无生效规则；请创建草稿、预览并激活。" }));
  }

  const ownerSelect = $("#rule-owner");
  clear(ownerSelect);
  for (const person of people()) {
    append(ownerSelect, option(person.id, person.display_name, person.id === current?.owner_person_id));
  }
  const itemsBox = $("#rule-items");
  clear(itemsBox);
  const defaults = { electricity: "days", water: "days", internet: "equal_household", trash: "equal_household", other: "equal_household" };
  const methods = { ...defaults, ...ruleMethods(current) };
  for (const category of CATEGORIES) {
    const select = h(
      "select",
      { dataset: { ruleCategory: category } },
      option("days", "按入住天数", methods[category] === "days"),
      option("equal_household", "按户均摊", methods[category] === "equal_household"),
    );
    append(
      itemsBox,
      h(
        "div",
        { class: "mini-card" },
        h("label", { class: "field-label", text: categoryLabel(category) }),
        select,
      ),
    );
  }
  $("#rule-save-draft").disabled = !isAdmin() || !people().length;
  const versions = $("#rule-versions");
  clear(versions);
  for (const rule of state.rules) {
    append(
      versions,
      h(
        "tr",
        {},
        h("td", { text: `v${rule.version_no}` }),
        h("td", {}, badge(rule.status, statusLabel(rule.status))),
        h("td", { text: rule.note || "—" }),
        h("td", { text: personName(rule.owner_person_id) }),
      ),
    );
  }
  renderRulePreview();
}

function renderRulePreview() {
  const box = $("#rule-preview");
  const data = state.rulePreview?.data || state.rulePreview;
  box.hidden = !data;
  $("#rule-activate-btn").hidden = !data;
  $("#rule-preview-btn").hidden = !state.ruleDraft;
  clear(box);
  if (!data) return;
  const rule = data.rule || state.ruleDraft;
  const periods = data.preview?.periods || [];
  append(
    box,
    h("strong", { text: `草稿 v${rule?.version_no ?? "?"} 已预览` }),
    h("p", { class: "small muted", text: `preview hash: ${shortId(data.preview_hash || "", 16)}` }),
  );
  if (!periods.length) {
    append(box, h("p", { class: "small", text: "当前没有开放账期可预览；激活后只影响之后创建的账单。" }));
    return;
  }
  for (const period of periods.slice(0, 3)) {
    append(
      box,
      h("div", {
        class: "small",
        text: `${period.period_key}：账单分摊差异 ${period.changed ? "有变化" : "无变化"}`,
      }),
    );
  }
}

function renderPayments() {
  const select = $("#payment-person");
  const previous = select.value;
  clear(select);
  for (const person of people()) {
    append(select, option(person.id, person.display_name, person.id === previous));
  }
  const body = $("#payments-table");
  clear(body);
  for (const payment of state.payments) {
    append(
      body,
      h(
        "tr",
        {},
        h("td", { text: formatDate(payment.paid_on) }),
        h("td", { text: personName(payment.person_id) }),
        h("td", { text: formatCents(payment.amount_cents) }),
        h("td", { text: methodLabel(payment.method) }),
        h("td", { text: payment.kind === "adjustment" ? "调整" : "付款" }),
      ),
    );
  }
  if (!state.payments.length) {
    append(body, h("tr", {}, h("td", { colspan: "5", class: "empty", text: "尚无实收记录" })));
  }
}

function renderSettlement() {
  const summary = $("#settlement-summary");
  clear(summary);
  const data = preview();
  if (!data) {
    append(summary, h("p", { class: "empty", text: "暂无结算预览；请先创建账期、规则和账单。" }));
  } else {
    const cards = [
      ["账单合计", formatCents(data.bills_total_cents)],
      ["实收合计", formatCents(data.payments_total_cents)],
      ["差额合计", formatCents(data.balance_total_cents)],
      ["账期版本", String(data.period_version)],
    ];
    for (const [label, value] of cards) {
      append(summary, h("div", { class: "stat" }, h("small", { text: label }), h("strong", { text: value })));
    }
  }
  const lines = $("#settlement-lines");
  clear(lines);
  for (const line of data?.lines || []) {
    append(
      lines,
      h(
        "tr",
        {},
        h("td", { text: personName(line.person_id) }),
        h("td", { text: formatCents(line.allocated_cents) }),
        h("td", { text: formatCents(line.paid_cents) }),
        h("td", { class: balanceClass(line.balance_cents), text: formatCents(line.balance_cents) }),
      ),
    );
  }
  if (!data?.lines?.length) {
    append(lines, h("tr", {}, h("td", { colspan: "4", class: "empty", text: "暂无结算行" })));
  }
  $("#settlement-create-btn").disabled = !isAdmin() || state.period?.status !== "locked";
  const table = $("#settlement-table");
  clear(table);
  for (const settlement of state.settlements) {
    append(
      table,
      h(
        "tr",
        {},
        h("td", { text: `r${settlement.revision}` }),
        h("td", {}, badge(settlement.status, statusLabel(settlement.status))),
        h("td", { text: formatCents(settlement.bills_total_cents) }),
        h("td", { text: formatCents(settlement.payments_total_cents) }),
        h("td", { text: formatCents(settlement.balance_total_cents) }),
        h(
          "td",
          {},
          h("button", {
            class: "btn small",
            type: "button",
            dataset: { exportSettlement: settlement.id, filename: `settlement-${state.period?.period_key || "period"}-r${settlement.revision}.csv` },
            text: "导出",
          }),
        ),
      ),
    );
  }
  if (!state.settlements.length) {
    append(table, h("tr", {}, h("td", { colspan: "6", class: "empty", text: "尚无正式结算" })));
  }
}

function renderMembers() {
  const body = $("#members-table");
  clear(body);
  for (const member of state.members) {
    const isSelf = member.user_id === state.user?.id;
    const canChange = isOwner() && member.role !== "owner";
    const actions = h("div", { class: "inline-form" });
    if (canChange) {
      append(
        actions,
        h("button", {
          class: "btn small",
          type: "button",
          dataset: { memberRole: member.user_id, role: member.role === "admin" ? "member" : "admin" },
          text: member.role === "admin" ? "降为 member" : "升为 admin",
        }),
        h("button", {
          class: "btn small danger",
          type: "button",
          dataset: { memberStatus: member.user_id, status: member.status === "active" ? "left" : "active" },
          text: member.status === "active" ? "移出" : "恢复",
        }),
      );
    } else {
      append(actions, h("span", { class: "muted small", text: isSelf ? "当前账户" : "—" }));
    }
    append(
      body,
      h(
        "tr",
        {},
        h("td", { class: "bill-name", text: member.display_name }),
        h("td", { text: member.email }),
        h("td", { text: ROLE_NAMES[member.role] || member.role }),
        h("td", {}, badge(member.status, statusLabel(member.status))),
        h("td", {}, actions),
      ),
    );
  }
  if (!state.members.length) {
    append(body, h("tr", {}, h("td", { colspan: "5", class: "empty", text: "暂无成员" })));
  }
}

function renderInvites() {
  const panel = $("#invites-panel");
  panel.hidden = !isAdmin();
  if (!isAdmin()) return;
  const body = $("#invites-table");
  clear(body);
  for (const invite of state.invites) {
    append(
      body,
      h(
        "tr",
        {},
        h("td", { text: invite.role }),
        h("td", { text: invite.email || "公开邀请" }),
        h("td", { text: formatDate(invite.expires_at) }),
      ),
    );
  }
  if (!state.invites.length) {
    append(body, h("tr", {}, h("td", { colspan: "3", class: "empty", text: "暂无有效邀请" })));
  }
}

function renderAudit() {
  const body = $("#audit-table");
  clear(body);
  if (!isAdmin()) {
    append(body, h("tr", {}, h("td", { colspan: "4", class: "empty", text: "仅 owner/admin 可见" })));
    return;
  }
  for (const row of state.audit || []) {
    append(
      body,
      h(
        "tr",
        {},
        h("td", { text: formatDateTime(row.created_at) }),
        h("td", { text: row.action }),
        h("td", { text: `${row.entity_type} ${shortId(row.entity_id)}` }),
        h("td", { text: shortId(row.actor_user_id) }),
      ),
    );
  }
  if (!state.audit?.length) {
    append(body, h("tr", {}, h("td", { colspan: "4", class: "empty", text: "暂无审计记录" })));
  }
}

function renderAgent() {
  const list = $("#conversation-list");
  clear(list);
  for (const conversation of state.conversations) {
    append(
      list,
      h("button", {
        class: `conversation-item${conversation.id === state.activeConversationId ? " active" : ""}`,
        type: "button",
        dataset: { conversationId: conversation.id },
        text: conversation.title,
      }),
    );
  }
  if (!state.conversations.length) {
    append(list, h("p", { class: "empty", text: "还没有对话" }));
  }
  const log = $("#agent-messages");
  clear(log);
  if (!state.activeConversationId) {
    append(log, h("p", { class: "message system", text: "创建对话后可以向 Agent 提问。" }));
  } else {
    for (const message of state.messages) {
      append(
        log,
        h("div", {
          class: `message ${message.role}`,
          text: message.content || "",
        }),
      );
    }
    if (!state.messages.length) {
      append(log, h("p", { class: "message system", text: "发送第一条消息。" }));
    }
  }
  const pending = $("#agent-pending");
  clear(pending);
  for (const action of state.pendingActions.filter((row) => row.status === "pending")) {
    append(
      pending,
      h(
        "article",
        { class: "pending-card" },
        h("h4", { text: `待确认：${action.action_type}` }),
        h("pre", { text: JSON.stringify(action.preview, null, 2) }),
        h(
          "div",
          { class: "btn-row" },
          h("button", {
            class: "btn primary small",
            type: "button",
            dataset: { confirmAction: action.id, hash: action.payload_hash },
            text: "确认执行",
          }),
          h("button", {
            class: "btn small danger",
            type: "button",
            dataset: { cancelAction: action.id },
            text: "取消",
          }),
        ),
      ),
    );
  }
  $("#agent-form").querySelector("button[type=submit]").disabled = !state.activeConversationId;
}

async function openConversation(conversationId) {
  if (!conversationId) return;
  state.activeConversationId = conversationId;
  try {
    const [conversation, actions] = await Promise.all([
      api.conversation(householdId(), conversationId),
      api.conversationActions(householdId(), conversationId),
    ]);
    state.messages = conversation.data.messages || [];
    state.pendingActions = actions.data.items || [];
    renderAgent();
  } catch (error) {
    if (error.status !== 503) showError(error.message || "会话加载失败");
    renderAgent();
  }
}

/* ---------------- actions ---------------- */

async function saveOccupancies() {
  if (!isAdmin() || !periodOpen()) return toast("当前不可修改入住天数", true);
  const items = people().map((person) => {
    const input = $(`#days-${CSS.escape(person.slug)}`);
    return { person_id: person.id, days: Number(input.value) };
  });
  if (items.some((item) => !Number.isInteger(item.days) || item.days < 0 || item.days > 31)) {
    return toast("入住天数必须是 0–31 的整数", true);
  }
  try {
    await api.setOccupancies(householdId(), state.period.id, state.period.version, items);
    toast("入住天数已保存");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function onNavClick(event) {
  const button = event.target.closest("#main-nav button[data-view]");
  if (!button) return;
  showView(button.dataset.view);
}

async function onBillsTableClick(event) {
  const edit = event.target.closest("[data-edit-bill]");
  if (edit) {
    const id = edit.dataset.editBill;
    const name = $(`input[data-bill-name-for="${CSS.escape(id)}"]`)?.value?.trim();
    const amountInput = $(`input[data-bill-amount-for="${CSS.escape(id)}"]`);
    try {
      const amount = parseYuanToCents(amountInput?.value ?? "");
      await api.updateBill(householdId(), id, {
        expected_version: Number(edit.dataset.version),
        name: name || undefined,
        amount_cents: amount,
      });
      toast("账单已更新");
      await refreshPeriod();
    } catch (error) {
      showError(error.message);
    }
    return;
  }
  const voidButton = event.target.closest("[data-void-bill]");
  if (voidButton) {
    const reason = window.prompt("作废原因（必填）");
    if (!reason) return;
    try {
      await api.voidBill(householdId(), voidButton.dataset.voidBill, {
        expected_version: Number(voidButton.dataset.version),
        reason,
      });
      toast("账单已作废");
      await refreshPeriod();
    } catch (error) {
      showError(error.message);
    }
  }
}

async function onMembersTableClick(event) {
  const roleButton = event.target.closest("[data-member-role]");
  if (roleButton) {
    try {
      await api.updateMember(householdId(), roleButton.dataset.memberRole, {
        role: roleButton.dataset.role,
      });
      toast("成员角色已更新");
      await loadMembers();
      renderMembers();
    } catch (error) {
      showError(error.message);
    }
    return;
  }
  const statusButton = event.target.closest("[data-member-status]");
  if (statusButton) {
    try {
      await api.updateMember(householdId(), statusButton.dataset.memberStatus, {
        status: statusButton.dataset.status,
      });
      toast("成员状态已更新");
      await loadMembers();
      renderMembers();
    } catch (error) {
      showError(error.message);
    }
  }
}

async function onSettlementTableClick(event) {
  const button = event.target.closest("[data-export-settlement]");
  if (!button) return;
  try {
    await api.downloadSettlement(householdId(), button.dataset.exportSettlement, button.dataset.filename);
  } catch (error) {
    showError(error.message);
  }
}

async function onAgentClick(event) {
  const item = event.target.closest("[data-conversation-id]");
  if (item) {
    await openConversation(item.dataset.conversationId);
    return;
  }
  const confirm = event.target.closest("[data-confirm-action]");
  if (confirm) {
    try {
      await api.confirmAction(householdId(), confirm.dataset.confirmAction, confirm.dataset.hash);
      toast("动作已确认");
      await openConversation(state.activeConversationId);
      await refreshPeriod();
    } catch (error) {
      showError(error.message);
    }
    return;
  }
  const cancel = event.target.closest("[data-cancel-action]");
  if (cancel) {
    try {
      await api.cancelAction(householdId(), cancel.dataset.cancelAction);
      toast("动作已取消");
      await openConversation(state.activeConversationId);
    } catch (error) {
      showError(error.message);
    }
  }
}

async function onBillInputClick(event) {
  const button = event.target.closest("[data-save-bill]");
  if (!button) return;
  const input = button.parentElement?.querySelector("input");
  try {
    const amount = parseYuanToCents(input?.value ?? "");
    await api.updateBill(householdId(), button.dataset.saveBill, {
      expected_version: Number(button.dataset.version),
      amount_cents: amount,
    });
    toast("账单金额已保存");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function createPeriod(periodKey) {
  if (!periodKey || !/^\d{4}-(0[1-9]|1[0-2])$/.test(periodKey)) {
    return toast("账期格式必须是 YYYY-MM", true);
  }
  const created = await api.createPeriod(householdId(), periodKey);
  toast("账期已创建");
  await loadPeriods();
  state.period =
    state.periods.find((period) => period.id === created.data.id) || state.period;
  await loadPeriod();
}

async function lockPeriod() {
  if (!state.period) return;
  try {
    await api.lockPeriod(householdId(), state.period.id, state.period.version);
    toast("账期已锁定");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function reopenPeriod() {
  if (!state.period) return;
  const reason = window.prompt("重开原因（必填）");
  if (!reason) return;
  try {
    await api.reopenPeriod(householdId(), state.period.id, state.period.version, reason);
    toast("账期已重开");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function saveRuleDraft() {
  if (!isAdmin()) return toast("需要管理员权限", true);
  const owner = $("#rule-owner").value;
  const note = $("#rule-note").value.trim();
  if (!owner || !note) return toast("请填写零头归属人与变更说明", true);
  const items = $$("#rule-items [data-rule-category]").map((select) => ({
    category: select.dataset.ruleCategory,
    split_method: select.value,
    fallback_method: "equal_household",
  }));
  const button = $("#rule-save-draft");
  setBusy(button, true);
  try {
    const data = await api.createRule(householdId(), { owner_person_id: owner, items, note });
    state.ruleDraft = data.data;
    state.rulePreview = await api.previewRule(householdId(), state.ruleDraft.id);
    renderRules();
    toast("草稿已创建并预览");
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(button, false);
  }
}

async function activateRule() {
  if (!state.ruleDraft || !state.rulePreview) return;
  const active = currentRule();
  const versionNo = active?.version_no || 0;
  try {
    await api.activateRule(householdId(), state.ruleDraft.id, {
      expected_active_version_no: versionNo,
      expected_preview_hash: state.rulePreview.data.preview_hash,
      expected_row_version: state.rulePreview.data.rule.row_version,
    });
    state.ruleDraft = null;
    state.rulePreview = null;
    toast("规则已激活");
    await refreshAll();
  } catch (error) {
    showError(error.message);
  }
}

async function createPayment(event) {
  event.preventDefault();
  const person = $("#payment-person").value;
  try {
    const amount = parseYuanToCents($("#payment-amount").value);
    if (amount <= 0) throw new Error("金额必须大于 0");
    await api.createPayment(householdId(), state.period.id, {
      person_id: person,
      amount_cents: amount,
      paid_on: $("#payment-date").value,
      method: $("#payment-method").value,
    });
    $("#payment-amount").value = "";
    toast("实收已登记");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function createBill(event) {
  event.preventDefault();
  if (!state.period) return toast("请先创建账期", true);
  try {
    const amount = parseYuanToCents($("#bill-amount").value);
    await api.createBill(householdId(), state.period.id, {
      category: $("#bill-category").value,
      name: $("#bill-name").value.trim(),
      amount_cents: amount,
    });
    $("#bill-name").value = "";
    $("#bill-amount").value = "";
    toast("账单已新增");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function createSettlement() {
  if (!preview() || state.period?.status !== "locked") {
    return toast("请先锁定账期并确认预览", true);
  }
  const active = state.settlements.find((row) => row.status === "final");
  if (active) {
    const ok = window.confirm("该账期已有正式结算；确定创建新修订？");
    if (!ok) return;
  }
  try {
    await api.createSettlement(householdId(), state.period.id, {
      expected_period_version: preview().period_version,
      preview_hash: preview().preview_hash,
    });
    toast("正式结算已创建");
    await refreshPeriod();
  } catch (error) {
    showError(error.message);
  }
}

async function createPerson(event, form) {
  event.preventDefault();
  const name = form.querySelector("input[name=display_name], #quick-person-name, #person-name")?.value?.trim();
  const slugInput = form.querySelector("#person-slug");
  if (!name) return toast("请填写显示名", true);
  try {
    await api.createPerson(householdId(), {
      display_name: name,
      slug: slugInput?.value.trim() || null,
    });
    if (slugInput) slugInput.value = "";
    toast("人员已添加");
    await refreshAll();
  } catch (error) {
    showError(error.message);
  }
}

async function createInvite(event) {
  event.preventDefault();
  if (!isAdmin()) return;
  try {
    const data = await api.createInvite(householdId(), {
      role: $("#invite-role").value,
      email: $("#invite-email").value.trim() || null,
    });
    const tokenBox = $("#invite-token");
    tokenBox.hidden = false;
    clear(tokenBox);
    append(tokenBox, h("strong", { text: "邀请已创建（只显示一次）" }), h("div", { class: "code-block", text: data.data.token }));
    $("#invite-email").value = "";
    await loadInvites();
  } catch (error) {
    showError(error.message);
  }
}

async function sendAgentMessage(event) {
  event.preventDefault();
  if (!state.activeConversationId) return;
  const input = $("#agent-input");
  const content = input.value.trim();
  if (!content) return;
  const button = event.submitter || $("#agent-form button[type=submit]");
  setBusy(button, true);
  try {
    const data = await api.sendAgentMessage(householdId(), state.activeConversationId, {
      content,
      client_message_id: globalThis.crypto?.randomUUID?.() ?? null,
    });
    input.value = "";
    state.messages.push({ role: "user", content });
    if (data.data.message) state.messages.push(data.data.message);
    state.pendingActions = data.data.pending_actions || [];
    renderAgent();
    await loadConversations(false);
    toast("Agent 已回复");
  } catch (error) {
    showError(error.message || "Agent 调用失败");
    if (error.status === 503) toast("模型未启用；核心账务功能仍可用", true);
    else toast(error.message || "Agent 调用失败", true);
  } finally {
    setBusy(button, false);
  }
}

async function createConversation() {
  try {
    const data = await api.createConversation(householdId(), "新对话");
    await loadConversations(false);
    await openConversation(data.data.id);
    showView("agent");
  } catch (error) {
    showError(error.message);
  }
}

/* ---------------- binding ---------------- */

function bindEvents() {
  if (bound) return;
  bound = true;
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showLoginError("");
    const button = event.submitter;
    setBusy(button, true);
    try {
      await api.login($("#login-email").value.trim(), $("#login-password").value);
      const me = await api.me();
      hydrateMe(me.data);
      await selectHousehold(state.householdId, { force: true });
    } catch (error) {
      showLoginError(error.message || "登录失败");
    } finally {
      setBusy(button, false);
    }
  });
  $("#logout-btn").addEventListener("click", async () => {
    try {
      await api.logout();
    } catch {
      // 会话可能已失效；仍然回到登录页。
    }
    showLogin();
  });
  window.addEventListener("auth-expired", () => {
    showLogin();
    showLoginError("会话已失效，请重新登录。");
  });
  $("#main-nav").addEventListener("click", onNavClick);
  $("#household-select").addEventListener("change", (event) => selectHousehold(event.target.value));
  $("#new-household-btn").addEventListener("click", () => $("#household-dialog").showModal());
  $("#household-cancel").addEventListener("click", () => $("#household-dialog").close());
  $("#household-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("#household-name").value.trim();
    if (!name) return;
    try {
      const data = await api.createHousehold(name);
      state.households.push({ ...data.data, role: "owner", person_id: null });
      $("#household-dialog").close();
      $("#household-name").value = "";
      state.householdId = data.data.id;
      populateHouseholdSelect();
      await selectHousehold(data.data.id, { force: true });
      toast("账本已创建");
    } catch (error) {
      showError(error.message);
    }
  });
  $("#save-occupancy-btn").addEventListener("click", saveOccupancies);
  $("#period-select").addEventListener("change", async (event) => {
    state.period = state.periods.find((period) => period.id === event.target.value) || null;
    await loadPeriod();
  });
  $("#period-refresh-btn").addEventListener("click", refreshPeriod);
  $("#period-lock-btn").addEventListener("click", lockPeriod);
  $("#period-reopen-btn").addEventListener("click", reopenPeriod);
  $("#period-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await createPeriod($("#period-key").value);
    } catch (error) {
      showError(error.message);
    }
  });
  $("#quick-person-form").addEventListener("submit", (event) => createPerson(event, event.currentTarget));
  $("#person-form").addEventListener("submit", (event) => createPerson(event, event.currentTarget));
  $("#bill-form").addEventListener("submit", createBill);
  $("#bills-table").addEventListener("click", onBillsTableClick);
  $("#bill-input-grid").addEventListener("click", onBillInputClick);
  $("#payment-form").addEventListener("submit", createPayment);
  $("#rule-save-draft").addEventListener("click", saveRuleDraft);
  $("#rule-activate-btn").addEventListener("click", activateRule);
  $("#rule-preview-btn").addEventListener("click", async () => {
    if (!state.ruleDraft) return;
    try {
      state.rulePreview = await api.previewRule(householdId(), state.ruleDraft.id);
      renderRulePreview();
    } catch (error) {
      showError(error.message);
    }
  });
  $("#settlement-preview-btn").addEventListener("click", refreshPeriod);
  $("#settlement-create-btn").addEventListener("click", createSettlement);
  $("#settlement-export-btn").addEventListener("click", async () => {
    const settlement = state.settlements.find((row) => row.status === "final") || state.settlements[0];
    if (!settlement) return toast("尚无正式结算", true);
    try {
      await api.downloadSettlement(householdId(), settlement.id, `settlement-${state.period?.period_key || "period"}-r${settlement.revision}.csv`);
    } catch (error) {
      showError(error.message);
    }
  });
  $("#settlement-table").addEventListener("click", onSettlementTableClick);
  $("#members-table").addEventListener("click", onMembersTableClick);
  $("#invite-form").addEventListener("submit", createInvite);
  $("#audit-refresh-btn").addEventListener("click", loadAudit);
  $("#new-conversation-btn").addEventListener("click", createConversation);
  $("#conversation-list").addEventListener("click", onAgentClick);
  $("#agent-pending").addEventListener("click", onAgentClick);
  $("#agent-form").addEventListener("submit", sendAgentMessage);
  $("#payment-date").value = todayISO();
  $("#period-key").value = currentMonth();
  showView("overview");
}

boot();
