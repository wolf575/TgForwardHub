import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workerUrl = new URL("../_worker.js", import.meta.url);
let workerSource = await readFile(workerUrl, "utf8");

workerSource = workerSource.replace(
  'import { DurableObject } from "cloudflare:workers";',
  "class DurableObject { constructor(ctx, env) { this.ctx = ctx; this.env = env; } }",
);

const moduleUrl = `data:text/javascript;base64,${Buffer.from(
  workerSource,
).toString("base64")}`;
const worker = await import(moduleUrl);

test("parses public single links", () => {
  assert.deepEqual(worker.parseMessageLink("https://t.me/durov/123"), {
    kind: "",
    chat: "durov",
    fromId: 123,
    toId: 123,
    single: true,
  });
});

test("parses private and bot links", () => {
  assert.deepEqual(worker.parseMessageLink("https://t.me/c/123456789/42"), {
    kind: "c/",
    chat: "123456789",
    fromId: 42,
    toId: 42,
    single: true,
  });
  assert.deepEqual(worker.parseMessageLink("https://t.me/b/example_bot/9"), {
    kind: "b/",
    chat: "example_bot",
    fromId: 9,
    toId: 9,
    single: true,
  });
});

test("parses hyphen and whitespace ranges", () => {
  assert.equal(
    worker.parseMessageLink("https://t.me/channel/100-120").toId,
    120,
  );
  assert.equal(
    worker.parseMessageLink("https://t.me/channel/100 120").toId,
    120,
  );
});

test("parses a second complete link as the range end", () => {
  const parsed = worker.parseMessageLink(
    "https://t.me/channel/100-https://t.me/channel/120",
  );
  assert.equal(parsed.fromId, 100);
  assert.equal(parsed.toId, 120);
  assert.equal(parsed.single, false);
});

test("ignores ?single while preserving the message range", () => {
  const parsed = worker.parseMessageLink("https://t.me/channel/100-120?single");
  assert.equal(parsed.fromId, 100);
  assert.equal(parsed.toId, 120);
  assert.equal(parsed.single, false);
  const userCase = worker.parseMessageLink(
    "https://t.me/kukutui2/55260?single https://t.me/kukutui2/55268",
  );
  assert.deepEqual(userCase, {
    kind: "",
    chat: "kukutui2",
    fromId: 55260,
    toId: 55268,
    single: false,
  });
  assert.equal(worker.parseMessageLink("not a telegram link"), null);
  assert.equal(worker.parseMessageLink("https://t.me/c/not-a-number/1"), null);
});

test("normalizes usernames and whitelist targets", () => {
  assert.equal(worker.normalizeUsername(" @Alice "), "alice");
  assert.deepEqual(worker.parseWhitelistTarget("@Alice"), {
    telegramId: "",
    username: "alice",
  });
  assert.deepEqual(worker.parseWhitelistTarget("123456789"), {
    telegramId: "123456789",
    username: "",
  });
  assert.equal(worker.parseWhitelistTarget("@bad-name"), null);
});

test("builds source references", () => {
  assert.equal(
    worker.sourceChatForLink({ kind: "c/", chat: "123456789" }),
    "-100123456789",
  );
  assert.equal(
    worker.sourceChatForLink({ kind: "", chat: "durov" }),
    "@durov",
  );
  assert.equal(
    worker.sourceChatForLink({ kind: "b/", chat: "example_bot" }),
    "@example_bot",
  );
});

test("builds summaries with success, skip and failure variants", () => {
  assert.equal(
    worker.buildSummary({
      total_messages: 3,
      success_count: 2,
      skipped_count: 1,
      failed_ids: [],
    }),
    "📊 批量转发完成\n\n✅ 成功: 2/3\n⏭️ 跳过: 1",
  );
  assert.equal(
    worker.buildSummary({
      total_messages: 3,
      success_count: 1,
      skipped_count: 0,
      failed_ids: [2, 3],
    }),
    "📊 批量转发完成\n\n✅ 成功: 1/3\n❌ 失败: 2\n⏭️ 跳过: 0\n\n失败的消息ID: 2, 3",
  );
  assert.equal(
    worker.buildSummary({
      total_messages: 1,
      success_count: 1,
      skipped_count: 0,
      failed_ids: [],
    }),
    "✅ 批量转发完成\n\n成功转发 1/1 条消息",
  );
});

class FakeKV {
  constructor() {
    this.values = new Map();
  }

  async get(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  async put(key, value) {
    this.values.set(key, String(value));
  }

  async delete(key) {
    this.values.delete(key);
  }

  async list({ prefix = "" } = {}) {
    return {
      keys: [...this.values.keys()]
        .filter((key) => key.startsWith(prefix))
        .map((name) => ({ name })),
      list_complete: true,
    };
  }
}

function makeCtx() {
  const pending = [];
  return {
    pending,
    waitUntil(promise) {
      pending.push(Promise.resolve(promise));
    },
  };
}

async function flushCtx(ctx) {
  while (ctx.pending.length > 0) {
    const batch = ctx.pending.splice(0);
    await Promise.all(batch);
  }
}

function makeEnv(kv, container = null) {
  return {
    BOT_TOKEN: "123:test",
    API_ID: "12345",
    API_HASH: "test-api-hash",
    ADMIN_ID: "999",
    STORAGE_BACKEND: "kv",
    MAX_RANGE_MESSAGES: "100",
    WHITELIST_KV: kv,
    BOT_CONTAINER: container,
  };
}

function makeFakeContainer(calls) {
  return {
    getByName(id) {
      return {
        async fetch(url, init) {
          const path = new URL(url).pathname;
          const body = JSON.parse(init.body);
          calls.push({ id, path, body });
          if (path === "/forward") {
            return new Response(
              JSON.stringify({ ok: true, accepted: true, job_id: "job-1" }),
              {
                status: 202,
                headers: { "content-type": "application/json" },
              },
            );
          }
          if (path === "/copy-range") {
            return new Response(
              JSON.stringify({
                ok: true,
                next_id: body.end_id + 1,
                success_count: body.end_id - body.start_id + 1,
                skipped_count: 0,
                failed_ids: [],
              }),
              {
                status: 200,
                headers: { "content-type": "application/json" },
              },
            );
          }
          return new Response(
            JSON.stringify({
              ok: true,
              copied_ids: [body.message_id],
              skipped: false,
            }),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        },
      };
    },
  };
}

function makeUpdate(updateId, fromId, text, chatId = fromId) {
  return {
    update_id: updateId,
    message: {
      message_id: updateId,
      text,
      from: { id: fromId, is_bot: false, first_name: "User" },
      chat: { id: chatId, type: "private" },
    },
  };
}

test("webhook rejects users outside the whitelist", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const method = new URL(url).pathname.split("/").pop();
    calls.push({ method, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ ok: true, result: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const kv = new FakeKV();
    const ctx = makeCtx();
    const response = await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(
          makeUpdate(1, 42, "https://t.me/example/1"),
        ),
      }),
      makeEnv(kv),
      ctx,
    );
    assert.equal(response.status, 200);
    await flushCtx(ctx);
    const sent = calls.find((call) => call.method === "sendMessage");
    assert.ok(sent);
    assert.match(sent.body.text, /不在白名单/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("help explains commands without internal routing details", async () => {
  const originalFetch = globalThis.fetch;
  let sentText = "";
  globalThis.fetch = async (url, init) => {
    const method = new URL(url).pathname.split("/").pop();
    if (method === "sendMessage") {
      sentText = JSON.parse(init.body).text;
    }
    return new Response(JSON.stringify({ ok: true, result: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const ctx = makeCtx();
    await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(makeUpdate(2, 999, "/help")),
      }),
      makeEnv(new FakeKV()),
      ctx,
    );
    await flushCtx(ctx);

    assert.ok(sentText.includes("普通命令："));
    assert.ok(sentText.includes("/allow <数字ID|@username> 添加白名单"));
    assert.ok(sentText.includes("?single 是 Telegram 分享参数"));
    assert.equal(sentText.includes("单条链接由 Container 处理"), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("admin can allow an ID and a range is copied through Container", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const containerCalls = [];
  globalThis.fetch = async (url, init) => {
    const method = new URL(url).pathname.split("/").pop();
    const body = JSON.parse(init.body);
    calls.push({ method, body });
    return new Response(JSON.stringify({ ok: true, result: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const kv = new FakeKV();
    const env = makeEnv(kv, makeFakeContainer(containerCalls));
    const allowCtx = makeCtx();
    await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(makeUpdate(2, 999, "/allow 42")),
      }),
      env,
      allowCtx,
    );
    await flushCtx(allowCtx);
    assert.ok(kv.values.has("allow:id:42"));

    const copyCtx = makeCtx();
    await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(
          makeUpdate(
            3,
            42,
            "https://t.me/example/1?single https://t.me/example/2",
          ),
        ),
      }),
      env,
      copyCtx,
    );
    await flushCtx(copyCtx);

    assert.equal(containerCalls.length, 1);
    assert.equal(containerCalls[0].path, "/forward");
    assert.equal(containerCalls[0].body.start_id, 1);
    assert.equal(containerCalls[0].body.end_id, 2);
    assert.equal("single_media_id" in containerCalls[0].body, false);
    assert.equal(containerCalls[0].body.notify, true);

    const duplicateCtx = makeCtx();
    await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(
          makeUpdate(
            4,
            42,
            "https://t.me/example/1?single https://t.me/example/2",
          ),
        ),
      }),
      env,
      duplicateCtx,
    );
    await flushCtx(duplicateCtx);
    assert.equal(containerCalls.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("web admin can login, add and delete a whitelist entry", async () => {
  const kv = new FakeKV();
  const env = {
    ...makeEnv(kv),
    WEB_ADMIN_USER: "admin",
    WEB_ADMIN_PASSWORD: "secret-password",
    SESSION_SECRET: "test-session-secret",
  };
  const ctx = makeCtx();

  const loginResponse = await worker.default.fetch(
    new Request("https://worker.test/admin/login", {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded",
        origin: "https://worker.test",
      },
      body: new URLSearchParams({
        username: "admin",
        password: "secret-password",
      }),
    }),
    env,
    ctx,
  );
  assert.equal(loginResponse.status, 302);
  const cookie = loginResponse.headers.get("set-cookie").split(";")[0];
  assert.match(cookie, /^tfh_admin=/);

  const pageResponse = await worker.default.fetch(
    new Request("https://worker.test/admin", {
      headers: { cookie },
    }),
    env,
    ctx,
  );
  assert.equal(pageResponse.status, 200);
  const pageHtml = await pageResponse.text();
  assert.match(pageHtml, /白名单/);
  assert.match(pageHtml, /Bot 通知/);
  const csrfMatch = pageHtml.match(/name="csrf" value="([^"]+)"/);
  assert.ok(csrfMatch);
  const csrf = csrfMatch[1];

  const addResponse = await worker.default.fetch(
    new Request("https://worker.test/admin/whitelist/add", {
      method: "POST",
      headers: {
        cookie,
        origin: "https://worker.test",
        "content-type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ csrf, target: "42" }),
    }),
    env,
    ctx,
  );
  assert.equal(addResponse.status, 302);
  assert.ok(kv.values.has("allow:id:42"));

  const afterAdd = await worker.default.fetch(
    new Request("https://worker.test/admin", {
      headers: { cookie },
    }),
    env,
    ctx,
  );
  assert.match(await afterAdd.text(), /class="mono">42<\/td>/);

  const deleteResponse = await worker.default.fetch(
    new Request("https://worker.test/admin/whitelist/delete", {
      method: "POST",
      headers: {
        cookie,
        origin: "https://worker.test",
        "content-type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        csrf,
        telegram_id: "42",
        username: "",
      }),
    }),
    env,
    ctx,
  );
  assert.equal(deleteResponse.status, 302);
  assert.equal(kv.values.has("allow:id:42"), false);

  const settingsResponse = await worker.default.fetch(
    new Request("https://worker.test/admin/settings", {
      method: "POST",
      headers: {
        cookie,
        origin: "https://worker.test",
        "content-type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ csrf }),
    }),
    env,
    ctx,
  );
  assert.equal(settingsResponse.status, 302);
  assert.equal(
    kv.values.get("setting:batch_completion_notifications_enabled"),
    "false",
  );
});

test("web login accepts a custom domain forwarded by Cloudflare", async () => {
  const kv = new FakeKV();
  const env = {
    ...makeEnv(kv),
    WEB_ADMIN_USER: "admin",
    WEB_ADMIN_PASSWORD: "secret-password",
    SESSION_SECRET: "test-session-secret",
  };
  const ctx = makeCtx();
  const response = await worker.default.fetch(
    new Request("https://worker.test/admin/login", {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded",
        origin: "https://forward.example.com",
        host: "forward.example.com",
      },
      body: new URLSearchParams({
        username: "admin",
        password: "secret-password",
      }),
    }),
    env,
    ctx,
  );
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "/admin");
});

test("completion notifications can be disabled while forwarding continues", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const containerCalls = [];
  globalThis.fetch = async (url, init) => {
    const method = new URL(url).pathname.split("/").pop();
    calls.push({ method, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ ok: true, result: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const kv = new FakeKV();
    kv.values.set(
      "allow:id:42",
      JSON.stringify({ telegram_id: "42", username: null, created_at: Date.now() }),
    );
    kv.values.set(
      "setting:batch_completion_notifications_enabled",
      "false",
    );
    const env = makeEnv(kv, makeFakeContainer(containerCalls));
    const ctx = makeCtx();
    await worker.default.fetch(
      new Request("https://worker.test/webhook", {
        method: "POST",
        body: JSON.stringify(
          makeUpdate(21, 42, "https://t.me/example/1-2"),
        ),
      }),
      env,
      ctx,
    );
    await flushCtx(ctx);
    assert.equal(containerCalls.length, 1);
    assert.equal(containerCalls[0].path, "/forward");
    assert.equal(containerCalls[0].body.notify, false);
    assert.equal(
      calls.filter((call) => call.method === "sendMessage").length,
      0,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
