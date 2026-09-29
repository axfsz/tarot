import os,sys,tempfile,json
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import geo
import pytest
from test_v072 import client,post,member,published,admin  # noqa: F401  (admin is a fixture)

PHONE='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'

# ---------- visitor attributes ----------
def test_geo_helpers():
 assert geo.classify('https://www.google.com.my/search?q=tarot')[:2]==('google','search')
 assert geo.classify('https://mail.google.com/mail/u/0')[:2]==('email','messaging')
 assert geo.classify('https://honeytime.life/ai',own_hosts={'honeytime.life'})[:2]==('direct','direct')
 assert geo.classify('','','',PHONE+' MicroMessenger/8.0.40')[:2]==('wechat','messaging')
 assert geo.classify('https://example.org/post')==('referral','referral','example.org')
 assert geo.classify('https://t.co/x','xhs')[:2]==('xiaohongshu','social')      # UTM wins over referrer
 assert geo.classify('','oct_newsletter','email')[:2]==('oct_newsletter','messaging')
 assert geo.country_of('Asia/Kuala_Lumpur')=='MY' and geo.country_of('Asia/Shanghai')=='CN' and geo.country_of('UTC')==''
 assert geo.country_name('HK')=='中国香港' and geo.country_name('MY','en')=='Malaysia'
 assert geo.device_of(PHONE)=='mobile' and geo.device_of('Mozilla/5.0 (iPad; CPU OS 17_0)')=='tablet' and geo.device_of('Mozilla/5.0 (Windows NT 10.0)')=='desktop'
 assert geo.is_bot('Mozilla/5.0 (compatible; Googlebot/2.1)') and not geo.is_bot(PHONE) and not geo.is_bot('pytest')
 assert geo.clean_tz('Asia/Kuala_Lumpur')=='Asia/Kuala_Lumpur' and geo.clean_tz('<script>')=='' and geo.clean_lang('zh-cn')=='zh-CN'

def view(c,**extra):
 return post(c,'/events',dict(name='page_view',page='home',**extra))

def test_audience_breakdown_and_channel_conversion(admin,monkeypatch):
 monkeypatch.setattr(m,'stats_day',lambda c=None,s=None:'2031-03-01')
 a=client('203.0.113.70',PHONE)
 assert view(a,tz='Asia/Kuala_Lumpur',lang='zh-CN',ref='https://www.google.com/',utm={},path='/').json==dict(ok=True)
 view(a,tz='Asia/Kuala_Lumpur',ref='https://x.com/',path='/ai')          # same visitor, same day: attributes kept from first view
 assert post(a,'/readings',dict(question='下个月的工作重点在哪里',period='一个月',spread='three',mode='ai',lang='zh')).status_code==200
 b=client('203.0.113.71','Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
 view(b,tz='America/New_York',lang='en-US',ref='',utm=dict(source='ig',medium='social',campaign='Oct Full Moon'),path='/learn/the-fool')
 assert post(b,'/register',dict(username='channel_b',password='eight888')).status_code==200
 bot=client('203.0.113.72','Mozilla/5.0 (compatible; bingbot/2.0)')
 assert view(bot,tz='Asia/Tokyo').json['skipped']=='bot'
 bad=client('203.0.113.73','Mozilla/5.0')
 view(bad,tz='../../etc',lang='<b>',ref='javascript:alert(1)',utm='nope',path='/<x>')
 monkeypatch.setattr(m,'_intarg',lambda name,default,lo,hi:{'days':3,'range':1}[name])
 r=admin.get('/api/admin/stats').json
 assert r['range']==1 and len(r['days'])==3 and r['days'][0]['day']=='2031-03-01'
 day=r['days'][0];assert day['visitors']==3 and day['events']['page_view']==4   # bot not counted
 aud=r['audience'];tot=aud['total']
 assert tot['visitors']==3 and tot['starters']==1 and tot['signups']==1 and tot['known_region']==2
 ch={x['key']:x for x in aud['channels']}
 assert ch['google']['visitors']==1 and ch['google']['starters']==1 and ch['google']['zh']=='Google 搜索' and ch['google']['group']=='search'
 assert ch['instagram']['signups']==1 and ch['instagram']['group']=='social'
 assert ch['direct']['visitors']==1     # the malformed request falls back to direct
 cc={x['key']:x for x in aud['countries']}
 assert cc['MY']['zh']=='马来西亚' and cc['US']['en']=='United States' and cc['']['visitors']==1
 assert aud['campaigns'][0]['key']=='oct_full_moon' and aud['campaigns'][0]['source']=='instagram'
 assert {x['key'] for x in aud['devices']}=={'mobile','desktop'} and any(x['key']=='iOS' for x in aud['os'])
 assert {x['key'] for x in aud['landings']}=={'/','/learn/the-fool'}
 assert {x['key'] for x in aud['langs'] if x['key']}=={'zh-CN','en-US'}
 # nothing identifying is stored on the visit marks
 with m.engine.begin() as c:
  marks=[json.loads(x[0]) for x in c.execute(m.select(m.records.c.payload).where(m.records.c.kind=='visit').where(m.records.c.id.like('visit:2031-03-01:%'))).all()]
 blob=json.dumps(marks)
 assert '203.0.113' not in blob and 'Windows NT' not in blob and 'google.com' in blob

def test_stats_api_stays_backward_compatible(admin):
 r=admin.get('/api/admin/stats?days=abc&range=zz').json
 assert len(r['days'])==14 and r['range']==7 and 'audience' in r
 assert admin.get('/api/admin/stats?days=500').status_code==200 and len(admin.get('/api/admin/stats?days=500').json['days'])==180
 assert client().get('/api/admin/stats').status_code==401

# ---------- card pages & SEO ----------
def test_card_pages_render_and_are_in_sitemap():
 c=client()
 assert len(m.CARD_SLUG)==78 and m.CARD_SLUG[0]=='the-fool' and 'ace-of-wands' in m.SLUG_CARD
 html=c.get('/learn/the-fool').get_data(as_text=True)
 assert '<h1>愚者<small class="card-alt">The Fool</small></h1>' in html and 'rel="canonical" href="'+m.SITE_URL+'/learn/the-fool"' in html
 assert '"BreadcrumbList"' in html and 'data-ssr="card"' in html and 'rel="next"' in html and 'index, follow' in html
 assert 'rel="alternate" hreflang="en"' not in html            # no English copy yet: no English alternate
 en=c.get('/learn/the-fool?lang=en').get_data(as_text=True)
 assert 'noindex' in en and 'coming soon' in en
 assert c.get('/learn/not-a-card').status_code==404
 lib=c.get('/learn').get_data(as_text=True);assert lib.count('href="/learn/')==78
 sm=c.get('/sitemap.xml').get_data(as_text=True)
 assert sm.count('/learn/')==78 and '/learn/the-fool?lang=en' not in sm

def test_seo_overrides_verification_and_card_copy(admin):
 x=admin.get('/api/admin/seo').json
 assert len(x['cards'])==78 and x['url_count']>=78+len(m.PAGES)*2 and x['indexnow_url'].endswith('.txt')
 assert any('CANONICAL_HOST' in k['zh'] for k in x['checks'])      # several hosts, no canonical host yet
 key=x['indexnow_url'].rsplit('/',1)[1][:-4]
 assert client().get(f'/{key}.txt').get_data(as_text=True)==key and client().get('/'+'0'*32+'.txt').status_code==404
 r=post(admin,'/admin/seo',dict(verify=dict(google='<meta name="google-site-verification" content="abcDEF123_-x" />',bing='B1NG'),pages=dict(ai=dict(zh_title='自定义 AI 标题',en_desc='Custom English description for the AI page.'))),'PUT')
 assert r.status_code==200
 html=client().get('/ai').get_data(as_text=True)
 assert '<title>自定义 AI 标题</title>' in html and '<meta name="google-site-verification" content="abcDEF123_-x">' in html and 'content="B1NG"' in html
 assert 'Custom English description for the AI page.' in client().get('/ai?lang=en').get_data(as_text=True)
 assert post(admin,'/admin/seo',dict(verify=dict(google='"><script>')),'PUT').status_code==400
 assert post(admin,'/admin/seo',dict(pages=dict(nope={})),'PUT').status_code==400
 assert post(admin,'/admin/seo',dict(og_image='http://insecure.example/x.jpg'),'PUT').status_code==400
 assert post(admin,'/admin/seo',dict(card=dict(slug='the-fool',intro_zh='第一段\n第二段',intro_en='An English introduction.',upright_en='new beginnings, freedom',reviewed=True)),'PUT').status_code==200
 html=client().get('/learn/the-fool').get_data(as_text=True)
 assert '<p>第一段</p><p>第二段</p>' in html and 'rel="alternate" hreflang="en"' in html
 en=client().get('/learn/the-fool?lang=en').get_data(as_text=True)
 assert 'noindex' not in en and 'An English introduction.' in en and 'new beginnings, freedom' in en
 assert '/learn/the-fool?lang=en' in client().get('/sitemap.xml').get_data(as_text=True)
 assert post(admin,'/admin/seo',dict(card=dict(slug='nope')),'PUT').status_code==400
 assert post(admin,'/admin/seo',dict(card=dict(slug='the-fool',intro_zh='x'*1501)),'PUT').status_code==400
 # local requests never ping search engines; manual push says why
 assert post(admin,'/admin/seo/indexnow').status_code==409
 u=member('seo_plain');assert post(u,'/admin/seo',dict(og_image=''),'PUT').status_code==403
 # reset overrides so other tests see defaults
 post(admin,'/admin/seo',dict(verify=dict(google='',bing=''),pages=dict(ai={})),'PUT')

def fake_model(payload,usage=(1000,500)):
 calls=[]
 def call(s,messages,max_tokens,json_mode):
  calls.append(dict(messages=messages,max_tokens=max_tokens,json_mode=json_mode))
  return (payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False)),dict(prompt_tokens=usage[0],completion_tokens=usage[1])
 return call,calls

def test_ai_card_copy_is_budgeted(admin,monkeypatch):
 call,calls=fake_model(dict(intro_zh='AI 中文介绍',intro_en='AI English intro',theme_en='endings and change',upright_en='closure',reversed_en='resisting change',desc_zh='死神牌含义',desc_en='Death card meaning'))
 monkeypatch.setattr(m,'_model_call',call)
 monkeypatch.setattr(m,'stats_day',lambda c=None,s=None:'2031-04-01')
 with m.engine.begin() as c:day=m.datetime.now(m.ZoneInfo(m.settings(c)['timezone'])).strftime('%Y-%m-%d');before=(m.get(c,'budget:'+day) or dict(spent=0))['spent']
 r=post(admin,'/admin/seo/cards/death/ai',dict(overwrite=True));assert r.status_code==200 and r.json['card']['intro_en']=='AI English intro'
 assert calls[0]['json_mode'] and '死神' in calls[0]['messages'][1]['content'] and 'guaranteed prediction' in calls[0]['messages'][0]['content']
 with m.engine.begin() as c:b=m.get(c,'budget:'+day)
 assert abs(b['spent']-before-(1000*1+500*2)/1_000_000)<1e-9 and b['calls']['studio:seo-card']>=1
 card=next(x for x in admin.get('/api/admin/seo').json['cards'] if x['slug']=='death');assert card['ai'] and card['has_en']
 # budget exhausted: refused before calling the model
 with m.engine.begin() as c:b=m.get(c,'budget:'+day);b['spent']=10**6;m.put(c,'budget:'+day,'budget','system',b)
 n=len(calls);assert post(admin,'/admin/seo/cards/death/ai').status_code==429 and len(calls)==n
 with m.engine.begin() as c:b=m.get(c,'budget:'+day);b['spent']=0;m.put(c,'budget:'+day,'budget','system',b)
 # garbage from the model is reported, not saved
 monkeypatch.setattr(m,'_model_call',fake_model('not json at all')[0])
 assert post(admin,'/admin/seo/cards/death/ai').status_code==502
 assert post(admin,'/admin/seo/cards/nope/ai').status_code==404

# ---------- marketing ----------
POSTS=dict(posts=[dict(platform='xiaohongshu',title='今天抽到愚者',text='正文内容',hashtags=['#塔罗','每日一牌'],image_idea='愚者牌放在窗边'),dict(platform='x',text='Short post',hashtags=['tarot']),dict(platform='facebook',text='not requested')])

def test_marketing_drafts_links_and_config(admin,monkeypatch):
 call,calls=fake_model(POSTS);monkeypatch.setattr(m,'_model_call',call)
 r=post(admin,'/admin/marketing/generate',dict(source='card',ref='the-fool',platforms=['xiaohongshu','x'],note='强调首次免费'))
 assert r.status_code==200,r.json
 d={x['platform']:x for x in r.json['drafts']}
 assert set(d)=={'xiaohongshu','x'}                                  # unrequested platform dropped
 assert d['xiaohongshu']['hashtags']==['塔罗','每日一牌'] and d['xiaohongshu']['trigger']=='manual'
 assert d['x']['link'].endswith('/learn/the-fool?utm_source=x&utm_medium=social&utm_campaign=card_the-fool')
 brief=json.loads(calls[0]['messages'][1]['content']);assert brief['subject']['card_zh']=='愚者' and brief['extra_note']=='强调首次免费'
 assert 'never invent testimonials' in calls[0]['messages'][0]['content']
 lst=admin.get('/api/admin/marketing').json
 assert {x['id'] for x in r.json['drafts']}<={x['id'] for x in lst['drafts']} and 'xiaohongshu' in lst['platforms'] and len(lst['cards'])==78
 did=d['x']['id'].split(':')[1]
 assert post(admin,f'/admin/marketing/drafts/{did}',dict(status='posted'),'PUT').json['draft']['status']=='posted'
 assert post(admin,f'/admin/marketing/drafts/{did}',dict(status='weird'),'PUT').status_code==400
 assert post(admin,f'/admin/marketing/drafts/{did}',dict(action='delete'),'PUT').status_code==200
 assert post(admin,f'/admin/marketing/drafts/{did}',dict(status='draft'),'PUT').status_code==404
 # validation
 assert post(admin,'/admin/marketing/generate',dict(source='card',ref='nope',platforms=['x'])).status_code==400
 assert post(admin,'/admin/marketing/generate',dict(source='topic',ref='',platforms=['x'])).status_code==400
 assert post(admin,'/admin/marketing/generate',dict(source='card',ref='the-fool',platforms=['myspace'])).status_code==400
 assert post(admin,'/admin/marketing/generate',dict(source='case',ref='deadbeef',platforms=['x'])).status_code==400
 monkeypatch.setattr(m,'_model_call',fake_model(dict(posts='nope'))[0])
 assert post(admin,'/admin/marketing/generate',dict(source='topic',ref='新月许愿',platforms=['x'])).status_code==502
 # UTM links
 l=post(admin,'/admin/marketing/links',dict(channel='WhatsApp',campaign='Oct Promo!',path='/human',note='群发')).json['link']
 assert l['url'].endswith('/human?utm_source=whatsapp&utm_medium=messaging&utm_campaign=oct_promo')
 assert post(admin,'/admin/marketing/links',dict(channel='x',path='https://evil.example/')).status_code==400
 assert any(x['id']==l['id'] for x in admin.get('/api/admin/marketing').json['links'])
 assert post(admin,'/admin/marketing/links/'+l['id'],method='DELETE').status_code==200
 assert not any(x['id']==l['id'] for x in admin.get('/api/admin/marketing').json['links'])
 # config
 assert post(admin,'/admin/marketing',dict(daily_hour=25),'PUT').status_code==400
 assert post(admin,'/admin/marketing',dict(platforms=['x','bogus']),'PUT').status_code==400
 cfg=post(admin,'/admin/marketing',dict(auto_case=True,daily=False,daily_hour=8,platforms=['instagram','threads'],voice='温柔'),'PUT').json['config']
 assert cfg==dict(auto_case=True,daily=False,daily_hour=8,platforms=['instagram','threads'],voice='温柔')
 assert client().get('/api/admin/marketing').status_code==401

def test_auto_drafts_for_published_case_and_daily_card(admin,monkeypatch):
 posts=dict(posts=[dict(platform='instagram',text='An anonymised example',hashtags=['tarot']),dict(platform='threads',text='What would you ask?')])
 call,calls=fake_model(posts);monkeypatch.setattr(m,'_model_call',call)
 started=[]
 class Now:
  def __init__(self,target,args=(),daemon=None):self.target,self.args=target,args
  def start(self):started.append(self.target.__name__);self.target(*self.args)
 monkeypatch.setattr(m.threading,'Thread',Now)
 post(admin,'/admin/marketing',dict(auto_case=True,platforms=['instagram','threads']),'PUT')
 slug,_=published(admin,member('auto_mkt'))
 assert 'auto_case_drafts' in started
 drafts=[x for x in admin.get('/api/admin/marketing').json['drafts'] if x['ref']==slug]
 assert {x['platform'] for x in drafts}=={'instagram','threads'} and all(x['trigger']=='case-published' for x in drafts)
 assert drafts[0]['link'].split('?')[0].endswith('/cases/'+slug)
 brief=json.loads(calls[-1]['messages'][1]['content']);assert brief['subject']['kind']=='case example' and 'reading_excerpt' in brief['subject']
 # daily card: once per day, only after the chosen hour
 post(admin,'/admin/marketing',dict(auto_case=False,daily=True,daily_hour=0),'PUT')
 n=len(calls);m.daily_marketing();m.daily_marketing()
 assert len(calls)==n+1
 daily=[x for x in admin.get('/api/admin/marketing').json['drafts'] if x['trigger']=='daily-card']
 assert len(daily)==2 and daily[0]['ref']==m.daily_card_slug(m.datetime.now(m.ZoneInfo('Asia/Kuala_Lumpur')).strftime('%Y-%m-%d'))
 post(admin,'/admin/marketing',dict(daily=False),'PUT')

def test_admin_console_assets():
 js=open(os.path.join(os.path.dirname(os.path.dirname(__file__)),'static/app.js')).read()
 for needle in ("['seo','SEO 与收录','SEO']","['marketing','自动营销','Marketing']",'function funnel(','function trendChart(','async function statsTab(','async function seoTab(','async function marketingTab(',"['card',p.split('/')[2]]"):
  assert needle in js,needle
 assert 'style="' not in js.split('// ================= v0.8')[1]    # CSP forbids inline style attributes
