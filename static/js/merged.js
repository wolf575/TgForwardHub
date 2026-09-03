const $ = (id) => document.getElementById(id);

function setMessage(id, text) {
  const el = $(id);
  el.textContent = text;
  el.hidden = !text;
}

async function apiFetch(url, options = {}) {
  const headers = options.body ? { "Content-Type": "application/json" } : {};
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      message = data.error || message;
    } catch (_) {}
    throw new Error(message);
  }
  return res.json();
}

function switchTab(tabId) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabId);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabId}`);
  });
}

async function loadStatus() {
  try {
    const status = await apiFetch("/api/status");
    const pill = $("clientStatus");
    pill.textContent = status.user_client_ready
      ? "用户客户端已连接"
      : "用户客户端未就绪";
    pill.style.color = status.user_client_ready ? "var(--success)" : "var(--danger)";
  } catch (error) {
    $("clientStatus").textContent = "状态读取失败";
  }
}

function historySubtitle(item) {
  const parts = [];
  if (item.sourceId) parts.push(`来源: ${item.sourceId}`);
  if (item.targetId) parts.push(`目标: ${item.targetId}`);
  if (item.status) parts.push(item.status);
  return parts.join(" · ");
}

async function loadHistory() {
  const body = $("historyBody");
  body.textContent = "";
  const items = await apiFetch("/api/history");
  if (!items.length) {
    body.textContent = "暂无历史记录";
    return;
  }

  for (const item of items) {
    const card = document.createElement("div");
    card.className = "history-item";
    const title = document.createElement("strong");
    title.textContent = item.taskName || item.targetId || "未命名任务";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = historySubtitle(item);
    card.append(title, meta);

    card.addEventListener("click", () => {
      const state = item.state || {};
      $("taskName").value = state.taskName || item.taskName || "";
      $("sourceId").value = state.sourceId || item.sourceId || "";
      $("targetId").value = state.targetId || item.targetId || "";
      $("rangeType").value = state.rangeType || "id";
      $("startValue").value = state.startValue || "";
      $("endValue").value = state.endValue || "";
      $("forwardMode").value = state.forwardMode || "clone";
      $("excludeKeywords").value = state.excludeKeywords || "";
      $("removeKeywords").value = state.removeKeywords || "";
      $("descFlag").checked = !!state.desc;
      setMessage("batchMessage", `已恢复任务: ${title.textContent}`);
    });

    const detail = document.createElement("pre");
    detail.textContent = JSON.stringify(item.task_spec || item.state || {}, null, 2);
    card.appendChild(detail);
    body.appendChild(card);
  }
}

let pollingTimer = null;

function updateMonitor(data) {
  $("jobId").textContent = data.jobId ? `jobId: ${data.jobId}` : "";
  $("jobStatus").textContent = data.status || "等待";
  const progress = data.progress || {};
  $("processedCount").textContent = progress.processed ?? 0;
  $("successCount").textContent = progress.success ?? 0;
  $("failedCount").textContent = progress.failed ?? 0;
  $("skippedCount").textContent = progress.skipped ?? 0;
  $("jobLog").value = data.stdoutTail || data.stderrTail || "";
  $("cancelBtn").hidden = data.status !== "running";
}

async function pollBatch(jobId) {
  if (pollingTimer) clearTimeout(pollingTimer);
  try {
    const data = await apiFetch(`/api/batch-forward/${jobId}`);
    updateMonitor(data);
    if (["done", "error", "cancelled"].includes(data.status)) {
      setMessage("batchMessage", `任务 ${data.status}`);
      loadHistory();
      return;
    }
  } catch (error) {
    setMessage("batchMessage", error.message);
  }
  pollingTimer = setTimeout(() => pollBatch(jobId), 1200);
}

async function submitBatch(event) {
  event.preventDefault();
  setMessage("batchMessage", "");
  $("cancelBtn").hidden = true;

  const spec = {
    task_name: $("taskName").value.trim(),
    source: $("sourceId").value.trim(),
    target: $("targetId").value.trim(),
    range_type: $("rangeType").value,
    start: $("startValue").value.trim(),
    end: $("endValue").value.trim(),
    forward_mode: $("forwardMode").value,
    reverse: $("descFlag").checked,
    exclude_keywords: $("excludeKeywords").value,
    remove_keywords: $("removeKeywords").value,
  };

  try {
    const result = await apiFetch("/api/batch-forward", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    $("jobId").textContent = `jobId: ${result.jobId}`;
    $("jobStatus").textContent = "running";
    $("cancelBtn").hidden = false;
    pollBatch(result.jobId);
  } catch (error) {
    setMessage("batchMessage", error.message);
  }
}

async function cancelBatch() {
  const text = $("jobId").textContent;
  const jobId = text.replace(/^jobId:\s*/, "").trim();
  if (!jobId) return;
  await apiFetch(`/api/batch-forward/${jobId}/cancel`, { method: "POST" });
  $("jobStatus").textContent = "cancelled";
  $("cancelBtn").hidden = true;
}

function parseList(value) {
  return String(value || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function fillFromTelegramLink(input) {
  const value = String(input.value || "").trim();
  const match = value.match(
    /^https?:\/\/t\.me\/(?:c\/(\d+)\/(\d+)|([A-Za-z0-9_]+)\/(\d+))/i
  );
  if (!match) return false;

  if (match[1]) {
    $("sourceId").value = match[1];
    input.value = match[2];
  } else if (match[3]) {
    $("sourceId").value = `@${match[3]}`;
    input.value = match[4];
  }
  return true;
}

["startValue", "endValue"].forEach((id) => {
  $(id).addEventListener("change", () => fillFromTelegramLink($(id)));
});

async function loadWatchConfig() {
  const config = await apiFetch("/api/watch-config");
  const list = $("watchList");
  list.textContent = "";
  let count = 0;
  for (const [userId, watches] of Object.entries(config || {})) {
    for (const [key, watch] of Object.entries(watches || {})) {
      count += 1;
      const item = document.createElement("div");
      item.className = "item";
      const head = document.createElement("div");
      head.className = "item-head";
      const strong = document.createElement("strong");
      strong.textContent = `${key} · ${watch.source || "未知来源"}`;
      const del = document.createElement("button");
      del.className = "danger small";
      del.textContent = "删除";
      del.addEventListener("click", async () => {
        await apiFetch(`/api/watch-config/${encodeURIComponent(userId)}/${encodeURIComponent(key)}`, {
          method: "DELETE",
        });
        loadWatchConfig();
      });
      head.append(strong, del);
      const p = document.createElement("p");
      p.textContent = JSON.stringify(watch, null, 2);
      item.append(head, p);
      list.appendChild(item);
    }
  }
  if (!count) list.textContent = "暂无监控规则";
}

async function saveWatch(event) {
  event.preventDefault();
  setMessage("watchMessage", "");
  const watch = {
    source: $("watchSource").value.trim(),
    dest: $("watchDest").value.trim(),
    record_mode: $("watchMode").value === "record",
    forward_mode: $("watchForwardMode").value,
    preserve_forward_source: $("watchPreserve").checked,
    whitelist: parseList($("watchWhitelist").value),
    blacklist: parseList($("watchBlacklist").value),
    whitelist_regex: [],
    blacklist_regex: [],
  };

  try {
    await apiFetch("/api/watch-config", {
      method: "POST",
      body: JSON.stringify({
        user_id: $("watchUser").value.trim(),
        key: $("watchKey").value.trim(),
        watch,
      }),
    });
    setMessage("watchMessage", "规则已保存");
    loadWatchConfig();
  } catch (error) {
    setMessage("watchMessage", error.message);
  }
}

async function loadNotes() {
  const search = $("noteSearch").value.trim();
  const data = await apiFetch(`/api/notes?search=${encodeURIComponent(search)}`);
  const list = $("notesList");
  list.textContent = "";
  if (!data.notes.length) {
    list.textContent = "暂无笔记";
    return;
  }
  for (const note of data.notes) {
    const item = document.createElement("div");
    item.className = "item";
    const head = document.createElement("div");
    head.className = "item-head";
    const strong = document.createElement("strong");
    strong.textContent = note.source_name || note.source_chat_id || "未知来源";
    const time = document.createElement("span");
    time.className = "muted";
    time.textContent = note.timestamp || "";
    head.append(strong, time);
    const p = document.createElement("p");
    p.textContent = note.message_text || note.media_type || "";
    item.append(head, p);
    list.appendChild(item);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  $("batchForm").addEventListener("submit", submitBatch);
  $("cancelBtn").addEventListener("click", cancelBatch);
  $("historyRefresh").addEventListener("click", loadHistory);
  $("historyClear").addEventListener("click", async () => {
    await apiFetch("/api/history", { method: "DELETE" });
    loadHistory();
  });

  $("watchForm").addEventListener("submit", saveWatch);
  $("watchRefresh").addEventListener("click", loadWatchConfig);
  $("noteRefresh").addEventListener("click", loadNotes);
  $("noteSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadNotes();
  });

  loadStatus();
  loadHistory();
  loadWatchConfig();
  loadNotes();
});
