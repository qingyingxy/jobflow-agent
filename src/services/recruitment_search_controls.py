"""Observe and submit unambiguous, public job-search controls.

Recipes are hints, revalidated against the current DOM on every visit. They
never invent URLs, execute page handlers, or establish job eligibility.
"""
import re
from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict, Field

SEARCH_VERSION = 1
_HINT = re.compile(r"职位|岗位|关键[词字]|job|position|keyword|search", re.IGNORECASE)


def site_search_terms(keywords):
    from src.services.discovery_matching import requested_role_terms

    roles = [re.sub(r"^ai\s+agent$", "agent", k.strip(), flags=re.IGNORECASE)
             for k in keywords if k not in {"校招", "实习"} and k.strip()]
    aliases = requested_role_terms("岗位方向：" + "、".join(roles)) if roles else []
    return list(dict.fromkeys([*roles, *(term for group in aliases for term in group)]))[:6]


def has_job_search(raw_html, *, include_unlabelled=False):
    class Inputs(HTMLParser):
        found = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag != "input" or attrs.get("type", "text").lower() not in {"text", "search"}:
                return
            if "disabled" in attrs or "hidden" in attrs:
                return
            if include_unlabelled:
                self.found = True  # Only a browser/model can identify an unfamiliar public search UI.
            self.found |= bool(_HINT.search(" ".join(str(attrs.get(k) or "") for k in
                ("placeholder", "aria-label", "name", "id", "type"))))

    parser = Inputs()
    parser.feed(raw_html)
    return parser.found


SEARCH_CONTROLS = r"""(options = {}) => {
  const relaxed = options?.relaxed === true;
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' &&
      !el.closest('[hidden],[aria-hidden="true"]');
  const usable = el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
  const selector = el => {
    const parts = [];
    while (el && el !== document.documentElement) {
      const parent = el.parentElement;
      if (!parent) break;
      parts.unshift(el.tagName.toLowerCase() + ':nth-child(' + ([...parent.children].indexOf(el)+1) + ')');
      el = parent;
    }
    return 'html > ' + parts.join(' > ');
  };
  const label = el => (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.value || '').trim();
  const searchButton = /^(?:搜索|查询|查找|搜索职位|搜索岗位|查询职位|查找职位|search(?: jobs| positions)?|find jobs)$/i;
  const choices = [];
  for (const input of document.querySelectorAll('input')) {
    if (!usable(input) || !['text','search'].includes(input.type) || input.readOnly) continue;
    const hint = [input.placeholder, input.getAttribute('aria-label'), input.name,
      ...[...(input.labels || [])].map(el => el.innerText)].filter(Boolean).join(' ').trim();
    if (!relaxed && !/职位|岗位|关键[词字]|job|position|keyword/i.test(hint) && input.type !== 'search') continue;
    if (/邮箱|电话|姓名|密码|简历|验证码|email|phone|password|resume|verification/i.test(hint)) continue;
    const form = input.form;
    if (form && [...form.querySelectorAll('input,textarea')].some(el => visible(el) &&
        (el.tagName === 'TEXTAREA' || ['email','password','file','tel'].includes(el.type)))) continue;
    // The only native form submission admitted here is a public GET search.
    if (form && (form.method || 'get').toLowerCase() !== 'get') continue;
    let container = form || input.closest('[role="search"]') || input.parentElement;
    let buttons = [];
    for (let depth=0; container && depth<4; depth++) {
      buttons = [...container.querySelectorAll('button,input[type="submit"],[role="button"],i[aria-label],svg[aria-label],span[aria-label]')]
        .filter(el => usable(el) && (searchButton.test(label(el).replace(/^(?:图标|icon)\s*[:：]\s*/i, '')) ||
          (relaxed && label(el).length > 0 && label(el).length < 40 &&
            !/申请|投递|注册|登录|订阅|发送|保存|删除|apply|sign|log.?in|subscribe|send|save|delete/i.test(label(el)))) &&
          (['BUTTON','INPUT'].includes(el.tagName) || el.getAttribute('role') === 'button' ||
            getComputedStyle(el).cursor === 'pointer'));
      if (buttons.length || form || container.getAttribute('role') === 'search') break;
      container = container.parentElement;
    }
    if (buttons.length > 1 && !relaxed) continue;
    if (container && [...container.querySelectorAll('input')].some(el => visible(el) &&
        ['email','password','file','tel'].includes(el.type))) continue;
    if (!buttons.length) buttons = [null];
    for (const button of buttons.slice(0, 4)) {
    if (!button && !((input.type === 'search' || relaxed) && (form || input.closest('[role="search"]'))) &&
        !/职位|岗位|job|position/i.test(hint)) continue;
    if (button?.form && button.form !== form) continue;
    choices.push({input: selector(input), button: button ? selector(button) : null,
      hint, button_label: button ? label(button) : null,
      action_url: form ? (button?.hasAttribute('formaction') ? button.formAction : form.action) : location.href,
      method: form ? (button?.getAttribute('formmethod') || form.method || 'get').toLowerCase() : 'get',
      ...(relaxed ? {context: ((container?.parentElement || container)?.innerText || '').slice(0, 600)} : {})});
    }
  }
  return choices;
}"""


class SearchControlChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    control_id: int = Field(ge=-1, le=11)


async def discover_search_control(page, reader, recipe):
    """The model selects observed controls; it cannot generate selectors/actions."""
    candidates = await page.evaluate(SEARCH_CONTROLS, {"relaxed": True})
    if not candidates or len(candidates) > 12:
        return None
    if recipe and recipe.get("discovery") == "source_semantics":
        previous = {k: v for k, v in recipe.items() if k not in {"discovery", "submit_method"}}
        if previous in candidates:
            return {**previous, "discovery": "source_semantics"}
    runtime = getattr(reader, "search_understanding", None)
    if runtime is None:
        from src.config import get_settings
        from src.services.source_understanding import SourceUnderstanding

        runtime = reader.search_understanding = SourceUnderstanding(get_settings())
    output = await runtime.generate(SearchControlChoice, {
        "url": page.url,
        "heading": await page.title(),
        "controls": [{"id": i, **c} for i, c in enumerate(candidates)],
    }, (
        "从实际观察到的控件中选择用于公开招聘职位列表关键词筛选的一组输入框和按钮。"
        "结合标签和附近文本判断；站点全局搜索、姓名邮箱、登录、订阅、申请表都不能选。"
        "不能唯一确定是职位搜索时control_id=-1；只能返回输入中存在的编号，不得生成URL或操作。"
    ), kind="official_search_control")
    if output is None or not 0 <= output["control_id"] < len(candidates):
        return None
    selected = candidates[output["control_id"]]
    # Re-observe after the remote call. Never act on a stale model selection.
    current = await page.evaluate(SEARCH_CONTROLS, {"relaxed": True})
    return {**selected, "discovery": "source_semantics"} if selected in current else None


# Ignore input values, spinners, counts and search chips: those can change even
# if the site has not filtered its results. Only job rows or an empty state count.
RESULT_STATE = r"""() => {
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const titleClass = /(?:job|position|pos|post|vacancy)[\w-]*(?:title|name)|(?:title|name)[\w-]*(?:job|position|pos|post|vacancy)/i;
  const rows = [...document.querySelectorAll('a[href],div,span,h2,h3,h4')].filter(el => {
    if (!visible(el) || el.closest('nav,footer,form,[role="search"]')) return false;
    const text = (el.innerText || '').trim();
    let structural = false;
    if (text.length > 2 && text.length < 140 && /工程师|研究员|产品经理|engineer|scientist|developer/i.test(text)) {
      for (let p=el.parentElement, d=0; p && d<4; p=p.parentElement, d++) {
        const cls=p.className || '', content=(p.innerText || '').trim();
        if (/(?:^|[\s_-])(?:item|card|row)(?:$|[\s_-])/i.test(cls) && content.startsWith(text) &&
            /工作地点|所属业务|岗位职责|工作职责|location|department/i.test(content) &&
            getComputedStyle(p).cursor === 'pointer') { structural=true; break; }
      }
    }
    return text.length > 2 && text.length < 180 && (structural || titleClass.test(el.className || '') ||
      (el.tagName === 'A' && /\/(?:jobs?|positions?|posDetail|post|vacanc|detail)[/?]/i.test(el.getAttribute('href') || '')));
  }).map(el => [el.innerText.trim(), el.getAttribute('href') || '']);
  const empty = /(?:暂无|没有找到|没有对应|未找到|无匹配).{0,12}(?:岗位|职位)|(?:no|0)\s+(?:matching\s+)?(?:jobs|positions|results)\b/i.test(document.body.innerText);
  return {rows, empty: empty && !rows.length};
}"""


async def submit_job_search(page, *, reader, term, recipe=None):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from src.services.browser_job_reader import BrowserReadError, _raise_for_human_gate
    from src.services.recruitment_listing import allowed_listing_url

    controls = await page.evaluate(SEARCH_CONTROLS)
    if len(controls) != 1:
        control = await discover_search_control(page, reader, recipe)
        if control is None:
            return {"status": "ambiguous" if controls else "unavailable", "term": term}
    else:
        control = controls[0]
    if control["method"] != "get" or not allowed_listing_url(control["action_url"], page.url):
        return {"status": "unsafe_action", "term": term}
    from urllib.parse import urlsplit

    if re.search(r"/(?:apply|application|login|register|subscribe)(?:/|$)", urlsplit(control["action_url"]).path, re.IGNORECASE):
        return {"status": "unsafe_action", "term": term}
    origin = page.url
    await reader._validate_url(control["action_url"])
    prior = await page.evaluate(RESULT_STATE)
    field = page.locator(control["input"])
    if await field.count() != 1 or not await field.is_visible() or not await field.is_enabled():
        return {"status": "changed", "term": term}
    await field.fill("", timeout=min(reader.timeout_ms, 3000))
    # Some search components update their query on keyboard events rather than
    # input alone. Use normal typing so their visible value and query agree.
    await field.press_sequentially(term, timeout=min(reader.timeout_ms, 3000))
    method = "enter" if (recipe or {}).get("submit_method") == "enter" or not control["button"] else "click"
    if method == "click":
        await page.locator(control["button"]).click(timeout=min(reader.timeout_ms, 3000))
    else:
        await field.press("Enter", timeout=min(reader.timeout_ms, 3000))

    async def changed_results():
        try:
            await page.wait_for_function(
                "old => { const current = (" + RESULT_STATE + ")(); return "
                "(current.rows.length || current.empty) && JSON.stringify(current) !== JSON.stringify(old); }",
                arg=prior, timeout=min(reader.timeout_ms, 4000),
            )
        except PlaywrightTimeoutError:
            pass
        current = await page.evaluate(RESULT_STATE)
        return current != prior and bool(current["rows"] or current["empty"])

    confirmed = await changed_results()
    if not confirmed and method == "click" and page.url == origin:
        # Some accessible search icons are decorative; the input only handles
        # Enter. Revalidate the same public control before that bounded fallback.
        semantic = control.get("discovery") == "source_semantics"
        current_controls = await page.evaluate(SEARCH_CONTROLS, {"relaxed": semantic})
        observed = {k: v for k, v in control.items() if k != "discovery"}
        if observed in current_controls and await field.input_value() == term:
            await field.press("Enter", timeout=min(reader.timeout_ms, 3000))
            method = "enter"
            confirmed = await changed_results()
    await reader._validate_url(page.url)
    if not allowed_listing_url(page.url, origin):
        raise BrowserReadError("岗位搜索离开已核验招聘来源", code="listing_scope_changed")
    _raise_for_human_gate(await page.locator("body").inner_text(timeout=reader.timeout_ms))
    current = await page.evaluate(RESULT_STATE)
    used_recipe = {**control, "submit_method": method}
    return {"version": SEARCH_VERSION, "term": term,
            "status": "confirmed" if confirmed else "unconfirmed",
            "recipe": used_recipe, "recipe_reused": recipe == used_recipe,
            "empty": current["empty"], "start_url": origin, "result_url": page.url}
