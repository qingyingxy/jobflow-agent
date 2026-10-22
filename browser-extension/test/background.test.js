import assert from "node:assert/strict";
import { test } from "node:test";

let listener, answers = [], created = [], removed = [], activated = [], nextClicks = 0;
const originalTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn) => originalTimeout(fn, 0);
globalThis.chrome = {
  action: { onClicked: { addListener() {} } },
  runtime: { onMessage: { addListener(fn) { listener = fn; } } },
  tabs: {
    async create(options) { created.push(options); return { id: 7 }; },
    async remove(id) { removed.push(id); },
    async update(id, options) { activated.push({ id, ...options }); },
  },
  scripting: { async executeScript({ func }) {
    if (func.name === "nextTongchengPage") { nextClicks++; return [{ result: true }]; }
    assert.ok(answers.length, "reader was polled beyond supplied observations");
    return [{ result: answers.shift() }];
  } },
};
const { allowedSender } = await import("../background.js");
const url = "https://mhr.ly.com/recruit/schoolPortal/#/personal";
const sender = { frameId: 0, url: "http://localhost:3000/" };
const row = title => ({ title, recruitment_type: "常规校招", location: "北京", submitted_at_text: "2026-10-21 12:30:00", raw_status: "进行中" });
const data = (rows, page, total, complete) => ({ state: "READY", page_url: url, rows, page, total, complete });
const reset = (observations) => { answers = observations; created = []; removed = []; activated = []; nextClicks = 0; };
const sync = () => new Promise(resolve => listener({ action: "sync", url }, sender, resolve));

test("only the top-level local JobFlow origin can request observations", () => {
  assert.equal(allowedSender(sender), true);
  for (const source of [
    { ...sender, url: "http://localhost:3001/" }, { ...sender, url: "https://evil.test/" },
    { ...sender, url: "http://localhost.evil.test:3000/" }, { ...sender, frameId: 1 },
  ]) assert.equal(allowedSender(source), false);
  let called = false;
  assert.equal(listener({ action: "sync", url: "https://campus.163.com/" }, sender, () => { called = true; }), false);
  assert.equal(called, false);
});

test("collect all pages, wait for changing rows, and close only the created tab", async () => {
  const first = data([row("A")], 1, 2, false);
  const second = data([row("B")], 2, 2, true);
  reset([{ state: "LOADING" }, first, first, first, second, second]);
  const response = await sync();
  assert.equal(response.ok, true);
  assert.deepEqual(response.data.rows.map(r => r.title), ["A", "B"]);
  assert.equal(response.data.complete, true);
  assert.equal(nextClicks, 1);
  assert.deepEqual(created, [{ url, active: false }]);
  assert.deepEqual(removed, [7]);
  assert.deepEqual(activated, []);
});

test("an unauthenticated empty table is never reported as a successful empty result", async () => {
  reset([{ state: "LOGIN_REQUIRED", page_url: url, complete: false, rows: [] }]);
  const response = await sync();
  assert.equal(response.data.state, "LOGIN_REQUIRED");
  assert.equal(response.data.complete, false);
  assert.deepEqual(removed, []);
  assert.deepEqual(activated, [{ id: 7, active: true }]);
});

test("changing page totals discard partial results", async () => {
  const first = data([row("A")], 1, 2, false);
  const changed = data([row("B")], 2, 3, true);
  reset([first, first, changed, changed]);
  const response = await sync();
  assert.equal(response.data.state, "ERROR");
  assert.deepEqual(response.data.rows, []);
  assert.deepEqual(removed, [7]);
});

test("successful authenticated empty page remains distinguishable from login loss", async () => {
  const empty = data([], 1, 0, true);
  reset([empty, empty]);
  const response = await sync();
  assert.equal(response.data.state, "READY");
  assert.deepEqual(response.data.rows, []);
});
