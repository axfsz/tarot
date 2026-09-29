"""Drives the real Chromium through each platform adapter against local stand-ins of
the creator pages (same element structure as selectors.json expects).

This proves the adapter logic (upload, typing, waiting, confirm dialogs, success and
failure detection); it cannot prove the live sites still match selectors.json, which
is what the console's "试运行" (dry run) is for.
"""
import os, sys, json, asyncio, shutil
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
pw = pytest.importorskip('playwright.async_api')
from publisher import automation as A

CAPTURE = "fetch('/__capture',{method:'POST',body:JSON.stringify(%s)})"
XHS = """<html><body><div class="creator-tab">上传视频</div><div class="creator-tab">上传图文</div>
<input class="upload-input" type="file" multiple style="display:none">
<div id="ed" hidden><input placeholder="填写标题会有更多赞哦"><div class="tiptap ProseMirror" contenteditable="true"></div>
<ul id="sug"></ul><button class="publishBtn">发布</button></div>
<script>
const inp=document.querySelector('input[type=file]'),ed=document.getElementById('ed'),body=document.querySelector('.tiptap');
let tab='';document.querySelectorAll('.creator-tab').forEach(t=>t.onclick=()=>tab=t.textContent);
inp.onchange=()=>setTimeout(()=>ed.hidden=false,800);
body.addEventListener('input',()=>{const m=body.innerText.match(/#(\\S+)$/);document.getElementById('sug').innerHTML=m?'<li>'+m[1]+'</li>':''});
document.querySelector('.publishBtn').onclick=async()=>{await %s;location.href='/publish/success?id=1'};
</script></body></html>""" % (CAPTURE % "{tab,files:[...inp.files].map(f=>f.name),title:document.querySelector('input[placeholder]').value,body:body.innerText}")
CHANNELS = """<html><body><div class="post-create"><input type="file" accept="video/*" style="display:none">
<div class="input-editor" contenteditable=""></div><input class="weui-input" placeholder="概括视频主要内容，字数建议6-16个字符">
<div class="form-btns"><button class="weui-desktop-btn weui-desktop-btn_disabled">发表</button></div></div>
<script>
const inp=document.querySelector('input[type=file]'),btn=document.querySelector('.form-btns button');
inp.onchange=()=>setTimeout(()=>btn.classList.remove('weui-desktop-btn_disabled'),2500);
btn.onclick=async()=>{if(btn.classList.contains('weui-desktop-btn_disabled'))return;await %s;location.href='/platform/post/list'};
</script></body></html>""" % (CAPTURE % "{files:[...inp.files].map(f=>f.name),short:document.querySelector('.weui-input').value,body:document.querySelector('.input-editor').innerText}")
TIKTOK = """<html><body><input type="file" accept="video/*" style="display:none"><div id="ed" hidden>
<div class="public-DraftEditor-content" contenteditable="true">my-video.mp4</div>
<button data-e2e="post_video_button" aria-disabled="true">Post</button></div><div id="dlg"></div>
<script>
const inp=document.querySelector('input[type=file]'),btn=document.querySelector('button'),cap=document.querySelector('.public-DraftEditor-content');
inp.onchange=()=>{document.getElementById('ed').hidden=false;setTimeout(()=>btn.setAttribute('aria-disabled','false'),2000)};
btn.onclick=()=>{if(btn.getAttribute('aria-disabled')==='true')return;document.getElementById('dlg').innerHTML='<div role="dialog"><button id="go">Post now</button></div>';
 document.getElementById('go').onclick=async()=>{await %s;location.href='/tiktokstudio/content'}};
</script></body></html>""" % (CAPTURE % "{files:[...inp.files].map(f=>f.name),caption:cap.innerText}")
LOGIN = """<html><body><div class="login-box-container"><img class="css-wemwzq" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="20" height="20" onclick="document.getElementById('qr').hidden=false">
<div id="qr" hidden class="qrcode"><img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><rect width='160' height='160' fill='black'/></svg>" width="160" height="160"></div></div>
<script>setTimeout(()=>{document.cookie='web_session=abc; path=/';location.href='/new/home'},9000)</script></body></html>"""


async def browser_with(pages, captured):
    p = await pw.async_playwright().start()
    b = await p.chromium.launch(headless=True)
    ctx = await b.new_context()

    async def handler(route):
        url = route.request.url
        if url.endswith('/__capture'):
            captured.append(json.loads(route.request.post_data))
            return await route.fulfill(status=204)
        for key, html in pages.items():
            if key in url:
                return await route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
        await route.fulfill(status=200, content_type='text/html', body='<html><body>ok</body></html>')
    await ctx.route('**/*', handler)
    return p, b, ctx


def media(tmp_path, names):
    out = []
    for n in names:
        f = tmp_path / n
        f.write_bytes(b'0' * 64)
        out.append(f)
    return out


def go(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    async def quick(lo=0, hi=0):
        await asyncio.sleep(0.01)
    monkeypatch.setattr(A, 'pause', quick)


PAYLOAD = dict(title='愚者：给自己一次重新出发', text='第一行\n第二行', hashtags=['塔罗', '每日一牌'])


async def post_on(platform, pages, files, kind, dry=False, payload=PAYLOAD):
    cap = []
    p, b, ctx = await browser_with(pages, cap)
    try:
        page = await ctx.new_page()
        res = await A.publish(page, platform, payload, files, kind, dry)
        return res, cap, page
    finally:
        await b.close()
        await p.stop()


def test_xiaohongshu_image_note(tmp_path):
    res, cap, _ = go(post_on('xiaohongshu', {'/publish/publish': XHS}, media(tmp_path, ['00.jpg', '01.jpg']), 'images'))
    assert '/publish/success' in res['url']
    c = cap[0]
    assert c['tab'] == '上传图文' and c['files'] == ['00.jpg', '01.jpg'] and c['title'] == PAYLOAD['title']
    assert '第一行' in c['body'] and '第二行' in c['body'] and '#塔罗' in c['body'] and '#每日一牌' in c['body']


def test_xiaohongshu_dry_run_never_clicks(tmp_path):
    res, cap, _ = go(post_on('xiaohongshu', {'/publish/publish': XHS}, media(tmp_path, ['00.jpg']), 'images', dry=True))
    assert res['dry_run'] and cap == []


def test_channels_waits_for_upload_then_posts(tmp_path):
    res, cap, _ = go(post_on('channels', {'/platform/post/create': CHANNELS}, media(tmp_path, ['slideshow.mp4']), 'video'))
    c = cap[0]
    assert res['url'].endswith('/platform/post/list') and c['files'] == ['slideshow.mp4']
    assert c['short'] == '愚者给自己一次重新出发' and '#塔罗' in c['body'] and '第二行' in c['body']


def test_tiktok_replaces_filename_caption_and_confirms(tmp_path):
    res, cap, _ = go(post_on('tiktok', {'/tiktokstudio/upload': TIKTOK}, media(tmp_path, ['v.mp4']), 'video',
                             payload=dict(title='', text='The Fool\n\nNew starts are allowed.', hashtags=['tarot'])))
    c = cap[0]
    assert res['url'].endswith('/tiktokstudio/content') and 'my-video.mp4' not in c['caption']
    assert 'New starts are allowed.' in c['caption'] and '#tarot' in c['caption']


def test_login_expired_and_risk_are_classified(tmp_path):
    redirect = '<script>location.href="https://creator.xiaohongshu.com/login?redirectReason=401"</script>'
    with pytest.raises(A.NeedLogin):
        go(post_on('xiaohongshu', {'/publish/publish': redirect, '/login': '<html>login</html>'}, media(tmp_path, ['a.jpg']), 'images'))
    with pytest.raises(A.RiskControl):
        go(post_on('channels', {'/platform/post/create': '<html><body>请完成安全验证后继续</body></html>'}, media(tmp_path, ['a.mp4']), 'video'))
    A.MISSING_TIMEOUT = 3
    broken = CHANNELS.replace('form-btns', 'something-else').replace('>发表<', '>提交<')
    with pytest.raises(A.PublishError) as e:
        go(post_on('channels', {'/platform/post/create': broken}, media(tmp_path, ['a.mp4']), 'video'))
    assert e.value.code == 'selector:publish button'
    A.MISSING_TIMEOUT = 60


def test_qr_login_flow():
    async def flow():
        cap = []
        p, b, ctx = await browser_with({'/login': LOGIN, '/new/home': '<html>home</html>'}, cap)
        try:
            page = await ctx.new_page()
            S = A.selectors()['xiaohongshu']
            png = await A.open_login(page, S)
            assert png[:4] == b'\x89PNG'
            assert not await A.login_done(ctx, page, S)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await A.login_done(ctx, page, S):
                    return True
            return False
        finally:
            await b.close()
            await p.stop()
    assert go(flow())
