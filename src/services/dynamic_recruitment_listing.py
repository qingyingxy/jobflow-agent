"""Bounded navigation of visible job cards and explicit pagination controls."""

import asyncio
import hashlib
import json
import re

from src.services.recruitment_listing import allowed_listing_url, inspect_listing
from src.services.url_reader import HTMLLink

ANNOUNCEMENT_CONTROL = r"(?:校招|招聘)(?:公告|简章)|(?:校招|校园招聘|管培生).*(?:启动|开启)"

# Inspect rendered DOM only. Never evaluate handlers or manufacture detail URLs.
CONTROLS = r"""() => {
    const unclipped = el => {
        let r = el.getBoundingClientRect(), left=r.left, right=r.right, top=r.top, bottom=r.bottom;
        for(let p=el.parentElement; p && p!==document.body; p=p.parentElement) {
            const s=getComputedStyle(p), b=p.getBoundingClientRect();
            if (/hidden|clip|auto|scroll/.test(s.overflowX)) { left=Math.max(left,b.left); right=Math.min(right,b.right); }
            if (/hidden|clip|auto|scroll/.test(s.overflowY)) { top=Math.max(top,b.top); bottom=Math.min(bottom,b.bottom); }
            if(right<=left || bottom<=top) return false;
        }
        return true;
    };
    const visible = el => el.getClientRects().length > 0 &&
        getComputedStyle(el).visibility !== 'hidden' &&
        !el.closest('[hidden],[aria-hidden="true"]') && unclipped(el);
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
    const forbidden = /投递|申请|意向单|登录|注册|收藏|订阅|提交|apply|application|sign in|log in|submit|subscribe/i;
    const announcementTitle = /(?:校招|招聘|管培生).{0,180}(?:启动|开启|公告|简章)/i;
    const job = /工程师|研究员|开发|算法|产品经理|实习生|设计师|分析师|engineer|developer|scientist|analyst|designer/i;
    const titleClass = /(?:job|position|pos|post|vacancy)[\w-]*(?:title|name)|(?:title|name)[\w-]*(?:job|position|pos|post|vacancy)/i;
    const cardClass = /(?:job|position|pos|post|vacancy|list)[\w-]*(?:card|item|row)|(?:card|item|row)[\w-]*(?:job|position|pos|post|vacancy)/i;
    const cards = [];
    for (const el of document.querySelectorAll('div,span,h2,h3,h4,a,button,[role="link"],[role="button"]')) {
        const text = label(el);
        const href = el.closest('a[href]')?.getAttribute('href');
        const realLink = href && !/^(?:#?$|javascript:)/i.test(href);
        if (!safe(el) || el.closest('nav,[role="navigation"]') || text.length < 3 ||
            text.length > 140 || !job.test(text) || forbidden.test(text) || announcementTitle.test(text) || realLink ||
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
    const viewJobs = /^(?:(?:查看|浏览|全部|搜索|进入)(?:所有|全部|在招|工作)?(?:\s*\d+\s*个?)?(?:职位|岗位)|(?:view|browse|all|search)\s+(?:all\s+)?(?:\d+\s+)?jobs)[\s→›»>]*$/i;
    const recruiting = /^(?:(?:\d{4}(?:届)?)?\s*(?:校园招聘|应届生招聘|应届校招|实习生招聘|实习招聘|社会招聘)(?:与实习)?|(?:校招|招聘)(?:公告|简章)|campus recruitment|internships?)[\s→›»]*$/i;
    const more = /^(?:了解更多|点击查看|马上启程|learn more|view more)[\s→›»>]*$/i;
    for (const el of document.querySelectorAll('button,a,p,span,div,[role="button"],[role="link"]')) {
        const text = label(el);
        const href = el.closest('a[href]')?.getAttribute('href');
        const announcement = text.length <= 250 && announcementTitle.test(text) && !/实习|春招|春季|社会招聘|社招/.test(text);
        if (!safe(el) || (href && !/^(?:#?$|javascript:)/i.test(href)) ||
            !(viewJobs.test(text) || recruiting.test(text) || more.test(text) || announcement)) continue;
        const selected = [...function*(n) { for(let i=0;n && i<4;i++,n=n.parentElement) yield n; }(el),
            ...el.querySelectorAll('[aria-current],[aria-selected],[class]')]
            .some(n => label(n) === text && (n.getAttribute('aria-current') === 'page' ||
                n.getAttribute('aria-selected') === 'true' ||
                /(?:^|[\s_-])(?:active|activity|current|selected)(?:[\s_-]|$)/i.test(n.className || '')));
        if (recruiting.test(text) && selected) continue;
        if (!['A','BUTTON'].includes(el.tagName) && !['button','link'].includes(el.getAttribute('role')) &&
            getComputedStyle(el).cursor !== 'pointer') continue;
        let parent = el.parentElement, context = text;
        for(let i=0; !recruiting.test(text) && !announcement && parent && i<4; i++, parent=parent.parentElement) {
            const value = label(parent);
            if(value.length < 500 && (/校园|应届|校招|实习|社会招聘|campus|internship|graduate/i.test(value) ||
                (viewJobs.test(text) && parent.querySelector('h2,h3,h4,[class*="title"],[class*="name"]')))) {
                context = value; break;
            }
        }
        // Plain project names often have no heading/class semantics. Preserve
        // the nearest bounded card around an otherwise identical View Jobs
        // button, stopping before another button's project is included.
        if (viewJobs.test(text) && context === text) {
            for(let node=el.parentElement, depth=0; node && depth<4; node=node.parentElement, depth++) {
                const value = label(node), occurrences = value.split(text).length - 1;
                if (occurrences > 1 || value.length >= 500) break;
                if (occurrences === 1 && value.length > text.length) context = value;
            }
        }
        if (more.test(text) && context === text) continue;
        if (entries.some(c => c.element.contains(el))) continue;
        const navigation = !!el.closest('nav,header,[role="navigation"]') ||
            [...function*(n) { for(let i=0;n && i<4;i++,n=n.parentElement) yield n; }(el)]
              .some(n => /(?:^|[\s_-])(?:nav|navbar|header|menu)(?:$|[\s_-])/i.test(n.className || ''));
        entries.push({element: el, selector: selector(el), label: context, navigation});
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
    // Expose observed navigation/filter choices to the Agent only. The
    // automatic listing traversal never schedules these controls itself.
    const navigation = [];
    for (const el of document.querySelectorAll('button,a,span,div,li,p,[role="tab"],[role="option"]')) {
        let text = label(el);
        const role = el.getAttribute('role');
        const carousel = el.closest('[class*="carousel__indicators"],[class*="swiper-pagination"]');
        if (!text && carousel) {
            const buttons=[...carousel.querySelectorAll('button,[role="tab"],.swiper-pagination-bullet')];
            const index=buttons.indexOf(el);
            const slides=carousel.parentElement.querySelectorAll('.el-carousel__item,.swiper-slide');
            if (index>=0) {
                const titles=slides[index] ? [...new Set([...slides[index].querySelectorAll('h1,h2,h3,h4')].map(label))].join('、') : '';
                text=('轮播第'+(index+1)+'页/'+buttons.length+(titles ? '：'+titles : '')).slice(0,120);
            }
        }
        if (!safe(el) || !text || text.length > 120 || forbidden.test(text) ||
            el.closest('a[href]')?.getAttribute('href')?.match(/^(?:https?:|\/|#.)/) ||
            (!['A','BUTTON'].includes(el.tagName) && !['tab','option'].includes(role) &&
             (el.children.length || getComputedStyle(el).cursor !== 'pointer'))) continue;
        const located = !!carousel || !!el.closest('nav,header,[role="navigation"],[role="tablist"],[role="listbox"]') ||
            [...function*(node) { for(let i=0;node && i<5;i++,node=node.parentElement) yield node; }(el)]
                .some(node => /filter|select|screen|nav|header|menu|tabs|option/i.test(node.className || ''));
        if (!located || [...entries, ...cards].some(c => c.element.contains(el) || el.contains(c.element))) continue;
        navigation.push({selector: selector(el), label: text, navigation: true});
    }
    return {cards: cards.map(({element, ...rest}) => rest), next: next.map(({element, ...rest}) => rest), navigation,
        entries: entries.map(({element, ...rest}) => rest), pagination};
}"""


def listing_fingerprint(links, cards):
    value = [(link.url, link.text) for link in links] + [("card", card["label"]) for card in cards]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def resolve_selected_control(selected, controls):
    """Rebind the same observed, scoped control after a DOM wrapper changes."""
    if selected in controls:
        return selected
    # Labels include the surrounding project/company. Never fall back to a
    # bare shared CTA, list position, substring, or another control category.
    def identity(control):
        return {k: " ".join(v.split()) if k == "label" else v
                for k, v in control.items() if k != "selector"}
    if not selected.get("label", "").strip():
        return None
    matches = [c for c in controls if identity(c) == identity(selected)]
    return matches[0] if len(matches) == 1 else None


async def read_dynamic_listing_page(page, *, reader, cursor=None, keywords=(), max_links=8, restore_after_navigation=True, entry_filter=None, exclude_entry_filter=None, allow_documents=False, selected_control=None):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from src.services.browser_job_reader import (
        BrowserPageSnapshot,
        BrowserReadError,
        _raise_for_human_gate,
        bounded_page_html,
        wait_for_recruitment_content,
    )

    replay = list((selected_control or {}).get("replay", []))
    if len(replay) > 4:
        raise BrowserReadError("同页导航回放超过上限，请重新读取入口", code="navigation_replay_limit")
    # Each item is a previously selected public control. Replaying them restores
    # the observed tab/carousel state when a new browser context is opened.
    for prior in replay:
        if "replay" in prior:
            raise BrowserReadError("导航回放结构无效", code="navigation_control_changed")
        restored = await read_dynamic_listing_page(page, reader=reader, max_links=1,
                                                   restore_after_navigation=False, selected_control=prior)
        if (restored.dynamic_listing or {}).get("reason") == "navigation_control_changed":
            return restored
    if selected_control is not None:
        selected_control = {k: v for k, v in selected_control.items() if k != "replay"}
    cursor = cursor or {}
    history = list(cursor.get("history", []))
    offset = max(0, int(cursor.get("offset", 0)))
    if len(history) > 20:
        raise BrowserReadError("动态分页续查超过单次回放上限", code="pagination_replay_limit")
    origin = page.url
    trace = getattr(page, "_jobflow_trace", None)
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
        if trace:
            trace.phase("inspect_dynamic_controls")
        if not page.url.startswith(("https://", "http://")):
            raise BrowserReadError("页面初始化后离开公开招聘网址，无法继续交互", code="browser_navigation_unavailable")
        await reader._validate_url(page.url)
        if not allowed_listing_url(page.url, origin, allow_documents=allow_documents):
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
    entry_mode = bool(entry_filter) or not controls["cards"] and not capabilities.jobs
    cards = controls["entries"] if entry_mode else controls["cards"]
    if entry_filter:
        cards = [card for card in cards if re.search(entry_filter, card["label"])]
    if entry_mode and exclude_entry_filter:
        cards = [card for card in cards if not re.search(exclude_entry_filter, card['label'])]
    if selected_control is not None:
        kind = selected_control.get("kind")
        selected = {key: value for key, value in selected_control.items() if key != "kind"}
        selected = resolve_selected_control(selected, controls.get(kind, [])) if kind in {"entries", "cards", "navigation"} else None
        if selected is None:
            return BrowserPageSnapshot(origin, listing_url, title, html, text, html_compacted=compacted,
                dynamic_listing={"reason": "navigation_control_changed", "navigation_executed": False},
                navigation_controls=tuple({"kind": k, **c, **({"replay": replay} if replay else {})}
                    for k in ("entries", "cards", "navigation") for c in controls[k]))
        entry_mode, cards, offset = kind != "cards", [selected], 0
    elif entry_mode:
        from src.services.recruitment_listing import recruitment_priority

        cards = sorted((c for c in cards if recruitment_priority(HTMLLink(origin, c["label"]), types) < 2),
                       key=lambda c: (recruitment_priority(HTMLLink(origin, c["label"]), types),
                                      c.get("navigation", False),
                                      not bool(re.search(r"20\d{2}|面向|毕业生|应届|招聘对象", c["label"])),
                                      listing_priority(c["label"], role_query, types)))
        if entry_filter:
            cards.sort(key=lambda c: -max((int(y) for y in re.findall(r"20\d{2}", c['label'])), default=0))
    end = min(len(cards), offset + (max(1, min(20, max_links)) if restore_after_navigation else 3 if entry_mode else 1))
    for index in range(offset, end):
        card = cards[index]
        # A restoration can re-sort a live page. Never click a stale selector.
        current = await page.evaluate(CONTROLS)
        control_kind = selected_control["kind"] if selected_control is not None else "entries" if entry_mode else "cards"
        refreshed = resolve_selected_control(card, current[control_kind]) if selected_control is not None else next(
            (c for c in current[control_kind] if c == card), None)
        if refreshed is None:
            reason, end = "listing_changed", index
            break
        card = refreshed
        locator = page.locator(card["selector"])
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
        page._jobflow_announcement_navigation = bool(entry_filter)
        try:
            if trace:
                trace.phase("click_navigation_control", label=card["label"][:100], entry=entry_mode)
            await locator.click(timeout=min(reader.timeout_ms, 3000))
            try:
                if trace:
                    trace.phase("wait_control_navigation", budget_ms=3000)
                await asyncio.wait_for(navigated.wait(), timeout=3)
            except TimeoutError:
                if trace:
                    trace.event("navigation_unresolved", page.url, label=card["label"][:100])
                reason, end = "dynamic_navigation_unresolved", index
                if selected_control is not None:
                    # In-page filters and carousel switches need fresh DOM and
                    # controls even when no URL navigation occurred.
                    html, text, compacted, capabilities, controls = await inspect()
                    replay = [*replay, selected_control]
                if entry_mode:
                    end = index + 1
                    continue
                break
            target_page = popups[0] if popups else page
            if trace:
                trace.phase("wait_navigation_document")
            await target_page.wait_for_url(re.compile(r"^https?://"), wait_until="domcontentloaded", timeout=reader.timeout_ms)
            target = await reader._validate_url(target_page.url)
            if trace:
                trace.event("navigation_target", target, label=card["label"][:100])
            if entry_mode and target == listing_url:
                reason = "dynamic_navigation_unresolved"
                continue
            from src.services.recruitment_listing import allowed_entry_navigation

            allowed = (allowed_listing_url(target, origin, allow_documents=True) if entry_filter else
                       allowed_entry_navigation(target, origin) if entry_mode else allowed_listing_url(target, origin))
            if target == listing_url or not allowed:
                reason, end = "listing_scope_changed", index
                break
            links.append(HTMLLink(target, card["label"]))
            observations.append({"label": card["label"], "url": target, "listing_url": listing_url})
            if not restore_after_navigation:
                end = index + 1
                break
        finally:
            page._jobflow_entry_navigation = False
            page._jobflow_announcement_navigation = False
            page.remove_listener("popup", popup)
            page.remove_listener("framenavigated", navigation)
            for child in popups:
                await child.close()
            if page.url != listing_url and restore_after_navigation:
                await page.go_back(wait_until="domcontentloaded", timeout=reader.timeout_ms)
                reload_listing = page.url != listing_url
                if reload_listing:
                    # SPA replaceState/replace navigation can remove the list from
                    # history. Replay the observed listing, never guess a new URL.
                    await page.goto(origin, wait_until="domcontentloaded", timeout=reader.timeout_ms)
                await wait_for_recruitment_content(page, timeout_ms=2000, listing=True, campaign=bool(entry_filter))
                restored = await inspect()
                changed = listing_fingerprint(restored[3].jobs, [*restored[4]["cards"], *restored[4]["entries"]]) != fingerprint
                if reload_listing or (changed and search_state and search_state.get("status") == "confirmed"):
                    # AJAX filters often disappear on Back. Recreate the
                    # observed search and page history before clicking again.
                    if not reload_listing:
                        await page.goto(origin, wait_until="domcontentloaded", timeout=reader.timeout_ms)
                        await wait_for_recruitment_content(page, timeout_ms=2000, listing=True)
                    if search_state and search_state.get("status") == "confirmed":
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
    if end < len(cards) and restore_after_navigation:
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

        empty = (await page.evaluate(RESULT_STATE))["empty"] if not capabilities.jobs and not cards else False
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
        navigation_controls=tuple({"kind": kind, **control, **({"replay": replay} if replay else {})}
            for kind in ("entries", "cards", "navigation") for control in controls[kind]) if selected_control is not None else (),
    )
