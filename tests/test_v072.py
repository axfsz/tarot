import os,sys,tempfile,json
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest

ip=[40]
def client(addr=None,ua='pytest'):
 c=m.app.test_client();ip[0]+=1;c.environ_base['REMOTE_ADDR']=addr or f'198.19.0.{ip[0]}';c.environ_base['HTTP_USER_AGENT']=ua
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
 return c
def member(name):
 c=client();assert post(c,'/register',dict(username=name,password='eight888')).status_code==200
 return c
def published(admin,owner,spread='three',n=3):
 r=post(owner,'/readings',dict(question='下个月的工作重点在哪里',period='一个月',spread=spread,mode='ai',lang='zh')).json
 for i in range(n):r=post(owner,f"/readings/{r['id']}/draw",dict(index=0,expected=i)).json
 with m.engine.begin() as conn:
  x=m.get(conn,r['id']);x.update(status='completed',reports=[dict(text='## 核心回应\n\n专注。',at=m.now(),followup='')]);m.put(conn,x['id'],'reading',x['owner'],x)
 slug=post(owner,f"/readings/{r['id']}/share",dict(consent=True)).json['share']['slug']
 assert post(admin,f'/admin/cases/{slug}',dict(question='工作重点',summary='先聚焦一个方向。',confirmed=True,action='publish'),'PUT').status_code==200
 return slug,r['id']

def test_likes_toggle_once_per_visitor(admin):
 u=member('likeowner');slug,_=published(admin,u)
 v=client('203.0.113.9')
 assert post(v,f'/cases/{slug}/like',dict(like='yes')).status_code==400
 assert post(v,f'/cases/{slug}/like',dict(like=True)).json==dict(likes=1,liked=True)
 assert post(v,f'/cases/{slug}/like',dict(like=True)).json['likes']==1   # same device: no double count
 assert post(client('203.0.113.9'),f'/cases/{slug}/like',dict(like=True)).json['likes']==1
 assert post(client('203.0.113.10'),f'/cases/{slug}/like',dict(like=True)).json['likes']==2
 assert v.get(f'/api/cases/{slug}/comments').json['liked'] is True
 assert post(v,f'/cases/{slug}/like',dict(like=False)).json==dict(likes=1,liked=False)
 assert client().get(f'/api/cases/{slug}').json['likes']==1
 html=client('203.0.113.10').get(f'/cases/{slug}').get_data(as_text=True)
 assert 'class="like-btn on"' in html and 'aria-pressed="true"' in html
 assert post(client(),'/cases/ffffffff/like',dict(like=True)).status_code==404

def test_comments_guest_review_member_direct(admin):
 u=member('cmowner');slug,_=published(admin,u)
 g=client()
 r=post(g,f'/cases/{slug}/comments',dict(text='很有启发，谢谢分享',name='小雨')).json
 assert r['status']=='pending' and r['comment']['status']=='pending' and r['comment']['mine'] is True   # echoed back to its author only
 assert client().get(f'/api/cases/{slug}/comments').json['items']==[]
 mem=member('cmreader');r=post(mem,f'/cases/{slug}/comments',dict(text='我也遇到类似的选择')).json
 assert r['status']=='published' and r['comment']['badge']=='member' and r['comment']['name']==''
 own=post(u,f'/cases/{slug}/comments',dict(text='半年后回来看，确实先聚焦是对的')).json
 assert own['comment']['badge']=='asker'
 st=post(admin,f'/cases/{slug}/comments',dict(text='谢谢反馈')).json;assert st['comment']['badge']=='studio'
 items=client().get(f'/api/cases/{slug}/comments').json['items'];assert len(items)==3
 assert all(set(x)=={'id','name','badge','text','date','mine','status'} for x in items)
 assert not any('who' in x or 'uid' in x for x in items)
 assert client().get(f'/api/cases/{slug}').json['comments']==3
 # the reviewer approves the guest comment
 pend=[x for x in admin.get('/api/admin/comments').json['items'] if x['slug']==slug and x['status']=='pending']
 assert len(pend)==1 and pend[0]['name']=='小雨'
 assert post(client(),f"/admin/comments/{pend[0]['id']}",dict(action='approve'),'PUT').status_code in (401,403)
 assert post(admin,f"/admin/comments/{pend[0]['id']}",dict(action='approve'),'PUT').status_code==200
 html=client().get(f'/cases/{slug}').get_data(as_text=True)
 assert '小雨' in html and html.count('class="comment"')==4 and '提问者本人' in html
 assert client().get(f'/api/cases/{slug}').json['comments']==4
 assert post(admin,f"/admin/comments/{pend[0]['id']}",dict(action='hide'),'PUT').status_code==200
 assert client().get(f'/api/cases/{slug}').json['comments']==3

def test_comment_safety(admin):
 u=member('cmsafe');slug,_=published(admin,u)
 mem=member('cmsafe2')
 assert post(mem,f'/cases/{slug}/comments',dict(text='加我微信 @tarot_fan 聊')).json['status']=='pending'
 assert post(mem,f'/cases/{slug}/comments',dict(text='要不要买比特币')).json['status']=='pending'
 assert post(mem,f'/cases/{slug}/comments',dict(text='x')).status_code==400
 assert post(mem,f'/cases/{slug}/comments',dict(text='a'*301)).status_code==400
 bot=post(client(),f'/cases/{slug}/comments',dict(text='cheap pills',website='http://spam'))
 assert bot.json['status']=='pending' and not any('pills' in x['text'] for x in admin.get('/api/admin/comments').json['items'])
 flood=client()
 codes=[post(flood,f'/cases/{slug}/comments',dict(text=f'第{i}条评价')).status_code for i in range(7)]
 assert codes[:5]==[200]*5 and codes[-1]==429
 assert post(member('cmxss'),f'/cases/{slug}/comments',dict(text='<script>alert(1)</script>好',name='<b>x</b>')).json['status']=='published'
 html=client().get(f'/cases/{slug}').get_data(as_text=True);assert '<script>alert' not in html and '&lt;script&gt;alert(1)&lt;/script&gt;好' in html and '&lt;b&gt;x&lt;/b&gt;' in html

def test_review_modes(admin):
 u=member('cmmode');slug,_=published(admin,u)
 assert post(admin,'/admin/settings',dict(comment_review='nope'),'PUT').status_code==400
 try:
  assert post(admin,'/admin/settings',dict(comment_review='flagged'),'PUT').status_code==200
  assert post(client(),f'/cases/{slug}/comments',dict(text='游客直接显示')).json['status']=='published'
  assert post(admin,'/admin/settings',dict(comment_review='all'),'PUT').status_code==200
  assert post(member('cmmode2'),f'/cases/{slug}/comments',dict(text='会员也要审核')).json['status']=='pending'
  assert '所有评价经工作室审核后显示' in client().get(f'/cases/{slug}').get_data(as_text=True)
 finally:assert post(admin,'/admin/settings',dict(comment_review='guests'),'PUT').status_code==200

def test_withdraw_and_delete_purge_reactions(admin):
 u=member('cmpurge');slug,rid=published(admin,u)
 post(client(),f'/cases/{slug}/like',dict(like=True));post(member('cmpurge2'),f'/cases/{slug}/comments',dict(text='很好的案例'))
 post(u,f'/readings/{rid}/share',dict(consent=False))
 with m.engine.begin() as conn:
  assert m.rows(conn,'comment',owner=slug)==[] and m.rows(conn,'like',owner=slug)==[]
 assert client().get(f'/api/cases/{slug}/comments').status_code==410
 assert post(client(),f'/cases/{slug}/comments',dict(text='还能评论吗')).status_code==410

def test_case_page_board_share_and_cards(admin):
 u=member('celticcase');slug,_=published(admin,u,'celtic',10)
 html=client().get(f'/cases/{slug}').get_data(as_text=True)
 assert 'data-static-board' in html and 'spread-board spread-celtic' in html and html.count('data-x="')==10
 assert 'class="tarot slot-2 crossed' in html.replace(' reversed','') and 'class="cross-pos">2 / 核心挑战' in html
 assert 'data-act="case-view"' in html and 'data-zoom="in"' in html
 assert 'id="comment-form"' in html and 'name="website"' in html
 assert 'https://wa.me/?text=' in html and 'service.weibo.com' in html and f'data-copy="{m.site_url()}/cases/{slug}"' in html
 api=client().get(f'/api/cases/{slug}').json
 assert api['spread']['coordinates'][0]==api['spread']['coordinates'][1]==[2,2]
 assert [c['x'] for c in api['cards']][:2]==[2,2]
 post(client(),f'/cases/{slug}/like',dict(like=True))
 strip=client().get('/cases').get_data(as_text=True);assert 'case-counts' in strip

def test_celtic_cross_formation():
 sp=next(s for s in m.SPREADS if s['id']=='celtic')
 co=sp['coordinates'];assert co[0]==co[1] and sp['horizontal_positions']==[2]
 assert co[4][1]<co[0][1]<co[5][1] and co[2][0]<co[0][0]<co[3][0]          # above/below, left/right of the cross
 assert [c[1] for c in co[6:]]==[4,3,2,1] and len({c[0] for c in co[6:]})==1  # staff climbs bottom to top

def test_new_events_are_accepted(admin):
 c=client()
 for name in ('case_share','site_share'):assert post(c,'/events',dict(name=name)).json['ok']
 assert post(c,'/events',dict(name='case_like')).status_code==400   # recorded by the server only
