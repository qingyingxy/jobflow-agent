"""Bounded navigation of visible job cards and explicit pagination controls."""

import asyncio
import hashlib
import json
import re

from src.services.recruitment_listing import allowed_listing_url, inspect_listing
from src.services.url_reader import HTMLLink

# Inspect rendered DOM only. Never evaluate handlers or manufacture detail URLs.
CONTROLS = r"""() => {
    const visible = el => el.getClientRects().length > 0 &&
        getComputedStyle(el).visibility !== 'hidden' &&
        !el.closest('[hidden],[aria-hidden="true"]');
    const disabled = el => el.closest('[disabled],[aria-disabled="true"]') ||
        [...function*(n) { while(n) { yield n; n=n.parentElement; } }(el)]
        .some(n => /(?:^|[\s_-])disabled(?:$|[\s_-])/i.test(n.className || ''));
    const safe = el => visible(el) && !disabled(el) &&
        !el.closest('form,footer,aside,[role="menu"]') &&
        el.getAttribute('type') !== 'submit';
    const selector = el => {
        const parts = [];
        while(el && el !== document.documentElement) {
            const parent = el.parentElement;
            if (!parent) break;
            parts.unshift(el.tagName.toLowerCase() + ':nth-child(' +
                ([...parent.children].indexOf(el) + 1) + ')');
            el = parent;
        }
        return 'html > ' + parts.join(' > ');
    };
    const label = el => (el.innerText || el.getAttribute('aria-label') ||
        el.getAttribute('title') || '').trim().replace(/\s+/g, ' ');
    const forbidden = /投递|申请|登录|注册|收藏|订阅|提交|apply|application|sign in|log in|submit|subscribe/i;
    const job = /工程师|研究员|开发|算法|产品经理|实习生|设计师|分析师|engineer|developer|scientist|analyst|designer/i;
    const titleClass = /(?:job|position|pos|post|vacancy)[\w-]*(?:title|name)|(?:title|name)[\w-]*(?:job|position|pos|post|vacancy)/i;
    const cardClass = /(?:job|position|pos|post|vacancy|list)[\w-]*(?:card|item|row)|(?:card|item|row)[\w-]*(?:job|position|pos|post|vacancy)/i;
    const cards = [];
    for (const el of document.querySelectorAll('div,span,h2,h3,h4,a,button,[role="link"],[role="button"]')) {
        const text = label(el);
        const href = el.closest('a[href]')?.getAttribute('href');
        const realLink = href && !/^(?:#?$|javascript:)/i.test(href);
        if (!safe(el) || el.closest('nav,[role="navigation"]') || text.length < 3 ||
            text.length > 140 || !job.test(text) || forbidden.test(text) || realLink ||
            /^(?:实习生|校园|社会|应届生)?招聘$/i.test(text)) continue;
        let structural = null;
        for (let parent=el.parentElement, depth=0; parent && depth<4; parent=parent.parentElement, depth++) {
            const cls = parent.className || '', content = label(parent);
            if (/(?:^|[\s_-])(?:item|card|row)(?:$|[\s_-])/i.test(cls) && content.startsWith(text) &&
                /工作地点|所属业务|岗位职责|工作职责|location|department/i.test(content) &&
                getComputedStyle(parent).cursor === 'pointer') { structural=parent; break; }
        }
        const title = structural || titleClass.test(el.className || '') ||
            /(?:^|[\s_-])(?:title|name)(?:$|[\s_-])/i.test(el.className || '') ||
            (el.children.length === 0 && titleClass.test(el.parentElement?.className || '')) ||
            ['A','BUTTON'].includes(el.tagName) || ['link','button'].includes(el.getAttribute('role'));
        if (!title) continue;
        let parent = el, card = !!structural;
        for(let i=0; parent && i<5; i++, parent=parent.parentElement) {
            if(cardClass.test(parent.className || '') || parent.getAttribute('role') === 'listitem') card = true;
        }
        if (!card && !titleClass.test(el.className || '') && !['A','BUTTON'].includes(el.tagName)) continue;
        if (!card && getComputedStyle(el).cursor !== 'pointer' && !['A','BUTTON'].includes(el.tagName)) continue;
        const duplicate = cards.findIndex(c => c.label === text && c.element.contains(el));
        const candidate = {element: el, selector: selector(el), label: text};
        if (duplicate >= 0) cards[duplicate] = candidate;
        else if (!cards.some(c => el.contains(c.element))) cards.push(candidate);
    }
    const entries = [];
    const viewJobs = /^(?:(?:查看|浏览|全部|搜索|进入)(?:工作)?(?:\s*\d+\s*个?)?(?:职位|岗位)|(?:view|browse|all|search)\s+(?:\d+\s+)?jobs)[\s→›»]*$/i;
    const recruiting = /^(?:(?:\d{4}(?:届)?)?\s*(?:校园招聘|应届生招聘|应届校招|实习生招聘|实习招聘|社会招聘)(?:与实习)?|campus recruitment|internships?)[\s→›»]*$/i;
    const more = /^(?:了解更多|点击查看|learn more|view more)[\s→›»]*$/i;
    for (const el of document.querySelectorAll('button,a,p,span,div,[role="button"],[role="link"]')) {
        const text = label(el);
        const href = el.getAttribute('href');
        if (!safe(el) || (href && !/^(?:#?$|javascript:)/i.test(href)) ||
            !(viewJobs.test(text) || recruiting.test(text) || more.test(text))) continue;
        if (recruiting.test(text) && (el.getAttribute('aria-current') === 'page' ||
            el.getAttribute('aria-selected') === 'true' ||
            /(?:^|\s)(?:active|activity|current|selected)(?:\s|$)/i.test(el.className || ''))) continue;
        if (!['A','BUTTON'].includes(el.tagName) && !['button','link'].includes(el.getAttribute('role')) &&
            getComputedStyle(el).cursor !== 'pointer') continue;
        let parent = el.parentElement, context = text;
        for(let i=0; !recruiting.test(text) && parent && i<4; i++, parent=parent.parentElement) {
            const value = label(parent);
            if(value.length < 500 && (/校园|应届|校招|实习|社会招聘|campus|internship|graduate/i.test(value) ||
                (viewJobs.test(text) && parent.querySelector('h2,h3,h4,[class*="title"],[class*="name"]')))) {
                context = value; break;
            }
        }
        if (more.test(text) && context === text) continue;
        if (entries.some(c => c.element.contains(el))) continue;
        entries.push({element: el, selector: selector(el), label: context});
    }
    const next = [];
    const nextLabel = /^(下一页|下页|加载更多|更多职位|next(?: page)?|load more)[\s›»>]*$/i;
    let pagination = false;
    for (const el of document.querySelectorAll('button,a,[role="button"],li')) {
        if(!visible(el)) continue;
        const text = label(el), accessible = el.getAttribute('aria-label') || el.getAttribute('title') || '';
        const container = el.closest('[class*="pagination"],[class*="pager"],[aria-label*="分页"],[aria-label*="Pagination"]');
        const semantic = nextLabel.test(text) || nextLabel.test(accessible) ||
            el.getAttribute('rel') === 'next' ||
            (container && /(?:^|[\s_-])next(?:$|[\s_-])/i.test(el.className || ''));
        if(container || semantic) pagination = true;
        if(!semantic || !safe(el) || forbidden.test(text)) continue;
        if(next.some(n => n.element.contains(el))) continue;
        next.push({element: el, selector: selector(el), label: text});
    }
    if (!next.length) {
        // Numbered pagination is usable only with one explicit current page and
        // one visible numeric successor in the same pagination container.
        const currents = [...document.querySelectorAll('[aria-current="page"],button[class*="active"],li[class*="active"]')]
            .filter(el => visible(el) && /^\d+$/.test(label(el)) &&
                el.closest('[class*="pagination"],[class*="pager"]'));
        if (currents.length === 1) {
            const current = currents[0], container = current.closest('[class*="pagination"],[class*="pager"]');
            let group = container;
            while (group.parentElement && group.querySelectorAll('button,a,[role="button"]').length < 2 &&
                   /pagination|pager/i.test(group.parentElement.className || '')) group = group.parentElement;
            const successors = [...group.querySelectorAll('button,a,[role="button"]')]
                .filter(el => safe(el) && label(el) === String(Number(label(current)) + 1));
            if(successors.length === 1) next.push({element:successors[0],selector:selector(successors[0]),label:label(successors[0])});
        }
    }
    return {cards: cards.map(({element, ...rest}) => rest), next: next.map(({element, ...rest}) => rest),
        entries: entries.map(({element, ...rest}) => rest), pagination};
}"""


def listing_fingerprint(links, cards):
    value = [(link.url, link.text) for link in links] + [("card", card["label"]) for card in cards]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


async def read_dynamic_listing_page(page, *, reader, cursor=None, keywords=(), max_links=8):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from src.services.browser_job_reader import (
        BrowserPageSnapshot,
        BrowserReadError,
        _raise_for_human_gate,
        bounded_page_html,
        wait_for_recruitment_content,
    )

    cursor = cursor or {}
    history = list(cursor.get("history", []))
    offset = max(0, int(cursor.get("offset", 0)))
    if len(history) > 20:
        raise BrowserReadError("动态分页续查超过单次回放上限", code="pagination_replay_limit")
    origin = page.url
    from src.services.recruitment_search_controls import (
        site_search_terms,
        submit_job_search,
    )
    from src.services.search_scheduling import listing_priority

    types = [k for k in keywords if k in {"校招", "实习"}]
    terms = site_search_terms(keywords)
    role_query = "岗位方向：" + "、".join(k for k in keywords if k not in {"校招", "实习"})
    search_state = cursor.get("search")
    # Legacy cursors must replay the original, unfiltered listing first.
    term = search_state.get("term") if search_state else terms[0] if terms and not cursor else None
    if term:
        submission = await submit_job_search(page, reader=reader, term=term,
                                             recipe=(search_state or {}).get("recipe"))
        if search_state and submission["status"] != "confirmed" and (history or offset):
            raise BrowserReadError("站内搜索结果变化，需要重新读取当前关键词", code="pagination_changed")
        if submission["status"] == "unconfirmed":
            # Typing alone does not prove filtering. Restore the public list;
            # keep exploring it without claiming a successful search recipe.
            await page.goto(origin, wait_until="domcontentloaded", timeout=reader.timeout_ms)
            await wait_for_recruitment_content(page, timeout_ms=2000, listing=True)
        search_state = submission

    async def inspect():
        if not page.url.startswith(("https://", "http://")):
            raise BrowserReadError("页面初始化后离开公开招聘网址，无法继续交互", code="browser_navigation_unavailable")
        await reader._validate_url(page.url)
        if not allowed_listing_url(page.url, origin):
            raise BrowserReadError("动态列表跳转离开已核验来源", code="listing_scope_changed")
        text = await page.locator("body").inner_text(timeout=reader.timeout_ms)
        _raise_for_human_gate(text)
        if len(text) > reader.max_chars:
            raise BrowserReadError("列表超过内容大小限制", code="browser_response_too_large")
        html, compacted = await bounded_page_html(page, max_chars=reader.max_chars)
        capabilities = inspect_listing(html, url=page.url)
        controls = await page.evaluate(CONTROLS)
        controls["cards"].sort(key=lambda c: listing_priority(c["label"], role_query, types))
        return html, text, compacted, capabilities, controls

    async def advance(control, old_html):
        locator = page.locator(control["selector"])
        if await locator.count() != 1 or not await locator.is_visible() or not await locator.is_enabled():
            raise BrowserReadError("分页控件已变化，保留当前页", code="pagination_unresolved")
        await locator.click(timeout=min(reader.timeout_ms, 3000))
        try:
            await page.wait_for_function("old => document.body.innerHTML !== old", arg=old_html, timeout=2000)
        except PlaywrightTimeoutError:
            pass
        await wait_for_recruitment_content(page, timeout_ms=2000, listing=True)

    async def replay_history():
        for expected in history:
            _, _, _, capabilities, controls = await inspect()
            if listing_fingerprint(capabilities.jobs, [*controls["cards"], *controls["entries"]]) != expected:
                raise BrowserReadError("列表顺序已变化，无法安全跳过旧页", code="pagination_changed")
            if len(controls["next"]) != 1:
                raise BrowserReadError("无法唯一确认下一页", code="pagination_unresolved")
            await advance(controls["next"][0], await page.locator("body").inner_html())

    await replay_history()

    html, text, compacted, capabilities, controls = await inspect()
    fingerprint = listing_fingerprint(capabilities.jobs, [*controls["cards"], *controls["entries"]])
    if fingerprint in history:
        raise BrowserReadError("分页没有前进，保留已读取进度", code="pagination_loop")
    if cursor.get("fingerprint") and fingerprint != cursor["fingerprint"]:
        raise BrowserReadError("当前页已变化，无法安全跳过旧卡片", code="pagination_changed")
    listing_url = page.url
    title = await page.title()
    links, observations = [], []
    reason = None
    entry_mode = not controls["cards"] and not capabilities.jobs
    cards = controls["entries"] if entry_mode else controls["cards"]
    if entry_mode:
        from src.services.recruitment_listing import recruitment_priority

        cards = sorted((c for c in cards if recruitment_priority(HTMLLink(origin, c["label"]), types) < 2),
                       key=lambda c: (recruitment_priority(HTMLLink(origin, c["label"]), types),
                                      listing_priority(c["label"], role_query, types)))
    end = min(len(cards), offset + max(1, min(20, max_links)))
    for index in range(offset, end):
        card = cards[index]
        # A restoration can re-sort a live page. Never click a stale selector.
        current = await page.evaluate(CONTROLS)
        locator = page.locator(card["selector"])
        if not any(c == card for c in current["entries" if entry_mode else "cards"]):
            reason, end = "listing_changed", index
            break
        popups = []
        navigated = asyncio.Event()

        def popup(new_page, popups=popups, navigated=navigated):
            popups.append(new_page)
            navigated.set()

        def navigation(frame, navigated=navigated):
            if frame == page.main_frame and frame.url != listing_url:
                navigated.set()

        page.on("popup", popup)
        page.on("framenavigated", navigation)
        page._jobflow_entry_navigation = entry_mode
        try:
            await locator.click(timeout=min(reader.timeout_ms, 3000))
            try:
                await asyncio.wait_for(navigated.wait(), timeout=3)
            except TimeoutError:
                reason, end = "dynamic_navigation_unresolved", index
                if entry_mode:
                    end = index + 1
                    continue
                break
            target_page = popups[0] if popups else page
            await target_page.wait_for_url(re.compile(r"^https?://"), wait_until="domcontentloaded", timeout=reader.timeout_ms)
            target = await reader._validate_url(target_page.url)
            if entry_mode and target == listing_url:
                reason = "dynamic_navigation_unresolved"
                continue
            from src.services.recruitment_listing import allowed_entry_navigation

            allowed = allowed_entry_navigation(target, origin) if entry_mode else allowed_listing_url(target, origin)
            if target == listing_url or not allowed:
                reason, end = "listing_scope_changed", index
                break
            links.append(HTMLLink(target, card["label"]))
            observations.append({"label": card["label"], "url": target, "listing_url": listing_url})
        finally:
            page._jobflow_entry_navigation = False
            page.remove_listener("popup", popup)
            page.remove_listener("framenavigated", navigation)
            for child in popups:
                await child.close()
            if page.url != listing_url:
                await page.go_back(wait_until="domcontentloaded", timeout=reader.timeout_ms)
                await wait_for_recruitment_content(page, timeout_ms=2000, listing=True)
                restored = await inspect()
                if (listing_fingerprint(restored[3].jobs, [*restored[4]["cards"], *restored[4]["entries"]]) != fingerprint
                        and search_state and search_state.get("status") == "confirmed"):
                    # AJAX filters often disappear on Back. Recreate the
                    # observed search and page history before clicking again.
                    await page.goto(origin, wait_until="domcontentloaded", timeout=reader.timeout_ms)
                    await wait_for_recruitment_content(page, timeout_ms=2000, listing=True)
                    replay = await submit_job_search(page, reader=reader, term=search_state["term"],
                                                     recipe=search_state.get("recipe"))
                    if replay["status"] != "confirmed":
                        raise BrowserReadError("返回列表后搜索状态无法恢复", code="pagination_changed")
                    await replay_history()
                    restored = await inspect()
                if listing_fingerprint(restored[3].jobs, [*restored[4]["cards"], *restored[4]["entries"]]) != fingerprint:
                    raise BrowserReadError("返回列表后内容变化，保留进度", code="pagination_changed")

    if entry_mode and links:
        reason = None
    next_cursor = None
    if end < len(cards):
        next_cursor = {"history": history, "fingerprint": fingerprint, "offset": end}
    elif len(controls["next"]) == 1 and (capabilities.jobs or cards):
        if len(history) >= 20:
            reason = "pagination_replay_limit"
        else:
            next_cursor = {"history": [*history, fingerprint], "offset": 0}
    elif len(controls["next"]) > 1:
        reason = "pagination_unresolved"
    if next_cursor and search_state:
        next_cursor["search"] = search_state if search_state.get("status") == "confirmed" else {"term": ""}
    if not reason and not next_cursor:
        from src.services.recruitment_search_controls import RESULT_STATE

        empty = (await page.evaluate(RESULT_STATE))["empty"]
        reason = ("listing_boundary" if capabilities.jobs or cards else
                  "listing_empty" if empty else
                  "listing_entry_only" if capabilities.entries else "listing_not_ready")
    return BrowserPageSnapshot(
        origin, listing_url, title, html, text, html_compacted=compacted,
        discovered_links=() if entry_mode else tuple(links),
        discovered_entries=tuple(links) if entry_mode else (),
        dynamic_listing={"next_cursor": next_cursor, "reason": reason,
                         "fingerprint": fingerprint, "observed_links": observations,
                         "search": search_state},
    )
