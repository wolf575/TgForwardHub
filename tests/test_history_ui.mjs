import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";


const testDir = path.dirname(fileURLToPath(import.meta.url));
const scriptPath = [
  path.join(testDir, "..", "static", "js", "merged.js"),
  path.join(testDir, "..", "container", "app", "static", "js", "merged.js"),
].find((candidate) => fs.existsSync(candidate));

if (!scriptPath) {
  throw new Error("Unable to locate static/js/merged.js");
}


function loadHistoryHelpers() {
  const element = {
    addEventListener() {},
    value: "",
  };
  const context = {
    clearInterval,
    clearTimeout,
    console,
    document: {
      addEventListener() {},
      getElementById() {
        return element;
      },
    },
    fetch() {
      throw new Error("fetch is not available in this unit test");
    },
    localStorage: {
      getItem() {
        return null;
      },
      setItem() {},
    },
    setInterval() {
      return 1;
    },
    setTimeout,
    window: {},
  };
  vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), context);
  return context;
}


test("time range history renders timestamps as local dates", () => {
  const context = loadHistoryHelpers();
  const start = Math.floor(new Date(2026, 9, 1).getTime() / 1000);
  const end = Math.floor(new Date(2026, 9, 7).getTime() / 1000);
  const summary = context.historySubtitle({
    sourceId: "@source",
    targetId: "@target",
    status: "done",
    createdAt: "2026-11-05T08:30:00+08:00",
    task_spec: {
      range_type: "time",
      start,
      end,
    },
    state: {},
  });

  assert.match(summary, /时间: 2026-10-01 → 2026-10-07/);
  assert.match(summary, /来源: @source/);
  assert.match(summary, /创建: /);
});


test("message id history keeps the id range visible", () => {
  const context = loadHistoryHelpers();
  const summary = context.historySubtitle({
    task_spec: {
      range_type: "id",
      start: 100,
      end: 250,
    },
    state: {},
  });

  assert.match(summary, /消息 ID: 100 → 250/);
});
