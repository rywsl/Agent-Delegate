"use strict";

const KIND_LABELS = {
  phase: "阶段", system: "会话", message: "回复", thinking: "思考", tool_call: "工具调用",
  tool_result: "工具结果", file_change: "文件变更", todo: "计划", usage: "用量", agent_result: "agent 结束",
  finish: "沙箱结束", error: "错误", stderr: "stderr", log: "日志",
};
const TERMINAL = ["succeeded", "failed", "cancelled", "timeout"];
const STATUS_LABELS = {
  queued: "排队中", preparing: "准备中", running: "运行中", succeeded: "成功",
  failed: "失败", cancelled: "已取消", timeout: "超时",
};

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v; else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fmtTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("zh-CN", { hour12: false });
}

function initTaskPage(taskId, initialStatus) {
  const timeline = document.getElementById("timeline");
  const counter = document.getElementById("ev-count");
  const filterBox = document.getElementById("ev-filters");
  const hidden = new Set(["stderr"]);
  const seenKinds = new Set();
  let after = 0;
  let total = 0;
  let status = initialStatus;

  function addFilter(kind) {
    if (seenKinds.has(kind)) return;
    seenKinds.add(kind);
    const box = el("input", { type: "checkbox" });
    box.checked = !hidden.has(kind);
    box.addEventListener("change", () => {
      if (box.checked) hidden.delete(kind); else hidden.add(kind);
      timeline.querySelectorAll(`.ev.k-${kind}`).forEach((n) => { n.hidden = !box.checked; });
    });
    filterBox.append(el("label", {}, box, KIND_LABELS[kind] || kind));
  }

  function render(ev) {
    addFilter(ev.kind);
    const body = el("details", {}, el("summary", { class: "s" }, ev.summary || "(空)"),
      el("pre", {}, JSON.stringify(ev.data, null, 2)));
    const row = el("div", { class: `ev k-${ev.kind}` },
      el("div", { class: "t", title: ev.ts }, fmtTime(ev.ts)),
      el("div", { class: "k" }, KIND_LABELS[ev.kind] || ev.kind),
      body);
    row.hidden = hidden.has(ev.kind);
    timeline.append(row);
  }

  async function poll() {
    try {
      const resp = await fetch(`/tasks/${taskId}/events?after=${after}`, { headers: { Accept: "application/json" } });
      if (resp.ok) {
        const data = await resp.json();
        for (const ev of data.events) { render(ev); after = ev.seq; total += 1; }
        counter.textContent = `${total} 条事件`;
        if (data.status !== status) {
          const wasActive = !TERMINAL.includes(status);
          status = data.status;
          const badge = document.getElementById("status-badge");
          badge.replaceChildren(el("span", { class: `badge ${status}` }, STATUS_LABELS[status] || status));
          if (wasActive && TERMINAL.includes(status)) { setTimeout(() => location.reload(), 1500); return; }
        }
        if (data.events.length >= 500) { setTimeout(poll, 50); return; }
      }
    } catch (e) { /* retry below */ }
    if (!TERMINAL.includes(status)) setTimeout(poll, 2000);
  }
  poll();
}

document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-copy]");
  if (!target) return;
  navigator.clipboard.writeText(target.getAttribute("data-copy")).then(() => {
    const old = target.textContent;
    target.textContent = "已复制";
    setTimeout(() => { target.textContent = old; }, 1200);
  });
});
