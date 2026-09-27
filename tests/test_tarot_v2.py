import copy,json,hashlib,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog import CARDS,SPREADS
import tarot_engine as e

@pytest.mark.parametrize('sid',[s['id'] for s in SPREADS])
@pytest.mark.parametrize('method',e.METHODS)
def test_every_spread_and_pool(sid,method):
 sp=next(s for s in SPREADS if s['id']==sid)
 data=dict(option_a='A',option_b='B',option_c='C',start_month='2026-11',draw_method=method,reversals=True)
 snapshot=e.snapshot(sp,data);r=dict(spread=snapshot,cards=[],**e.initialize(snapshot,data))
 initial=copy.deepcopy(r);e.cut_deck(r,1)
 for i in range(sp['base_count']):
  chosen=e.eligible(r)[-1]
  card=e.take(r,len(e.eligible(r))-1)
  assert card['reversed']==initial['orientations'][str(chosen)]
  if method=='quota':assert (card['card']['id']<22)==(i+1 in sp['quota_major'])
  if method=='major':assert card['card']['id']<22
  if method=='minor':assert card['card']['id']>=22
  assert card['display_rotation']==(90 if sid=='celtic' and i==1 else 0)
 assert len({c['card']['id'] for c in r['cards']})==sp['base_count']
 before={c['card']['id'] for c in r['cards']}
 extra=e.take(r,0,clarifier=True)
 assert extra['card']['id'] not in before
 if method=='quota':assert extra['card']['id']>=22
 assert sp['positions']==next(s for s in SPREADS if s['id']==sid)['positions']

@pytest.mark.parametrize('enabled',[True,False])
def test_orientation_policy(monkeypatch,enabled):
 values=iter([0,1]*39);monkeypatch.setattr(e.secrets,'randbits',lambda _:next(values))
 sp=next(s for s in SPREADS if s['id']=='celtic');r=dict(spread=sp,cards=[],**e.initialize(sp,dict(reversals=enabled)))
 assert sum(r['orientations'].values())==(39 if enabled else 0)
 original=dict(r['orientations']);e.cut_deck(r,21)
 assert r['orientations']==original
 for _ in range(10):e.take(r,0)
 if not enabled:assert all(not c['reversed'] for c in r['cards'])
 assert r['cards'][1]['display_rotation']==90

@pytest.mark.parametrize('q,expected',[
 ('今天我需要注意什么？','one'),('我应该选A还是B？','choice'),('Compare three options for my future','three_paths'),
 ('未来一年每个月有哪些观察重点？','annual'),('未来四季度如何规划学习？','quarters'),('盘点十二宫生活领域','houses'),
 ('今年如何脱单？','relationship_action'),('同时做两份工作需要什么条件？','execution'),('面试该准备什么？','career'),
 ('我想复盘过去经历','past_present'),('A complex comprehensive life transition','celtic'),('How can I improve communication with my partner?','relationship'),
 ('I need to review life balance','houses')])
def test_matching(q,expected):
 r=e.recommend(q);assert r['recommendations'][0]['spread']['id']==expected
 assert r['recommendations'][0]['reason_zh'] and r['recommendations'][0]['reason_en']

def test_match_structure_not_card_count():
 assert not e.recommend('年度每月规划',depth='beginner')['recommendations']
 assert e.recommend('How to prepare for work?',option_count=3)['recommendations'][0]['spread']['id']=='three_paths'
 assert all(x['spread']['level']=='intermediate' for x in e.recommend('工作',depth='intermediate')['recommendations'])
 assert e.recommend('something unclear')['recommendations'][0]['spread']['id']=='three'

def test_dates_and_validation():
 sp=next(s for s in SPREADS if s['id']=='annual');s=e.snapshot(sp,{'start_month':'2026-11'})
 assert s['positions'][0]=='2026-11' and s['positions'][2]=='2027-01' and s['positions'][11]=='2027-10'
 assert sp['positions'][0]=='第1个月'
 for bad in ['','2026-13','2026-00','x','9999-12']:
  with pytest.raises(e.RuleError):e.snapshot(sp,{'start_month':bad})
 with pytest.raises(e.RuleError):e.snapshot(next(s for s in SPREADS if s['id']=='three_paths'),dict(option_a='A',option_b='B'))
 with pytest.raises(e.RuleError):e.initialize(sp,dict(reversals='false'))
 with pytest.raises(e.RuleError):e.initialize(sp,dict(draw_method='invalid'))
 with pytest.raises(e.RuleError):e.initialize(sp,dict(draw_method='major',clarifier_pool='minor'))
 for v in ['x',1.5,True,None]:
  with pytest.raises(e.RuleError):e.int_field(v)

def test_assets_and_stable_ids():
 root=Path(__file__).resolve().parents[1]
 deck=json.loads((root/'static/tarot/deck.json').read_text())
 assert len(CARDS)==78 and len({c['id'] for c in CARDS})==78
 assert [sum(s['level']==l for s in SPREADS) for l in ['beginner','intermediate','advanced']]==[11,4,5]
 assert CARDS[22]['asset_id']=='wands-01' and CARDS[36]['asset_id']=='cups-01' and CARDS[64]['asset_id']=='pentacles-01'
 for c in CARDS:
  src=next(x for x in deck['cards'] if x['id']==c['asset_id'])
  path=root/c['image'].lstrip('/')
  assert hashlib.sha256(path.read_bytes()).hexdigest()==src['source']['sha256']
  assert c['upright'] and c['reversed_keywords']
 assert len({c['back'] for c in CARDS})==1

def test_legacy_without_orientation_map():
 sp=dict(id='three',positions=['旧1','旧2','旧3'],positions_en=['old1','old2','old3'])
 r=dict(spread=sp,cards=[dict(card=CARDS[0],reversed=False)],reversals=True,deck=list(range(1,78)))
 old=copy.deepcopy(r['cards'][0]);e.take(r,0)
 assert r['cards'][0]==old and r['cards'][1]['card']['id']==1
