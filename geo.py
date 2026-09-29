"""Visitor attributes for first-party analytics (v0.8).

Everything here is derived from what a browser tells every website anyway
(time zone, language, referrer, UTM tags, User-Agent). No IP address is
looked up or stored; the region is inferred from the browser time zone.
"""
import json, re
from pathlib import Path
from urllib.parse import urlparse

_GEO = json.loads((Path(__file__).parent / 'content' / 'geo.json').read_text())
TZ_COUNTRY = _GEO['tz']            # IANA zone -> ISO country code
COUNTRY_NAMES = _GEO['names']      # ISO code -> [zh, en]

def country_of(tz):
    return TZ_COUNTRY.get(tz or '', '')

def country_name(cc, lang='zh'):
    n = COUNTRY_NAMES.get(cc)
    if not n:
        return '未知' if lang == 'zh' else 'Unknown'
    return n[0] if lang == 'zh' else n[1]

# ---------- traffic source ----------
# (host suffix, channel, group). Groups: search / social / messaging / referral / direct / campaign
REFERRERS = [
    ('mail.google.com', 'email', 'messaging'), ('gemini.google.com', 'ai_assistant', 'referral'),
    ('google.', 'google', 'search'), ('bing.com', 'bing', 'search'), ('baidu.com', 'baidu', 'search'),
    ('duckduckgo.com', 'duckduckgo', 'search'), ('yandex.', 'yandex', 'search'), ('sogou.com', 'sogou', 'search'),
    ('so.com', '360', 'search'), ('sm.cn', 'shenma', 'search'), ('naver.com', 'naver', 'search'),
    ('yahoo.', 'yahoo', 'search'), ('ecosia.org', 'ecosia', 'search'),
    ('xiaohongshu.com', 'xiaohongshu', 'social'), ('xhslink.com', 'xiaohongshu', 'social'),
    ('instagram.com', 'instagram', 'social'), ('facebook.com', 'facebook', 'social'), ('fb.com', 'facebook', 'social'),
    ('fb.me', 'facebook', 'social'), ('t.co', 'x', 'social'), ('twitter.com', 'x', 'social'), ('x.com', 'x', 'social'),
    ('threads.net', 'threads', 'social'), ('threads.com', 'threads', 'social'), ('weibo.com', 'weibo', 'social'),
    ('weibo.cn', 'weibo', 'social'), ('youtube.com', 'youtube', 'social'), ('youtu.be', 'youtube', 'social'),
    ('tiktok.com', 'tiktok', 'social'), ('douyin.com', 'douyin', 'social'), ('linkedin.com', 'linkedin', 'social'),
    ('lnkd.in', 'linkedin', 'social'), ('reddit.com', 'reddit', 'social'), ('pinterest.', 'pinterest', 'social'),
    ('zhihu.com', 'zhihu', 'social'), ('douban.com', 'douban', 'social'), ('bilibili.com', 'bilibili', 'social'),
    ('t.me', 'telegram', 'messaging'), ('telegram.', 'telegram', 'messaging'), ('whatsapp.com', 'whatsapp', 'messaging'),
    ('wa.me', 'whatsapp', 'messaging'), ('weixin.qq.com', 'wechat', 'messaging'), ('wechat.com', 'wechat', 'messaging'),
    ('line.me', 'line', 'messaging'), ('discord.com', 'discord', 'messaging'),
    ('outlook.', 'email', 'messaging'), ('mail.', 'email', 'messaging'),
    ('chatgpt.com', 'ai_assistant', 'referral'), ('perplexity.ai', 'ai_assistant', 'referral'), ('claude.ai', 'ai_assistant', 'referral'),
]
# In-app browsers usually send no referrer; their User-Agent still tells us where the click came from.
IN_APP = [
    (r'MicroMessenger', 'wechat', 'messaging'), (r'xhsdiscover|XiaoHongShu', 'xiaohongshu', 'social'),
    (r'Instagram', 'instagram', 'social'), (r'FBAN|FBAV|FB_IAB', 'facebook', 'social'), (r'\bLine/', 'line', 'messaging'),
    (r'musical_ly|BytedanceWebview|TikTok', 'tiktok', 'social'), (r'aweme', 'douyin', 'social'),
    (r'Weibo', 'weibo', 'social'), (r'Telegram', 'telegram', 'messaging'), (r'WhatsApp', 'whatsapp', 'messaging'),
    (r'LinkedInApp', 'linkedin', 'social'), (r'Threads', 'threads', 'social'),
]
CHANNEL_NAMES = {
    'direct': ('直接访问', 'Direct'), 'google': ('Google 搜索', 'Google'), 'bing': ('Bing 搜索', 'Bing'),
    'baidu': ('百度', 'Baidu'), 'duckduckgo': ('DuckDuckGo', 'DuckDuckGo'), 'yandex': ('Yandex', 'Yandex'),
    'sogou': ('搜狗', 'Sogou'), '360': ('360 搜索', '360 Search'), 'shenma': ('神马搜索', 'Shenma'), 'naver': ('Naver', 'Naver'),
    'yahoo': ('Yahoo', 'Yahoo'), 'ecosia': ('Ecosia', 'Ecosia'),
    'xiaohongshu': ('小红书', 'Xiaohongshu'), 'instagram': ('Instagram', 'Instagram'), 'facebook': ('Facebook', 'Facebook'),
    'x': ('X / Twitter', 'X / Twitter'), 'threads': ('Threads', 'Threads'), 'weibo': ('微博', 'Weibo'), 'youtube': ('YouTube', 'YouTube'),
    'tiktok': ('TikTok', 'TikTok'), 'douyin': ('抖音', 'Douyin'), 'linkedin': ('LinkedIn', 'LinkedIn'), 'reddit': ('Reddit', 'Reddit'),
    'pinterest': ('Pinterest', 'Pinterest'), 'zhihu': ('知乎', 'Zhihu'), 'douban': ('豆瓣', 'Douban'), 'bilibili': ('哔哩哔哩', 'Bilibili'),
    'telegram': ('Telegram', 'Telegram'), 'whatsapp': ('WhatsApp', 'WhatsApp'), 'wechat': ('微信', 'WeChat'), 'line': ('LINE', 'LINE'),
    'discord': ('Discord', 'Discord'), 'email': ('邮件', 'Email'), 'ai_assistant': ('AI 助手', 'AI assistants'), 'referral': ('其他网站', 'Other sites'),
}
GROUP_NAMES = {'search': ('搜索引擎', 'Search'), 'social': ('社交媒体', 'Social'), 'messaging': ('聊天/邮件', 'Messaging'),
               'referral': ('外部链接', 'Referral'), 'direct': ('直接访问', 'Direct'), 'campaign': ('推广链接', 'Campaign')}
UTM_ALIAS = {'xhs': 'xiaohongshu', 'redbook': 'xiaohongshu', 'rednote': 'xiaohongshu', 'ig': 'instagram', 'fb': 'facebook',
             'twitter': 'x', 'tg': 'telegram', 'wa': 'whatsapp', 'weixin': 'wechat', 'wx': 'wechat', 'yt': 'youtube'}

def clean_token(v, n=40):
    v = re.sub(r'[^a-z0-9_.\-]', '', str(v or '').strip().lower().replace(' ', '_'))
    return v[:n]

def host_of(url):
    try:
        h = (urlparse(str(url or '')).hostname or '').lower()
    except ValueError:
        return ''
    return h[4:] if h.startswith('www.') else h

def _match(host, pattern):
    # 'google.' matches any google.<tld> (and subdomains); 'x.com' matches x.com and *.x.com.
    if pattern.endswith('.'):
        return host.startswith(pattern) or ('.' + pattern) in host
    return host == pattern or host.endswith('.' + pattern)

def classify(ref='', utm_source='', utm_medium='', ua='', own_hosts=()):
    """Return (channel, group, referrer_host)."""
    src = UTM_ALIAS.get(clean_token(utm_source), clean_token(utm_source))
    host = host_of(ref)
    if host and (host in own_hosts or 'www.' + host in own_hosts):
        host = ''  # internal navigation is not a source
    if src:
        group = next((g for _, ch, g in REFERRERS if ch == src), 'campaign')
        if clean_token(utm_medium) in ('email', 'newsletter'):
            group = 'messaging'
        return src, group, host
    if host:
        for suffix, ch, g in REFERRERS:
            if _match(host, suffix):
                return ch, g, host
        return 'referral', 'referral', host
    for pat, ch, g in IN_APP:
        if re.search(pat, ua or ''):
            return ch, g, ''
    return 'direct', 'direct', ''

# ---------- device ----------
BOT_RE = re.compile(r'bot\b|bot/|spider|crawl|slurp|headlesschrome|lighthouse|facebookexternalhit|preview|monitor|curl|wget|python-requests|httpx|scrapy', re.I)

def is_bot(ua):
    return bool(BOT_RE.search(ua or ''))

def device_of(ua):
    ua = ua or ''
    if re.search(r'iPad|Tablet|PlayBook|Silk|(Android(?!.*Mobile))', ua):
        return 'tablet'
    if re.search(r'Mobi|iPhone|iPod|Android|Windows Phone', ua):
        return 'mobile'
    return 'desktop'

def os_of(ua):
    ua = ua or ''
    for pat, name in ((r'iPhone|iPad|iPod', 'iOS'), (r'Android', 'Android'), (r'Windows', 'Windows'),
                      (r'Mac OS X|Macintosh', 'macOS'), (r'CrOS', 'ChromeOS'), (r'Linux', 'Linux')):
        if re.search(pat, ua):
            return name
    return 'Other'

def clean_lang(v):
    m = re.match(r'^([a-zA-Z]{2,3})(?:[-_]([a-zA-Z]{4}|[a-zA-Z]{2})(?![a-zA-Z]))?', str(v or ''))
    if not m:
        return ''
    sub = m.group(2) or ''
    sub = sub.upper() if len(sub) == 2 else sub.title()
    return m.group(1).lower() + ('-' + sub if sub else '')

def clean_tz(v):
    v = str(v or '')[:60]
    return v if re.fullmatch(r'[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}', v) else ''
