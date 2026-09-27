import os,sys,tempfile,json,time,re
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest

ip=[100]
def client(host=None):
 c=m.app.test_client();ip[0]+=1;c.environ_base['REMOTE_ADDR']=f'203.0.113.{ip[0]}'
 return c
def post(c,path,data=None,method='POST'):
 token=c.get('/api/bootstrap').json['csrf']
 return c.open('/api'+path,method=method,json=data or {},headers={'X-CSRF':token})

@pytest.fixture(scope='module')
def admin():
 c=client()
 if not c.get('/api/bootstrap').json['installed']:
  assert post(c,'/setup',dict(token='test-install-token',username='admin',password='test-password-123')).status_code==200
 else:
  assert post(c,'/login',dict(username='admin',password='test-password-123')).status_code==200
 assert post(c,'/admin/settings',dict(api_key='test-key',input_price=1,output_price=2,daily_budget=30,user_daily_limit=5),'PUT').status_code==200
 return c

def draw_all(c,r):
 for i in range(len(r['spread']['positions'])):r=post(c,f"/readings/{r['id']}/draw",dict(index=0,expected=i)).json
 return r
def new_reading(c,**kw):
 d=dict(question='What should I focus on?',period='one month',spread='three',mode='ai',lang='en',reversals=True);d.update(kw)
 return post(c,'/readings',d)

def test_canonical_follows_known_hosts_only():
 for host in ['honeytime.life','tarot.opsglobalonline.com']:
  html=m.app.test_client().get('/learn',base_url=f'https://{host}').get_data(as_text=True)
  assert f'<link rel="canonical" href="https://{host}/learn">' in html and f'https://{host}/static/og-cover.jpg' in html
  assert f'https://{host}/sitemap.xml' in m.app.test_client().get('/robots.txt',base_url=f'https://{host}').get_data(as_text=True)
  assert f'<loc>https://{host}/ai</loc>' in m.app.test_client().get('/sitemap.xml',base_url=f'https://{host}').get_data(as_text=True)
 spoofed=m.app.test_client().get('/',base_url='https://evil.example').get_data(as_text=True)
 assert 'evil.example' not in spoofed and m.SITE_URL in spoofed

def test_brand_comes_from_settings(admin):
 assert post(admin,'/admin/settings',dict(brand_zh='蜜时塔罗',brand_en='HoneyTime Tarot'),'PUT').status_code==200
 try:
  html=client().get('/ai').get_data(as_text=True)
  assert '| 蜜时塔罗</title>' in html and 'HoneyTime Tarot' in html and '奥普塔罗' not in html.split('</head>')[0]
  assert client().get('/manifest.webmanifest').json['name'].startswith('HoneyTime Tarot')
 finally:
  assert post(admin,'/admin/settings',dict(brand_zh='奥普塔罗工作室',brand_en='Ops Tarot Studio'),'PUT').status_code==200

def test_trust_faq_and_contacts_render_server_side(admin):
 assert post(admin,'/admin/settings',{'contacts':[dict(type='wechat',enabled=True,account='studio-wechat',label='WeChat')],'readers':[dict(id='luna',enabled=True,zh='露娜',en='Luna',bio_zh='关系与沟通',languages='中文')]},'PUT').status_code==200
 home=client().get('/').get_data(as_text=True)
 assert 'id="quick-ask"' in home and 'class="panel plan"' in home and '露娜' in home and '"FAQPage"' in home
 assert home.count('<details>')==len(m.FAQ)
 assert 'studio-wechat' in client().get('/contact').get_data(as_text=True)
 boot=client().get('/api/bootstrap').json
 assert boot['faq']==m.FAQ and boot['settings']['guest_trial'] is True
 assert all('account' in x for x in boot['settings']['contacts'])

def test_guest_trial_reading_and_limits(admin):
 g=client()
 assert g.get('/api/history').status_code==401
 r=new_reading(g);assert r.status_code==200
 me=g.get('/api/bootstrap').json['user'];assert me['guest'] is True and me['id'].startswith('g')
 r=draw_all(g,r.json);assert r['status']=='ready'
 assert post(g,f"/readings/{r['id']}/generate").json['status']=='generating'
 assert g.get('/api/history').status_code==200
 # Guests get one AI reading per day; everything beyond that asks them to sign up.
 r2=draw_all(g,new_reading(g).json)
 x=post(g,f"/readings/{r2['id']}/generate");assert x.status_code==401 and x.json['code']=='signup'
 with m.engine.begin() as c:
  row=m.get(c,r['id']);row.update(status='completed',reports=[dict(text='ok',at=m.now(),followup='')]);m.put(c,row['id'],'reading',row['owner'],row)
 assert post(g,f"/readings/{r['id']}/generate",dict(followup='More?')).json['code']=='signup'
 for path in ['clarify','transfer']:
  x=post(g,f"/readings/{r['id']}/{path}",dict(question='Why?'));assert x.status_code==401 and x.json['code']=='signup'
 assert post(g,'/bookings',dict(reading=r['id'])).json['code']=='signup'
 # Other visitors cannot see the guest's reading.
 assert client().get(f"/api/readings/{r['id']}").status_code==401

def test_signup_adopts_guest_readings(admin):
 g=client();r=new_reading(g).json;gid=g.get('/api/bootstrap').json['user']['id']
 x=post(g,'/register',dict(username='fromguest',password='eight888',email='FromGuest@Example.com'))
 assert x.status_code==200 and x.json['moved']==1
 me=g.get('/api/bootstrap').json['user'];assert me['guest'] is False and me['email']=='fromguest@example.com'
 assert [h['id'] for h in g.get('/api/history').json['readings']]==[r['id']]
 with m.engine.begin() as c:assert m.get(c,'user:'+gid) is None and m.get(c,r['id'])['owner']==me['id']
 # Signing in to an existing account from a guest session also keeps the trial reading.
 g2=client();r2=new_reading(g2).json
 assert post(g2,'/login',dict(username='fromguest',password='eight888')).json['moved']==1
 assert r2['id'] in [h['id'] for h in g2.get('/api/history').json['readings']]

def test_password_rules_and_duplicate_email():
 c=client()
 assert post(c,'/register',dict(username='shortpw',password='seven77')).status_code==400
 assert post(client(),'/register',dict(username='dupmail1',password='eight888',email='same@example.com')).status_code==200
 assert post(client(),'/register',dict(username='dupmail2',password='eight888',email='same@example.com')).status_code==409
 assert post(client(),'/register',dict(username='badmail',password='eight888',email='nope')).status_code==400

def test_account_email_update():
 c=client();assert post(c,'/register',dict(username='mailless',password='eight888')).status_code==200
 assert post(c,'/account',dict(email='Mailless@Example.com'),'PUT').json['email']=='mailless@example.com'
 assert post(c,'/account',dict(email='same@example.com'),'PUT').status_code==409
 assert client().open('/api/account',method='PUT',json={}).status_code==403

def test_forgot_and_reset_password(monkeypatch):
 sent=[]
 monkeypatch.setattr(m,'send_mail',lambda to,subject,text:sent.append((to,subject,text)) or True)
 c=client();assert post(c,'/register',dict(username='resetme',password='old-pass-1',email='resetme@example.com')).status_code==200
 other=client();assert post(other,'/login',dict(username='resetme',password='old-pass-1')).status_code==200
 # Without SMTP nothing is sent, and the answer never reveals whether the user exists.
 assert post(client(),'/password/forgot',dict(login='resetme')).json==dict(ok=True,mail=False)
 assert post(client(),'/password/forgot',dict(login='nobody')).json==dict(ok=True,mail=False)
 assert sent==[]
 monkeypatch.setattr(m,'mail_ready',lambda:True)
 assert post(client(),'/password/forgot',dict(login='RESETME@example.com')).json['ok']
 assert post(client(),'/password/forgot',dict(login='nobody')).json['ok']
 assert len(sent)==1 and sent[0][0]=='resetme@example.com'
 token=re.search(r'#reset/([\w-]+)',sent[0][2]).group(1)
 assert post(client(),'/password/reset',dict(token=token,password='short')).status_code==400
 r=client();assert post(r,'/password/reset',dict(token=token,password='new-pass-1')).status_code==200
 assert r.get('/api/bootstrap').json['user']['username']=='resetme'
 assert post(client(),'/password/reset',dict(token=token,password='new-pass-2')).status_code==400
 assert other.get('/api/history').status_code==401
 assert post(client(),'/login',dict(username='resetme',password='old-pass-1')).status_code==401
 assert post(client(),'/login',dict(username='resetme',password='new-pass-1')).status_code==200

def test_expired_reset_link(monkeypatch):
 sent=[];monkeypatch.setattr(m,'send_mail',lambda to,subject,text:sent.append(text) or True);monkeypatch.setattr(m,'mail_ready',lambda:True)
 assert post(client(),'/register',dict(username='expired',password='eight888',email='expired@example.com')).status_code==200
 post(client(),'/password/forgot',dict(login='expired'))
 token=re.search(r'#reset/([\w-]+)',sent[-1]).group(1)
 monkeypatch.setattr(m.time,'time',lambda:time.monotonic()+10**10)
 assert post(client(),'/password/reset',dict(token=token,password='eight8888')).status_code==400

def test_events_and_admin_stats(admin):
 c=client()
 for _ in range(3):assert post(c,'/events',dict(name='page_view',page='home')).json['ok']
 assert post(c,'/events',dict(name='reading_created')).status_code==400
 assert post(c,'/events',dict(name='nonsense')).status_code==400
 today=admin.get('/api/admin/stats?days=3').json['days'][0]
 assert today['events']['page_view']>=3 and today['pages']['home']>=3 and today['visitors']>=1
 assert today['events'].get('reading_created',0)>=1
 assert client().get('/api/admin/stats').status_code==401
 assert admin.get('/api/admin/stats?days=abc').status_code==200

def test_ai_limit_code(admin):
 u=client();assert post(u,'/register',dict(username='limituser',password='eight888')).status_code==200
 r=draw_all(u,new_reading(u).json)
 assert post(admin,'/admin/settings',dict(daily_budget=.000001),'PUT').status_code==200
 try:
  x=post(u,f"/readings/{r['id']}/generate");assert x.status_code==429 and x.json['code']=='ai_limit'
  assert admin.get('/api/admin/stats?days=1').json['days'][0]['events'].get('budget_hit',0)>=1
 finally:assert post(admin,'/admin/settings',dict(daily_budget=30),'PUT').status_code==200

def test_booking_emails(admin,monkeypatch):
 sent=[];monkeypatch.setattr(m,'send_mail',lambda to,subject,text:sent.append((to,subject)) or bool(to))
 monkeypatch.setenv('NOTIFY_EMAIL','owner@example.com')
 u=client();assert post(u,'/register',dict(username='bookmail',password='eight888')).status_code==200
 r=draw_all(u,new_reading(u,mode='human').json)
 b=post(u,'/bookings',dict(reading=r['id'],package='text',phone='+60123456789',email='client@example.com',date='2031-01-05',time_slot='10:00',timezone='Asia/Kuala_Lumpur',language='zh')).json
 assert [x[0] for x in sent]==['client@example.com','owner@example.com']
 assert post(admin,f"/admin/bookings/{b['id']}",dict(action='confirm',scheduled='2031-01-05T10:00:00+08:00')).status_code==200
 assert sent[-1][0]=='client@example.com' and 'confirmed' in sent[-1][1]

def test_original_card_pngs_not_served():
 c=client()
 assert c.get('/static/tarot/cards/major/17-the-star.png').status_code==404
 r=c.get('/static/tarot/cards/major/17-the-star-safe.webp');assert r.status_code==200;r.close()
 assert c.get('/static/tarot/cards/major/17-the-star.webp').status_code==404
 assert next(x for x in m.CARDS if x['id']==17)['webp'].endswith('17-the-star-safe.webp')
 assert '17-the-star' not in c.get('/').get_data(as_text=True)
