"""v0.8.1 scheduled posting: queue core, admin API, and the publisher worker's decisions."""
import os, sys, json, asyncio, shutil, subprocess
from datetime import datetime, timezone, timedelta
import pytest
from test_v072 import client, post, admin  # noqa: F401  (admin is a fixture)
import app as m
import publisher.core as core

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')
POSTS = dict(posts=[dict(platform='xiaohongshu', title='今天抽到愚者，送给想重新开始的你', text='第一段\n第二段', hashtags=['#塔罗', '每日一牌']),
                    dict(platform='tiktok', title='The Fool', text='New starts are allowed.', hashtags=['tarot', 'fyp']),
                    dict(platform='channels', title='愚者：给自己一次重新出发', text='视频号正文', hashtags=['塔罗'])])


def fake_model(payload):
    def call(s, messages, max_tokens, json_mode):
        return json.dumps(payload, ensure_ascii=False), dict(prompt_tokens=100, completion_tokens=100)
    return call


def reset_queue():
    with m.engine.begin() as c:
        c.execute(m.delete(m.jobs))
        for k in ('publish:config', 'publish:account:xiaohongshu', 'publish:account:tiktok', 'publish:account:channels'):
            c.execute(m.delete(m.records).where(m.records.c.id == k))


@pytest.fixture
def drafts(admin, monkeypatch):
    reset_queue()
    monkeypatch.setattr(m, '_model_call', fake_model(POSTS))
    r = post(admin, '/admin/marketing/generate', dict(source='card', ref='the-fool', platforms=['xiaohongshu', 'tiktok', 'channels']))
    assert r.status_code == 200, r.json
    return {d['platform']: d for d in r.json['drafts']}


# ---------------------------------------------------------------- core
def test_compose_fits_each_platform():
    d = dict(title='今天抽到愚者，送给想重新开始的你', text='正文', hashtags=['#塔罗', ' 每日 一牌 ', '', 'x' * 50])
    x = core.compose('xiaohongshu', d)
    assert x['title'] == d['title'][:20] and x['hashtags'] == ['塔罗', '每日一牌', 'x' * 30]
    t = core.compose('tiktok', dict(title='The Fool', text='Body', hashtags=['tarot']))
    assert t['title'] == '' and t['text'] == 'The Fool\n\nBody'
    assert core.compose('channels', dict(title='一' * 30, text='a'))['title'] == '一' * 16
    assert core.kit_text(dict(payload=dict(title='T', text='B', hashtags=['a', 'b']))) == 'T\n\nB\n\n#a #b'


def test_slots_and_pacing():
    meta = m.MetaData()
    eng = m.create_engine('sqlite://')
    jobs = core.table(meta)
    meta.create_all(eng)
    cfg = {**core.DEFAULTS, 'slots': ['09:00', '20:30'], 'daily_cap': 2, 'min_gap': 60}
    now = datetime(2031, 5, 1, 1, 0, tzinfo=timezone.utc)          # 09:00 in Kuala Lumpur (UTC+8)
    with eng.begin() as c:
        s1 = core.next_slot(c, jobs, 'tiktok', cfg, 'Asia/Kuala_Lumpur', now)
        assert abs((s1 - datetime(2031, 5, 1, 12, 30, tzinfo=timezone.utc)).total_seconds()) <= 360   # 09:00 is too close; 20:30 today
        core.new_job(c, jobs, 'tiktok', dict(id='mkt:a'), s1)
        s2 = core.next_slot(c, jobs, 'tiktok', cfg, 'Asia/Kuala_Lumpur', now)
        assert s2.astimezone(timezone.utc).date().isoformat() == '2031-05-02' and abs((s2 - datetime(2031, 5, 2, 1, 0, tzinfo=timezone.utc)).total_seconds()) <= 360
        # pacing: min gap, then rolling daily cap
        assert core.pacing(c, jobs, 'tiktok', cfg, now) is None
        a = core.new_job(c, jobs, 'tiktok', dict(id='mkt:b'), now)
        core.set_state(c, jobs, a, 'published')
        later = core.pacing(c, jobs, 'tiktok', cfg, core.utcnow())
        assert later and later > core.utcnow() + timedelta(minutes=55)
        b = core.new_job(c, jobs, 'tiktok', dict(id='mkt:c'), now)
        core.set_state(c, jobs, b, 'published')
        later = core.pacing(c, jobs, 'tiktok', {**cfg, 'min_gap': 10}, core.utcnow() + timedelta(minutes=30))
        assert later and later > core.utcnow() + timedelta(hours=23)
        with pytest.raises(ValueError):
            core.clean_config(cfg, dict(slots='25:00'))
        assert core.clean_config(cfg, dict(slots='20:30，09:05', mode='manual'))['slots'] == ['09:05', '20:30']


def test_claim_is_atomic_and_recovers_dead_leases():
    meta = m.MetaData()
    eng = m.create_engine('sqlite://')
    jobs = core.table(meta)
    meta.create_all(eng)
    with eng.begin() as c:
        a = core.new_job(c, jobs, 'xiaohongshu', dict(id='mkt:a'), core.utcnow() - timedelta(minutes=1))
        core.new_job(c, jobs, 'xiaohongshu', dict(id='mkt:b'), core.utcnow() + timedelta(hours=1))   # not due
        j = core.claim(c, jobs)
        assert j['id'] == a and j['status'] == 'running' and j['attempts'] == 1
        assert core.claim(c, jobs) is None
        c.execute(m.update(jobs).where(jobs.c.id == a).values(lease=core.iso(core.utcnow() - timedelta(seconds=1))))
        j = core.claim(c, jobs)
        assert j['id'] == a and j['attempts'] == 2 and any('lease expired' in x[1] for x in j['result']['log'])
        assert core.set_state(c, jobs, a, 'published', expect=('scheduled',)) is None       # guarded transition


# ---------------------------------------------------------------- admin API
def test_new_platforms_and_card_picture(drafts, admin):
    mk = admin.get('/api/admin/marketing').json
    assert {'channels', 'tiktok'} <= set(mk['platforms']) and mk['channels'].count('tiktok') == 1
    x = drafts['xiaohongshu']
    assert x['media'][0]['file'].startswith('static/tarot/cards/major/00-the-fool') and x['media'][0]['file'].endswith('.webp')
    assert client().get('/' + x['media'][0]['file']).status_code == 200      # the reviewed copy is public; PNG originals stay blocked
    pub = admin.get('/api/admin/publish').json
    assert set(pub['platforms']) == {'xiaohongshu', 'channels', 'tiktok'} and pub['worker']['online'] is False
    assert pub['platforms']['tiktok']['account']['status'] == 'unknown' and pub['platforms']['tiktok']['needs'] == 'video'
    assert client().get('/api/admin/publish').status_code == 401


def test_schedule_edit_and_actions(drafts, admin):
    xid = drafts['xiaohongshu']['id'].split(':')[1]
    r = post(admin, f'/admin/marketing/drafts/{xid}/schedule', dict(when='at', at='2020-01-01T10:00'))
    assert r.status_code == 400
    at = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(m.ZoneInfo('Asia/Kuala_Lumpur')).strftime('%Y-%m-%dT%H:%M')
    j = post(admin, f'/admin/marketing/drafts/{xid}/schedule', dict(when='at', at=at)).json['job']
    assert j['status'] == 'scheduled' and j['title'] == '今天抽到愚者，送给想重新开始的你'[:20] and j['hashtags'] == ['塔罗', '每日一牌']
    assert j['run_at'][:16] == datetime.fromisoformat(at).replace(tzinfo=m.ZoneInfo('Asia/Kuala_Lumpur')).astimezone(timezone.utc).isoformat()[:16]
    assert post(admin, f'/admin/marketing/drafts/{xid}/schedule', dict(when='slot')).status_code == 400      # already queued
    # editing the draft updates the queued post
    post(admin, f'/admin/marketing/drafts/{xid}', dict(text='改过的正文', hashtags=['#新标签']), 'PUT')
    j2 = next(x for x in admin.get('/api/admin/publish').json['jobs'] if x['id'] == j['id'])
    assert j2['text'] == '改过的正文' and j2['hashtags'] == ['新标签'] and '改过的正文' in j2['kit']
    # actions
    assert post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='retry')).status_code == 409
    assert post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='now')).json['job']['status'] == 'scheduled'
    assert post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='posted', url='http://x')).status_code == 400
    done = post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='posted', url='https://www.xiaohongshu.com/explore/1')).json['job']
    assert done['status'] == 'published' and done['via'] == 'manual'
    d = next(x for x in admin.get('/api/admin/marketing').json['drafts'] if x['id'] == drafts['xiaohongshu']['id'])
    assert d['status'] == 'posted' and d['posted_url'].endswith('/explore/1')
    assert post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='delete')).status_code == 200
    assert post(admin, '/admin/publish/jobs/pub_0000000000000000', dict(action='cancel')).status_code == 404
    # platform switched off: refuses to queue (a dry run is still allowed)
    tid = drafts['tiktok']['id'].split(':')[1]
    assert post(admin, '/admin/publish/tiktok', dict(mode='off'), 'PUT').json['config']['mode'] == 'off'
    assert post(admin, f'/admin/marketing/drafts/{tid}/schedule', dict(when='now')).status_code == 400
    t = post(admin, f'/admin/marketing/drafts/{tid}/schedule', dict(when='now', dry_run=True)).json['job']
    assert t['dry_run'] and t['status'] == 'scheduled'
    assert post(admin, '/admin/publish/tiktok', dict(slots='9pm'), 'PUT').status_code == 400
    assert post(admin, '/admin/publish/tiktok', dict(daily_cap=99), 'PUT').status_code == 400
    assert post(admin, '/admin/publish/myspace', dict(mode='auto'), 'PUT').status_code == 404
    # deleting a draft cancels what is still queued for it
    cid = drafts['channels']['id'].split(':')[1]
    cj = post(admin, f'/admin/marketing/drafts/{cid}/schedule', dict(when='slot')).json['job']
    post(admin, f'/admin/marketing/drafts/{cid}', dict(action='delete'), 'PUT')
    assert next(x for x in admin.get('/api/admin/publish').json['jobs'] if x['id'] == cj['id'])['status'] == 'cancelled'
    # platforms without automation are refused
    with m.engine.begin() as c:
        xd = next(x for x in m.rows(c, 'mkt_draft') if x['platform'] not in core.PLATFORMS) if any(x['platform'] not in core.PLATFORMS for x in m.rows(c, 'mkt_draft')) else None
    if xd:
        assert post(admin, f"/admin/marketing/drafts/{xd['id'].split(':')[1]}/schedule", dict(when='now')).status_code == 400


def upload(c, id, data, name):
    token = c.get('/api/bootstrap').json['csrf']
    return c.post(f'/api/admin/marketing/drafts/{id}/media', data=data, headers={'X-CSRF': token, 'X-Filename': name, 'Content-Type': 'application/octet-stream'})


def test_media_upload_and_topic_needs_media(admin, monkeypatch):
    reset_queue()
    monkeypatch.setattr(m, '_model_call', fake_model(dict(posts=[dict(platform='tiktok', text='topic post', hashtags=['tarot'])])))
    d = post(admin, '/admin/marketing/generate', dict(source='topic', ref='新月许愿', platforms=['tiktok'])).json['drafts'][0]
    id = d['id'].split(':')[1]
    assert d['media'] == []
    assert post(admin, f'/admin/marketing/drafts/{id}/schedule', dict(when='now')).json['error'].endswith('请先添加图片或视频')
    assert upload(admin, id, b'not an image', 'x.png').status_code == 400
    assert upload(admin, id, PNG, 'x.gif').status_code == 400
    assert upload(admin, id, b'\xff\xd8\xff' + b'0' * (21 * 1024 * 1024), 'big.jpg').status_code == 413
    assert upload(client(), id, PNG, 'x.png').status_code in (401, 403)
    r = upload(admin, id, PNG, '%E6%9C%88%E4%BA%AE.png')
    assert r.status_code == 200, r.json
    item = r.json['draft']['media'][0]
    assert item['kind'] == 'image' and item['name'] == '月亮.png' and item['file'].startswith('media/mkt/')
    fn = item['file'].split('/')[-1]
    assert admin.get('/api/admin/marketing/media/' + fn).data == PNG
    assert client().get('/api/admin/marketing/media/' + fn).status_code == 401
    assert admin.get('/api/admin/marketing/media/../secret').status_code == 404
    mp4 = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 100
    v = upload(admin, id, mp4, 'clip.mp4').json['draft']['media']
    assert [x['kind'] for x in v] == ['image', 'video'] and upload(admin, id, mp4, 'b.mp4').status_code == 400
    # reorder/remove, then schedule
    r = post(admin, f'/admin/marketing/drafts/{id}', dict(media=[v[1]['id'], 'bogus']), 'PUT').json['draft']
    assert [x['id'] for x in r['media']] == [v[1]['id']]
    assert post(admin, f'/admin/marketing/drafts/{id}/schedule', dict(when='now')).status_code == 200
    # unreferenced uploads are cleaned up
    orphan = m.MEDIA_DIR / fn
    os.utime(orphan, (0, 0))
    m.purge_media()
    assert not orphan.exists() and (m.MEDIA_DIR / v[1]['file'].split('/')[-1]).exists()


def test_auto_queue_on_new_drafts(admin, monkeypatch):
    reset_queue()
    post(admin, '/admin/publish/xiaohongshu', dict(auto_queue=True, slots=['08:00', '21:00'], mode='manual'), 'PUT')
    monkeypatch.setattr(m, '_model_call', fake_model(POSTS))
    r = post(admin, '/admin/marketing/generate', dict(source='card', ref='the-star', platforms=['xiaohongshu', 'tiktok'])).json['drafts']
    jobs = admin.get('/api/admin/publish').json['jobs']
    assert [j['platform'] for j in jobs] == ['xiaohongshu'] and jobs[0]['source'] == 'auto:manual'
    local = datetime.fromisoformat(jobs[0]['run_at']).astimezone(m.ZoneInfo('Asia/Kuala_Lumpur'))
    assert (local.hour, local.minute) in [(h, mm) for h in (7, 8, 20, 21) for mm in range(60)]
    post(admin, '/admin/publish/xiaohongshu', dict(auto_queue=False, mode='auto'), 'PUT')


def test_publisher_proxy(admin, monkeypatch):
    assert post(admin, '/admin/publish/tiktok/login').status_code == 503             # worker not running in tests
    seen = []

    class R:
        status_code = 200
        content = b'\x89PNG'
        text = ''

        def json(self):
            return dict(status='waiting', qr='abc')

    def fake(method, url, headers, timeout):
        seen.append((method, url, headers['X-Publisher-Token']))
        return R()
    monkeypatch.setattr(m.httpx, 'request', fake)
    assert post(admin, '/admin/publish/tiktok/login').json == dict(status='waiting', qr='abc')
    assert admin.get('/api/admin/publish/tiktok/login').status_code == 200
    assert post(admin, '/admin/publish/channels/check').status_code == 200
    assert admin.get('/api/admin/publish/shot/pub_1-abc.png').data == b'\x89PNG'
    assert admin.get('/api/admin/publish/shot/..%2Fx.png').status_code == 404
    import publisher.db as pdb
    assert seen[0][:2] == ('POST', 'http://publisher:8200/login/tiktok') and seen[0][2] == pdb.token()
    assert [s[1].rsplit('/', 2)[-2:] for s in seen[1:]] == [['login', 'tiktok'], ['check', 'channels'], ['shot', 'pub_1-abc.png']]


# ---------------------------------------------------------------- worker decisions
class FakePage:
    url = 'https://example.test/'

    async def screenshot(self, path=None, **kw):
        open(path, 'wb').write(PNG)


class FakeCtx:
    def __init__(self):
        self.pages = [FakePage()]

    async def close(self):
        pass


@pytest.fixture
def worker(monkeypatch, tmp_path):
    import publisher.worker as w
    monkeypatch.setattr(w, 'SHOTS', tmp_path / 'shots')
    mails = []
    monkeypatch.setattr(w, 'mail', lambda s, t: mails.append((s, t)))

    async def ctx(platform):
        return FakeCtx()
    monkeypatch.setattr(w.B, 'context', ctx)
    w.mails = mails
    return w


def run(w, outcome):
    async def fake_publish(page, platform, payload, files, kind, dry_run=False):
        run.seen.append((platform, kind, [f.suffix for f in files], dry_run))
        if isinstance(outcome, Exception):
            raise outcome
        return dict(url=outcome)
    w.publish = fake_publish
    with m.engine.begin() as c:
        j = core.claim(c, m.jobs)
    assert j, 'nothing due'
    asyncio.run(w.run_job(j))
    with m.engine.begin() as c:
        return core.get_job(c, m.jobs, j['id'])


run.seen = []


def queue(admin, draft, **kw):
    return post(admin, f"/admin/marketing/drafts/{draft['id'].split(':')[1]}/schedule", dict(when='now', **kw)).json['job']


def set_account(p, **kw):
    with m.engine.begin() as c:
        m.put(c, 'publish:account:' + p, 'config', 'system', {**core.account(m.get, c, p), **kw})


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg missing')
def test_worker_posts_and_falls_back(drafts, admin, worker):
    w = worker
    # 1) not logged in yet -> manual with an email reminder
    queue(admin, drafts['xiaohongshu'])
    j = run(w, 'https://x')
    assert j['status'] == 'manual' and j['result']['reason'] == 'login' and '第一段' in w.mails[-1][1]
    post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='cancel'))
    # 2) logged in -> published, draft marked, pictures fitted to 3:4 JPEG
    set_account('xiaohongshu', status='ok')
    queue(admin, drafts['xiaohongshu'])
    j = run(w, 'https://creator.xiaohongshu.com/publish/success')
    assert j['status'] == 'published' and j['result']['via'] == 'auto' and j['result']['shot'].endswith('.png')
    assert run.seen[-1] == ('xiaohongshu', 'images', ['.jpg'], False)
    with m.engine.begin() as c:
        assert m.get(c, drafts['xiaohongshu']['id'])['posted_via'] == 'auto:xiaohongshu'
    # 3) pacing: a second post right away is pushed back, not posted
    post(admin, f"/admin/marketing/drafts/{drafts['xiaohongshu']['id'].split(':')[1]}", dict(status='draft'), 'PUT')
    queue(admin, drafts['xiaohongshu'])
    j = run(w, 'https://x')
    assert j['status'] == 'scheduled' and j['run_at'] > core.iso(core.utcnow() + timedelta(minutes=80))
    post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='cancel'))
    # 4) TikTok: the card picture becomes a vertical video; login expiry pauses and emails
    set_account('tiktok', status='ok')
    queue(admin, drafts['tiktok'])
    j = run(w, w.NeedLogin('expired'))
    assert run.seen[-1][:3] == ('tiktok', 'video', ['.mp4']) and j['status'] == 'manual' and j['result']['reason'] == 'login'
    assert admin.get('/api/admin/publish').json['platforms']['tiktok']['account']['status'] == 'expired'
    assert any('登录已失效' in s for s, _ in w.mails)
    # 5) risk control -> cooldown; later jobs go straight to manual without opening the browser
    set_account('channels', status='ok')
    queue(admin, drafts['channels'])
    j = run(w, w.RiskControl('安全验证'))
    acc = admin.get('/api/admin/publish').json['platforms']['channels']['account']
    assert j['status'] == 'manual' and acc['status'] == 'risk' and acc['paused_until'] > core.iso(core.utcnow() + timedelta(hours=23))
    post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='retry'))
    n = len(run.seen)
    j = run(w, 'https://x')
    assert j['status'] == 'manual' and j['result']['reason'] == 'risk' and len(run.seen) == n
    # 6) other errors retry with back-off, then fall back to manual
    set_account('channels', status='ok', paused_until='')
    post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='cancel'))
    queue(admin, drafts['channels'])
    for attempt in range(1, core.MAX_ATTEMPTS + 1):
        j = run(w, w.PublishError('page element not found: publish button', 'selector:publish button'))
        if attempt < core.MAX_ATTEMPTS:
            assert j['status'] == 'scheduled' and j['result']['code'] == 'selector:publish button'
            with m.engine.begin() as c:
                c.execute(m.update(m.jobs).where(m.jobs.c.id == j['id']).values(run_at=core.iso(core.utcnow())))
    assert j['status'] == 'manual' and j['result']['reason'] == 'error' and j['attempts'] == core.MAX_ATTEMPTS
    # 7) dry run: fills everything, never clicks publish, ends as "tested" with a screenshot
    post(admin, f"/admin/publish/jobs/{j['id']}", dict(action='cancel'))
    t = queue(admin, drafts['channels'], dry_run=True)
    j = run(w, 'https://x')
    assert j['id'] == t['id'] and j['status'] == 'tested' and run.seen[-1][3] is True and j['result']['shot']


@pytest.mark.skipif(not shutil.which('ffprobe'), reason='ffprobe missing')
def test_media_formats(tmp_path):
    from publisher import media
    img = [{'file': m.card_media('the-sun')[0]['file']}, {'file': m.card_media('the-moon')[0]['file']}]
    kind, files, tmp = media.prepare('tiktok', img, 'video')
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(files[0])], capture_output=True, text=True).stdout)
    v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert kind == 'video' and (v['width'], v['height']) == (1080, 1920) and any(s['codec_type'] == 'audio' for s in probe['streams'])
    assert 6.5 < float(v.get('duration', 7)) < 7.5
    kind, files, _ = media.prepare('xiaohongshu', img, 'images_or_video')
    assert kind == 'images' and len(files) == 2
    with pytest.raises(media.MediaError):
        media.prepare('tiktok', [{'file': '../../etc/passwd'}], 'video')
    with pytest.raises(media.MediaError):
        media.prepare('tiktok', [], 'video')


def test_console_assets():
    root = os.path.dirname(os.path.dirname(__file__))
    js = open(os.path.join(root, 'static/app.js')).read()
    part = js.split('// ================= v0.8.1 scheduled posting')[1]
    for needle in ('function pubBlock(', 'async function pubAction(', 'function jobCard(', 'async function uploadMedia(', "api('/admin/publish')", '${pubBlock(d)}', '<div id="pub-area">'):
        assert needle in js, needle
    assert 'style="' not in part and 'innerHTML=r.' not in part
    compose = open(os.path.join(root, 'compose.yaml')).read()
    assert 'publisher:' in compose and 'app_data:/data:ro' in compose and 'PUBLISHER_URL: http://publisher:8200' in compose
    assert '8200:' not in compose            # the worker API is never exposed on the host


def test_case_drafts_carry_card_pictures(admin, monkeypatch):
    from test_v072 import published, member
    slug, _ = published(admin, member('pub_case_pics'))
    monkeypatch.setattr(m, '_model_call', fake_model(dict(posts=[dict(platform='xiaohongshu', title='案例', text='正文', hashtags=['塔罗'])])))
    d = post(admin, '/admin/marketing/generate', dict(source='case', ref=slug, platforms=['xiaohongshu'])).json['drafts'][0]
    assert len(d['media']) == 3 and all(x['file'].startswith('static/tarot/cards/') and x['file'].endswith('.webp') for x in d['media'])
