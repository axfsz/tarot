import os,sys,tempfile,json,re
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest

ip=[10]
def client():
 c=m.app.test_client();ip[0]+=1;c.environ_base['REMOTE_ADDR']=f'198.18.0.{ip[0]}'
 return c
def post(c,path,data=None,method='POST'):
 token=c.get('/api/bootstrap').json['csrf']
 return c.open('/api'+path,method=method,json=data or {},headers={'X-CSRF':token})

@pytest.fixture(scope='module')
def admin():
 c=client()
 if not c.get('/api/bootstrap').json['installed']:
  assert post(c,'/setup',dict(token='test-install-token',username='admin',password='test-password-123')).status_code==200
 else:assert post(c,'/login',dict(username='admin',password='test-password-123')).status_code==200
 assert post(c,'/admin/settings',dict(api_key='k',input_price=1,output_price=2,daily_budget=30,user_daily_limit=50),'PUT').status_code==200
 # start each module with an empty showcase
 with m.engine.begin() as conn:
  for x in m.rows(conn,'case'):conn.execute(m.delete(m.records).where(m.records.c.id==x['id']))
 return c

def member(name):
 c=client();assert post(c,'/register',dict(username=name,password='eight888')).status_code==200
 return c
def completed_reading(c,question='下个月我该把精力放在哪份工作上？联系我 test@example.com',report='## 核心回应\n\n专注一个方向。\n\n- 先做一件小事'):
 r=post(c,'/readings',dict(question=question,period='一个月',spread='three',mode='ai',lang='zh')).json
 for i in range(3):r=post(c,f"/readings/{r['id']}/draw",dict(index=0,expected=i)).json
 with m.engine.begin() as conn:
  x=m.get(conn,r['id']);x.update(status='completed',reports=[dict(text=report,at=m.now(),followup='')]);m.put(conn,x['id'],'reading',x['owner'],x)
 return r['id']
def publish(admin,slug,**kw):
 d=dict(question='下个月的工作重点',summary='先聚焦一个方向，再做小步尝试。',confirmed=True,action='publish');d.update(kw)
 return post(admin,f'/admin/cases/{slug}',d,'PUT')

def test_consent_creates_private_draft(admin):
 u=member('caseuser1');rid=completed_reading(u)
 assert post(u,f'/readings/{rid}/share',dict(consent='yes')).status_code==400
 s=post(u,f'/readings/{rid}/share',dict(consent=True)).json['share'];assert s['status']=='pending'
 assert post(u,f'/readings/{rid}/share',dict(consent=True)).json['share']['slug']==s['slug']
 assert u.get(f'/api/readings/{rid}').json['share']['slug']==s['slug']
 assert [h['share'] for h in u.get('/api/history').json['readings']][0]['status']=='pending'
 # pending drafts are invisible publicly
 assert client().get(f"/api/cases/{s['slug']}").status_code==404 and client().get(f"/cases/{s['slug']}").status_code==404
 items=admin.get('/api/admin/cases').json['items'];x=next(i for i in items if i['slug']==s['slug'])
 assert 'owner' not in x and any(f['kind']=='email' for f in x['original_flags']['pii'])
 assert x['topic']=='career' and x['source']=='ai'

def test_only_owner_member_can_consent(admin):
 u=member('caseuser2');rid=completed_reading(u)
 assert post(member('caseuser3'),f'/readings/{rid}/share',dict(consent=True)).status_code==404
 g=client();r=post(g,'/readings',dict(question='q',period='p',spread='one',mode='ai')).json
 x=post(g,f"/readings/{r['id']}/share",dict(consent=True));assert x.status_code==401 and x.json['code']=='signup'
 fresh=post(u,'/readings',dict(question='q',period='p',spread='one',mode='ai')).json
 assert post(u,f"/readings/{fresh['id']}/share",dict(consent=True)).status_code==409

def test_publish_rules_and_public_projection(admin):
 u=member('caseuser4');rid=completed_reading(u);slug=post(u,f'/readings/{rid}/share',dict(consent=True)).json['share']['slug']
 assert publish(admin,slug,confirmed=False).status_code==409
 assert publish(admin,slug,summary='').status_code==400
 assert publish(admin,slug,summary='x'*61).status_code==400
 assert publish(admin,slug,question='我在考虑要不要做手术').status_code==409
 r=publish(admin,slug);assert r.status_code==200 and r.json['status']=='published'
 pub=client().get(f'/api/cases/{slug}').json
 text=json.dumps(pub,ensure_ascii=False)
 for secret in ['caseuser4','test@example.com','owner','reading:','一个月']:assert secret not in text
 assert pub['question']=='下个月的工作重点' and len(pub['cards'])==3 and pub['report'].startswith('## 核心回应')
 page=client().get(f'/cases/{slug}');html=page.get_data(as_text=True)
 assert page.status_code==200 and '下个月的工作重点' in html and '<h3>核心回应</h3>' in html and 'test@example.com' not in html
 assert '/#question/three' in html and 'data-track="case_to_reading"' in html
 assert f'/cases/{slug}</loc>' in client().get('/sitemap.xml').get_data(as_text=True)
 assert any(i['slug']==slug for i in client().get('/api/cases').json['items'])

def test_withdraw_removes_everything(admin):
 u=member('caseuser5');rid=completed_reading(u);slug=post(u,f'/readings/{rid}/share',dict(consent=True)).json['share']['slug']
 assert publish(admin,slug).status_code==200
 assert post(u,f'/readings/{rid}/share',dict(consent=False)).json['share'] is None
 assert client().get(f'/api/cases/{slug}').status_code==410
 page=client().get(f'/cases/{slug}');assert page.status_code==410 and 'noindex' in page.get_data(as_text=True)
 assert f'/cases/{slug}<' not in client().get('/sitemap.xml').get_data(as_text=True)
 x=next(i for i in admin.get('/api/admin/cases').json['items'] if i['slug']==slug)
 assert x['status']=='withdrawn' and x['question']=='' and x['report']=='' and x['original']['question']==''
 assert publish(admin,slug).status_code==409
 # consenting again creates a fresh draft
 assert post(u,f'/readings/{rid}/share',dict(consent=True)).json['share']['slug']!=slug

def test_strip_needs_three_and_pins(admin):
 with m.engine.begin() as conn:
  for x in m.rows(conn,'case'):conn.execute(m.delete(m.records).where(m.records.c.id==x['id']))
 slugs=[]
 for i in range(4):
  u=member(f'stripuser{i}');rid=completed_reading(u);slugs.append(post(u,f'/readings/{rid}/share',dict(consent=True)).json['share']['slug'])
 publish(admin,slugs[0]);publish(admin,slugs[1])
 assert client().get('/api/bootstrap').json['cases']==[] and 'data-strip-section' not in client().get('/').get_data(as_text=True)
 publish(admin,slugs[2]);publish(admin,slugs[3])
 strip=client().get('/api/bootstrap').json['cases'];assert [x['slug'] for x in strip][:1]==[slugs[3]]
 assert 'report' not in strip[0] and 'data-strip-section' in client().get('/').get_data(as_text=True)
 assert post(admin,f'/admin/cases/{slugs[0]}',dict(action='pin'),'PUT').status_code==200
 assert client().get('/api/bootstrap').json['cases'][0]['slug']==slugs[0]
 for s in slugs[1:3]:assert post(admin,f'/admin/cases/{s}',dict(action='pin'),'PUT').status_code==200
 assert post(admin,f'/admin/cases/{slugs[3]}',dict(action='pin'),'PUT').status_code==409
 assert post(admin,f'/admin/cases/{slugs[3]}',dict(action='hide'),'PUT').json['status']=='hidden'
 assert client().get(f'/cases/{slugs[3]}').status_code==410
 html=client().get('/cases?topic=career').get_data(as_text=True);assert html.count('class="case-card"')==3
 assert client().get('/cases?topic=love').get_data(as_text=True).count('class="case-card"')==0

def test_ab_toggle_hides_strip_on_even_days(admin,monkeypatch):
 assert post(admin,'/admin/settings',dict(cases_ab_test=True),'PUT').status_code==200
 try:
  monkeypatch.setattr(m,'stats_day',lambda c=None,s=None:'2030-01-02')
  assert client().get('/api/bootstrap').json['cases']==[]
  monkeypatch.setattr(m,'stats_day',lambda c=None,s=None:'2030-01-03')
  assert len(client().get('/api/bootstrap').json['cases'])>=3
 finally:assert post(admin,'/admin/settings',dict(cases_ab_test=False),'PUT').status_code==200

def test_studio_example_and_human_case(admin):
 rid=completed_reading(admin,question='工作室示范：如何开始新的一年？',report='## 核心回应\n\n慢慢来。')
 x=post(admin,'/admin/cases/from-reading',dict(reading=rid)).json;assert x['source']=='studio' and x['status']=='pending'
 u=member('humancase');r=post(u,'/readings',dict(question='关系怎么沟通',period='一个月',spread='three',mode='human')).json
 for i in range(3):r=post(u,f"/readings/{r['id']}/draw",dict(index=0,expected=i)).json
 b=post(u,'/bookings',dict(reading=r['id'],package='text',phone='+60123456789',email='hc@example.com',date='2031-02-01',time_slot='10:00',timezone='Asia/Kuala_Lumpur')).json
 assert post(u,f"/bookings/{b['id']}/share",dict(consent=True)).status_code==409
 post(admin,f"/admin/bookings/{b['id']}",dict(action='confirm',scheduled='2031-02-01T10:00:00+08:00'))
 post(admin,f"/admin/bookings/{b['id']}",dict(action='complete',report='## 回应\n\n多倾听。'))
 s=post(u,f"/bookings/{b['id']}/share",dict(consent=True)).json['share']
 y=next(i for i in admin.get('/api/admin/cases').json['items'] if i['slug']==s['slug'])
 assert y['source']=='human' and y['report'].startswith('## 回应') and y['topic']=='love'
 assert next(h for h in u.get('/api/history').json['bookings'] if h['id']==b['id'])['share']['slug']==s['slug']

def test_case_events_and_viewer_comparison(admin):
 c=client()
 assert post(c,'/events',dict(name='case_strip_view')).json['ok']
 assert post(c,'/events',dict(name='prompt_chip')).json['ok']
 post(c,'/readings',dict(question='q',period='p',spread='one',mode='ai'))
 day=admin.get('/api/admin/stats?days=1').json['days'][0]
 assert day['case_viewers']>=1 and day['case_viewer_starts']>=1 and day['starters']>=day['case_viewer_starts']
 assert day['events']['case_strip_view']>=1 and day['events']['case_consent']>=1

def test_scan_and_format():
 f=m.scan('我老公叫张三，电话 +60 12-345 6789，在 ABC公司，2026年3月5日 见面')
 kinds={x['kind'] for x in f['pii']};assert {'phone','organisation','date','relation','name'}<=kinds and f['banned']==[]
 assert m.scan('买比特币会赚吗')['banned']==['比特币']
 html=str(m.format_report('## 标题\n\n- a <b>\n- c\n\n段落'))
 assert html=='<section class="report-section"><h3>标题</h3></section><ul><li>a &lt;b&gt;</li><li>c</li></ul><p>段落</p>'

def test_packages_delivery_and_assets(admin):
 boot=client().get('/api/bootstrap').json
 assert boot['settings']['packages'][0]['delivery_zh']
 assert '现在可以免费体验' in client().get('/').get_data(as_text=True)
 r=client().get('/static/fonts/ops-serif.woff');assert r.status_code==200 and len(r.data)<200_000;r.close()
 assert all(c['thumb'].startswith('/static/tarot/thumbs/') for c in m.CARDS)
 r=client().get(m.CARDS[17]['thumb']);assert r.status_code==200;r.close()
