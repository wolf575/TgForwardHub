import { DurableObject } from "cloudflare:workers";

/**
 * Edit these values if you prefer a copy/paste deployment without Worker vars.
 * Runtime environment variables always take precedence over these defaults.
 */
const CODE_CONFIG = Object.freeze({
  BOT_TOKEN: "",
  ADMIN_ID: "",
  API_ID: "",
  API_HASH: "",
  WEBHOOK_SECRET: "",
  WEB_ADMIN_USER: "",
  WEB_ADMIN_PASSWORD: "",
  SESSION_SECRET: "",
  STORAGE_BACKEND: "auto",
  MAX_RANGE_MESSAGES: 10000,
  CONTAINER_PORT: 8080,
  CONTAINER_INACTIVITY_MS: 60 * 60 * 1000,
  CONTAINER_INSTANCE_ID: "singleton-v7",
});

const TELEGRAM_API_BASE = "https://api.telegram.org";
const IMMEDIATE_RANGE_LIMIT = 100;
const CONTAINER_RANGE_CHUNK_SIZE = 30;
const JOB_MAX_CHUNKS_PER_RUN = 3;
const JOB_MAX_PER_CRON = 3;
const JOB_RETRY_DELAY_MS = 60_000;
const STALE_JOB_MS = 5 * 60_000;
const UPDATE_TTL_SECONDS = 7 * 24 * 60 * 60;
const JOB_TTL_SECONDS = 7 * 24 * 60 * 60;
const WHITELIST_LIST_LIMIT = 200;
const MESSAGE_TEXT_LIMIT = 4000;

const MESSAGE_LINK_RE =
  /https:\/\/t\.me\/((?:c\/|b\/)?)([^/?#\s]+)\/(\d+)/gi;
const NUMERIC_ID_RE = /^\d{1,20}$/;
const USERNAME_RE = /^[a-z0-9_]{1,32}$/;

const JOB_UPDATE_FIELDS = new Set([
  "status",
  "next_id",
  "success_count",
  "skipped_count",
  "failed_ids",
  "updated_at",
  "next_attempt",
  "last_error",
  "summary_sent",
  "attempts",
]);

class TelegramApiError extends Error {
  constructor(message, { code = 0, retryAfter = 0 } = {}) {
    super(message);
    this.name = "TelegramApiError";
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

function nowMs() {
  return Date.now();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function textResponse(text, status = 200) {
  return new Response(text, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function htmlResponse(body, status = 200, extraHeaders = {}) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-frame-options": "DENY",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "content-security-policy":
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      ...extraHeaders,
    },
  });
}

function redirectResponse(location, extraHeaders = {}) {
  return new Response(null, {
    status: 302,
    headers: {
      location,
      "cache-control": "no-store, max-age=0",
      ...extraHeaders,
    },
  });
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/g, "");
}

function base64UrlToBytes(value) {
  const normalized = String(value)
    .replaceAll("-", "+")
    .replaceAll("_", "/");
  const padded = normalized.padEnd(
    normalized.length + ((4 - (normalized.length % 4)) % 4),
    "=",
  );
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function digestBytes(value) {
  return new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
  );
}

async function safeEqualString(left, right) {
  const [leftDigest, rightDigest] = await Promise.all([
    digestBytes(String(left ?? "")),
    digestBytes(String(right ?? "")),
  ]);
  let diff = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    diff |= leftDigest[index] ^ rightDigest[index];
  }
  return diff === 0;
}

function sessionSecret(config) {
  return config.sessionSecret || config.webAdminPassword || "";
}

async function hmacBytes(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)),
  );
}

async function createSessionToken(config, username) {
  const payload = bytesToBase64Url(
    new TextEncoder().encode(
      JSON.stringify({
        u: username,
        exp: nowMs() + 12 * 60 * 60 * 1000,
      }),
    ),
  );
  const signature = bytesToBase64Url(
    await hmacBytes(sessionSecret(config), payload),
  );
  return `${payload}.${signature}`;
}

async function verifySessionToken(config, token) {
  if (!token || !sessionSecret(config)) return false;
  const parts = String(token).split(".");
  if (parts.length !== 2) return false;
  const [payload, signature] = parts;
  const expected = bytesToBase64Url(
    await hmacBytes(sessionSecret(config), payload),
  );
  if (!(await safeEqualString(signature, expected))) return false;
  try {
    const decoded = JSON.parse(
      new TextDecoder().decode(base64UrlToBytes(payload)),
    );
    return (
      decoded.u === config.webAdminUser &&
      Number(decoded.exp || 0) > nowMs()
    );
  } catch {
    return false;
  }
}

async function createCsrfToken(config, sessionToken) {
  return bytesToBase64Url(
    await hmacBytes(sessionSecret(config), `csrf:${sessionToken}`),
  );
}

async function verifyCsrfToken(config, sessionToken, csrf) {
  const expected = await createCsrfToken(config, sessionToken);
  return safeEqualString(csrf, expected);
}

function parseCookies(header) {
  const cookies = {};
  for (const part of String(header || "").split(";")) {
    const index = part.indexOf("=");
    if (index < 0) continue;
    const name = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (name) cookies[name] = value;
  }
  return cookies;
}

function adminSessionToken(request) {
  return parseCookies(request.headers.get("cookie") || "").tfh_admin || "";
}

function isSecureRequest(request) {
  return new URL(request.url).protocol === "https:";
}

function sessionCookie(token, request) {
  const secure = isSecureRequest(request) ? "; Secure" : "";
  return `tfh_admin=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200${secure}`;
}

function clearSessionCookie(request) {
  const secure = isSecureRequest(request) ? "; Secure" : "";
  return `tfh_admin=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0${secure}`;
}

function webConfigured(config) {
  return Boolean(config.webAdminUser && config.webAdminPassword);
}

function formatAdminTime(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "-";
  try {
    return new Date(timestamp).toISOString().replace("T", " ").slice(0, 19);
  } catch {
    return "-";
  }
}

function pageShell(
  title,
  bodyHtml,
  { login = false, headerActions = "" } = {},
) {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f9;
      --surface: #ffffff;
      --text: #18202b;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --danger: #b42318;
      --danger-bg: #fff1f0;
      --success: #067647;
      --success-bg: #ecfdf3;
      --warning: #b54708;
      --warning-bg: #fffaeb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    a { color: var(--accent); }
    .topbar {
      background: #111827;
      color: #f8fafc;
      border-bottom: 1px solid #0b1220;
    }
    .topbar-inner {
      max-width: 1180px;
      margin: 0 auto;
      padding: 16px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .brand { font-weight: 700; letter-spacing: 0; }
    .brand small { display: block; color: #aeb8c8; font-weight: 400; margin-top: 2px; }
    .topbar-actions { display: flex; align-items: center; gap: 12px; }
    .topbar form { margin: 0; }
    .main { max-width: 1180px; margin: 0 auto; padding: 24px; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }
    .panel h2 { margin: 0 0 6px; font-size: 18px; }
    .panel p { margin: 0 0 16px; color: var(--muted); }
    .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f9fafb;
      color: #344054;
      font-size: 12px;
      font-weight: 600;
    }
    .chip.ok { color: var(--success); background: var(--success-bg); border-color: #abefc6; }
    .chip.warn { color: var(--warning); background: var(--warning-bg); border-color: #fedf89; }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 12px;
      align-items: end;
    }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 12px; color: var(--muted); font-weight: 600; }
    .toggle-row {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 40px;
      font-weight: 600;
    }
    .toggle-row input {
      width: 18px;
      height: 18px;
      min-height: 0;
      padding: 0;
    }
    input {
      width: 100%;
      min-height: 40px;
      padding: 9px 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    input:focus { outline: 2px solid #99f6e4; outline-offset: 1px; border-color: var(--accent); }
    button {
      min-height: 38px;
      padding: 8px 14px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary { background: #fff; color: var(--text); border-color: var(--line); }
    button.secondary:hover { background: #f8fafc; }
    .button-link {
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      text-decoration: none;
      font-weight: 650;
    }
    .button-link:hover { background: #f8fafc; }
    button.danger { background: var(--danger); }
    button.danger:hover { background: #912018; }
    button.small { min-height: 30px; padding: 5px 10px; font-size: 12px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .message {
      padding: 11px 13px;
      border-radius: 6px;
      margin-bottom: 18px;
      border: 1px solid;
      font-size: 14px;
    }
    .message.success { color: var(--success); background: var(--success-bg); border-color: #abefc6; }
    .message.error { color: var(--danger); background: var(--danger-bg); border-color: #fecdca; }
    .message.warning { color: var(--warning); background: var(--warning-bg); border-color: #fedf89; }
    .table-wrap { overflow-x: auto; margin-top: 18px; }
    table { width: 100%; border-collapse: collapse; min-width: 680px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
    th { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0; }
    tr:last-child td { border-bottom: none; }
    .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }
    .muted { color: var(--muted); }
    .empty { padding: 28px 12px; text-align: center; color: var(--muted); }
    .login-wrap { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
    .login {
      width: min(420px, 100%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 18px 50px rgba(16, 24, 40, .08);
    }
    .login h1 { margin: 0 0 6px; font-size: 22px; }
    .login p { color: var(--muted); margin: 0 0 20px; }
    .login form { display: grid; gap: 14px; }
    .login button { width: 100%; }
    .error { color: var(--danger); font-size: 13px; min-height: 20px; }
    @media (max-width: 760px) {
      .main { padding: 16px; }
      .topbar-inner { padding: 14px 16px; align-items: flex-start; }
      .toolbar { grid-template-columns: 1fr; }
      .topbar-actions { flex-wrap: wrap; justify-content: flex-end; }
      table { min-width: 0; }
      th, td { padding: 10px 8px; }
      .time-col { display: none; }
    }
  </style>
</head>
<body>
${login ? bodyHtml : `<header class="topbar"><div class="topbar-inner"><div class="brand">TG Forward Hub<small>Cloudflare Worker 管理台</small></div><div class="topbar-actions">${headerActions}</div></div></header><main class="main">${bodyHtml}</main>`}
</body>
</html>`;
}

function renderWebUnavailable() {
  const body = `<div class="login-wrap"><section class="login"><h1>Web 管理未启用</h1><p>请配置 <span class="mono">WEB_ADMIN_USER</span> 和 <span class="mono">WEB_ADMIN_PASSWORD</span>。</p></section></div>`;
  return htmlResponse(pageShell("Web 管理未配置", body, { login: true }), 503);
}

function renderLoginPage(error = "") {
  const body = `<div class="login-wrap">
  <section class="login">
    <h1>TG Forward Hub</h1>
    <p>使用管理员账号登录白名单管理台。</p>
    <form method="post" action="/admin/login">
      <div class="field">
        <label for="username">管理员账号</label>
        <input id="username" name="username" autocomplete="username" required>
      </div>
      <div class="field">
        <label for="password">管理员密码</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
      </div>
      <div class="error">${escapeHtml(error)}</div>
      <button type="submit">登录</button>
    </form>
  </section>
</div>`;
  return htmlResponse(pageShell("管理员登录", body, { login: true }), error ? 401 : 200);
}

function renderAdminPage({
  env,
  entries,
  query,
  message,
  messageType,
  csrf,
  notificationsEnabled,
}) {
  const rows = entries.length
    ? entries
        .map((entry) => {
          const telegramId = entry.telegram_id
            ? String(entry.telegram_id)
            : "";
          const username = entry.username || "";
          const displayId = telegramId || "未解析";
          const displayUsername = username ? `@${username}` : "未设置";
          return `<tr>
            <td class="mono">${escapeHtml(displayId)}</td>
            <td>${escapeHtml(displayUsername)}</td>
            <td class="muted time-col">${escapeHtml(formatAdminTime(entry.created_at))}</td>
            <td>
              <form method="post" action="/admin/whitelist/delete">
                <input type="hidden" name="csrf" value="${escapeHtml(csrf)}">
                <input type="hidden" name="telegram_id" value="${escapeHtml(telegramId)}">
                <input type="hidden" name="username" value="${escapeHtml(username)}">
                <button class="danger small" type="submit">删除</button>
              </form>
            </td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="4" class="empty">没有匹配的白名单记录</td></tr>`;

  const messageHtml = message
    ? `<div class="message ${escapeHtml(
        ["success", "error", "warning"].includes(messageType)
          ? messageType
          : "success",
      )}">${escapeHtml(message)}</div>`
    : "";

  const backend = env.DB ? "D1" : env.WHITELIST_KV ? "KV" : "未绑定";
  const container = env.BOT_CONTAINER ? "已绑定" : "未绑定";
  const headerActions = `<span class="chip ${env.BOT_CONTAINER ? "ok" : "warn"}">Container ${escapeHtml(container)}</span>
    <form method="post" action="/admin/logout"><button class="secondary small" type="submit">退出登录</button></form>`;

  const body = `${messageHtml}
  <div class="stats">
    <span class="chip ${backend === "未绑定" ? "warn" : "ok"}">存储 ${escapeHtml(backend)}</span>
    <span class="chip">白名单 ${entries.length}</span>
  </div>
  <section class="panel">
    <h2>Bot 通知</h2>
    <p>关闭后仍会转发内容，但不再发送批量转发完成汇总。</p>
    <form method="post" action="/admin/settings" class="toolbar">
      <input type="hidden" name="csrf" value="${escapeHtml(csrf)}">
      <label class="toggle-row">
        <input type="checkbox" name="batch_completion_notifications_enabled" value="1" ${notificationsEnabled ? "checked" : ""}>
        <span>发送转发完成通知</span>
      </label>
      <button type="submit">保存设置</button>
    </form>
  </section>
  <div class="grid">
    <section class="panel">
      <h2>添加白名单</h2>
      <p>支持 Telegram 数字 ID 或 @username。用户名解析失败时只保存用户名别名。</p>
      <form method="post" action="/admin/whitelist/add" class="toolbar">
        <input type="hidden" name="csrf" value="${escapeHtml(csrf)}">
        <div class="field">
          <label for="target">Telegram 用户 ID 或用户名</label>
          <input id="target" name="target" placeholder="123456789 或 @username" required>
        </div>
        <button type="submit">添加白名单</button>
      </form>
    </section>
    <section class="panel">
      <h2>白名单</h2>
      <p>查询、核对和删除白名单用户。用户名会以当前 Telegram 资料为准动态匹配。</p>
      <form method="get" action="/admin" class="toolbar">
        <div class="field">
          <label for="q">搜索 ID 或用户名</label>
          <input id="q" name="q" value="${escapeHtml(query)}" placeholder="输入 ID 或 @username">
        </div>
        <div class="actions">
          <button type="submit">查询</button>
          <a class="button-link" href="/admin">清除</a>
        </div>
      </form>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Telegram ID</th><th>用户名</th><th class="time-col">添加时间</th><th>操作</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  </div>`;

  return htmlResponse(
    pageShell("白名单管理", body, { headerActions }),
  );
}

function adminRedirect(message, type = "success") {
  const params = new URLSearchParams({ message, type });
  return redirectResponse(`/admin?${params.toString()}`);
}

async function getAdminSession(request, config) {
  const token = adminSessionToken(request);
  if (!token || !(await verifySessionToken(config, token))) {
    return null;
  }
  return token;
}

async function handleAdminLogin(request, env, config) {
  if (!webConfigured(config)) return renderWebUnavailable();
  if (request.method === "GET") return renderLoginPage();
  if (request.method !== "POST") return textResponse("Method not allowed", 405);

  let form;
  try {
    form = await request.formData();
  } catch {
    return renderLoginPage("登录表单格式错误");
  }
  const username = String(form.get("username") || "").trim();
  const password = String(form.get("password") || "");
  const validUsername = await safeEqualString(username, config.webAdminUser);
  const validPassword = await safeEqualString(
    password,
    config.webAdminPassword,
  );
  if (!validUsername || !validPassword) {
    return renderLoginPage("账号或密码错误");
  }

  const token = await createSessionToken(config, config.webAdminUser);
  return redirectResponse("/admin", {
    "set-cookie": sessionCookie(token, request),
  });
}

async function handleAdminPage(request, env, config) {
  if (!webConfigured(config)) return renderWebUnavailable();
  if (request.method !== "GET") return textResponse("Method not allowed", 405);
  const token = await getAdminSession(request, config);
  if (!token) return redirectResponse("/admin/login");

  const store = createStore(env, config);
  await store.init();
  const url = new URL(request.url);
  const query = String(url.searchParams.get("q") || "").trim();
  const normalizedQuery = query.replace(/^@+/, "").toLowerCase();
  const allEntries = await store.list(1000);
  const entries = normalizedQuery
    ? allEntries.filter((entry) => {
        const id = String(entry.telegram_id || "");
        const username = normalizeUsername(entry.username);
        return id.includes(normalizedQuery) || username.includes(normalizedQuery);
      })
    : allEntries;
  const notificationsEnabled = await store.getSetting(
    "batch_completion_notifications_enabled",
    true,
  );
  const csrf = await createCsrfToken(config, token);
  return renderAdminPage({
    env,
    entries,
    query,
    message: String(url.searchParams.get("message") || ""),
    messageType: String(url.searchParams.get("type") || "success"),
    csrf,
    notificationsEnabled,
  });
}

async function requireAdminForm(request, config) {
  if (!webConfigured(config)) {
    return { error: renderWebUnavailable() };
  }
  const token = await getAdminSession(request, config);
  if (!token) {
    return { error: redirectResponse("/admin/login") };
  }
  let form;
  try {
    form = await request.formData();
  } catch {
    return { error: adminRedirect("表单格式错误", "error") };
  }
  const csrf = String(form.get("csrf") || "");
  if (!(await verifyCsrfToken(config, token, csrf))) {
    return { error: adminRedirect("CSRF 校验失败，请重新登录", "error") };
  }
  return { form };
}

async function handleAdminAdd(request, env, config) {
  if (request.method !== "POST") return textResponse("Method not allowed", 405);
  const checked = await requireAdminForm(request, config);
  if (checked.error) return checked.error;
  const target = parseWhitelistTarget(checked.form.get("target"));
  if (!target) {
    return adminRedirect("格式错误，请输入数字 ID 或 @username", "error");
  }

  let resolved = null;
  if (target.username) {
    resolved = await resolveUsernameToId(config, target.username);
  }
  const store = createStore(env, config);
  await store.init();
  const entry = await store.add({
    telegramId: target.telegramId || resolved?.telegramId || "",
    username: target.username || resolved?.username || "",
  });
  const id = entry?.telegram_id ? String(entry.telegram_id) : "未解析";
  const username = entry?.username ? ` (@${entry.username})` : "";
  if (target.username && !resolved) {
    return adminRedirect(
      `已保存用户名别名 ${username || `@${target.username}`}，但暂时无法解析数字 ID`,
      "warning",
    );
  }
  return adminRedirect(`已添加 ${id}${username}`);
}

async function handleAdminDelete(request, env, config) {
  if (request.method !== "POST") return textResponse("Method not allowed", 405);
  const checked = await requireAdminForm(request, config);
  if (checked.error) return checked.error;
  const telegramId = String(checked.form.get("telegram_id") || "").trim();
  const username = normalizeUsername(checked.form.get("username"));

  if (telegramId && telegramId === String(config.adminId)) {
    return adminRedirect("管理员 ID 不能从 Web 界面删除", "error");
  }
  if (username) {
    const resolved = await resolveUsernameToId(config, username);
    if (resolved?.telegramId === String(config.adminId)) {
      return adminRedirect("管理员 ID 不能从 Web 界面删除", "error");
    }
  }

  const store = createStore(env, config);
  await store.init();
  const removed = await store.remove({ telegramId, username });
  return removed > 0
    ? adminRedirect("已删除白名单记录")
    : adminRedirect("没有找到对应的白名单记录", "warning");
}

async function handleAdminSettings(request, env, config) {
  if (request.method !== "POST") return textResponse("Method not allowed", 405);
  const checked = await requireAdminForm(request, config);
  if (checked.error) return checked.error;
  const enabled =
    String(
      checked.form.get("batch_completion_notifications_enabled") || "",
    ) === "1";
  const store = createStore(env, config);
  await store.init();
  await store.setSetting("batch_completion_notifications_enabled", enabled);
  return adminRedirect(
    enabled ? "已开启转发完成通知" : "已关闭转发完成通知",
  );
}

async function handleAdminRoute(request, env, config) {
  const path = new URL(request.url).pathname.replace(/\/+$/, "") || "/";
  if (path === "/admin/login") {
    return handleAdminLogin(request, env, config);
  }
  if (path === "/admin") {
    return handleAdminPage(request, env, config);
  }
  if (path === "/admin/logout") {
    if (request.method !== "POST") return textResponse("Method not allowed", 405);
    return redirectResponse("/admin/login", {
      "set-cookie": clearSessionCookie(request),
    });
  }
  if (path === "/admin/whitelist/add") {
    return handleAdminAdd(request, env, config);
  }
  if (path === "/admin/whitelist/delete") {
    return handleAdminDelete(request, env, config);
  }
  if (path === "/admin/settings") {
    return handleAdminSettings(request, env, config);
  }
  return textResponse("Not found", 404);
}

function asString(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

export function normalizeUsername(value) {
  return asString(value).replace(/^@+/, "").toLowerCase();
}

export function parseWhitelistTarget(value) {
  const raw = asString(value);
  if (!raw) return null;
  if (NUMERIC_ID_RE.test(raw)) {
    return { telegramId: raw, username: "" };
  }
  const username = normalizeUsername(raw);
  if (!USERNAME_RE.test(username)) return null;
  return { telegramId: "", username };
}

function identityFromTelegramUser(user) {
  if (!user || user.is_bot) return null;
  const id = asString(user.id);
  if (!id) return null;
  return {
    id,
    username: normalizeUsername(user.username),
    displayName: [user.first_name, user.last_name].filter(Boolean).join(" "),
  };
}

function resolveConfig(env = {}) {
  const pick = (key) => asString(env[key] ?? CODE_CONFIG[key] ?? "");
  const maxRangeRaw = pick("MAX_RANGE_MESSAGES") || "10000";
  const maxRangeMessages = Number.parseInt(maxRangeRaw, 10);
  const containerPort = Number.parseInt(
    pick("CONTAINER_PORT") || "8080",
    10,
  );
  const inactivityRaw =
    pick("CONTAINER_INACTIVITY_MS") || String(10 * 60 * 1000);
  const containerInactivityMs = Number.parseInt(inactivityRaw, 10);

  return {
    botToken: pick("BOT_TOKEN"),
    adminId: pick("ADMIN_ID"),
    apiId: pick("API_ID"),
    apiHash: pick("API_HASH"),
    webhookSecret: pick("WEBHOOK_SECRET"),
    webAdminUser: pick("WEB_ADMIN_USER"),
    webAdminPassword: pick("WEB_ADMIN_PASSWORD"),
    sessionSecret: pick("SESSION_SECRET"),
    storageBackend: (pick("STORAGE_BACKEND") || "auto").toLowerCase(),
    maxRangeMessages:
      Number.isFinite(maxRangeMessages) && maxRangeMessages > 0
        ? maxRangeMessages
        : 10000,
    containerPort:
      Number.isFinite(containerPort) && containerPort > 0
        ? containerPort
        : 8080,
    containerInactivityMs:
      Number.isFinite(containerInactivityMs) && containerInactivityMs > 0
        ? containerInactivityMs
        : 60 * 60 * 1000,
    containerInstanceId: pick("CONTAINER_INSTANCE_ID") || "singleton-v7",
  };
}

function configIssues(config, { requireContainer = false } = {}) {
  const issues = [];
  if (!config.botToken) issues.push("BOT_TOKEN is missing");
  if (!NUMERIC_ID_RE.test(config.adminId)) {
    issues.push("ADMIN_ID must be a Telegram numeric user ID");
  }
  if (!["auto", "d1", "kv"].includes(config.storageBackend)) {
    issues.push("STORAGE_BACKEND must be auto, d1, or kv");
  }
  if (requireContainer) {
    if (!NUMERIC_ID_RE.test(config.apiId)) {
      issues.push("API_ID is missing or not numeric");
    }
    if (!config.apiHash) issues.push("API_HASH is missing");
  }
  return issues;
}

async function telegramApi(config, method, params = {}, options = {}) {
  if (!config.botToken) {
    throw new TelegramApiError("BOT_TOKEN is missing");
  }

  const response = await fetch(
    `${TELEGRAM_API_BASE}/bot${config.botToken}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
      signal: options.signal,
    },
  );

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok || !payload?.ok) {
    const retryAfterRaw =
      payload?.parameters?.retry_after ?? response.headers.get("retry-after");
    const retryAfter = Number.parseInt(String(retryAfterRaw || "0"), 10);
    throw new TelegramApiError(
      payload?.description || `Telegram API ${method} failed (${response.status})`,
      {
        code: Number(payload?.error_code || response.status || 0),
        retryAfter: Number.isFinite(retryAfter) ? retryAfter : 0,
      },
    );
  }

  return payload.result;
}

function replyParameters(messageId) {
  if (!messageId) return undefined;
  return {
    message_id: messageId,
    allow_sending_without_reply: true,
  };
}

function splitMessageText(text, limit = MESSAGE_TEXT_LIMIT) {
  const value = String(text ?? "");
  if (value.length <= limit) return [value];

  const chunks = [];
  let remaining = value;
  while (remaining.length > limit) {
    let cut = remaining.lastIndexOf("\n", limit);
    if (cut < Math.floor(limit / 2)) cut = limit;
    chunks.push(remaining.slice(0, cut));
    remaining = remaining.slice(cut).replace(/^\n+/, "");
  }
  if (remaining) chunks.push(remaining);
  return chunks;
}

async function sendText(config, chatId, text, messageId = null) {
  const chunks = splitMessageText(text);
  for (let index = 0; index < chunks.length; index += 1) {
    const params = {
      chat_id: String(chatId),
      text: chunks[index],
      disable_web_page_preview: true,
    };
    if (index === 0) {
      const reply = replyParameters(messageId);
      if (reply) params.reply_parameters = reply;
    }
    await telegramApi(config, "sendMessage", params);
  }
}

export function parseMessageLink(value) {
  const raw = String(value ?? "");
  const cleaned = raw.replace(/\?single\b/gi, "");
  const matches = [...cleaned.matchAll(MESSAGE_LINK_RE)];
  if (matches.length === 0) return null;

  const first = matches[0];
  const kind = first[1] || "";
  const chat = first[2];
  const fromId = Number.parseInt(first[3], 10);
  let toId = fromId;

  if (matches.length >= 2) {
    toId = Number.parseInt(matches[1][3], 10);
  } else {
    const tail = cleaned.slice(first.index + first[0].length);
    const tailMatch = tail.match(/^[\s-]*(\d+)/);
    if (tailMatch) toId = Number.parseInt(tailMatch[1], 10);
  }

  if (!Number.isSafeInteger(fromId) || fromId <= 0) return null;
  if (!Number.isSafeInteger(toId) || toId <= 0) return null;
  if (kind === "c/" && !/^\d+$/.test(chat)) return null;
  if (kind !== "c/" && !/^[A-Za-z0-9_]+$/.test(chat)) return null;

  return {
    kind,
    chat,
    fromId,
    toId,
    single: fromId === toId,
  };
}

export function sourceChatForLink(link) {
  if (link.kind === "c/") return `-100${link.chat}`;
  return `@${link.chat}`;
}

export function buildSummary(job) {
  const total = Number(job.total_messages || 0);
  const success = Number(job.success_count || 0);
  const failedIds = Array.isArray(job.failed_ids) ? job.failed_ids : [];
  const failed = failedIds.length;
  const skipped = Number(job.skipped_count || 0);

  if (failed > 0) {
    return (
      "📊 批量转发完成\n\n" +
      `✅ 成功: ${success}/${total}\n` +
      `❌ 失败: ${failed}\n` +
      `⏭️ 跳过: ${skipped}\n\n` +
      `失败的消息ID: ${failedIds.join(", ")}`
    );
  }
  if (skipped > 0) {
    return (
      "📊 批量转发完成\n\n" +
      `✅ 成功: ${success}/${total}\n` +
      `⏭️ 跳过: ${skipped}`
    );
  }
  return `✅ 批量转发完成\n\n成功转发 ${success}/${total} 条消息`;
}

function createJob({
  kind,
  chatId,
  sourceChat,
  startId,
  endId,
  replyToMessageId,
}) {
  const now = nowMs();
  return {
    id: crypto.randomUUID(),
    kind,
    chat_id: String(chatId),
    source_chat: sourceChat,
    start_id: startId,
    end_id: endId,
    next_id: startId,
    status: "queued",
    total_messages: endId - startId + 1,
    success_count: 0,
    skipped_count: 0,
    failed_ids: [],
    created_at: now,
    updated_at: now,
    next_attempt: 0,
    last_error: "",
    summary_sent: 0,
    attempts: 0,
    reply_to_message_id: replyToMessageId || null,
  };
}

function jobFromD1Row(row) {
  if (!row) return null;
  let failedIds = [];
  try {
    failedIds = JSON.parse(row.failed_ids || "[]");
  } catch {
    failedIds = [];
  }
  return {
    ...row,
    start_id: Number(row.start_id),
    end_id: Number(row.end_id),
    next_id: Number(row.next_id),
    total_messages: Number(row.total_messages),
    success_count: Number(row.success_count),
    skipped_count: Number(row.skipped_count),
    created_at: Number(row.created_at),
    updated_at: Number(row.updated_at),
    next_attempt: Number(row.next_attempt),
    summary_sent: Number(row.summary_sent),
    attempts: Number(row.attempts),
    reply_to_message_id:
      row.reply_to_message_id === null || row.reply_to_message_id === undefined
        ? null
        : Number(row.reply_to_message_id),
    failed_ids: Array.isArray(failedIds) ? failedIds.map(Number) : [],
  };
}

const d1InitCache = new WeakMap();

async function ensureD1Schema(db) {
  if (!d1InitCache.has(db)) {
    const promise = (async () => {
      const statements = [
        `CREATE TABLE IF NOT EXISTS whitelist (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          telegram_id TEXT,
          username TEXT,
          created_at INTEGER NOT NULL
        )`,
        `CREATE UNIQUE INDEX IF NOT EXISTS idx_whitelist_telegram_id
          ON whitelist(telegram_id) WHERE telegram_id IS NOT NULL`,
        `CREATE UNIQUE INDEX IF NOT EXISTS idx_whitelist_username
          ON whitelist(lower(username)) WHERE username IS NOT NULL`,
        `CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          source_chat TEXT NOT NULL,
          start_id INTEGER NOT NULL,
          end_id INTEGER NOT NULL,
          next_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          total_messages INTEGER NOT NULL,
          success_count INTEGER NOT NULL DEFAULT 0,
          skipped_count INTEGER NOT NULL DEFAULT 0,
          failed_ids TEXT NOT NULL DEFAULT '[]',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          next_attempt INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '',
          summary_sent INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0,
          reply_to_message_id INTEGER
        )`,
        `CREATE INDEX IF NOT EXISTS idx_jobs_ready
          ON jobs(status, next_attempt, created_at)`,
        `CREATE TABLE IF NOT EXISTS seen_updates (
          update_id TEXT PRIMARY KEY,
          created_at INTEGER NOT NULL
        )`,
        `CREATE INDEX IF NOT EXISTS idx_seen_updates_created
          ON seen_updates(created_at)`,
        `CREATE TABLE IF NOT EXISTS app_settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )`,
        `CREATE TABLE IF NOT EXISTS request_dedup (
          request_key TEXT PRIMARY KEY,
          created_at INTEGER NOT NULL
        )`,
        `CREATE INDEX IF NOT EXISTS idx_request_dedup_created
          ON request_dedup(created_at)`,
      ];
      await db.batch(statements.map((statement) => db.prepare(statement)));
    })();
    d1InitCache.set(db, promise);
  }
  return d1InitCache.get(db);
}

class D1Store {
  constructor(db) {
    this.db = db;
    this.backend = "d1";
  }

  async init() {
    await ensureD1Schema(this.db);
  }

  async claimUpdate(updateId) {
    if (!updateId) return true;
    const result = await this.db
      .prepare(
        "INSERT OR IGNORE INTO seen_updates (update_id, created_at) VALUES (?, ?)",
      )
      .bind(String(updateId), nowMs())
      .run();
    return Number(result.meta?.changes || 0) === 1;
  }

  async claimRequest(requestKey, ttlSeconds = 30) {
    const now = nowMs();
    const cutoff = now - ttlSeconds * 1000;
    const result = await this.db
      .prepare(
        `INSERT INTO request_dedup (request_key, created_at) VALUES (?, ?)
         ON CONFLICT(request_key) DO UPDATE SET created_at = excluded.created_at
         WHERE request_dedup.created_at < ?`,
      )
      .bind(requestKey, now, cutoff)
      .run();
    return Number(result.meta?.changes || 0) === 1;
  }

  async getSetting(key, fallback = true) {
    const row = await this.db
      .prepare("SELECT value FROM app_settings WHERE key = ? LIMIT 1")
      .bind(key)
      .first();
    if (!row) return fallback;
    return String(row.value) === "true";
  }

  async setSetting(key, value) {
    await this.db
      .prepare(
        `INSERT INTO app_settings (key, value) VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
      )
      .bind(key, value ? "true" : "false")
      .run();
  }

  async isAllowed(identity) {
    if (!identity?.id) return false;
    const row = await this.db
      .prepare(
        `SELECT 1 AS ok
         FROM whitelist
         WHERE telegram_id = ?
            OR (? <> '' AND username IS NOT NULL AND lower(username) = lower(?))
         LIMIT 1`,
      )
      .bind(identity.id, identity.username || "", identity.username || "")
      .first();
    return Boolean(row);
  }

  async add({ telegramId = "", username = "" }) {
    const id = asString(telegramId);
    const name = normalizeUsername(username);
    if (!id && !name) return null;

    const rowById = id
      ? await this.db
          .prepare("SELECT * FROM whitelist WHERE telegram_id = ? LIMIT 1")
          .bind(id)
          .first()
      : null;
    const rowByName = name
      ? await this.db
          .prepare(
            "SELECT * FROM whitelist WHERE lower(username) = lower(?) LIMIT 1",
          )
          .bind(name)
          .first()
      : null;

    if (rowById && rowByName && rowById.id !== rowByName.id) {
      await this.db
        .prepare("DELETE FROM whitelist WHERE id = ?")
        .bind(rowByName.id)
        .run();
    }

    const existing = rowById || rowByName;
    const nextId = id || existing?.telegram_id || null;
    const nextName = name || existing?.username || null;
    const createdAt = Number(existing?.created_at || nowMs());

    if (existing) {
      await this.db
        .prepare(
          `UPDATE whitelist
           SET telegram_id = ?, username = ?, created_at = ?
           WHERE id = ?`,
        )
        .bind(nextId, nextName, createdAt, existing.id)
        .run();
      return { telegram_id: nextId, username: nextName };
    }

    await this.db
      .prepare(
        "INSERT INTO whitelist (telegram_id, username, created_at) VALUES (?, ?, ?)",
      )
      .bind(nextId, nextName, createdAt)
      .run();
    return { telegram_id: nextId, username: nextName };
  }

  async remove({ telegramId = "", username = "" }) {
    const id = asString(telegramId);
    const name = normalizeUsername(username);
    if (!id && !name) return 0;
    const result = await this.db
      .prepare(
        `DELETE FROM whitelist
         WHERE (? <> '' AND telegram_id = ?)
            OR (? <> '' AND username IS NOT NULL AND lower(username) = lower(?))`,
      )
      .bind(id, id, name, name)
      .run();
    return Number(result.meta?.changes || 0);
  }

  async list(limit = WHITELIST_LIST_LIMIT) {
    const result = await this.db
      .prepare(
        `SELECT telegram_id, username, created_at
         FROM whitelist
         ORDER BY created_at DESC
         LIMIT ?`,
      )
      .bind(limit)
      .all();
    return result.results || [];
  }

  async createJob(job) {
    await this.db
      .prepare(
        `INSERT INTO jobs (
          id, kind, chat_id, source_chat, start_id, end_id, next_id, status,
          total_messages, success_count, skipped_count, failed_ids, created_at,
          updated_at, next_attempt, last_error, summary_sent, attempts,
          reply_to_message_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        job.id,
        job.kind,
        job.chat_id,
        job.source_chat,
        job.start_id,
        job.end_id,
        job.next_id,
        job.status,
        job.total_messages,
        job.success_count,
        job.skipped_count,
        JSON.stringify(job.failed_ids || []),
        job.created_at,
        job.updated_at,
        job.next_attempt,
        job.last_error,
        job.summary_sent,
        job.attempts,
        job.reply_to_message_id,
      )
      .run();
  }

  async getJob(id) {
    const row = await this.db
      .prepare("SELECT * FROM jobs WHERE id = ? LIMIT 1")
      .bind(id)
      .first();
    return jobFromD1Row(row);
  }

  async claimJobById(id, now = nowMs()) {
    const result = await this.db
      .prepare(
        `UPDATE jobs
         SET status = 'running', updated_at = ?
         WHERE id = ?
           AND (
             status IN ('queued', 'retrying', 'summary_pending')
             OR (status = 'running' AND updated_at < ?)
           )`,
      )
      .bind(now, id, now - STALE_JOB_MS)
      .run();
    if (Number(result.meta?.changes || 0) !== 1) return null;
    return this.getJob(id);
  }

  async claimJob(now = nowMs()) {
    const row = await this.db
      .prepare(
        `SELECT id
         FROM jobs
         WHERE (
           status IN ('queued', 'retrying', 'summary_pending')
           AND next_attempt <= ?
         ) OR (
           status = 'running' AND updated_at < ?
         )
         ORDER BY created_at ASC
         LIMIT 1`,
      )
      .bind(now, now - STALE_JOB_MS)
      .first();
    if (!row?.id) return null;
    return this.claimJobById(row.id, now);
  }

  async updateJob(id, patch) {
    const entries = Object.entries(patch).filter(([key]) =>
      JOB_UPDATE_FIELDS.has(key),
    );
    if (entries.length === 0) return;
    const values = entries.map(([key, value]) => {
      if (key === "failed_ids") return JSON.stringify(value || []);
      return value;
    });
    const assignments = entries.map(([key]) => `${key} = ?`).join(", ");
    await this.db
      .prepare(`UPDATE jobs SET ${assignments} WHERE id = ?`)
      .bind(...values, id)
      .run();
  }

  async cleanup() {
    const cutoff = nowMs() - 7 * 24 * 60 * 60 * 1000;
    await this.db.batch([
      this.db
        .prepare("DELETE FROM jobs WHERE status = 'done' AND updated_at < ?")
        .bind(cutoff),
      this.db
        .prepare("DELETE FROM seen_updates WHERE created_at < ?")
        .bind(cutoff),
      this.db
        .prepare("DELETE FROM request_dedup WHERE created_at < ?")
        .bind(cutoff),
    ]);
  }
}

class KVStore {
  constructor(kv) {
    this.kv = kv;
    this.backend = "kv";
  }

  async init() {}

  async claimUpdate(updateId) {
    if (!updateId) return true;
    const key = `update:${updateId}`;
    const existing = await this.kv.get(key);
    if (existing !== null) return false;
    await this.kv.put(key, "1", { expirationTtl: UPDATE_TTL_SECONDS });
    return true;
  }

  async claimRequest(requestKey, ttlSeconds = 30) {
    const key = `request:${requestKey}`;
    if ((await this.kv.get(key)) !== null) return false;
    await this.kv.put(key, "1", { expirationTtl: ttlSeconds });
    return true;
  }

  async getSetting(key, fallback = true) {
    const value = await this.kv.get(`setting:${key}`);
    if (value === null) return fallback;
    return String(value) === "true";
  }

  async setSetting(key, value) {
    await this.kv.put(`setting:${key}`, value ? "true" : "false");
  }

  async isAllowed(identity) {
    if (!identity?.id) return false;
    const byId = await this.kv.get(`allow:id:${identity.id}`);
    if (byId !== null) return true;
    if (!identity.username) return false;
    const byName = await this.kv.get(
      `allow:username:${normalizeUsername(identity.username)}`,
    );
    return byName !== null;
  }

  async add({ telegramId = "", username = "" }) {
    const id = asString(telegramId);
    const name = normalizeUsername(username);
    if (!id && !name) return null;
    const createdAt = nowMs();
    const record = { telegram_id: id || null, username: name || null, created_at: createdAt };
    if (id) {
      await this.kv.put(`allow:id:${id}`, JSON.stringify(record));
    }
    if (name) {
      await this.kv.put(`allow:username:${name}`, JSON.stringify(record));
    }
    return record;
  }

  async remove({ telegramId = "", username = "" }) {
    const id = asString(telegramId);
    const name = normalizeUsername(username);
    let removed = 0;

    if (id) {
      const raw = await this.kv.get(`allow:id:${id}`);
      if (raw !== null) {
        const record = safeJsonParse(raw, {});
        await this.kv.delete(`allow:id:${id}`);
        removed += 1;
        if (record.username) {
          const alias = safeJsonParse(
            (await this.kv.get(`allow:username:${record.username}`)) || "{}",
            {},
          );
          if (String(alias.telegram_id || "") === id) {
            await this.kv.delete(`allow:username:${record.username}`);
          }
        }
      }
    }

    if (name) {
      const raw = await this.kv.get(`allow:username:${name}`);
      if (raw !== null) {
        const record = safeJsonParse(raw, {});
        await this.kv.delete(`allow:username:${name}`);
        removed += 1;
        if (record.telegram_id) {
          const alias = safeJsonParse(
            (await this.kv.get(`allow:id:${record.telegram_id}`)) || "{}",
            {},
          );
          if (normalizeUsername(alias.username) === name) {
            await this.kv.delete(`allow:id:${record.telegram_id}`);
          }
        }
      }
    }

    return removed;
  }

  async list(limit = WHITELIST_LIST_LIMIT) {
    const keys = await kvListAll(this.kv, "allow:");
    const byIdentity = new Map();
    for (const key of keys.slice(0, limit * 3)) {
      const raw = await this.kv.get(key.name);
      if (raw === null) continue;
      const record = safeJsonParse(raw, null);
      if (!record) continue;
      const identity =
        record.telegram_id || record.username
          ? `${record.telegram_id || ""}:${record.username || ""}`
          : key.name;
      if (!byIdentity.has(identity)) {
        byIdentity.set(identity, record);
      }
      if (byIdentity.size >= limit) break;
    }
    return [...byIdentity.values()];
  }

  async createJob(job) {
    await this.putJob(job);
  }

  async getJob(id) {
    const raw = await this.kv.get(`job:${id}`);
    return raw === null ? null : safeJsonParse(raw, null);
  }

  async putJob(job) {
    const options =
      job.status === "done" ? { expirationTtl: JOB_TTL_SECONDS } : undefined;
    await this.kv.put(`job:${job.id}`, JSON.stringify(job), options);
  }

  async claimJobById(id, now = nowMs()) {
    const job = await this.getJob(id);
    if (!job) return null;
    const canClaim =
      (["queued", "retrying", "summary_pending"].includes(job.status) &&
        Number(job.next_attempt || 0) <= now) ||
      (job.status === "running" &&
        Number(job.updated_at || 0) < now - STALE_JOB_MS);
    if (!canClaim) return null;
    job.status = "running";
    job.updated_at = now;
    await this.putJob(job);
    return job;
  }

  async claimJob(now = nowMs()) {
    const keys = await kvListAll(this.kv, "job:");
    const candidates = [];
    for (const key of keys) {
      const raw = await this.kv.get(key.name);
      const job = raw === null ? null : safeJsonParse(raw, null);
      if (!job) continue;
      const ready =
        (["queued", "retrying", "summary_pending"].includes(job.status) &&
          Number(job.next_attempt || 0) <= now) ||
        (job.status === "running" &&
          Number(job.updated_at || 0) < now - STALE_JOB_MS);
      if (ready) candidates.push(job);
    }
    candidates.sort((a, b) => Number(a.created_at) - Number(b.created_at));
    if (candidates.length === 0) return null;
    return this.claimJobById(candidates[0].id, now);
  }

  async updateJob(id, patch) {
    const job = await this.getJob(id);
    if (!job) return;
    for (const [key, value] of Object.entries(patch)) {
      if (JOB_UPDATE_FIELDS.has(key)) job[key] = value;
    }
    await this.putJob(job);
  }

  async cleanup() {}
}

function safeJsonParse(raw, fallback) {
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

async function kvListAll(kv, prefix) {
  const keys = [];
  let cursor;
  do {
    const page = await kv.list({ prefix, cursor });
    keys.push(...page.keys);
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return keys;
}

function createStore(env, config) {
  if (config.storageBackend === "d1") {
    if (!env.DB) throw new Error("STORAGE_BACKEND=d1 but DB binding is missing");
    return new D1Store(env.DB);
  }
  if (config.storageBackend === "kv") {
    if (!env.WHITELIST_KV) {
      throw new Error("STORAGE_BACKEND=kv but WHITELIST_KV binding is missing");
    }
    return new KVStore(env.WHITELIST_KV);
  }
  if (env.DB) return new D1Store(env.DB);
  if (env.WHITELIST_KV) return new KVStore(env.WHITELIST_KV);
  throw new Error("Bind either DB (D1) or WHITELIST_KV (KV)");
}

async function resolveUsernameToId(config, username) {
  const normalized = normalizeUsername(username);
  if (!normalized) return null;
  try {
    const chat = await telegramApi(config, "getChat", {
      chat_id: `@${normalized}`,
    });
    if (
      chat?.type === "private" &&
      !chat.is_bot &&
      chat.id !== undefined
    ) {
      return { telegramId: String(chat.id), username: normalized };
    }
  } catch {
    return null;
  }
  return null;
}

function isAdmin(config, identity) {
  return Boolean(identity?.id && String(identity.id) === String(config.adminId));
}

async function identityAllowed(store, config, identity) {
  if (isAdmin(config, identity)) return true;
  return store.isAllowed(identity);
}

function commandName(text) {
  const first = asString(text).split(/\s+/)[0] || "";
  if (!first.startsWith("/")) return "";
  return first.split("@")[0].toLowerCase();
}

function commandArgs(text) {
  return asString(text).split(/\s+/).slice(1);
}

function startText() {
  return [
    "TG Forward Hub Worker Bot",
    "",
    "发送 Telegram 消息链接即可复制内容。",
    "支持完整相册、单条消息和消息 ID 区间。",
    "",
    "链接示例：",
    "https://t.me/username/123",
    "https://t.me/username/100-120",
    "",
    "常用命令：",
    "/help 查看全部链接格式和命令说明",
    "/whoami 查看 ID、用户名、管理员和白名单状态",
  ].join("\n");
}

function helpText(isAdminUser) {
  const lines = [
    "使用说明",
    "",
    "发送以下任一链接即可复制内容：",
    "",
    "公开频道/群组：",
    "https://t.me/username/123",
    "",
    "私有频道/群组（Bot 必须是成员）：",
    "https://t.me/c/123456789/123",
    "",
    "Bot 消息：",
    "https://t.me/b/botname/123",
    "",
    "区间：",
    "https://t.me/username/100-120",
    "https://t.me/username/100 120",
    "https://t.me/username/100-https://t.me/username/120",
    "https://t.me/username/100 https://t.me/username/120",
    "",
    "说明：",
    "- 相册链接会复制完整媒体组。",
    "- ?single 是 Telegram 分享参数，不会只复制第一项，也不影响区间终点。",
    "- 只有管理员和白名单用户可以使用。",
    "",
    "普通命令：",
    "/start 查看快速入门",
    "/help 查看本说明",
    "/whoami 查看 Telegram ID、用户名、管理员和白名单状态",
  ];
  if (isAdminUser) {
    lines.push(
      "",
      "管理员命令：",
      "/allow <数字ID|@username> 添加白名单",
      "/deny <数字ID|@username> 移出白名单",
      "/list 查看全部白名单",
    );
  }
  return lines.join("\n");
}

function formatWhitelist(entries) {
  if (!entries.length) return "白名单为空";
  const lines = entries.map((entry) => {
    const id = entry.telegram_id ? String(entry.telegram_id) : "未解析ID";
    const username = entry.username ? ` (@${entry.username})` : "";
    return `• ${id}${username}`;
  });
  return `白名单（${entries.length}）：\n${lines.join("\n")}`;
}

async function sendNotAllowed(config, chatId, identity, messageId) {
  const username = identity.username ? ` (@${identity.username})` : "";
  await sendText(
    config,
    chatId,
    "⛔ 你不在白名单中。\n\n" +
      `Telegram ID: ${identity.id}${username}\n` +
      "请把上面的数字 ID 或用户名发给管理员加入白名单。",
    messageId,
  );
}

async function handleCommand({
  update,
  config,
  store,
  identity,
  message,
  command,
}) {
  const admin = isAdmin(config, identity);
  const chatId = message.chat.id;
  const messageId = message.message_id;

  if (command === "/start") {
    await sendText(config, chatId, startText(), messageId);
    return true;
  }
  if (command === "/help") {
    await sendText(config, chatId, helpText(admin), messageId);
    return true;
  }
  if (command === "/whoami") {
    const allowed = await identityAllowed(store, config, identity);
    await sendText(
      config,
      chatId,
      `Telegram ID: ${identity.id}\n` +
        `用户名: ${identity.username ? `@${identity.username}` : "未设置"}\n` +
        `管理员: ${admin ? "是" : "否"}\n` +
        `白名单: ${allowed ? "是" : "否"}`,
      messageId,
    );
    return true;
  }

  if (!["/allow", "/deny", "/list"].includes(command)) {
    return false;
  }
  if (!admin) {
    await sendText(config, chatId, "⛔ 只有管理员可以使用这个命令。", messageId);
    return true;
  }

  if (command === "/list") {
    const entries = await store.list();
    await sendText(config, chatId, formatWhitelist(entries), messageId);
    return true;
  }

  const args = commandArgs(message.text || "");
  const targetRaw = args[0] || "";
  const target = parseWhitelistTarget(targetRaw);
  if (!target) {
    await sendText(
      config,
      chatId,
      "参数格式错误。用法：\n" +
        "/allow <数字ID|@username>\n" +
        "/deny <数字ID|@username>",
      messageId,
    );
    return true;
  }

  if (command === "/deny") {
    if (target.telegramId && target.telegramId === String(config.adminId)) {
      await sendText(config, chatId, "管理员 ID 不能被移出白名单。", messageId);
      return true;
    }
    const removed = await store.remove(target);
    await sendText(
      config,
      chatId,
      removed > 0 ? "✅ 已移出白名单。" : "没有找到对应的白名单记录。",
      messageId,
    );
    return true;
  }

  let resolved = null;
  if (target.username) {
    resolved = await resolveUsernameToId(config, target.username);
  }
  const entry = await store.add({
    telegramId: target.telegramId || resolved?.telegramId || "",
    username: target.username || resolved?.username || "",
  });

  if (target.username && !resolved) {
    await sendText(
      config,
      chatId,
      `⚠️ 已保存用户名 @${target.username}，但 Bot API 暂时无法把它解析成数字 ID。\n` +
        "请让该用户先给 Bot 发送 /start，或改用数字 ID 添加。",
      messageId,
    );
    return true;
  }

  const id = entry?.telegram_id ? String(entry.telegram_id) : "未解析";
  const name = entry?.username ? ` (@${entry.username})` : "";
  await sendText(
    config,
    chatId,
    `✅ 已加入白名单：${id}${name}`,
    messageId,
  );
  return true;
}

async function callContainer(
  env,
  config,
  path,
  payload,
  { allowError = false } = {},
) {
  if (!env.BOT_CONTAINER) {
    throw new Error("BOT_CONTAINER binding is missing");
  }
  const issues = configIssues(config, { requireContainer: true });
  if (issues.length) throw new Error(issues.join("; "));

  const stub = env.BOT_CONTAINER.getByName(config.containerInstanceId);
  const response = await stub.fetch(`https://container${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(120_000),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data?.ok) {
    if (allowError) {
      return (
        data || {
          ok: false,
          error: `Container returned ${response.status}`,
          retry_after: 0,
        }
      );
    }
    const error = new TelegramApiError(
      data?.error || `Container returned ${response.status}`,
      {
        code: response.status,
        retryAfter: Number(data?.retry_after || 0),
      },
    );
    throw error;
  }
  return data;
}

async function sendJobError(config, job, error) {
  const text =
    `❌ 转发失败\n\n` +
    `来源: ${job.source_chat}\n` +
    `消息: ${job.start_id}-${job.end_id}\n` +
    `错误: ${error?.message || String(error)}`;
  await sendText(config, job.chat_id, text, job.reply_to_message_id);
}

async function processSingleJob(env, config, store, job) {
  try {
    const result = await callContainer(
      env,
      config,
      "/copy-single",
      {
        chat_id: job.chat_id,
        source_chat: job.source_chat,
        message_id: job.start_id,
      },
    );
    const copiedIds = Array.isArray(result.copied_ids)
      ? result.copied_ids
      : [];
    const skipped = Boolean(result.skipped) || copiedIds.length === 0;
    job.success_count = skipped ? 0 : 1;
    job.skipped_count = skipped ? 1 : 0;
    job.next_id = job.end_id + 1;
    job.status = "summary_pending";
    job.next_attempt = 0;
    job.updated_at = nowMs();
    job.last_error = "";
    await store.updateJob(job.id, job);
    await sendJobSummary(store, config, job);
  } catch (error) {
    job.attempts = Number(job.attempts || 0) + 1;
    job.updated_at = nowMs();
    job.last_error = error?.message || String(error);
    if (error?.retryAfter > 0) {
      job.status = "retrying";
      job.next_attempt = nowMs() + error.retryAfter * 1000;
      await store.updateJob(job.id, job);
      return;
    }
    job.status = "failed";
    job.next_attempt = 0;
    await store.updateJob(job.id, job);
    await sendJobError(config, job, error).catch(() => {});
  }
}

async function processRangeJob(env, config, store, job) {
  let processedChunks = 0;
  while (
    processedChunks < JOB_MAX_CHUNKS_PER_RUN &&
    job.next_id <= job.end_id
  ) {
    const chunkStart = Number(job.next_id);
    const chunkEnd = Math.min(
      chunkStart + CONTAINER_RANGE_CHUNK_SIZE - 1,
      job.end_id,
    );

    try {
      const result = await callContainer(
        env,
        config,
        "/copy-range",
        {
          chat_id: job.chat_id,
          source_chat: job.source_chat,
          start_id: chunkStart,
          end_id: chunkEnd,
        },
        { allowError: true },
      );
      job.success_count =
        Number(job.success_count || 0) +
        Number(result.success_count || 0);
      job.skipped_count =
        Number(job.skipped_count || 0) +
        Number(result.skipped_count || 0);
      job.failed_ids = [
        ...new Set([
          ...(job.failed_ids || []).map(Number),
          ...(Array.isArray(result.failed_ids)
            ? result.failed_ids.map(Number)
            : []),
        ]),
      ];
      job.next_id = Math.max(
        chunkStart + 1,
        Number(result.next_id || chunkEnd + 1),
      );
      job.updated_at = nowMs();
      job.last_error = result.ok
        ? ""
        : result.error || "container range copy failed";

      if (!result.ok) {
        job.attempts = Number(job.attempts || 0) + 1;
        job.status = "retrying";
        job.next_attempt =
          nowMs() +
          (Number(result.retry_after || 0) > 0
            ? Number(result.retry_after) * 1000
            : JOB_RETRY_DELAY_MS);
        await store.updateJob(job.id, job);
        return;
      }

      await store.updateJob(job.id, job);
      processedChunks += 1;
    } catch (error) {
      job.attempts = Number(job.attempts || 0) + 1;
      job.updated_at = nowMs();
      job.last_error = error?.message || String(error);

      job.status = "retrying";
      job.next_attempt =
        nowMs() +
        (Number(error?.retryAfter || 0) > 0
          ? Number(error.retryAfter) * 1000
          : JOB_RETRY_DELAY_MS);
      await store.updateJob(job.id, job);
      return;
    }
  }

  if (job.next_id > job.end_id) {
    job.status = "summary_pending";
    job.next_attempt = 0;
    job.updated_at = nowMs();
    await store.updateJob(job.id, job);
    await sendJobSummary(store, config, job);
    return;
  }

  job.status = "queued";
  job.next_attempt = 0;
  job.updated_at = nowMs();
  await store.updateJob(job.id, job);
}

async function sendJobSummary(store, config, job) {
  if (job.summary_sent) {
    job.status = "done";
    job.next_attempt = 0;
    job.updated_at = nowMs();
    await store.updateJob(job.id, job);
    return;
  }
  if (!(await store.getSetting("batch_completion_notifications_enabled", true))) {
    job.status = "done";
    job.next_attempt = 0;
    job.updated_at = nowMs();
    await store.updateJob(job.id, job);
    return;
  }
  try {
    await sendText(
      config,
      job.chat_id,
      buildSummary(job),
      job.reply_to_message_id,
    );
    job.summary_sent = 1;
    job.status = "done";
    job.next_attempt = 0;
    job.updated_at = nowMs();
    await store.updateJob(job.id, job);
  } catch (error) {
    job.status = "summary_pending";
    job.next_attempt = nowMs() + JOB_RETRY_DELAY_MS;
    job.updated_at = nowMs();
    job.last_error = error?.message || String(error);
    await store.updateJob(job.id, job);
  }
}

async function processClaimedJob(env, config, store, job) {
  if (!job) return;
  if (job.kind === "single") {
    await processSingleJob(env, config, store, job);
    return;
  }
  if (job.status === "summary_pending" || job.next_id > job.end_id) {
    await sendJobSummary(store, config, job);
    return;
  }
  await processRangeJob(env, config, store, job);
}

async function processJobById(env, config, store, jobId) {
  const job = await store.claimJobById(jobId);
  if (!job) return;
  await processClaimedJob(env, config, store, job);
}

async function processQueue(env, config, store) {
  for (let index = 0; index < JOB_MAX_PER_CRON; index += 1) {
    const job = await store.claimJob();
    if (!job) break;
    await processClaimedJob(env, config, store, job);
  }
  await store.cleanup();
}

async function handleLink({
  env,
  ctx,
  config,
  store,
  message,
  link,
  identity,
}) {
  const totalMessages = link.toId - link.fromId + 1;
  if (totalMessages <= 0) {
    await sendText(
      config,
      message.chat.id,
      "❌ 消息区间无效：结束 ID 必须大于等于开始 ID。",
      message.message_id,
    );
    return;
  }
  if (totalMessages > config.maxRangeMessages) {
    await sendText(
      config,
      message.chat.id,
      `❌ 消息区间过大，最多 ${config.maxRangeMessages} 条。`,
      message.message_id,
    );
    return;
  }

  const sourceChat = sourceChatForLink(link);
  const issues = configIssues(config, { requireContainer: true });
  if (issues.length) {
    await sendText(
      config,
      message.chat.id,
      `❌ Container 配置不完整：${issues.join("; ")}`,
      message.message_id,
    );
    return;
  }

  const requestKey = [
    "link",
    message.chat.id,
    sourceChat,
    link.fromId,
    link.toId,
    link.single ? "single" : "range",
  ].join(":");
  if (!(await store.claimRequest(requestKey, 30))) {
    console.log("duplicate link request ignored", requestKey);
    return;
  }

  const notify = await store.getSetting(
    "batch_completion_notifications_enabled",
    true,
  );
  try {
    await callContainer(env, config, "/forward", {
      chat_id: message.chat.id,
      source_chat: sourceChat,
      start_id: link.fromId,
      end_id: link.toId,
      reply_to_message_id: message.message_id,
      notify,
    });
  } catch (error) {
    await sendText(
      config,
      message.chat.id,
      `❌ 提交转发任务失败：${error?.message || String(error)}`,
      message.message_id,
    );
  }
}

async function handleCallbackQuery({ config, store, callbackQuery }) {
  const identity = identityFromTelegramUser(callbackQuery.from);
  if (!identity) return;
  if (!(await identityAllowed(store, config, identity))) {
    await telegramApi(config, "answerCallbackQuery", {
      callback_query_id: callbackQuery.id,
      text: "你不在白名单中",
      show_alert: true,
    }).catch(() => {});
    return;
  }
  await telegramApi(config, "answerCallbackQuery", {
    callback_query_id: callbackQuery.id,
    text: "OK",
  }).catch(() => {});
}

async function handleUpdate(update, env, config, ctx) {
  const store = createStore(env, config);
  await store.init();

  if (update?.update_id && !(await store.claimUpdate(update.update_id))) {
    return;
  }

  if (update?.callback_query) {
    await handleCallbackQuery({
      config,
      store,
      callbackQuery: update.callback_query,
    });
    return;
  }

  const message = update?.message;
  if (!message || !message.from || message.from.is_bot) return;
  if (message.chat?.type !== "private") return;

  const identity = identityFromTelegramUser(message.from);
  if (!identity) return;

  const text = asString(message.text);
  const command = commandName(text);
  if (command) {
    const handled = await handleCommand({
      update,
      config,
      store,
      identity,
      message,
      command,
    });
    if (handled) return;
  }

  if (!(await identityAllowed(store, config, identity))) {
    await sendNotAllowed(config, message.chat.id, identity, message.message_id);
    return;
  }

  if (!text) return;
  const link = parseMessageLink(text);
  if (!link) {
    await sendText(
      config,
      message.chat.id,
      "❌ 无效链接。发送 /help 查看支持的格式。",
      message.message_id,
    );
    return;
  }

  await handleLink({
    env,
    ctx,
    config,
    store,
    message,
    link,
    identity,
  });
}

export class BotContainer extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.starting = null;
    this.ready = false;
    if (ctx.container?.running) {
      ctx.blockConcurrencyWhile(() =>
        ctx.container.setInactivityTimeout(
          resolveConfig(env).containerInactivityMs,
        ),
      );
    }
  }

  async fetch(request) {
    await this.ensureRunning();
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");
    try {
      return await this.ctx.container.getTcpPort(
        resolveConfig(this.env).containerPort,
      ).fetch(forwarded);
    } catch (error) {
      this.ready = false;
      throw error;
    }
  }

  async ensureRunning() {
    if (this.ready && this.ctx.container?.running) return;
    this.ready = false;
    this.starting ??= this.startAndWaitForPort().finally(() => {
      this.starting = null;
    });
    await this.starting;
    this.ready = true;
  }

  async startAndWaitForPort() {
    const config = resolveConfig(this.env);
    const container = this.ctx.container;
    if (!container) throw new Error("Container binding is unavailable");

    if (!container.running) {
      container.start({
        image: container.images.base,
        instance: "standard-1",
        enableInternet: true,
        env: {
          BOT_TOKEN: config.botToken,
          API_ID: config.apiId,
          API_HASH: config.apiHash,
          PORT: String(config.containerPort),
        },
      });
    }
    await container.setInactivityTimeout(config.containerInactivityMs);

    const port = container.getTcpPort(config.containerPort);
    let lastError;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        const response = await port.fetch("http://container/healthz", {
          signal: AbortSignal.timeout(1000),
        });
        await response.body?.cancel();
        if (!response.ok) {
          throw new Error(`healthz returned ${response.status}`);
        }
        return;
      } catch (error) {
        lastError = error;
        await sleep(200);
      }
    }
    throw new Error("Container did not become ready on port 8080", {
      cause: lastError,
    });
  }
}

async function handleInstall(request, config) {
  if (!config.webhookSecret) {
    return jsonResponse(
      { ok: false, error: "WEBHOOK_SECRET is required for /install" },
      400,
    );
  }
  const url = new URL(request.url);
  if (url.searchParams.get("secret") !== config.webhookSecret) {
    return jsonResponse({ ok: false, error: "invalid secret" }, 401);
  }
  const issues = configIssues(config);
  if (issues.length) {
    return jsonResponse({ ok: false, error: issues.join("; ") }, 400);
  }

  const webhookUrl = `${url.origin}/webhook`;
  const result = await telegramApi(config, "setWebhook", {
    url: webhookUrl,
    secret_token: config.webhookSecret,
    allowed_updates: ["message", "callback_query"],
  });
  return jsonResponse({ ok: true, webhook: webhookUrl, result });
}

async function handleHealth(env, config) {
  const issues = configIssues(config);
  if (!env.DB && !env.WHITELIST_KV) {
    issues.push("Bind either DB (D1) or WHITELIST_KV (KV)");
  }
  let backend = "none";
  if (env.DB) backend = "d1";
  else if (env.WHITELIST_KV) backend = "kv";
  return jsonResponse({
    ok: issues.length === 0,
    backend,
    bindings: {
      db: Boolean(env.DB),
      kv: Boolean(env.WHITELIST_KV),
      container: Boolean(env.BOT_CONTAINER),
    },
    configured: {
      bot_token: Boolean(config.botToken),
      admin_id: Boolean(config.adminId),
      api_id: Boolean(config.apiId),
      api_hash: Boolean(config.apiHash),
      webhook_secret: Boolean(config.webhookSecret),
      web_admin: webConfigured(config),
    },
    issues,
  });
}

export default {
  async fetch(request, env, ctx) {
    const config = resolveConfig(env);
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return redirectResponse("/admin");
    }
    if (
      url.pathname === "/admin" ||
      url.pathname.startsWith("/admin/")
    ) {
      try {
        return await handleAdminRoute(request, env, config);
      } catch (error) {
        console.error("admin route failed", error);
        return textResponse("Admin page failed", 500);
      }
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return handleHealth(env, config);
    }
    if (request.method === "GET" && url.pathname === "/install") {
      try {
        return await handleInstall(request, config);
      } catch (error) {
        return jsonResponse({ ok: false, error: error.message }, 502);
      }
    }
    if (request.method !== "POST" || url.pathname !== "/webhook") {
      return textResponse("Not found", 404);
    }

    if (config.webhookSecret) {
      const received = request.headers.get(
        "x-telegram-bot-api-secret-token",
      );
      if (received !== config.webhookSecret) {
        return textResponse("Unauthorized", 401);
      }
    }

    const issues = configIssues(config);
    if (issues.length) {
      return jsonResponse({ ok: false, error: issues.join("; ") }, 500);
    }
    if (!env.DB && !env.WHITELIST_KV) {
      return jsonResponse(
        { ok: false, error: "Bind either DB (D1) or WHITELIST_KV (KV)" },
        500,
      );
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return textResponse("Invalid JSON", 400);
    }

    ctx.waitUntil(
      handleUpdate(update, env, config, ctx).catch((error) => {
        console.error("handleUpdate failed", error);
      }),
    );
    return textResponse("ok");
  },
};
