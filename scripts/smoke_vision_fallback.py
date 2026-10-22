"""Opt-in live vision check using a synthetic local screenshot, no user data."""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from src.config import get_settings
from src.services.vision_job_extraction import extract_visual_job


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1000, "height": 700})
        await page.set_content('<html><body style="font:26px sans-serif;padding:30px"><h1>智能体应用开发工程师</h1><p>示例公司 · 上海 · 校园招聘</p><h2>岗位职责</h2><p>负责智能体应用开发、检索增强系统建设和模型效果评测。</p><h2>任职要求</h2><p>熟悉 Python、数据库和服务部署，具有团队协作能力。</p></body></html>')
        data = await page.screenshot(type="jpeg")
        await browser.close()
    result = await extract_visual_job([{"base64": base64.b64encode(data).decode("ascii")}], settings=get_settings())
    print(json.dumps({"status": result["status"], "fields": result.get("fields"), "error_type": result.get("error_type")}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
