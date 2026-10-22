/** 同源 API 客户端：Cookie、CSRF、账本头、幂等键。 */

export class ApiError extends Error {
  constructor(message, { status = 0, code = "UNKNOWN", details = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let householdId = null;

export function setHouseholdId(value) {
  householdId = value || null;
}

export function getHouseholdId() {
  return householdId;
}

export function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function cookie(name) {
  const prefix = `${name}=`;
  for (const row of document.cookie.split(";")) {
    const part = row.trim();
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return "";
}

async function ensureCsrf() {
  let token = cookie("rba_csrf");
  if (token) return token;
  const response = await fetch("/api/v1/auth/csrf", {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) return "";
  const data = await response.json().catch(() => null);
  return data?.data?.csrf_token || cookie("rba_csrf");
}

async function parseResponse(response) {
  const type = response.headers.get("content-type") || "";
  if (response.status === 204) return null;
  if (type.includes("application/json")) return response.json();
  return response.text();
}

export async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined && options.body !== null) {
    headers["Content-Type"] = "application/json";
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = await ensureCsrf();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const targetHousehold = options.householdId ?? householdId;
  if (targetHousehold) headers["X-Household-ID"] = targetHousehold;

  const response = await fetch(path, {
    method,
    headers,
    credentials: "include",
    cache: "no-store",
    body:
      options.body !== undefined && options.body !== null
        ? JSON.stringify(options.body)
        : undefined,
  });
  const data = await parseResponse(response);
  if (!response.ok) {
    const error = data?.error || {};
    if (response.status === 401 && !path.endsWith("/auth/login")) {
      window.dispatchEvent(new CustomEvent("auth-expired"));
    }
    throw new ApiError(error.message || `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      code: error.code || "HTTP_ERROR",
      details: data,
    });
  }
  return data;
}

export const api = {
  request,
  login(email, password) {
    return request("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    });
  },
  logout() {
    return request("/api/v1/auth/logout", { method: "POST" });
  },
  me() {
    return request("/api/v1/auth/me");
  },
  changePassword(currentPassword, newPassword) {
    return request("/api/v1/auth/password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    });
  },
  acceptInvite(token) {
    return request("/api/v1/auth/invites/accept", {
      method: "POST",
      body: { token },
    });
  },
  households() {
    return request("/api/v1/households");
  },
  createHousehold(name) {
    return request("/api/v1/households", { method: "POST", body: { name } });
  },
  household(id) {
    return request(`/api/v1/households/${id}`);
  },
  people(id) {
    return request(`/api/v1/households/${id}/people`);
  },
  createPerson(id, body) {
    return request(`/api/v1/households/${id}/people`, { method: "POST", body });
  },
  members(id) {
    return request(`/api/v1/households/${id}/members`);
  },
  updateMember(id, userId, body) {
    return request(`/api/v1/households/${id}/members/${userId}`, {
      method: "PATCH",
      body,
    });
  },
  invites(id) {
    return request(`/api/v1/households/${id}/invites`);
  },
  createInvite(id, body) {
    return request(`/api/v1/households/${id}/invites`, { method: "POST", body });
  },
  audit(id, beforeId) {
    const query = beforeId ? `?before_id=${encodeURIComponent(beforeId)}` : "";
    return request(`/api/v1/households/${id}/audit-logs${query}`);
  },
  periods(id) {
    return request(`/api/v1/households/${id}/periods`);
  },
  createPeriod(id, periodKey) {
    return request(`/api/v1/households/${id}/periods`, {
      method: "POST",
      body: { period_key: periodKey },
    });
  },
  period(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}`);
  },
  occupancies(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}/occupancies`);
  },
  setOccupancies(id, periodId, expectedVersion, items) {
    return request(`/api/v1/households/${id}/periods/${periodId}/occupancies`, {
      method: "PUT",
      body: { expected_version: expectedVersion, items },
    });
  },
  lockPeriod(id, periodId, expectedVersion) {
    return request(`/api/v1/households/${id}/periods/${periodId}/lock`, {
      method: "POST",
      body: { expected_version: expectedVersion },
    });
  },
  reopenPeriod(id, periodId, expectedVersion, reason) {
    return request(`/api/v1/households/${id}/periods/${periodId}/reopen`, {
      method: "POST",
      body: { expected_version: expectedVersion, reason },
    });
  },
  bills(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}/bills`);
  },
  createBill(id, periodId, body) {
    return request(`/api/v1/households/${id}/periods/${periodId}/bills`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  updateBill(id, billId, body) {
    return request(`/api/v1/households/${id}/bills/${billId}`, {
      method: "PATCH",
      body,
    });
  },
  voidBill(id, billId, body) {
    return request(`/api/v1/households/${id}/bills/${billId}/void`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  payments(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}/payments`);
  },
  createPayment(id, periodId, body) {
    return request(`/api/v1/households/${id}/periods/${periodId}/payments`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  rules(id) {
    return request(`/api/v1/households/${id}/rule-versions`);
  },
  createRule(id, body) {
    return request(`/api/v1/households/${id}/rule-versions`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  previewRule(id, ruleId) {
    return request(`/api/v1/households/${id}/rule-versions/${ruleId}/preview`, {
      method: "POST",
      body: {},
    });
  },
  activateRule(id, ruleId, body) {
    return request(`/api/v1/households/${id}/rule-versions/${ruleId}/activate`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  settlementPreview(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}/settlement-preview`);
  },
  settlements(id, periodId) {
    return request(`/api/v1/households/${id}/periods/${periodId}/settlements`);
  },
  settlement(id, settlementId) {
    return request(`/api/v1/households/${id}/settlements/${settlementId}`);
  },
  createSettlement(id, periodId, body) {
    return request(`/api/v1/households/${id}/periods/${periodId}/settlements`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body,
    });
  },
  conversations(id) {
    return request(`/api/v1/households/${id}/agent/conversations`);
  },
  createConversation(id, title = null) {
    return request(`/api/v1/households/${id}/agent/conversations`, {
      method: "POST",
      body: { title },
    });
  },
  conversation(id, conversationId) {
    return request(
      `/api/v1/households/${id}/agent/conversations/${conversationId}`,
    );
  },
  conversationActions(id, conversationId) {
    return request(
      `/api/v1/households/${id}/agent/conversations/${conversationId}/actions`,
    );
  },
  sendAgentMessage(id, conversationId, body) {
    return request(
      `/api/v1/households/${id}/agent/conversations/${conversationId}/messages`,
      { method: "POST", body },
    );
  },
  confirmAction(id, actionId, payloadHash) {
    return request(`/api/v1/households/${id}/actions/${actionId}/confirm`, {
      method: "POST",
      headers: { "Idempotency-Key": newIdempotencyKey() },
      body: { expected_payload_hash: payloadHash },
    });
  },
  cancelAction(id, actionId) {
    return request(`/api/v1/households/${id}/actions/${actionId}/cancel`, {
      method: "POST",
    });
  },
  async downloadSettlement(id, settlementId, filename) {
    const response = await fetch(
      `/api/v1/households/${id}/settlements/${settlementId}/export`,
      { credentials: "include", headers: householdId ? { "X-Household-ID": householdId } : {} },
    );
    if (!response.ok) {
      throw new ApiError("导出失败", { status: response.status, code: "EXPORT_FAILED" });
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename || "settlement.csv";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
};
