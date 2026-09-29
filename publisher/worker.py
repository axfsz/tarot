"""Publisher worker: runs scheduled posting jobs and QR-code logins.

Runs in its own container (Chromium + ffmpeg), next to the web app:
  - every 20s claims due jobs from the shared database and posts them;
  - serves a small private HTTP API (compose network only, token-protected)
    that the admin console uses for QR login, login checks and screenshots.

Fallback policy (per the studio's choice "auto first, manual when blocked"):
  mode=manual, login expired, risk-control cooldown, missing media, or repeated
  failures -> the job becomes "manual": the admin gets an email with the text
  to paste, and the console shows a one-tap copy / "I posted it" card.
"""
import asyncio, base64, hmac, json, logging, os, re, secrets, shutil, smtplib, ssl, threading, time
from datetime import timedelta
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import core, db, media
from .automation import STORE, NeedLogin, RiskControl, PublishError, selectors, open_login, qr_image, login_done, is_logged_in, publish

log = logging.getLogger('publisher')
HEADLESS = os.getenv('PUBLISHER_HEADLESS', '0') == '1'
SHOTS = STORE / 'shots'
PROFILES = STORE / 'profiles'
LOGIN_TTL = 180
COOLDOWN_HOURS = int(os.getenv('PUBLISHER_RISK_COOLDOWN_HOURS', '24'))
SITE_URL = (('https://' + os.getenv('CANONICAL_HOST')) if os.getenv('CANONICAL_HOST') else os.getenv('SITE_URL', 'https://tarot.opsglobalonline.com')).rstrip('/')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'


# ---------------------------------------------------------------- helpers
def now():
    return core.utcnow()


def proxy_for(platform):
    v = os.getenv('PUBLISHER_PROXY_' + platform.upper()) or ''
    return {'server': v} if v else None


def mail(subject, text):
    to = [x.strip() for x in os.getenv('NOTIFY_EMAIL', '').split(',') if x.strip()]
    host, sender = os.getenv('SMTP_HOST'), os.getenv('SMTP_FROM')
    if not (to and host and sender):
        return False
    try:
        port = int(os.getenv('SMTP_PORT', '587'))
        srv = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) if port == 465 else smtplib.SMTP(host, port, timeout=20)
        with srv:
            if port != 465 and os.getenv('SMTP_STARTTLS', '1') != '0':
                srv.starttls(context=ssl.create_default_context())
            if os.getenv('SMTP_USER'):
                srv.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD', ''))
            for addr in to:
                m = EmailMessage()
                m['From'], m['To'], m['Subject'] = sender, addr, subject
                m.set_content(text)
                srv.send_message(m)
        return True
    except Exception as e:
        log.warning('mail failed: %s', str(e)[:200])
        return False


def set_account(platform, **kw):
    with db.engine.begin() as c:
        a = core.account(db.get, c, platform)
        a.update(kw, checked=core.iso(now()))
        db.put(c, 'publish:account:' + platform, 'config', 'system', a)
        return a


def friendly(platform, e):
    msg = str(e).strip().split('\n')[0][:200]
    if 'net::ERR' in msg or 'Timeout' in msg:
        return (f'服务器打不开{name(platform)}网站（{msg.split(" at ")[0]}）。请检查服务器网络，或在 .env 设置 '
                f'PUBLISHER_PROXY_{platform.upper()} 代理 / cannot reach the site from the server')
    return msg


def name(platform):
    return core.PLATFORMS[platform]['zh']


async def _shot(page, tag):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        fn = f'{tag}-{secrets.token_hex(3)}.png'
        await page.screenshot(path=str(SHOTS / fn), full_page=False, timeout=10000)
        # keep the folder small: newest 200 screenshots
        for old in sorted(SHOTS.glob('*.png'), key=lambda p: p.stat().st_mtime)[:-200]:
            old.unlink(missing_ok=True)
        return fn
    except Exception:
        return ''


# ---------------------------------------------------------------- browser
class Browsers:
    def __init__(self):
        self.pw = None
        self.locks = {p: asyncio.Lock() for p in core.PLATFORMS}
        self.logins = {}

    async def start(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()

    async def context(self, platform):
        d = PROFILES / platform
        d.mkdir(parents=True, exist_ok=True)
        for lock in d.glob('Singleton*'):          # stale lock after a container restart
            lock.unlink(missing_ok=True)
        kw = dict(user_data_dir=str(d), headless=HEADLESS, viewport=dict(width=1366, height=900),
                  locale='en-US' if platform == 'tiktok' else 'zh-CN',
                  timezone_id=os.getenv('PUBLISHER_TZ_' + platform.upper()) or ('America/Los_Angeles' if platform == 'tiktok' else 'Asia/Shanghai'),
                  args=['--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check'])
        if HEADLESS:
            kw['user_agent'] = UA
        if proxy_for(platform):
            kw['proxy'] = proxy_for(platform)
        ctx = await self.pw.chromium.launch_persistent_context(**kw)
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.set_default_timeout(30000)
        return ctx


B = Browsers()


# ---------------------------------------------------------------- QR login
async def login_start(platform):
    await login_cancel(platform)
    lock = B.locks[platform]
    try:
        await asyncio.wait_for(lock.acquire(), 5)
    except asyncio.TimeoutError:
        return dict(status='busy', message='正在发帖，请一分钟后再试 / Posting in progress, retry in a minute')
    ctx = page = None
    try:
        ctx = await B.context(platform)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        S = selectors()[platform]
        png = await open_login(page, S)
        if await login_done(ctx, page, S):         # the saved profile is still logged in
            await ctx.close()
            lock.release()
            set_account(platform, status='ok', note='', paused_until='')
            return dict(status='ok')
        sess = dict(ctx=ctx, page=page, S=S, status='waiting', qr=base64.b64encode(png).decode(), started=time.time(), lock=lock)
        B.logins[platform] = sess
        sess['task'] = asyncio.ensure_future(login_watch(platform, sess))
        return dict(status='waiting', qr=sess['qr'], ttl=LOGIN_TTL)
    except Exception as e:
        if ctx:
            await ctx.close()
        lock.release()
        log.warning('login start failed: %s', e)
        return dict(status='error', message=friendly(platform, e))


async def login_watch(platform, sess):
    ctx, page, S = sess['ctx'], sess['page'], sess['S']
    try:
        while time.time() - sess['started'] < LOGIN_TTL and sess['status'] == 'waiting':
            await asyncio.sleep(2)
            if await login_done(ctx, page, S):
                await asyncio.sleep(4)            # let the site finish writing its cookies
                sess['status'] = 'ok'
                set_account(platform, status='ok', note='扫码登录成功 / logged in', paused_until='')
                break
            try:
                sess['qr'] = base64.b64encode(await qr_image(page, S)).decode()   # QR codes refresh themselves
            except Exception:
                pass
        if sess['status'] == 'waiting':
            sess['status'] = 'expired'
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
        if sess['lock'].locked():
            sess['lock'].release()


async def login_state(platform):
    s = B.logins.get(platform)
    if not s:
        return dict(status='none')
    return dict(status=s['status'], qr=s['qr'] if s['status'] == 'waiting' else '', left=max(0, int(LOGIN_TTL - (time.time() - s['started']))))


async def login_cancel(platform):
    s = B.logins.pop(platform, None)
    if s and s['status'] == 'waiting':
        s['status'] = 'cancelled'
        await asyncio.sleep(0)
        t = s.get('task')
        if t:
            try:
                await asyncio.wait_for(t, 10)
            except Exception:
                pass
    return dict(status='cancelled')


async def check(platform):
    lock = B.locks[platform]
    try:
        await asyncio.wait_for(lock.acquire(), 30)
    except asyncio.TimeoutError:
        return dict(status='busy')
    try:
        ctx = await B.context(platform)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            ok = await is_logged_in(ctx, page, selectors()[platform])
        finally:
            await ctx.close()
        a = set_account(platform, status='ok' if ok else 'expired', note='' if ok else '登录已失效，请重新扫码 / login expired')
        return dict(status=a['status'])
    except Exception as e:
        return dict(status='error', message=friendly(platform, e))
    finally:
        lock.release()


async def logout(platform):
    await login_cancel(platform)
    async with B.locks[platform]:
        shutil.rmtree(PROFILES / platform, ignore_errors=True)
    set_account(platform, status='logged_out', note='', paused_until='')
    return dict(status='logged_out')


# ---------------------------------------------------------------- jobs
def to_manual(j, reason, note):
    with db.engine.begin() as c:
        x = core.set_state(c, db.jobs, j['id'], 'manual', note, expect=('running', 'scheduled'), reason=reason, lease='')
    if not x or j['payload'].get('dry_run'):
        return
    link = f"{SITE_URL}/admin"
    mail(f"待手动发布 · {name(j['platform'])} / Post by hand: {core.PLATFORMS[j['platform']]['en']}",
         f"这条{name(j['platform'])}帖子没有自动发出：{note}\n请在手机上打开后台“自动营销 → 发布队列”，一键复制文案和下载配图后手动发布，发完点“我已发布”。\n{link}\n\n"
         f"—— 文案 / Text ——\n{core.kit_text(j)}\n\nJob: {j['id']}")


def fail(j, status, note, **kw):
    with db.engine.begin() as c:
        core.set_state(c, db.jobs, j['id'], status, note, expect=('running',), lease='', **kw)


def mark_draft(j, url):
    if not j.get('draft'):
        return
    with db.engine.begin() as c:
        d = db.get(c, j['draft'])
        if d:
            d.update(status='posted', posted_at=core.iso(now()), posted_url=url or '', posted_via='auto:' + j['platform'])
            db.put(c, d['id'], 'mkt_draft', 'system', d)


async def run_job(j):
    p, dry = j['platform'], bool(j['payload'].get('dry_run'))
    with db.engine.begin() as c:
        cfg = core.config(db.get, c)[p]
        acc = core.account(db.get, c, p)
    if not dry:
        if cfg['mode'] != 'auto':
            return to_manual(j, 'mode', '该平台设为手动发布，到点提醒 / manual mode: reminder')
        if acc.get('paused_until') and acc['paused_until'] > core.iso(now()):
            return to_manual(j, 'risk', f"平台风控冷却中（至 {acc['paused_until'][:16]} UTC）/ risk cooldown")
        if acc['status'] in ('expired', 'logged_out', 'unknown'):
            return to_manual(j, 'login', '账号未登录或登录已失效，请在后台扫码登录 / not logged in')
        with db.engine.begin() as c:
            later = core.pacing(c, db.jobs, p, cfg)
            if later:
                core.set_state(c, db.jobs, j['id'], 'scheduled', f'paced to {core.iso(later)}', expect=('running',), run_at=later, lease='')
                return
    try:
        kind, files, tmp = await asyncio.get_running_loop().run_in_executor(
            None, media.prepare, p, j['payload'].get('media'), core.PLATFORMS[p]['needs'], core.PLATFORMS[p]['max_images'])
    except media.MediaError as e:
        return fail(j, 'failed', str(e)) if dry else to_manual(j, 'media', f'配图/视频不可用：{e}')
    lock = B.locks[p]
    if lock.locked() and p in B.logins:
        with db.engine.begin() as c:
            core.set_state(c, db.jobs, j['id'], 'scheduled', 'login in progress, retry in 5 min', expect=('running',), run_at=now() + timedelta(minutes=5), lease='')
        return
    async with lock:
        ctx = page = None
        try:
            ctx = await B.context(p)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            res = await publish(page, p, j['payload'], files, kind, dry)
            shot = await _shot(page, j['id'])
            if dry:
                return fail(j, 'tested', '试运行成功：已填好内容，未点击发布 / dry run ok, not posted', shot=shot)
            with db.engine.begin() as c:
                core.set_state(c, db.jobs, j['id'], 'published', '', expect=('running',), url=res.get('url', ''), via='auto', shot=shot, lease='')
            set_account(p, status='ok', note='')
            mark_draft(j, res.get('url', ''))
        except NeedLogin:
            shot = await _shot(page, j['id']) if page else ''
            set_account(p, status='expired', note='登录已失效，请重新扫码 / login expired')
            if dry:
                return fail(j, 'failed', 'login expired', shot=shot)
            with db.engine.begin() as c:
                core.set_state(c, db.jobs, j['id'], 'running', 'login expired', expect=('running',), shot=shot)
            to_manual(j, 'login', '登录已失效，请在后台重新扫码登录 / login expired')
            mail(f"{name(p)}登录已失效 / {core.PLATFORMS[p]['en']} login expired", f"请在后台“自动营销 → 自动发帖账号”重新扫码登录。\n{SITE_URL}/admin")
        except RiskControl as e:
            shot = await _shot(page, j['id']) if page else ''
            until = core.iso(now() + timedelta(hours=COOLDOWN_HOURS))
            set_account(p, status='risk', note=f'触发平台验证：{e}', paused_until=until)
            if dry:
                return fail(j, 'failed', f'risk control: {e}', shot=shot)
            with db.engine.begin() as c:
                core.set_state(c, db.jobs, j['id'], 'running', f'risk control: {e}', expect=('running',), shot=shot)
            to_manual(j, 'risk', f'平台弹出验证/风控（{e}），自动发帖暂停 {COOLDOWN_HOURS} 小时 / risk control, paused')
        except Exception as e:
            code = getattr(e, 'code', type(e).__name__)
            shot = await _shot(page, j['id']) if page else ''
            log.warning('job %s failed: %s', j['id'], e)
            err = friendly(p, e)
            if dry:
                return fail(j, 'failed', f'{code}: {err}', shot=shot, error=err, code=code)
            if j['attempts'] < core.MAX_ATTEMPTS:
                with db.engine.begin() as c:
                    core.set_state(c, db.jobs, j['id'], 'scheduled', f'retry after error: {err[:160]}', expect=('running',),
                                   run_at=now() + timedelta(minutes=10 * j['attempts']), lease='', shot=shot, error=err, code=code)
            else:
                with db.engine.begin() as c:
                    core.set_state(c, db.jobs, j['id'], 'running', f'giving up: {err[:160]}', expect=('running',), shot=shot, error=err, code=code)
                to_manual(j, 'error', f'自动发布 {core.MAX_ATTEMPTS} 次都失败（{err[:120]}）/ failed {core.MAX_ATTEMPTS} times')
        finally:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)


async def job_loop():
    while True:
        try:
            with db.engine.begin() as c:
                j = core.claim(c, db.jobs, 'publisher')
            if j:
                await run_job(j)
                continue
        except Exception:
            log.exception('job loop iteration failed')
        await asyncio.sleep(20)


async def heartbeat():
    while True:
        try:
            with db.engine.begin() as c:
                db.put(c, 'publish:heartbeat', 'config', 'system', dict(at=core.iso(now()), headless=HEADLESS,
                                                                         logins=[p for p, s in B.logins.items() if s['status'] == 'waiting']))
        except Exception:
            log.exception('heartbeat failed')
        await asyncio.sleep(30)


# ---------------------------------------------------------------- private HTTP API
LOOP = None


def call(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout)


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200, ctype='application/json'):
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def route(self, method):
        if self.path == '/health':
            return self.send(dict(ok=True))
        if not hmac.compare_digest(self.headers.get('X-Publisher-Token', ''), db.token()):
            return self.send(dict(error='forbidden'), 403)
        m = re.fullmatch(r'/(login|check|logout)/([a-z]+)', self.path)
        if m and m.group(2) in core.PLATFORMS:
            act, p = m.groups()
            if act == 'login':
                fn = {'POST': login_start, 'GET': login_state, 'DELETE': login_cancel}.get(method)
                return self.send(call(fn(p), 90)) if fn else self.send(dict(error='method'), 405)
            if method == 'POST':
                return self.send(call(check(p) if act == 'check' else logout(p), 150))
        m = re.fullmatch(r'/shot/([A-Za-z0-9_\-]+\.png)', self.path)
        if m and method == 'GET':
            f = SHOTS / m.group(1)
            return self.send(f.read_bytes(), 200, 'image/png') if f.is_file() else self.send(dict(error='not found'), 404)
        self.send(dict(error='not found'), 404)

    def do_GET(self):
        self.route('GET')

    def do_POST(self):
        self.route('POST')

    def do_DELETE(self):
        self.route('DELETE')


async def main():
    global LOOP
    LOOP = asyncio.get_running_loop()
    STORE.mkdir(parents=True, exist_ok=True)
    await B.start()
    srv = ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PUBLISHER_PORT', '8200'))), Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info('publisher ready (headless=%s)', HEADLESS)
    await asyncio.gather(job_loop(), heartbeat())


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main())
