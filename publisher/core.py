"""Shared scheduling core for automatic posting (v0.8.1).

Imported by both the web app (to queue jobs and show status) and the publisher
worker (to claim and run jobs). It must stay light: no Playwright here.

Jobs live in their own SQL table so a job can be claimed atomically
(UPDATE ... WHERE status='scheduled'), which the JSON `records` table cannot do.
"""
import json, re, secrets, random
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import Table, Column, String, Text, Integer, select, insert, update, and_

# Platforms that can be posted automatically. `needs` = what the platform accepts:
# a video, or images/video. Images for a video platform are turned into a short
# slideshow video by the worker.
PLATFORMS = {
    'xiaohongshu': dict(zh='小红书', en='Xiaohongshu', needs='images_or_video', title_max=20, text_max=1000, max_images=18),
    'channels': dict(zh='微信视频号', en='WeChat Channels', needs='video', title_max=16, text_max=1000, max_images=9),
    'tiktok': dict(zh='TikTok', en='TikTok', needs='video', title_max=0, text_max=2200, max_images=9),
}
MODES = ('auto', 'manual', 'off')
DEFAULTS = dict(mode='auto', auto_queue=False, slots=['20:30'], min_gap=90, daily_cap=2)
STATUSES = ('scheduled', 'running', 'published', 'manual', 'failed', 'cancelled', 'tested')
OPEN = ('scheduled', 'running', 'manual')      # still needs something to happen
MAX_ATTEMPTS = 3


def table(meta):
    if 'publish_jobs' in meta.tables:
        return meta.tables['publish_jobs']
    return Table('publish_jobs', meta,
                 Column('id', String(40), primary_key=True),
                 Column('platform', String(20), index=True, nullable=False),
                 Column('status', String(20), index=True, nullable=False),
                 Column('run_at', String(40), index=True, nullable=False),
                 Column('draft', String(40), index=True, default=''),
                 Column('attempts', Integer, default=0),
                 Column('lease', String(40), default=''),
                 Column('payload', Text, nullable=False),
                 Column('result', Text, default='{}'),
                 Column('created', String(40)),
                 Column('updated', String(40)))


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse(v):
    d = datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def config(get, c):
    """Per-platform settings, merged with defaults. `get` is the records getter."""
    saved = get(c, 'publish:config') or {}
    return {p: {**DEFAULTS, **(saved.get(p) or {})} for p in PLATFORMS}


def clean_config(cur, d):
    """Validate a settings update for one platform; returns the new dict."""
    out = dict(cur)
    if 'mode' in d:
        if d['mode'] not in MODES:
            raise ValueError('mode')
        out['mode'] = d['mode']
    if 'auto_queue' in d:
        out['auto_queue'] = bool(d['auto_queue'])
    if 'slots' in d:
        slots = d['slots'] if isinstance(d['slots'], list) else str(d['slots']).replace('，', ',').split(',')
        slots = sorted({s.strip() for s in slots if str(s).strip()})
        if not slots or len(slots) > 8 or not all(re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', s) for s in slots):
            raise ValueError('slots')
        out['slots'] = slots
    for k, lo, hi in (('min_gap', 10, 1440), ('daily_cap', 1, 10)):
        if k in d:
            v = int(d[k])
            if not lo <= v <= hi:
                raise ValueError(k)
            out[k] = v
    return out


def account(get, c, platform):
    return {**dict(status='unknown', checked='', note='', paused_until=''), **(get(c, 'publish:account:' + platform) or {})}


def compose(platform, draft):
    """Turn a marketing draft into what gets typed into the platform."""
    meta = PLATFORMS[platform]
    tags = [re.sub(r'[\s#]+', '', t)[:30] for t in draft.get('hashtags') or []]
    tags = [t for t in tags if t][:10 if platform == 'xiaohongshu' else 8]
    title = (draft.get('title') or '').strip()
    text = (draft.get('text') or '').strip()
    if meta['title_max']:
        title = title[:meta['title_max']]
    else:
        # TikTok has no title field: lead with the headline if the body does not already.
        if title and not text.startswith(title):
            text = title + '\n\n' + text
        title = ''
    budget = meta['text_max'] - sum(len(t) + 2 for t in tags) - 2
    return dict(title=title, text=text[:max(budget, 100)], hashtags=tags)


def snapshot(platform, draft):
    return dict(**compose(platform, draft), media=list(draft.get('media') or []), link=draft.get('link', ''),
                draft_title=draft.get('title', ''), draft_text=draft.get('text', ''), draft_tags=draft.get('hashtags') or [])


def new_job(c, jobs, platform, draft, run_at, dry_run=False, source='manual'):
    if platform not in PLATFORMS:
        raise ValueError('platform')
    id = 'pub_' + secrets.token_hex(8)
    t = iso(utcnow())
    payload = dict(snapshot(platform, draft), dry_run=bool(dry_run), source=source)
    c.execute(insert(jobs).values(id=id, platform=platform, status='scheduled', run_at=iso(run_at), draft=draft.get('id', ''),
                                  attempts=0, lease='', payload=json.dumps(payload, ensure_ascii=False),
                                  result=json.dumps(dict(log=[[t, 'scheduled']]), ensure_ascii=False), created=t, updated=t))
    return id


def row(r):
    if r is None:
        return None
    x = dict(r._mapping)
    x['payload'] = json.loads(x['payload'] or '{}')
    x['result'] = json.loads(x['result'] or '{}')
    return x


def get_job(c, jobs, id):
    return row(c.execute(select(jobs).where(jobs.c.id == id)).first())


def list_jobs(c, jobs, limit=100, draft=None, statuses=None):
    q = select(jobs)
    if draft:
        q = q.where(jobs.c.draft == draft)
    if statuses:
        q = q.where(jobs.c.status.in_(statuses))
    q = q.order_by(jobs.c.run_at.desc()).limit(limit)
    return [row(r) for r in c.execute(q)]


def set_state(c, jobs, id, status, note='', expect=None, **fields):
    """Move a job to `status`, append to its log; `expect` guards the transition."""
    j = get_job(c, jobs, id)
    if not j or (expect and j['status'] not in expect):
        return None
    res = j['result']
    for k in ('url', 'error', 'code', 'shot', 'via', 'reason'):
        if k in fields:
            res[k] = fields.pop(k)
    res.setdefault('log', []).append([iso(utcnow()), status + (': ' + note if note else '')])
    res['log'] = res['log'][-30:]
    vals = dict(status=status, result=json.dumps(res, ensure_ascii=False), updated=iso(utcnow()))
    if 'run_at' in fields:
        vals['run_at'] = iso(fields.pop('run_at'))
    if 'lease' in fields:
        vals['lease'] = fields.pop('lease')
    if 'payload' in fields:
        vals['payload'] = json.dumps(fields.pop('payload'), ensure_ascii=False)
    q = update(jobs).where(jobs.c.id == id)
    if expect:
        q = q.where(jobs.c.status.in_(expect))
    if c.execute(q.values(**vals)).rowcount != 1:
        return None
    return get_job(c, jobs, id)


def claim(c, jobs, worker='worker', lease_minutes=20):
    """Atomically take the oldest due job. Returns the job or None."""
    now = utcnow()
    # A worker that died mid-job leaves an expired lease: put it back in the queue.
    for r in c.execute(select(jobs.c.id).where(and_(jobs.c.status == 'running', jobs.c.lease < iso(now), jobs.c.lease != ''))).all():
        set_state(c, jobs, r[0], 'scheduled', 'lease expired, will retry', expect=('running',), lease='')
    for r in c.execute(select(jobs.c.id).where(and_(jobs.c.status == 'scheduled', jobs.c.run_at <= iso(now))).order_by(jobs.c.run_at).limit(5)).all():
        vals = dict(status='running', lease=iso(now + timedelta(minutes=lease_minutes)), updated=iso(now), attempts=jobs.c.attempts + 1)
        if c.execute(update(jobs).where(and_(jobs.c.id == r[0], jobs.c.status == 'scheduled')).values(**vals)).rowcount == 1:
            j = get_job(c, jobs, r[0])
            j['result'].setdefault('log', []).append([iso(now), f'running (attempt {j["attempts"]}) on {worker}'])
            c.execute(update(jobs).where(jobs.c.id == j['id']).values(result=json.dumps(j['result'], ensure_ascii=False)))
            return j
    return None


def recent_published(c, jobs, platform, since):
    q = select(jobs.c.updated).where(and_(jobs.c.platform == platform, jobs.c.status == 'published', jobs.c.updated >= iso(since)))
    return sorted(parse(r[0]) for r in c.execute(q))


def pacing(c, jobs, platform, cfg, now=None):
    """None if the platform may post now, otherwise the earliest allowed time.

    Keeps a minimum gap between posts and a rolling 24h cap, so a backlog never
    turns into a burst (bursts are what platforms flag as bot behaviour)."""
    now = now or utcnow()
    done = recent_published(c, jobs, platform, now - timedelta(hours=24))
    later = []
    if done and now - done[-1] < timedelta(minutes=cfg['min_gap']):
        later.append(done[-1] + timedelta(minutes=cfg['min_gap']))
    if len(done) >= cfg['daily_cap']:
        later.append(done[len(done) - cfg['daily_cap']] + timedelta(hours=24))
    if not later:
        return None
    return max(later) + timedelta(seconds=random.randint(60, 600))


def next_slot(c, jobs, platform, cfg, tz, now=None, horizon_days=14):
    """Next posting slot (studio time zone) that has no job yet, as a UTC datetime."""
    now = now or utcnow()
    zone = ZoneInfo(tz)
    taken = set()
    for r in c.execute(select(jobs.c.run_at).where(and_(jobs.c.platform == platform, jobs.c.status.in_(('scheduled', 'running', 'manual', 'published')), jobs.c.run_at >= iso(now - timedelta(days=1))))).all():
        taken.add(parse(r[0]).astimezone(zone).strftime('%Y-%m-%d %H'))
    local = now.astimezone(zone)
    per_day = {}
    for key in taken:
        per_day[key[:10]] = per_day.get(key[:10], 0) + 1
    for d in range(horizon_days):
        day = (local + timedelta(days=d)).date()
        if per_day.get(day.isoformat(), 0) >= cfg['daily_cap']:
            continue
        for s in cfg['slots']:
            h, m = map(int, s.split(':'))
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
            if at <= local + timedelta(minutes=5) or at.strftime('%Y-%m-%d %H') in taken:
                continue
            # Small random offset so posts do not land on the exact same minute every day.
            return (at + timedelta(minutes=random.randint(-6, 6))).astimezone(timezone.utc)
    return None


def kit_text(job):
    """Everything to paste when posting by hand."""
    p = job['payload']
    tags = ' '.join('#' + t for t in p.get('hashtags') or [])
    return '\n\n'.join(x for x in (p.get('title'), p.get('text'), tags) if x)
