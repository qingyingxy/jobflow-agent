import { expect, test } from "@playwright/test";

test("account export downloads a file and deletion requires exact confirmation", async ({ page }) => {
  let exports = 0;
  let deletions = 0;
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,DELETE,OPTIONS" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/account/export") {
      expect(request.postDataJSON()).toEqual({ confirmed: true });
      exports++;
      return route.fulfill({ headers: { ...headers, "content-type": "application/zip" }, body: Buffer.from("test archive") });
    }
    if (path === "/api/account" && request.method() === "DELETE") {
      expect(request.postDataJSON()).toEqual({ confirmation: "DELETE_MY_DATA" });
      deletions++;
      return route.fulfill({ headers, json: { deleted_counts: {} } });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "简历资料", exact: true }).click();
  await page.getByText("账户数据与隐私", { exact: true }).click();
  await expect(page.getByRole("button", { name: "永久删除我的数据", exact: true })).toBeDisabled();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出我的数据", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("jobflow-data.zip");
  expect(exports).toBe(1);
  await page.getByLabel("删除数据确认").fill("删除");
  await expect(page.getByRole("button", { name: "永久删除我的数据", exact: true })).toBeDisabled();
  expect(deletions).toBe(0);
  await page.getByLabel("删除数据确认").fill("删除我的数据");
  await page.getByRole("button", { name: "永久删除我的数据", exact: true }).click();
  await expect.poll(() => deletions).toBe(1);
});
