import { readTongchengPage, nextTongchengPage } from "./tongcheng.js";

const PORTAL = "https://mhr.ly.com/recruit/schoolPortal/#/personal";
const ORIGINS = new Set(["http://localhost:3000", "http://127.0.0.1:3000"]);
let syncing = false;
chrome.action.onClicked.addListener(() => chrome.tabs.create({ url: "http://localhost:3000" }));

export function allowedSender(sender) {
  try { return sender.frameId === 0 && ORIGINS.has(new URL(sender.url).origin); }
  catch { return false; }
}

async function sync() {
  if (syncing) throw new Error("已有同步正在进行，请稍后重试。");
  syncing = true;
  let tab;
  let keepOpen = false;
  try {
    // A fresh tab avoids reading a stale cached table or moving a user's tab.
    tab = await chrome.tabs.create({ url: PORTAL, active: false });
    const allRows = [];
    let expectedPage = 1, expectedTotal = null, previous = "";
    const deadline = Date.now() + 75000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 800));
      let result;
      try {
        [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: readTongchengPage });
      } catch { continue; } // The new document may still be navigating.
      const data = result?.result;
      if (!data || data.state === "LOADING") { previous = ""; continue; }
      if (data.state === "LOGIN_REQUIRED") {
        keepOpen = true;
        await chrome.tabs.update(tab.id, { active: true });
        return data;
      }
      if (data.state !== "READY") return data;
      if (data.page !== expectedPage) { previous = ""; continue; }
      // Observe the same rendered rows twice to let asynchronous tables settle.
      const fingerprint = JSON.stringify(data);
      if (previous !== fingerprint) { previous = fingerprint; continue; }
      if (expectedTotal !== null && data.total !== expectedTotal) throw new Error("PAGE_CHANGED");
      expectedTotal = data.total;
      allRows.push(...data.rows);
      if (allRows.length > 500) throw new Error("PAGE_CHANGED");
      if (data.complete) {
        if (allRows.length !== data.total) throw new Error("PAGE_CHANGED");
        return { state: "READY", page_url: PORTAL, complete: true, rows: allRows };
      }
      const [next] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: nextTongchengPage });
      if (!next.result) throw new Error("PAGE_CHANGED");
      expectedPage += 1;
      previous = "";
    }
    return { state: "ERROR", page_url: PORTAL, complete: false, rows: [] };
  } finally {
    syncing = false;
    if (tab && !keepOpen) await chrome.tabs.remove(tab.id).catch(() => {});
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!allowedSender(sender)) return false;
  if (message.action === "ping") { sendResponse({ ok: true, version: "0.1.0" }); return false; }
  if (message.action !== "sync" || message.url !== PORTAL) return false;
  sync().then(data => sendResponse({ ok: true, data }))
    .catch(() => sendResponse({ ok: true, data: { state: "ERROR", page_url: PORTAL, complete: false, rows: [] } }));
  return true;
});
