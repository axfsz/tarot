import os,sys,tempfile,json
os.environ['DATA_DIR']=tempfile.mkdtemp()
os.environ['SETUP_TOKEN']='test-install-token'
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest
@pytest.fixture(scope='module')
def admin():
 c=m.app.test_client();post(c,'/setup',{'token':'test-install-token','username':'admin','password':'test-password-123'})
 return c

def post(c,path,data={},method='POST'):
 token=c.get('/api/bootstrap').json['csrf']
 return c.open('/api'+path,method=method,json=data,headers={'X-CSRF':token})
user_index=0
def user(name):
 global user_index
 user_index+=1
 c=m.app.test_client();c.environ_base['REMOTE_ADDR']='192.0.2.'+str(user_index);assert post(c,'/register',dict(username=name,password='test-password-123')).status_code==200
 return c

def reading(c,mode='ai'):
 r=post(c,'/readings',dict(question='How should I prepare?',period='one month',spread='three',mode=mode,lang='en',reversals=True))
 assert r.status_code==200,r.json
 return r.json

def draw_all(c,r):
 for i in range(3):
  r=post(c,'/readings/'+r['id']+'/draw',dict(index=0,expected=i)).json
 return r

def test_setup_locked(admin):
 assert post(admin,'/setup',dict(token='test-install-token',username='evil',password='test-password-123')).status_code==409

def test_csrf_and_permissions(admin):
 c=user('alice')
 assert c.post('/api/readings',json={}).status_code==403
 assert c.get('/api/admin/settings').status_code==403
 assert m.app.test_client().get('/api/history').status_code==401
 r=reading(c);other=user('bob')
 assert other.get('/api/readings/'+r['id']).status_code==404
 assert 'deck' not in r

def test_draw_stable_idempotent(admin):
 c=user('drawuser');r=reading(c)
 r=draw_all(c,r)
 assert r['status']=='ready'
 assert len(set(x['card']['id'] for x in r['cards']))==3
 assert c.get('/api/readings/'+r['id']).json['cards']==r['cards']
 again=post(c,'/readings/'+r['id']+'/draw',dict(index=0,expected=2)).json
 assert again['cards']==r['cards']
 assert post(c,'/readings/'+r['id']+'/cut',{'position':20}).status_code==409
 assert post(c,'/readings/'+r['id']+'/generate').status_code==503

def test_contacts_secrets(admin):
 assert post(admin,'/admin/settings',{'contacts':[dict(type='telegram',enabled=True,account='@studio',link='https://t.me/studio')],'api_key':'test-secret'},'PUT').status_code==200
 p=m.app.test_client().get('/api/bootstrap').json
 assert len(p['settings']['contacts'])==1
 assert 'api_key' not in p['settings']
 assert admin.get('/api/admin/settings').json['settings']['api_key']==''
 assert post(admin,'/admin/settings',{'contacts':[dict(type='telegram',enabled=True,account='@x',link='javascript:alert(1)')]},'PUT').status_code==400

def test_booking(admin):
 c=user('bookuser');r=draw_all(c,reading(c,'human'))
 data=dict(reading=r['id'],package='text',phone='+60123456789',whatsapp='+60123456789',date='2030-10-01',time_slot='14:00',timezone='Asia/Kuala_Lumpur',language='en')
 assert post(c,'/bookings',{**data,'whatsapp':''}).status_code==400
 assert post(c,'/bookings',{**data,'date':'2020-01-01'}).status_code==400
 assert post(c,'/bookings',{**data,'time_slot':'23:30'}).status_code==400
 assert post(c,'/bookings',{**data,'email':'invalid'}).status_code==400
 b=post(c,'/bookings',data).json
 assert b['status']=='requested'
 assert b['contacts']['whatsapp']=='+60123456789'
 assert b['preferred']=='2030-10-01 14:00'
 assert post(c,'/bookings',data).json['id']==b['id']
 assert post(admin,'/admin/bookings/'+b['id'],dict(action='complete',report='Report')).status_code==409
 assert post(admin,'/admin/bookings/'+b['id'],dict(action='confirm',scheduled='2030-10-01T14:00:00+08:00')).status_code==200
 assert post(admin,'/admin/bookings/'+b['id'],dict(action='complete',report='Personal report')).json['status']=='completed'
 assert c.get('/api/history').json['bookings'][0]['report']=='Personal report'

def test_manual_payment(admin):
 assert post(admin,'/admin/settings',dict(billing=True,charge_ai=True,ai_price='10'),'PUT').status_code==400
 assert post(admin,'/admin/settings',dict(billing=True,charge_ai=True,ai_price='10',payments=[dict(type='tng',enabled=True,account='Studio')]),'PUT').status_code==200
 c=user('paiduser');r=reading(c)
 assert r['status']=='payment'
 assert post(c,'/readings/'+r['id']+'/draw',dict(index=0,expected=0)).status_code==409
 o=c.get('/api/history').json['orders'][0]
 assert post(c,'/orders/'+o['id']+'/proof',dict(channel='tng',proof='transfer123')).json['status']=='submitted'
 assert post(admin,'/admin/orders/'+o['id'],dict(action='approve',reference='receipt123')).status_code==200
 assert post(admin,'/admin/orders/'+o['id'],dict(action='approve',reference='receipt123')).status_code==409
 assert c.get('/api/readings/'+r['id']).json['status']=='drawing'
 assert post(admin,'/admin/settings',dict(billing=False),'PUT').status_code==200
 assert c.get('/api/readings/'+r['id']).json['status']=='drawing'

def test_budget_atomic_idempotence(admin):
 assert post(admin,'/admin/settings',dict(api_key='test-key',input_price=1,output_price=2,daily_budget=30),'PUT').status_code==200
 c=user('aiuser');r=draw_all(c,reading(c))
 assert post(c,'/readings/'+r['id']+'/generate').json['status']=='generating'
 before=admin.get('/api/admin/settings').json['budgets']
 assert post(c,'/readings/'+r['id']+'/generate').json['status']=='generating'
 assert admin.get('/api/admin/settings').json['budgets']==before
 d=user('budgetuser');q=draw_all(d,reading(d))
 assert post(admin,'/admin/settings',dict(daily_budget=.000001),'PUT').status_code==200
 assert post(d,'/readings/'+q['id']+'/generate').status_code==429

def test_ai_worker_stream(admin,monkeypatch):
 with m.engine.begin() as c:
  r=next(r for r in m.rows(c,'reading') if r['status']=='generating')
 class Response:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def raise_for_status(self):pass
  def iter_lines(self):
   yield 'data: '+json.dumps({'choices':[{'delta':{'content':'A conditional reflection.'},'finish_reason':None}]})
   yield 'data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':20}})
   yield 'data: [DONE]'
 class Client:
  def __init__(self,*a,**kw):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def stream(self,*a,**kw):return Response()
 monkeypatch.setattr(m.httpx,'Client',Client);monkeypatch.setattr(m,'model_url',lambda s:s['base_url'])
 m.run_task(r['id'])
 with m.engine.begin() as c:
  got=m.get(c,r['id']);assert got['status']=='completed';assert got['reports'][0]['text']=='A conditional reflection.'

def test_clarifier_and_transfer_privacy(admin):
 c=user('transferuser');r=draw_all(c,reading(c))
 with m.engine.begin() as conn:
  x=m.get(conn,r['id']);x['status']='completed';x['reports']=[dict(text='private AI report',at=m.now(),followup='')];m.put(conn,x['id'],'reading',x['owner'],x)
 result=post(c,'/readings/'+r['id']+'/clarify',{'question':'What can I improve?'}).json
 assert len(result['cards'])==4
 assert len({x['card']['id'] for x in result['cards']})==4
 assert post(c,'/readings/'+r['id']+'/clarify',{'question':'Again'}).status_code==409
 with m.engine.begin() as conn:
  x=m.get(conn,r['id']);x['status']='completed';m.put(conn,x['id'],'reading',x['owner'],x)
 transferred=post(c,'/readings/'+r['id']+'/transfer',{'include_reports':False}).json
 assert transferred['reports']==[]
 assert transferred['cards']==result['cards']
 assert c.get('/api/readings/'+r['id']).json['reports'][0]['text']=='private AI report'

def test_database_and_price_rejections(admin):
 assert post(admin,'/admin/database',dict(url='sqlite:////etc/passwd',save=True)).status_code==400
 assert post(admin,'/admin/settings',dict(ai_price='NaN'),'PUT').status_code==400
 assert post(admin,'/admin/settings',dict(daily_budget='NaN'),'PUT').status_code==400

def test_v2_api_rules(admin):
 c=user('v2reader')
 result=post(c,'/recommend',dict(question='我今年怎么脱单？')).json
 assert result['recommendations'][0]['spread']['id']=='relationship_action'
 r=post(c,'/readings',dict(question='年度计划',period='一年',spread='annual',start_month='2026-11',draw_method='quota',reversals=False,mode='human')).json
 assert 'orientations' not in r and 'deck' not in r
 assert r['next_pool']=='minor' and r['remaining_count']==56
 for i in range(13):
  r=post(c,'/readings/'+r['id']+'/draw',dict(index=0,expected=i)).json
 assert len(r['cards'])==13
 assert [x['card']['id']<22 for x in r['cards']]==[False]*12+[True]
 assert all(not x['reversed'] for x in r['cards'])
 assert r['spread']['positions'][2]=='2027-01'
 assert c.get('/api/readings/'+r['id']).json['cards']==r['cards']
 old=r['cards'][:]
 assert post(c,'/readings/'+r['id']+'/draw',dict(index=0,expected=12)).json['cards']==old
 assert post(c,'/readings',dict(question='三选一',period='半年',spread='three_paths',option_a='A',option_b='B')).status_code==400
