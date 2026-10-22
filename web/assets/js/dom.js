/** 无 innerHTML 的 DOM 构建与页面提示。 */

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "text") el.textContent = String(value);
    else if (key === "html") throw new Error("innerHTML is not allowed");
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in el) {
      el[key] = value;
    } else {
      el.setAttribute(key, String(value));
    }
  }
  append(el, children);
  return el;
}

export function append(parent, ...children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function text(value, className = "") {
  return h("span", { class: className, text: value ?? "—" });
}

export function $(selector, root = document) {
  return root.querySelector(selector);
}

export function $$(selector, root = document) {
  return [...root.querySelectorAll(selector)];
}

export function setStatus(message, isError = false) {
  const node = $("#status");
  if (!node) return;
  node.textContent = message;
  node.className = isError ? "status positive" : "status";
}

export function showError(message = "") {
  const node = $("#global-error");
  if (!node) return;
  node.textContent = message;
  node.hidden = !message;
}

export function showLoginError(message = "") {
  const node = $("#login-error");
  if (!node) return;
  node.textContent = message;
  node.hidden = !message;
}

let toastTimer = null;
export function toast(message, isError = false) {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.className = isError ? "toast error" : "toast";
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.hidden = true;
  }, 3600);
}

export function badge(status, label = status) {
  return h("span", { class: `badge ${status || ""}`, text: label || "—" });
}

export function option(value, label, selected = false) {
  return h("option", { value, text: label, selected });
}

export function formValue(form, name) {
  return new FormData(form).get(name)?.toString() ?? "";
}
