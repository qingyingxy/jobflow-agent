// This function is self-contained so Chrome can execute it in an isolated world.
// Read only the rendered application table, never cookies, storage or app state.
export function readTongchengPage() {
  const page_url = "https://mhr.ly.com/recruit/schoolPortal/#/personal";
  const failure = state => ({ state, page_url, complete: false, rows: [] });
  if (location.origin !== "https://mhr.ly.com" || location.pathname !== "/recruit/schoolPortal/") return failure("PAGE_CHANGED");
  if (location.hash.startsWith("#/login")) return failure("LOGIN_REQUIRED");
  if (location.hash !== "#/personal") return failure("PAGE_CHANGED");
  const visible = el => el && el.getClientRects().length > 0;
  const loggedIn = Array.from(document.querySelectorAll('a[aria-haspopup="menu"]'))
    .some(el => visible(el) && el.getAttribute("href") === "#/personal");
  const loginLink = Array.from(document.querySelectorAll("a"))
    .some(el => visible(el) && el.innerText.trim() === "登录");
  if (loginLink) return failure("LOGIN_REQUIRED");
  if (!loggedIn) return failure("LOADING");
  const expected = ["职位", "招聘类型", "工作地点", "投递时间", "投递状态"];
  const tables = Array.from(document.querySelectorAll(".el-table")).filter(el =>
    JSON.stringify(Array.from(el.querySelectorAll("thead th"), th => th.innerText.trim())) === JSON.stringify(expected));
  if (tables.length !== 1) return failure("LOADING");
  const table = tables[0];
  const section = table.parentElement;
  const title = section.querySelector(".title");
  if (title?.innerText.trim() !== "我的申请") return failure("PAGE_CHANGED");
  if (Array.from(section.querySelectorAll(".el-loading-mask")).some(visible)) return failure("LOADING");
  const totalText = section.querySelector(".el-pagination__total")?.innerText || "";
  const totalMatch = totalText.match(/^共\s*(\d+)\s*条$/);
  const page = Number(section.querySelector('.el-pager [aria-current="true"]')?.innerText);
  const pageSize = Number(section.querySelector(".el-pagination__sizes")?.innerText.match(/(\d+)条\/页/)?.[1]);
  const total = totalMatch ? Number(totalMatch[1]) : -1;
  if (total < 0 || total > 500 || page < 1 || !pageSize) return failure("PAGE_CHANGED");
  const rows = [];
  for (const tr of table.querySelectorAll("tbody tr")) {
    const cells = Array.from(tr.querySelectorAll("td"), td => td.innerText.trim());
    if (cells.length !== 5 || !cells[0] || !cells[1] || !cells[4]
      || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(cells[3])) return failure("PAGE_CHANGED");
    rows.push({ title: cells[0], recruitment_type: cells[1], location: cells[2], submitted_at_text: cells[3], raw_status: cells[4] });
  }
  const expectedRows = Math.min(pageSize, Math.max(0, total - (page - 1) * pageSize));
  if (rows.length !== expectedRows) return failure("LOADING");
  const next = section.querySelector('button[aria-label="下一页"]');
  if (!next) return failure("PAGE_CHANGED");
  return { state: "READY", page_url, complete: next.disabled, rows, total, page, pageSize };
}

// The only automated click is this bounded, application-table pagination button.
export function nextTongchengPage() {
  if (location.href !== "https://mhr.ly.com/recruit/schoolPortal/#/personal") return false;
  const expected = "职位|招聘类型|工作地点|投递时间|投递状态";
  const table = Array.from(document.querySelectorAll(".el-table")).find(el =>
    Array.from(el.querySelectorAll("thead th"), th => th.innerText.trim()).join("|") === expected);
  const next = table?.parentElement.querySelector('button[aria-label="下一页"]');
  if (!next || next.disabled) return false;
  next.click();
  return true;
}
