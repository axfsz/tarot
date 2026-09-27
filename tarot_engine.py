"""Versioned course rules. Pure drawing helpers shared by HTTP endpoints and tests."""
import copy,re,secrets
from datetime import date
from catalog import CARDS,SPREADS

VERSION='ops-tarot-rules-2.0'
METHODS=('mixed','major','minor','quota')
class RuleError(ValueError):pass

def int_field(value):
 if isinstance(value,bool):raise RuleError('Integer required / 必须填写整数')
 try:
  i=int(value)
  if str(i)!=str(value):raise ValueError()
  return i
 except (ValueError,TypeError):raise RuleError('Integer required / 必须填写整数')

def month_at(start,offset):
 try:
  if not re.fullmatch(r'\d{4}-\d{2}',start):raise ValueError()
  year,month=map(int,start.split('-'));date(year,month,1)
  idx=year*12+month-1+offset;date(idx//12,idx%12+1,1)
 except (ValueError,TypeError):raise RuleError('Valid YYYY-MM required / 请填写有效起始年月')
 return f'{idx//12:04d}-{idx%12+1:02d}'

def snapshot(spread,data):
 sp=copy.deepcopy(spread)
 if sp.get('option_count'):
  for k in ['option_a','option_b','option_c'][:sp['option_count']]:
   if not str(data.get(k,'')).strip():raise RuleError('Define every option / 请填写所有选项')
 if sp.get('needs_start_month'):
  start=str(data.get('start_month',''))
  month_at(start,11)
  if sp['id']=='annual':
   sp['positions']=[month_at(start,i) for i in range(12)]+['年度主题']
   sp['positions_en']=[month_at(start,i) for i in range(12)]+['Year theme']
  elif sp['id']=='timeline':
   sp['positions']=['现在']+[month_at(start,i) for i in range(3)]
   sp['positions_en']=['Now']+[month_at(start,i) for i in range(3)]
  else:
   for q in range(4):
    period=f'{month_at(start,q*3)} ~ {month_at(start,q*3+2)}'
    for k in range(3):
     sp['positions'][q*3+k]+=f' ({period})';sp['positions_en'][q*3+k]+=f' ({period})'
  sp['start_month']=start
 return sp

def initialize(sp,data):
 method=data.get('draw_method','mixed')
 if method not in METHODS:raise RuleError('Invalid drawing method / 抽牌方式无效')
 rev=data.get('reversals',True)
 if not isinstance(rev,bool):raise RuleError('Reversals must be true/false / 正逆位开关无效')
 pool=data.get('clarifier_pool','minor' if method=='quota' else method)
 if pool=='mixed':pool='all'
 if pool not in ('all','major','minor'):raise RuleError('Invalid clarifier pool / 补牌牌池无效')
 if method=='major' and pool!='major' or method=='minor' and pool!='minor':raise RuleError('Clarifier must use the same pool / 补牌需使用原牌池')
 deck=[c['id'] for c in CARDS if method not in ('major','minor') or (c['id']<22)==(method=='major')]
 if len(deck)<len(sp['positions']):raise RuleError('Insufficient cards / 牌池不足')
 secrets.SystemRandom().shuffle(deck)
 return dict(rule_version=VERSION,draw_method=method,reversals=rev,reverse_probability=.5 if rev else 0,clarifier_pool=pool,deck=deck,orientations={str(i):bool(secrets.randbits(1)) if rev else False for i in deck},shuffle_count=1,cut=False)

def eligible(r,clarifier=False):
 pool=r.get('clarifier_pool','all') if clarifier else 'all'
 if not clarifier and r.get('draw_method')=='quota':
  i=len(r['cards'])
  if i>=r['spread'].get('base_count',len(r['spread']['positions'])):return []
  pool=r['spread']['quota_pools'][i]
 return [cid for cid in r['deck'] if pool=='all' or (cid<22)==(pool=='major')]

def take(r,index,clarifier=False):
 options=eligible(r,clarifier)
 if not 0<=index<len(options):raise RuleError('Invalid card selection / 选牌位置无效')
 cid=options[index];r['deck'].remove(cid)
 # Pre-v0.2 sessions have no saved orientations for undrawn cards; assign once on draw.
 reverse=r.get('orientations',{}).get(str(cid))
 if reverse is None:reverse=bool(r['reversals'] and secrets.randbits(1))
 position=len(r['cards'])+1
 result=dict(card=copy.deepcopy(CARDS[cid]),reversed=reverse,position=position,display_rotation=90 if position in r['spread'].get('horizontal_positions',[]) and not clarifier else 0)
 r['cards'].append(result)
 return result

def cut_deck(r,index):
 if not 1<=index<len(r['deck']):raise RuleError('Invalid cut position / 切牌位置超出牌池')
 r['deck']=r['deck'][index:]+r['deck'][:index];r['cut']=True;r['cut_position']=index

FEATURES={
 'relationship':r'感情|关系|恋爱|复合|暧昧|伴侣|分手|爱我|想我|relationship|romance|partner|love|breakup|reconcil',
 'connection':r'脱单|单身|认识新|dating|single|meet someone',
 'career':r'事业|工作|求职|面试|转职|跳槽|职业|offer|career|job|interview|employment',
 'execution':r'同时|两份工作|兼顾|兼职|执行|减负|多任务|two jobs|multitask|workload|execution',
 'daily':r'今天|今日|每日|提醒|daily|today|reminder',
 'action':r'行动|尝试|改善|下一步|action|next step|improve',
 'past':r'过去|复盘经历|前因后果|past|history|previous',
 'complex':r'综合|全面|深入|深度|多因素|长期|复杂|complex|comprehensive|in.depth|long.term',
 'timeline':r'三个月|阶段|时间线|分期|three months|timeline|stages',
 'annual':r'年度|全年|十二个月|12个月|每个月|annual|year ahead|12 months|twelve months',
 'quarters':r'季度|quarter',
 'houses':r'十二宫|12宫|生活领域|生活平衡|各个领域|life areas|houses|life balance',
 'choice':r'二选一|选择[ABＡＢ]|选[ABＡＢ]|两个选项|两种方案|还是|比较|对比|choose|versus|\bvs\b|two options|between',
 'three_paths':r'三选一|三路线|三个方案|三个选择|三种选择|三个选项|three options|three paths|three alternatives'
}
CANDIDATES={
 'relationship':['relationship','relationship_six','relationship_action','cross','celtic'],
 'connection':['relationship_action','relationship','relationship_six'],
 'career':['career','three','cross','nine','celtic'],
 'execution':['execution','action','nine','timeline','celtic'],
 'daily':['one','two','three'],
 'action':['action','two','execution','three'],
 'past':['past_present','horseshoe','cross'],
 'complex':['celtic','nine','horseshoe','cross'],
 'timeline':['timeline','past_present','annual'],
 'annual':['annual'], 'quarters':['quarters'], 'houses':['houses'],
 'choice':['choice'], 'three_paths':['three_paths']}
REASONS={
 'relationship':('聚焦双方已表达的需要、可观察互动和沟通','Focuses on expressed needs, observed interaction and communication'),
 'connection':('聚焦建立新连接所需的资源和行动','Explores resources and actions for new connections'),
 'career':('对应职业主题、资源、阻力与准备行动','Covers career themes, resources, constraints and preparation'),
 'execution':('先检查并行任务的执行条件与减负方式','Examines conditions and workload for parallel commitments'),
 'daily':('问题范围较小，适合少量牌形成行动焦点','A focused question benefits from a small spread'),
 'action':('将目标、行动和观察结果连接起来','Connects goals, actions and observable changes'),
 'past':('将已知经历、当前处境与后续观察串联','Links known history, the present and further observation'),
 'complex':('需要分组联读多个条件，并保留不确定性','Supports grouped reading of multiple conditions'),
 'timeline':('用预先指定的阶段讨论观察重点','Uses predefined stages as observation points'),
 'annual':('逐月牌位与年度主题相互配合','Combines monthly positions with a yearly theme'),
 'quarters':('每季度包含主题、行动和限制','Each quarter includes a theme, action and limitation'),
 'houses':('按生活领域盘点，不按月份预测','Reviews life areas rather than months'),
 'choice':('两个选项采用对称牌位与相同观察区间','Uses symmetrical positions and the same horizon for two options'),
 'three_paths':('三个选项采用相同的机会、代价、行动标准','Compares three options using equal criteria')}

def recommend(question,topic='auto',depth='auto',option_count=0):
 if topic not in ['auto']+list(FEATURES):raise RuleError('Invalid topic')
 if depth not in ('auto','beginner','intermediate','advanced'):raise RuleError('Invalid level')
 if option_count not in (0,2,3):raise RuleError('Option count must be 0, 2 or 3')
 hits=[k for k,pattern in FEATURES.items() if re.search(pattern,question,re.I)]
 if topic!='auto' and topic not in hits:hits.append(topic)
 primary=topic if topic!='auto' else next((k for k in ['three_paths','houses','quarters','annual','choice','execution','connection','daily','relationship','career','past','timeline','complex','action'] if k in hits),'general')
 if option_count:primary='three_paths' if option_count==3 else 'choice'
 scores={};why={}
 for feature in hits:
  for rank,id in enumerate(CANDIDATES[feature]):
   scores[id]=scores.get(id,0)+max(1,10-rank*2);why.setdefault(id,feature)
 preferred=CANDIDATES.get(primary,['three','cross','nine','celtic'])
 for rank,id in enumerate(preferred):scores[id]=scores.get(id,0)+50-rank*5;why[id]=primary
 # These structures must not be replaced with an incompatible lower-level spread.
 strict=primary in ('three_paths','choice','houses','annual','quarters')
 result=[]
 for sp in SPREADS:
  if depth!='auto' and sp['level']!=depth:continue
  if strict and sp['id'] not in preferred:continue
  if sp['id'] not in scores:continue
  feature=why.get(sp['id'],'general');reason=REASONS.get(feature,('问题较宽泛，先用现状、阻碍和行动梳理','Start by exploring the situation, challenge and action'))
  result.append(dict(spread=sp,score=scores[sp['id']],reason_zh=reason[0],reason_en=reason[1]))
 result.sort(key=lambda x:(-x['score'],x['spread']['base_count']))
 missing=[]
 if primary in ('choice','three_paths'):missing.append('options')
 if primary in ('annual','quarters','timeline'):missing.append('start_month')
 return dict(rule_version=VERSION,primary=primary,matched_features=hits,recommendations=result[:3],needs=missing,notice_zh='推荐基于问题结构，不代表牌更多或等级更高就更准确。'+('当前级别没有合适结构，请切换“自动”或手动选择。' if not result else ''),notice_en='Recommendations reflect question structure, not predictive accuracy.'+(' No suitable spread at this level; switch to Auto or choose manually.' if not result else ''))
