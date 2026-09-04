const $ = (id) => document.getElementById(id);

function setMessage(id, text) {
  const el = $(id);
  el.textContent = text;
  el.hidden = !text;
}

async function apiFetch(url, options = {}) {
  const { timeout, ...fetchOptions } = options;
  const requestTimeout = timeout || 90000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), requestTimeout);
  const headers = options.body ? { "Content-Type": "application/json" } : {};

  try {
    const res = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });
    if (!res.ok) {
      let message = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        message = data.error || message;
      } catch (_) {}
      throw new Error(message);
    }
    return res.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`请求超时（${Math.round(requestTimeout / 1000)} 秒），请检查服务器网络和 Telegram 连通性`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

let setupState = {
  stage: "idle",
  setupId: "",
  phone: "",
  busy: false,
  unlocked: false,
};

function setSetupMessage(text) {
  const el = $("setupMessage");
  el.textContent = text;
  el.hidden = !text;
}

function setSetupFieldEnabled(enabled) {
  ["setupToken", "setupApiId", "setupApiHash", "setupPhone"].forEach((id) => {
    $(id).disabled = setupState.busy || !enabled;
  });
}

function setSetupStage(stage) {
  setupState.stage = stage;
  const editable = setupState.unlocked || stage === "idle";
  $("setupStageIdle").hidden = stage !== "idle" && !setupState.unlocked;
  $("setupStageCode").hidden = stage !== "code" || setupState.unlocked;
  $("setupStagePassword").hidden = stage !== "password" || setupState.unlocked;
  $("setupStageDone").hidden = stage !== "done" || setupState.unlocked;
  setSetupFieldEnabled(editable);
  updateSetupLockButton();
}

function setSetupBusy(busy) {
  setupState.busy = busy;
  ["setupSaveBtn", "setupStartBtn", "setupCodeBtn", "setupPasswordBtn", "setupLockBtn"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = busy;
  });
  setSetupFieldEnabled(setupState.unlocked || setupState.stage === "idle");
}

function updateSetupLockButton() {
  const button = $("setupLockBtn");
  button.textContent = setupState.unlocked ? "锁定参数" : "解锁参数";
  button.setAttribute("aria-pressed", setupState.unlocked ? "true" : "false");
}

function toggleSetupLock() {
  if (setupState.busy) return;

  setupState.unlocked = !setupState.unlocked;
  setSetupStage(setupState.stage);
  setSetupMessage(setupState.unlocked ? "参数已解锁，可以修改后重新发送验证码" : "参数已锁定");
}

async function pollSetupStatus(setupId, untilStatuses) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    let status;
    try {
      status = await apiFetch(
        `/api/setup/status?setup_id=${encodeURIComponent(setupId)}`,
        { timeout: 5000 }
      );
    } catch (_) {
      continue;
    }
    if (status.status === "error" || status.status === "missing") {
      return status;
    }
    if (untilStatuses.includes(status.status)) {
      return status;
    }
  }
  throw new Error("登录流程超时，请重新开始");
}

function updateSessionBadge(config) {
  const badge = $("sessionBadge");
  if (config && config.has_session) {
    badge.textContent = `已配置 ${config.session_masked || ""}`;
  } else {
    badge.textContent = "未生成";
  }
}

function readSetupCredentials() {
  return {
    token: $("setupToken").value.trim(),
    api_id: $("setupApiId").value.trim(),
    api_hash: $("setupApiHash").value.trim(),
    phone_number: $("setupPhone").value.trim(),
  };
}

function readPendingSetup() {
  const params = new URLSearchParams(window.location.search);
  return {
    setupId: params.get("setup") || "",
    stage: params.get("stage") || "idle",
    phone: params.get("phone") || "",
    action: params.get("action") || "",
    message: params.get("setup_message") || "",
    error: params.get("setup_error") || "",
  };
}

function setPendingSetupFields(setupId, phone) {
  setupState.setupId = setupId;
  setupState.phone = phone;
  $("setupIdInput").value = setupId;
  $("setupPhone").value = phone;
  $("setupCode").value = "";
  $("setupPassword").value = "";
}

function clearSetupQuery() {
  if (window.history && window.history.replaceState) {
    window.history.replaceState(null, "", window.location.pathname);
  }
}

function resetSetupFlow() {
  setupState.setupId = "";
  setupState.phone = "";
  setupState.unlocked = false;
  $("setupIdInput").value = "";
  $("setupCode").value = "";
  $("setupPassword").value = "";
  setSetupStage("idle");
  clearSetupQuery();
}

function codeFlowNeedsReset(error) {
  return /验证码已过期|验证码不正确|验证码为空|重新获取验证码|登录流程已过期|验证码尚未发送/.test(
    error || ""
  );
}

async function loadSetupState() {
  const pending = readPendingSetup();
  setupState.unlocked = false;
  try {
    const config = await apiFetch("/api/setup/state");
    $("setupToken").value = config.token || "";
    $("setupApiId").value = config.api_id || "";
    $("setupApiHash").value = config.api_hash || "";
    $("setupSession").value = "";
    updateSessionBadge(config);

    if (pending.setupId) {
      setPendingSetupFields(pending.setupId, pending.phone);
      setSetupStage(pending.stage === "password" ? "password" : "code");
      if (pending.message) setSetupMessage(pending.message);
      else if (pending.error) setSetupMessage(pending.error);
      else setSetupMessage("");
      resumeSetupFlow(pending);
      return;
    }

    $("setupPhone").value = "";
    $("setupCode").value = "";
    $("setupPassword").value = "";
    $("setupIdInput").value = "";
    setSetupStage("idle");
    setSetupMessage(pending.error || pending.message || "");
  } catch (error) {
    setSetupMessage(error.message);
  }
}

async function resumeSetupFlow(pending) {
  const stage = pending.stage === "password" ? "password" : "code";
  setSetupBusy(true);
  setSetupStage(stage);

  const untilStatuses =
    pending.action === "start"
      ? ["sent", "ready", "done"]
      : pending.action === "password"
        ? ["done"]
        : ["ready", "done"];

  try {
    const status = await pollSetupStatus(pending.setupId, untilStatuses);

    if (status.status === "error") {
      setSetupMessage(status.error || "Telegram 登录流程失败");
      const shouldReset =
        pending.action === "start" ||
        /验证码已过期|验证码不正确|验证码为空|重新获取验证码/.test(
          status.error || ""
        );
      if (shouldReset) {
        setSetupStage("idle");
        setPendingSetupFields("", "");
        clearSetupQuery();
      }
      return;
    }

    if (status.status === "missing") {
      setSetupMessage("登录流程不存在或已过期，请重新开始");
      setSetupStage("idle");
      setPendingSetupFields("", "");
      clearSetupQuery();
      return;
    }

    if (pending.action === "start" && status.status === "sent") {
      setSetupStage("code");
      setSetupMessage(`验证码已发送到 ${pending.phone || setupState.phone}`);
      return;
    }

    if (status.stage === "password") {
      setSetupStage("password");
      setSetupMessage(status.message || "账号已开启两步验证，请输入密码");
      return;
    }

    if (status.status === "done" || status.session_string) {
      $("setupSession").value = status.session_string || "";
      updateSessionBadge(status.saved || {});
      setSetupStage("done");
      setSetupMessage(status.message || "Session String 已生成");
      clearSetupQuery();
      loadStatus();
      return;
    }

    setSetupMessage(status.message || "登录状态已更新");
  } catch (error) {
    setSetupMessage(error.message);
  } finally {
    setSetupBusy(false);
  }
}

async function saveSetupConfig() {
  if (setupState.busy) return;

  const creds = readSetupCredentials();
  if (!creds.token || !creds.api_id || !creds.api_hash) {
    setSetupMessage("Bot Token、API ID 和 API Hash 均不能为空");
    return;
  }

  setSetupBusy(true);
  setSetupMessage("");
  try {
    const result = await apiFetch("/api/setup/save", {
      method: "POST",
      body: JSON.stringify(creds),
    });
    updateSessionBadge(result);
    setSetupStage("idle");
    setSetupMessage(result.message || "配置已保存");
    loadStatus();
  } catch (error) {
    setSetupStage("idle");
    setSetupMessage(error.message);
  } finally {
    setSetupBusy(false);
  }
}

async function startSetup() {
  const creds = readSetupCredentials();
  if (!creds.token || !creds.api_id || !creds.api_hash || !creds.phone_number) {
    setSetupMessage("生成 Session String 需要填写 Bot Token、API ID、API Hash 和 Telegram 手机号");
    return;
  }
  if (setupState.busy) return;

  setupState.unlocked = false;
  setSetupStage("idle");
  updateSetupLockButton();
  setSetupBusy(true);
  setSetupMessage("正在请求 Telegram 发送验证码，请稍候...");
  try {
    const result = await apiFetch("/api/setup/start", {
      method: "POST",
      body: JSON.stringify(creds),
    });
    setupState.setupId = result.setup_id;
    setupState.phone = result.phone_number || creds.phone_number;

    const status = await pollSetupStatus(result.setup_id, ["sent"]);
    if (status.status === "error") {
      setSetupMessage(status.error || "发送验证码失败");
      resetSetupFlow();
      return;
    }
    if (status.status === "missing") {
      setSetupMessage("登录流程不存在或已过期，请重新开始");
      resetSetupFlow();
      return;
    }

    $("setupCode").value = "";
    setSetupStage("code");
    setSetupMessage(`验证码已发送到 ${setupState.phone}`);
  } catch (error) {
    setSetupMessage(error.message);
    resetSetupFlow();
  } finally {
    setSetupBusy(false);
  }
}

async function submitSetupCode() {
  const code = $("setupCode").value.trim();
  if (!setupState.setupId) {
    setSetupMessage("登录流程已失效，请重新开始");
    return;
  }
  if (!code) {
    setSetupMessage("验证码不能为空");
    return;
  }
  if (setupState.busy) return;

  setSetupBusy(true);
  setSetupMessage("正在验证并生成 Session String...");
  try {
    const result = await apiFetch("/api/setup/code", {
      method: "POST",
      body: JSON.stringify({ setup_id: setupState.setupId, code }),
    });

    if (result.error) {
      setSetupMessage(result.error);
      if (codeFlowNeedsReset(result.error)) {
        resetSetupFlow();
      }
      return;
    }

    const status = await pollSetupStatus(setupState.setupId, ["ready", "done"]);
    if (status.status === "error") {
      setSetupMessage(status.error || "验证码验证失败");
      resetSetupFlow();
      return;
    }
    if (status.status === "missing") {
      setSetupMessage("登录流程不存在或已过期，请重新开始");
      resetSetupFlow();
      return;
    }

    if (status.stage === "password") {
      setSetupStage("password");
      $("setupPassword").value = "";
      setSetupMessage(status.message || "账号已开启两步验证，请输入密码");
      return;
    }

    if (status.status === "done" || status.session_string) {
      $("setupSession").value = status.session_string || "";
      updateSessionBadge(status.saved || {});
      setupState.setupId = "";
      $("setupIdInput").value = "";
      setSetupStage("done");
      setSetupMessage(status.message || "Session String 已生成");
      clearSetupQuery();
      loadStatus();
      return;
    }

    setSetupMessage(status.message || "登录状态已更新");
  } catch (error) {
    setSetupMessage(error.message);
    if (
      codeFlowNeedsReset(error.message) ||
      error.message.includes("登录流程不存在")
    ) {
      resetSetupFlow();
    }
  } finally {
    setSetupBusy(false);
  }
}

async function submitSetupPassword() {
  const password = $("setupPassword").value;
  if (!setupState.setupId) {
    setSetupMessage("登录流程已失效，请重新开始");
    return;
  }
  if (!password) {
    setSetupMessage("两步验证密码不能为空");
    return;
  }
  if (setupState.busy) return;

  setSetupBusy(true);
  setSetupMessage("正在完成两步验证...");
  try {
    const result = await apiFetch("/api/setup/password", {
      method: "POST",
      body: JSON.stringify({ setup_id: setupState.setupId, password }),
    });

    if (result.error) {
      setSetupMessage(result.error);
      return;
    }

    const status = await pollSetupStatus(setupState.setupId, ["done"]);
    if (status.status === "error") {
      setSetupMessage(status.error || "两步验证失败");
      if ((status.error || "").includes("登录流程不存在")) {
        loadSetupState();
      }
      return;
    }
    if (status.status === "missing") {
      setSetupMessage("登录流程不存在或已过期，请重新开始");
      loadSetupState();
      return;
    }

    if (status.status === "done" || status.session_string) {
      $("setupSession").value = status.session_string || "";
      updateSessionBadge(status.saved || {});
      setupState.setupId = "";
      $("setupIdInput").value = "";
      setSetupStage("done");
      setSetupMessage(status.message || "Session String 已生成");
      clearSetupQuery();
      loadStatus();
      return;
    }

    setSetupMessage(status.message || "登录状态已更新");
  } catch (error) {
    setSetupMessage(error.message);
    if (error.message.includes("登录流程不存在")) {
      loadSetupState();
    }
  } finally {
    setSetupBusy(false);
  }
}

async function savePassword() {
  const currentPassword = $("passwordCurrent").value;
  const newPassword = $("passwordNew").value;
  const confirmPassword = $("passwordConfirm").value;
  if (!currentPassword || !newPassword || !confirmPassword) {
    setMessage("passwordMessage", "请完整填写当前密码、新密码和确认密码");
    return;
  }

  try {
    const result = await apiFetch("/api/admin/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword }),
    });
    $("passwordCurrent").value = "";
    $("passwordNew").value = "";
    $("passwordConfirm").value = "";
    setMessage("passwordMessage", result.message || "密码更新成功");
  } catch (error) {
    setMessage("passwordMessage", error.message);
  }
}

async function loadWebdavConfig() {
  try {
    const config = await apiFetch("/api/admin/webdav");
    $("webdavEnabled").checked = !!config.enabled;
    $("webdavUrl").value = config.url || "";
    $("webdavUsername").value = config.username || "";
    $("webdavPassword").value = config.password || "";
    $("webdavBasePath").value = config.base_path || "/telegram_media";
    $("webdavKeepLocal").checked = !!config.keep_local_copy;
  } catch (error) {
    setMessage("webdavMessage", error.message);
  }
}

async function saveWebdavConfig() {
  try {
    const result = await apiFetch("/api/admin/webdav", {
      method: "POST",
      body: JSON.stringify({
        enabled: $("webdavEnabled").checked,
        url: $("webdavUrl").value.trim(),
        username: $("webdavUsername").value.trim(),
        password: $("webdavPassword").value,
        base_path: $("webdavBasePath").value.trim(),
        keep_local_copy: $("webdavKeepLocal").checked,
      }),
    });
    setMessage("webdavMessage", result.message || "WebDAV 配置已保存");
  } catch (error) {
    setMessage("webdavMessage", error.message);
  }
}

async function loadCalibrationConfig() {
  try {
    const data = await apiFetch("/api/admin/calibration");
    const config = data.config || {};
    $("calibrationEnabled").checked = !!config.enabled;
    $("calibrationFilterMode").value = config.filter_mode || "empty_only";
    $("calibrationFirstDelay").value = config.first_delay ?? 600;
    $("calibrationMaxRetries").value = config.max_retries ?? 3;
    $("calibrationConcurrent").value = config.concurrent_limit ?? 5;
    $("calibrationMagnetTimeout").value = config.timeout_per_magnet ?? 30;
    $("calibrationBatchTimeout").value = config.batch_timeout ?? 300;
    $("calibrationRetry1").value = config.retry_delay_1 ?? 3600;
    $("calibrationRetry2").value = config.retry_delay_2 ?? 14400;
    $("calibrationRetry3").value = config.retry_delay_3 ?? 28800;
    const stats = data.stats || {};
    $("calibrationTotal").textContent = stats.total ?? 0;
    $("calibrationPending").textContent = stats.ready_to_process ?? 0;
  } catch (error) {
    setMessage("calibrationMessage", error.message);
  }
}

async function saveCalibrationConfig() {
  try {
    const result = await apiFetch("/api/admin/calibration", {
      method: "POST",
      body: JSON.stringify({
        enabled: $("calibrationEnabled").checked,
        filter_mode: $("calibrationFilterMode").value,
        first_delay: $("calibrationFirstDelay").value,
        retry_delay_1: $("calibrationRetry1").value,
        retry_delay_2: $("calibrationRetry2").value,
        retry_delay_3: $("calibrationRetry3").value,
        max_retries: $("calibrationMaxRetries").value,
        concurrent_limit: $("calibrationConcurrent").value,
        timeout_per_magnet: $("calibrationMagnetTimeout").value,
        batch_timeout: $("calibrationBatchTimeout").value,
      }),
    });
    const stats = result.stats || {};
    $("calibrationTotal").textContent = stats.total ?? 0;
    $("calibrationPending").textContent = stats.ready_to_process ?? 0;
    setMessage("calibrationMessage", result.message || "自动校准配置已保存");
  } catch (error) {
    setMessage("calibrationMessage", error.message);
  }
}

async function loadViewerConfig() {
  try {
    const config = await apiFetch("/api/admin/viewer");
    $("viewerUrl").value = config.viewer_url || "";
  } catch (error) {
    setMessage("viewerMessage", error.message);
  }
}

async function saveViewerConfig() {
  try {
    const result = await apiFetch("/api/admin/viewer", {
      method: "POST",
      body: JSON.stringify({ viewer_url: $("viewerUrl").value.trim() }),
    });
    setMessage("viewerMessage", result.message || "观看网站配置已保存");
  } catch (error) {
    setMessage("viewerMessage", error.message);
  }
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
    const clientPill = $("clientStatus");
    clientPill.textContent = status.user_client_running
      ? "用户客户端已连接"
      : status.user_client_ready
        ? "用户客户端启动中"
        : "用户客户端未就绪";
    clientPill.style.color = status.user_client_running
      ? "var(--success)"
      : "var(--danger)";

    const dualPill = $("dualStatus");
    dualPill.textContent = status.dual_end_ready
      ? "网页端 + Bot 双端在线"
      : status.bot_running
        ? "Bot 在线，用户客户端未就绪"
        : "Bot 未运行";
    dualPill.style.color = status.dual_end_ready ? "var(--success)" : "var(--danger)";

    $("statusWeb").textContent = status.web_ready ? "在线" : "离线";
    $("statusBot").textContent = status.bot_running
      ? "在线"
      : status.bot_ready
        ? "启动中"
        : "未运行";
    $("statusUser").textContent = status.user_client_running
      ? "在线"
      : status.user_client_ready
        ? "启动中"
        : "未连接";
    $("statusMonitors").textContent = status.monitored_sources_count ?? 0;
  } catch (error) {
    $("clientStatus").textContent = "状态读取失败";
    $("dualStatus").textContent = "状态读取失败";
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
    $("sourceId").value = `-100${match[1]}`;
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
  $("setupForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (setupState.busy) return;

    const formAction =
      event.submitter?.getAttribute("formaction") || "/setup/save";
    if (formAction.endsWith("/setup/start")) {
      startSetup();
    } else if (formAction.endsWith("/setup/code")) {
      submitSetupCode();
    } else if (formAction.endsWith("/setup/password")) {
      submitSetupPassword();
    } else {
      saveSetupConfig();
    }
  });
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
  $("setupResetBtn").addEventListener("click", loadSetupState);
  $("setupLockBtn").addEventListener("click", toggleSetupLock);
  $("passwordSaveBtn").addEventListener("click", savePassword);
  $("webdavSaveBtn").addEventListener("click", saveWebdavConfig);
  $("calibrationSaveBtn").addEventListener("click", saveCalibrationConfig);
  $("viewerSaveBtn").addEventListener("click", saveViewerConfig);

  loadStatus();
  loadSetupState();
  loadWebdavConfig();
  loadCalibrationConfig();
  loadViewerConfig();
  loadHistory();
  loadWatchConfig();
  loadNotes();
  setInterval(loadStatus, 3000);
});
