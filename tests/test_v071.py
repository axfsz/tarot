import os,sys,tempfile
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m
from catalog import SPREADS

def test_relationship_action_is_a_quincunx():
 sp=next(s for s in SPREADS if s['id']=='relationship_action')
 assert sp['layout']=='quincunx' and len(sp['positions'])==5
 # centre card plus four corners
 assert sp['coordinates'][0]==[2,2] and sorted(map(tuple,sp['coordinates'][1:]))==[(1,1),(1,3),(3,1),(3,3)]

def test_every_spread_has_one_coordinate_per_position():
 for sp in SPREADS:assert len(sp['coordinates'])==len(sp['positions']),sp['id']

def test_report_bold_is_rendered_and_escaped():
 html=str(m.format_report('## 核心 **回应**\n\n它指出：**关键在你** <x>\n\n- **我的模式｜星币国王**：稳定\n\n孤立的 ** 符号'))
 assert '<h3>核心 <strong>回应</strong></h3>' in html
 assert '<strong>关键在你</strong> &lt;x&gt;' in html
 assert '<li><strong>我的模式｜星币国王</strong>：稳定</li>' in html
 assert '**' not in html
