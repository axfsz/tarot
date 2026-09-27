import os,sys,tempfile
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
import pytest
from test_v072 import client,post,member,published,admin  # noqa: F401  (admin is a fixture)

def test_author_sees_own_pending_comment_and_can_follow_up(admin):
 u=member('mine1');slug,_=published(admin,u)
 g=client('203.0.113.50','phone-a')
 assert post(g,f'/cases/{slug}/comments',dict(text='第一次评价，还在审核')).json['status']=='pending'
 me=g.get(f'/api/cases/{slug}/comments').json
 assert [x['text'] for x in me['mine']]==['第一次评价，还在审核'] and me['mine'][0]['status']=='pending' and me['items']==[]
 # other visitors never see it
 other=client('203.0.113.51','phone-b').get(f'/api/cases/{slug}/comments').json
 assert other['mine']==[] and other['items']==[]
 html=client('203.0.113.50','phone-a').get(f'/cases/{slug}').get_data(as_text=True)
 assert '第一次评价，还在审核' in html and '审核中 · 仅你可见' in html and '追加评价' in html and 'data-cm-del=' in html
 page=client('203.0.113.51','phone-b').get(f'/cases/{slug}').get_data(as_text=True)
 assert '第一次评价，还在审核' not in page and '写下你的感受' in page and 'data-my-block hidden' in page
 # a follow-up is simply another comment
 assert post(g,f'/cases/{slug}/comments',dict(text='补充：后来想通了')).json['status']=='pending'
 assert len(g.get(f'/api/cases/{slug}/comments').json['mine'])==2

def test_member_comment_is_marked_mine_everywhere_and_deletable(admin):
 u=member('mine2');slug,_=published(admin,u)
 mem=member('mine3');r=post(mem,f'/cases/{slug}/comments',dict(text='会员评价直接显示')).json
 cid=r['comment']['id'];assert r['comment']['mine'] is True
 items=mem.get(f'/api/cases/{slug}/comments').json['items'];assert items[0]['mine'] is True
 assert client().get(f'/api/cases/{slug}/comments').json['items'][0]['mine'] is False
 assert 'class="comment is-mine"' in mem.get(f'/cases/{slug}').get_data(as_text=True)
 # nobody else can delete it
 assert post(client(),f'/cases/{slug}/comments/{cid}/delete').status_code==404
 assert post(member('mine4'),f'/cases/{slug}/comments/{cid}/delete').status_code==404
 d=post(mem,f'/cases/{slug}/comments/{cid}/delete');assert d.status_code==200 and d.json['comments']==0
 assert client().get(f'/api/cases/{slug}').json['comments']==0

def test_in_page_anchor_and_phone_header():
 html=client().get('/').get_data(as_text=True)
 assert 'id="header-account"' in html and 'class="menu-toggle"' in html
 js=open(os.path.join(os.path.dirname(os.path.dirname(__file__)),'static/app.js')).read()
 assert "root.dataset.ssr&&document.getElementById(location.hash.slice(1))" in js   # #case-comments is not an app route
