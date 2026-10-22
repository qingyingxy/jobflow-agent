(() => {
  if (window !== window.top || !["http://localhost:3000", "http://127.0.0.1:3000"].includes(location.origin)) return;
  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== "jobflow-portal-request") return;
    const { id, action, url } = event.data;
    if (typeof id !== "string" || id.length > 100 || !["ping", "sync"].includes(action)) return;
    chrome.runtime.sendMessage({ action, url }, response => {
      const error = chrome.runtime.lastError;
      window.postMessage({ channel: "jobflow-portal-response", id,
        ...(error ? { ok: false, error: "浏览器连接已失效，请刷新 JobFlow 页面。" } : response) }, location.origin);
    });
  });
})();
