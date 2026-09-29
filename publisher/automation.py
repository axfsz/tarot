"""Browser automation for creator websites (Xiaohongshu, WeChat Channels, TikTok).

None of these platforms offers a posting API to individual creators, so the
worker drives their creator web pages the way a person would, in a persistent
browser profile per platform (one QR-code login lasts until the platform expires it).

Locators live in selectors.json and can be overridden without a rebuild.
Every failure is classified so the worker can react:
  NeedLogin   -> login expired: pause auto posting, ask for a new QR scan
  RiskControl -> captcha / rate warning: cool down, fall back to manual posting
  PublishError-> anything else: retry a few times, then manual
"""
import asyncio, json, os, re, time, random
from pathlib import Path

HERE = Path(__file__).parent
STORE = Path(os.getenv('PUBLISHER_DIR', '/pubdata'))


class NeedLogin(Exception):
    pass


class RiskControl(Exception):
    pass


class PublishError(Exception):
    def __init__(self, msg, code='error'):
        super().__init__(msg)
        self.code = code


def selectors():
    base = json.loads((HERE / 'selectors.json').read_text())
    override = STORE / 'selectors.json'
    if override.exists():
        try:
            for k, v in json.loads(override.read_text()).items():
                if isinstance(v, dict) and k in base:
                    base[k].update(v)
        except Exception:
            pass
    return base


async def pause(lo=0.6, hi=1.6):
    await asyncio.sleep(random.uniform(lo, hi))


def frames(page):
    return [page.main_frame] + [f for f in page.frames if f != page.main_frame]


async def find(page, cands, timeout=15, state='visible'):
    """First candidate that matches (searching iframes too); None after `timeout` seconds."""
    end = time.monotonic() + timeout
    while True:
        for fr in frames(page):
            for sel in cands:
                try:
                    loc = fr.locator(sel)
                    n = await loc.count()
                    for i in range(min(n, 5)):
                        el = loc.nth(i)
                        if state == 'attached' or await el.is_visible():
                            return el
                except Exception:
                    continue
        if time.monotonic() > end:
            return None
        await asyncio.sleep(0.5)


async def need(page, cands, what, timeout=20, state='visible'):
    el = await find(page, cands, timeout, state)
    if el is None:
        await check_risk(page, SEL_CACHE.get('current') or {})
        raise PublishError(f'page element not found: {what}', 'selector:' + what)
    return el


SEL_CACHE = {}


async def page_text(page):
    out = []
    for fr in frames(page):
        try:
            out.append(await fr.locator('body').inner_text(timeout=3000))
        except Exception:
            pass
    return '\n'.join(out)


async def check_risk(page, S):
    text = (await page_text(page)).lower()
    for w in S.get('risk_text', []):
        if w.lower() in text:
            raise RiskControl(f'platform shows: {w}')


def logged_out(page, S):
    return any(m in page.url for m in S.get('logged_out_url', []))


async def has_session(ctx, S):
    names = {c['name'] for c in await ctx.cookies()}
    return any(n in names for n in S.get('session_cookies', []))


async def is_logged_in(ctx, page, S):
    await page.goto(S['home_url'], wait_until='domcontentloaded', timeout=60000)
    await asyncio.sleep(4)
    return not logged_out(page, S)


async def open_login(page, S):
    """Open the QR login page; returns PNG bytes of the QR code (or the whole page)."""
    await page.goto(S['login_url'], wait_until='domcontentloaded', timeout=60000)
    await asyncio.sleep(3)
    for sel in S.get('qr_switch', []):
        el = await find(page, [sel], timeout=1.5)
        if el is not None:
            try:
                await el.click(timeout=3000)
                await asyncio.sleep(1.5)
                break
            except Exception:
                pass
    return await qr_image(page, S)


async def qr_image(page, S):
    el = await find(page, S.get('qr', []), timeout=10)
    if el is not None:
        try:
            box = await el.bounding_box()
            if box and box['width'] >= 80 and box['height'] >= 80:
                return await el.screenshot(timeout=5000)
        except Exception:
            pass
    return await page.screenshot(full_page=False)


async def login_done(ctx, page, S):
    # Logged in once the site has left the login page (all three redirect to the dashboard).
    return not (page.url.split('?')[0] == S['login_url'].split('?')[0] or logged_out(page, S))


async def type_lines(page, text):
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line:
            await page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            await page.keyboard.press('Enter')
        await asyncio.sleep(random.uniform(0.05, 0.2))


async def type_tags(page, tags, S, pick_suggestion=False):
    if not tags:
        return
    await page.keyboard.press('Enter')
    for t in tags:
        await page.keyboard.type('#' + t, delay=random.randint(60, 140))
        await asyncio.sleep(1.4)
        sug = await find(page, S.get('tag_suggestion', []), timeout=1) if pick_suggestion else None
        if sug is not None:
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.4)
        else:
            await page.keyboard.type(' ')
        await pause(0.3, 0.8)


async def wait_success(page, S, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(u in page.url for u in S.get('success_url', [])):
            return page.url
        text = await page_text(page)
        if any(w in text for w in S.get('success_text', [])):
            return page.url
        await check_risk(page, S)
        await asyncio.sleep(2)
    raise PublishError('no confirmation after clicking publish', 'no_confirmation')


async def enabled(el, disabled_class=''):
    try:
        if await el.is_disabled():
            return False
        if (await el.get_attribute('aria-disabled')) == 'true':
            return False
        if disabled_class and disabled_class in (await el.get_attribute('class') or ''):
            return False
        return True
    except Exception:
        return False


MISSING_TIMEOUT = 60


async def wait_enabled(page, cands, S, timeout, what='publish button'):
    start_t = time.monotonic()
    end = start_t + timeout
    seen = False
    while time.monotonic() < end:
        el = await find(page, cands, timeout=2)
        seen = seen or el is not None
        if el is not None and await enabled(el, S.get('disabled_class', '')):
            return el
        if not seen and time.monotonic() - start_t > MISSING_TIMEOUT:
            raise PublishError(f'page element not found: {what}', 'selector:' + what)
        await check_risk(page, S)
        await asyncio.sleep(3)
    raise PublishError(f'{what} did not become ready (upload too slow or rejected)', 'upload_timeout')


async def start(page, S):
    SEL_CACHE['current'] = S
    await page.goto(S['publish_url'], wait_until='domcontentloaded', timeout=90000)
    await asyncio.sleep(4)
    if logged_out(page, S):
        raise NeedLogin('login expired')
    await check_risk(page, S)


# ---------------------------------------------------------------- platforms
async def xiaohongshu(page, S, p, files, kind, dry_run):
    await start(page, S)
    tab = await find(page, S['tab_video' if kind == 'video' else 'tab_images'], timeout=15)
    if tab is not None:
        await tab.click()
        await pause()
    inp = await need(page, S['file_input'], 'file input', 20, 'attached')
    await inp.set_input_files([str(f) for f in files])
    if kind == 'video':
        if await find(page, S['upload_done_video'], timeout=900) is None:
            raise PublishError('video upload did not finish', 'upload_timeout')
    title = await need(page, S['title'], 'title', 180)
    await pause()
    if p.get('title'):
        await title.click()
        await title.fill(p['title'])
        await pause()
    body = await need(page, S['body'], 'body', 30)
    await body.click()
    await type_lines(page, p.get('text', ''))
    await type_tags(page, p.get('hashtags', []), S, pick_suggestion=True)
    await pause(1.5, 3)
    await check_risk(page, S)
    if dry_run:
        return dict(url=page.url, dry_run=True)
    btn = await need(page, S['publish_button'], 'publish button', 20)
    await btn.click()
    return dict(url=await wait_success(page, S, 120))


def short_title(t):
    t = re.sub(r'[^\w一-鿿《》“”:+?%°\s]', '', t or '').strip()
    return t[:16] if len(t) >= 6 else ''


async def channels(page, S, p, files, kind, dry_run):
    await start(page, S)
    inp = await need(page, S['file_input'], 'file input', 30, 'attached')
    await inp.set_input_files(str(files[0]))
    body = await need(page, S['body'], 'description', 60)
    await body.click()
    await type_lines(page, p.get('text', ''))
    await type_tags(page, p.get('hashtags', []), S)
    st = short_title(p.get('title', ''))
    if st:
        el = await find(page, S['short_title'], timeout=5)
        if el is not None:
            await el.click()
            await el.fill(st)
    btn = await wait_enabled(page, S['publish_button'], S, 1200)
    await pause(1.5, 3)
    await check_risk(page, S)
    if dry_run:
        return dict(url=page.url, dry_run=True)
    await btn.click()
    return dict(url=await wait_success(page, S, 120))


async def tiktok(page, S, p, files, kind, dry_run):
    await start(page, S)
    inp = await need(page, S['file_input'], 'file input', 30, 'attached')
    await inp.set_input_files(str(files[0]))
    body = await need(page, S['body'], 'caption', 120)
    btn = await wait_enabled(page, S['publish_button'], S, 1200)
    await body.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.press('Backspace')
    await type_lines(page, p.get('text', ''))
    await type_tags(page, p.get('hashtags', []), S)
    await pause(2, 4)
    await check_risk(page, S)
    if dry_run:
        return dict(url=page.url, dry_run=True)
    await btn.click()
    await asyncio.sleep(3)
    ok = await find(page, S.get('confirm_buttons', []), timeout=5)
    if ok is not None:
        await ok.click()
    return dict(url=await wait_success(page, S, 180))


ADAPTERS = dict(xiaohongshu=xiaohongshu, channels=channels, tiktok=tiktok)


async def publish(page, platform, payload, files, kind, dry_run=False):
    S = selectors()[platform]
    return await ADAPTERS[platform](page, S, payload, files, kind, dry_run)
