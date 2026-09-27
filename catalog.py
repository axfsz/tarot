import json
from pathlib import Path
CONTENT=Path(__file__).parent / "content"
STATIC=Path(__file__).parent / "static"
CARDS=json.loads((CONTENT / "cards.json").read_text())
SPREADS=json.loads((CONTENT / "spreads.json").read_text())
# Web-optimised copies of the verified PNG artwork (same pixels, ~85% smaller).
# The PNG path stays the source of truth for provenance checks; browsers get WebP.
for _c in CARDS:
 for _k,_w in (('image','webp'),('back','back_webp')):
  _p=_c.get(_k,'')
  if not _p.endswith('.png'):continue
  # A reviewed replacement ("-safe") wins over the straight conversion. It uses a new
  # file name so browsers and CDNs never keep serving a cached copy of the old artwork.
  for _cand in (_p[:-4]+'-safe.webp',_p[:-4]+'.webp'):
   if (STATIC.parent/_cand.lstrip('/')).exists():_c[_w]=_cand;break
 # Small (120px) copies for strips and deck backs.
 for _src,_dst in (('webp','thumb'),('back_webp','back_thumb')):
  _t=_c.get(_src,'').replace('/static/tarot/cards/','/static/tarot/thumbs/')
  if _t and (STATIC.parent/_t.lstrip('/')).exists():_c[_dst]=_t
DEFAULTS=dict(brand_zh='奥普塔罗工作室',brand_en='Ops Tarot Studio',full_name='Ops Global Online Tarot Studio',tagline_zh='全球在线塔罗咨询与教学',tagline_en='Online tarot readings and learning, worldwide',timezone='Asia/Kuala_Lumpur',billing=False,charge_ai=False,charge_human=False,ai_price='0',currency='MYR',daily_budget=30.0,user_daily_limit=5,base_url='https://api.deepseek.com',model='deepseek-flash',api_key='',input_price=0.0,output_price=0.0,max_tokens=2200,contacts=[],payments=[],readers=[],packages=[dict(id='text',zh='文字报告',en='Written reading',description_zh='提交问题后，工作室联系确认交付时间与范围。',description_en='The studio will confirm scope and delivery time.',delivery_zh='48 小时内交付文字报告',delivery_en='Written report within 48 hours',price='0',enabled=True),dict(id='voice',zh='语音咨询',en='Voice consultation',description_zh='提交方便联系的时间，工作室确认预约。',description_en='Suggest a time; the studio will confirm your booking.',delivery_zh='约 30 分钟语音咨询',delivery_en='About 30 minutes by voice',price='0',enabled=True)],cases_ab_test=False,comment_review='guests')
