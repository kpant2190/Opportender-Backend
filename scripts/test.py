from __future__ import annotations
# quick_snap_qtenders.py
import asyncio, os
from playwright.async_api import async_playwright

URL = "https://qtenders.epw.qld.gov.au/qtenders/"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="en-AU",
        )
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        # try to click through to results if obvious links exist
        for sel in ["a:has-text('Current Tenders')", "a:has-text('Find Tenders')", "a:has-text('Open Tenders')"]:
            if await page.locator(sel).count():
                await page.locator(sel).first.click()
                await page.wait_for_load_state("domcontentloaded")
                break

        # save artifacts
        html = await page.content()
        with open("qtenders_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        await page.screenshot(path="qtenders_dump.png", full_page=True)

        # print the first 3 candidate blocks’ text so we can see structure
        candidates = ["tbody tr", ".card", ".search-results li", ".results li"]
        for sel in candidates:
            n = await page.locator(sel).count()
            if n:
                print(f"[CANDIDATE] {sel} -> {n} nodes")
                for i in range(min(3, n)):
                    txt = await page.locator(sel).nth(i).inner_text()
                    print("----")
                    print(txt[:1000])
                break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

