import os,sys,tempfile,json
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest
from test_v072 import client,post,member,published,admin  # noqa: F401  (admin is a fixture)

IOS='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 OpsTarotApp/ios'
ANDROID='Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36 OpsTarotApp/android'

def app_member(name,ua):
 c=client(ua=ua);assert post(c,'/register',dict(username=name,password='eight888')).status_code==200
 return c

def test_app_is_recognised_and_marked_on_the_page():
 web=client().get('/').get_data(as_text=True)
 assert '<html lang="zh-CN">' in web and 'is-app' not in web
 assert '/static/native.js?v=' in web and web.index('/static/native.js')<web.index('/static/app.js')
 ios=client(ua=IOS).get('/').get_data(as_text=True)
 assert 'class="is-app is-ios"' in ios
 assert client(ua=IOS).get('/api/bootstrap').json['settings']['app']=='ios'
 assert client(ua=ANDROID).get('/api/bootstrap').json['settings']['app']=='android'
 assert client().get('/api/bootstrap').json['settings']['app']==''
 # "OpsTarotApp" must be a whole token: a look-alike string is a normal browser
 assert client(ua='XOpsTarotApp/iosX').get('/api/bootstrap').json['settings']['app']==''

def test_csp_relaxed_only_for_the_android_shell():
 # The Android shell injects its bridge as an inline script; nobody else gets 'unsafe-inline'.
 assert "'unsafe-inline'" not in client().get('/').headers['Content-Security-Policy']
 assert "'unsafe-inline'" not in client(ua=IOS).get('/').headers['Content-Security-Policy']
 assert "script-src 'self' 'unsafe-inline';" in client(ua=ANDROID).get('/').headers['Content-Security-Policy']

def test_deep_link_files_only_when_configured(monkeypatch):
 c=client()
 monkeypatch.delenv('APP_ANDROID_SHA256',raising=False);monkeypatch.delenv('APP_IOS_TEAM_ID',raising=False)
 assert c.get('/.well-known/assetlinks.json').status_code==404
 assert c.get('/.well-known/apple-app-site-association').status_code==404
 monkeypatch.setenv('APP_ANDROID_SHA256','aa:bb:cc, dd:ee')
 j=c.get('/.well-known/assetlinks.json').json
 assert j[0]['target']=={'namespace':'android_app','package_name':'life.honeytime.tarot','sha256_cert_fingerprints':['AA:BB:CC','DD:EE']}
 monkeypatch.setenv('APP_IOS_TEAM_ID','bad')
 assert c.get('/.well-known/apple-app-site-association').status_code==404
 monkeypatch.setenv('APP_IOS_TEAM_ID','ab12cd34ef')
 r=c.get('/.well-known/apple-app-site-association')
 assert r.status_code==200 and r.mimetype=='application/json'
 d=r.json['applinks']['details'][0]
 assert d['appIDs']==['AB12CD34EF.life.honeytime.tarot']
 assert {'/':'/api/*','exclude':True} in d['components'] and d['components'][-1]=={'/':'/*'}
 assert c.get('/apple-app-site-association').json==r.json

def test_pwa_manifest_service_worker_and_offline_page():
 c=client()
 mf=json.loads(c.get('/manifest.webmanifest').get_data(as_text=True))
 assert mf['id']=='/' and mf['scope']=='/' and mf['display']=='standalone'
 assert any(i.get('purpose')=='maskable' for i in mf['icons']) and len(mf['shortcuts'])==3
 assert all(c.get(i['src']).status_code==200 for i in mf['icons'])
 assert json.loads(c.get('/manifest.webmanifest?lang=en').get_data(as_text=True))['lang']=='en'
 sw=c.get('/sw.js')
 assert sw.status_code==200 and sw.mimetype=='text/javascript' and sw.headers['Cache-Control']=='no-cache'
 body=sw.get_data(as_text=True);assert '__VERSION__' not in body and m.ASSET_V in body
 off=c.get('/offline');html=off.get_data(as_text=True)
 assert off.status_code==200 and '暂时没有网络' in html and 'noindex' in html and '<script' not in html
 assert 'You are offline' in client().get('/offline?lang=en').get_data(as_text=True)
 assert c.get('/static/offline.css').status_code==200

def test_ios_app_never_charges_for_ai_readings(admin):
 pay=dict(billing=True,charge_ai=True,ai_price='12',payments=[dict(type='tng',enabled=True,account='TNG-001',label='TNG')])
 try:
  assert post(admin,'/admin/settings',pay,'PUT').status_code==200
  web=member('webpayer');ios=app_member('iospayer',IOS);droid=app_member('droidpayer',ANDROID)
  q=dict(question='接下来三个月我需要注意什么',period='三个月',spread='three',mode='ai',lang='zh')
  assert post(web,'/readings',q).json['status']=='payment'
  assert post(droid,'/readings',q).json['status']=='payment'   # Android: Google Play allows external payment for this
  r=post(ios,'/readings',q).json;assert r['status']=='drawing' and not r.get('order')
  assert ios.get('/api/bootstrap').json['settings']['charge_ai'] is False
  assert ios.get('/api/bootstrap').json['settings']['payments']==[]
  assert web.get('/api/bootstrap').json['settings']['charge_ai'] is True
  # the iOS app does not show payment details for a member's orders (unless the studio enables it)
  assert web.get('/api/history').json['orders'][0]['payments']
  with m.engine.begin() as c:o=next(x for x in m.rows(c,'order') if x['owner']==m.hashlib.sha256(b'webpayer').hexdigest()[:32])
  o_ios=client(ua=IOS);assert post(o_ios,'/login',dict(username='webpayer',password='eight888')).status_code==200
  h=o_ios.get('/api/history').json['orders'][0];assert h['payments']==[] and h['pay_elsewhere'] is True
  assert post(admin,'/admin/settings',dict(app_ios_payments=True),'PUT').status_code==200
  assert o_ios.get('/api/history').json['orders'][0]['payments']
  # 'off': the iOS app does not offer AI readings at all
  assert post(admin,'/admin/settings',dict(app_ios_ai='off'),'PUT').status_code==200
  r=post(ios,'/readings',q);assert r.status_code==403 and r.json['code']=='ios_ai_off'
  assert post(ios,'/readings',dict(q,mode='human')).status_code==200
  assert post(admin,'/admin/settings',dict(app_ios_ai='paid'),'PUT').status_code==400
  assert o['status']=='pending'
 finally:
  assert post(admin,'/admin/settings',dict(billing=False,charge_ai=False,app_ios_ai='free',app_ios_payments=False),'PUT').status_code==200

def test_report_hides_for_reporter_and_three_reports_take_it_down(admin):
 u=member('rpowner');slug,_=published(admin,u)
 writer=member('rpwriter');cid=post(writer,f'/cases/{slug}/comments',dict(text='这条评价会被举报')).json['comment']['id']
 a,b,cc,d=(client(f'203.0.113.{n}',f'phone-{n}') for n in (71,72,73,74))
 assert post(writer,f'/cases/{slug}/comments/{cid}/report',dict(reason='spam')).status_code==400   # not your own
 assert post(a,f'/cases/{slug}/comments/{cid}/report',dict(reason='abuse')).json=={'ok':True}
 assert a.get(f'/api/cases/{slug}/comments').json['items']==[]                 # hidden for the reporter at once
 assert cid not in a.get(f'/cases/{slug}').get_data(as_text=True)
 assert [x['id'] for x in d.get(f'/api/cases/{slug}/comments').json['items']]==[cid]   # still public
 assert post(a,f'/cases/{slug}/comments/{cid}/report',dict(reason='abuse')).status_code==200  # repeat: counted once
 post(b,f'/cases/{slug}/comments/{cid}/report',dict(reason='weird'))           # unknown reason -> other
 with m.engine.begin() as c:y=m.get(c,'comment:'+cid)
 assert len(y['reports'])==2 and y['reports'][1]['reason']=='other' and y['status']=='published'
 post(cc,f'/cases/{slug}/comments/{cid}/report',dict(reason='privacy'))
 assert d.get(f'/api/cases/{slug}/comments').json['items']==[]                 # third report: taken down
 assert client().get(f'/api/cases/{slug}').json['comments']==0
 adm=[x for x in admin.get('/api/admin/comments').json['items'] if x['id']==cid][0]
 assert adm['status']=='pending' and len(adm['reports'])==3 and 'by' not in adm['reports'][0]
 # the author still sees it, as their own comment in review
 assert [x['id'] for x in writer.get(f'/api/cases/{slug}/comments').json['mine']]==[cid]
 assert post(a,f'/cases/{slug}/comments/ffffffffffff/report',dict(reason='spam')).status_code==404

def test_block_hides_every_comment_by_that_author(admin):
 u=member('bkowner');slug,_=published(admin,u);slug2,_=published(admin,u)
 rude=member('bkrude');kind=member('bkkind')
 c1=post(rude,f'/cases/{slug}/comments',dict(text='第一条不友善的评价')).json['comment']['id']
 post(rude,f'/cases/{slug2}/comments',dict(text='第二条不友善的评价'))
 post(kind,f'/cases/{slug}/comments',dict(text='友善的评价'))
 viewer=member('bkviewer')
 assert post(viewer,f'/cases/{slug}/comments/{c1}/block').json=={'ok':True}
 assert [x['text'] for x in viewer.get(f'/api/cases/{slug}/comments').json['items']]==['友善的评价']
 assert viewer.get(f'/api/cases/{slug2}/comments').json['items']==[]             # across cases
 assert '第一条不友善的评价' not in viewer.get(f'/cases/{slug}').get_data(as_text=True)
 # the block follows the member to another device
 other=client(ua='another-phone');assert post(other,'/login',dict(username='bkviewer',password='eight888')).status_code==200
 assert len(other.get(f'/api/cases/{slug}/comments').json['items'])==1
 assert len(client().get(f'/api/cases/{slug}/comments').json['items'])==2        # everyone else unaffected
 assert post(viewer,'/blocks/clear').json=={'ok':True}
 assert len(viewer.get(f'/api/cases/{slug}/comments').json['items'])==2
 # pages show report/block buttons on others' comments, delete on your own
 html=kind.get(f'/cases/{slug}').get_data(as_text=True)
 assert f'data-cm-report="{c1}"' in html and f'data-cm-block="{c1}"' in html and 'data-cm-del=' in html

def test_account_deletion_removes_personal_data(admin):
 u=member('leaver');slug,rid=published(admin,u)
 cid=post(u,f'/cases/{slug}/comments',dict(text='我自己的评价')).json['comment']['id']
 hr=post(u,'/readings',dict(question='想预约真人看看',period='一个月',spread='three',mode='human',lang='zh')).json
 for i in range(3):hr=post(u,f"/readings/{hr['id']}/draw",dict(index=0,expected=i)).json
 bk=post(u,'/bookings',dict(reading=hr['id'],package='text',phone='+60123456789',email='leaver@example.com',timezone='Asia/Kuala_Lumpur',date='2030-01-02',time_slot='10:00')).json
 assert bk['status']=='requested'
 assert post(u,'/account/delete',dict(password='wrong-pass')).status_code==403      # 403, not 401: stays signed in
 assert u.get('/api/bootstrap').json['user']['username']=='leaver'
 assert post(admin,'/account/delete',dict(password='test-password-123')).status_code==403   # admins cannot
 r=post(u,'/account/delete',dict(password='eight888'))
 assert r.status_code==200 and r.json=={'ok':True,'cancelled':1}
 assert u.get('/api/bootstrap').json['user'] is None
 uid=m.hashlib.sha256(b'leaver').hexdigest()[:32]
 with m.engine.begin() as c:
  assert m.get(c,'user:'+uid) is None and m.get(c,rid) is None and m.get(c,hr['id']) is None
  assert m.get(c,'comment:'+cid) is None and m.rows(c,'reading',uid)==[] and m.rows(c,'booking',uid)==[]
  case=m.get(c,'case:'+slug);b=m.get(c,bk['id'])
 assert case['status']=='withdrawn' and case['question']=='' and case['owner'].startswith('deleted:')
 assert b['status']=='cancelled' and b['contacts']=={} and b['owner'].startswith('deleted:') and b['account_deleted']
 assert client().get(f'/cases/{slug}').status_code==410
 again=member('leaver')   # the name can be registered again, and starts empty
 assert again.get('/api/history').json['readings']==[] and again.get('/api/history').json['bookings']==[]
 assert post(client(),'/account/delete',dict(password='x')).status_code==401

def test_settings_defaults_and_admin_form():
 from catalog import DEFAULTS
 assert DEFAULTS['app_ios_ai']=='free' and DEFAULTS['app_ios_payments'] is False
 js=open(os.path.join(os.path.dirname(m.__file__),'static','app.js'),encoding='utf-8').read()
 assert 'name="app_ios_ai"' in js and "'app_ios_payments'" in js and 'delete-account-form' in js and 'data-cm-report' in js
 native=open(os.path.join(os.path.dirname(m.__file__),'static','native.js'),encoding='utf-8').read()
 for key in ('LocalNotifications','appUrlOpen','backButton','Browser','Share','Haptics','serviceWorker'):assert key in native

def test_capacitor_project_is_consistent():
 root=os.path.join(os.path.dirname(m.__file__),'mobile')
 cfg=json.load(open(os.path.join(root,'capacitor.config.json')))
 assert cfg['appId']==m.APP_ID and cfg['server']['url']=='https://honeytime.life'
 assert cfg['ios']['appendUserAgent'].strip()=='OpsTarotApp/ios' and cfg['android']['appendUserAgent']=='OpsTarotApp/android'
 assert m.APP_UA.search('x '+cfg['ios']['appendUserAgent'].strip()) and m.APP_UA.search('x '+cfg['android']['appendUserAgent'])
 assert os.path.exists(os.path.join(root,cfg['webDir'],cfg['server']['errorPath']))
 pkg=json.load(open(os.path.join(root,'package.json')))
 for plugin in ('@capacitor/app','@capacitor/browser','@capacitor/share','@capacitor/haptics','@capacitor/local-notifications','@capacitor/splash-screen'):assert plugin in pkg['dependencies']
 for f in ('icon-only.png','icon-foreground.png','icon-background.png','splash.png','splash-dark.png'):assert os.path.exists(os.path.join(root,'assets',f))
