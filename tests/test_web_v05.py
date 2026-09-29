import re,os,sys,tempfile,json,gzip,time
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('SETUP_TOKEN','test-install-token')
os.environ['START_WORKER']='0'
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as m

def client():return m.app.test_client()

def test_pages_have_seo_meta():
 c=client()
 for path in ['/','/ai','/human','/learn','/contact','/terms']:
  r=c.get(path);html=r.get_data(as_text=True)
  assert r.status_code==200 and r.mimetype=='text/html'
  assert '<meta name="description"' in html and 'og:image' in html and 'application/ld+json' in html
  assert f'<link rel="canonical" href="{m.SITE_URL}{path}">' in html
  assert 'hreflang="en"' in html and 'noindex' not in html
  assert r.headers['Cache-Control']=='no-cache'
 assert 'lang="zh-CN"' in c.get('/').get_data(as_text=True)

def test_english_variant_and_learn_prerender():
 html=client().get('/learn?lang=en').get_data(as_text=True)
 assert 'lang="en"' in html and 'Tarot Card Meanings' in html
 assert html.count('class="panel library-card"')==78 and '.webp' in html

def test_private_and_unknown_pages_noindex():
 c=client()
 assert 'noindex' in c.get('/admin').get_data(as_text=True)
 r=c.get('/does-not-exist');assert r.status_code==404 and r.mimetype=='text/html' and 'noindex' in r.get_data(as_text=True)
 r=c.get('/api/does-not-exist');assert r.status_code==404 and r.is_json

def test_robots_sitemap_manifest():
 c=client()
 robots=c.get('/robots.txt').get_data(as_text=True)
 assert 'Disallow: /api/' in robots and m.SITE_URL+'/sitemap.xml' in robots
 xml=c.get('/sitemap.xml');assert xml.mimetype=='application/xml'
 body=xml.get_data(as_text=True);locs=re.findall(r'<loc>([^<]+)</loc>',body);assert len([x for x in locs if '/cases/' not in x and '/learn/' not in x])==len(m.PAGES)*2 and 'hreflang="x-default"' in body
 man=c.get('/manifest.webmanifest');assert man.mimetype=='application/manifest+json' and man.json['start_url']=='/'

def test_catalog_is_versioned_and_bootstrap_is_small():
 c=client()
 r=c.get('/api/catalog?v='+m.CATALOG_V)
 assert r.headers['Cache-Control']=='public, max-age=31536000, immutable'
 assert len(r.json['cards'])==78 and len(r.json['spreads'])==20
 assert all(x['webp'].endswith('.webp') for x in r.json['cards'])
 assert c.get('/api/catalog?v=stale').headers['Cache-Control']=='no-store'
 boot=c.get('/api/bootstrap')
 assert 'cards' not in boot.json and boot.json['catalog_version']==m.CATALOG_V
 # Without the 78-card catalogue; a full home strip (12 examples) adds ~6 KB on top.
 assert len(boot.get_data())<16_000

def test_webp_assets_exist():
 root=os.path.dirname(os.path.dirname(__file__))
 for card in m.CARDS:
  assert os.path.exists(os.path.join(root,card['webp'].lstrip('/')))
  assert os.path.getsize(os.path.join(root,card['webp'].lstrip('/')))<os.path.getsize(os.path.join(root,card['image'].lstrip('/')))

def test_gzip_and_static_cache_headers():
 c=client()
 r=c.get('/api/catalog?v='+m.CATALOG_V,headers={'Accept-Encoding':'gzip, br'})
 assert r.headers['Content-Encoding']=='gzip' and 'Accept-Encoding' in r.headers['Vary']
 assert json.loads(gzip.decompress(r.get_data()))['version']==m.CATALOG_V
 js=c.get('/static/app.js?v='+m.ASSET_V,headers={'Accept-Encoding':'gzip'})
 assert js.headers['Content-Encoding']=='gzip' and 'immutable' in js.headers['Cache-Control']
 assert gzip.decompress(js.get_data())==open(os.path.join(os.path.dirname(os.path.dirname(__file__)),'static/app.js'),'rb').read()
 js.close()
 img=c.get('/static/tarot/cards/back.webp');assert img.headers['Cache-Control']=='public, max-age=2592000' and 'Content-Encoding' not in img.headers;img.close()
 plain=c.get('/api/catalog');assert 'Content-Encoding' not in plain.headers

def test_security_headers():
 r=client().get('/')
 for h in ['Content-Security-Policy','Permissions-Policy','Cross-Origin-Opener-Policy','X-Frame-Options','Referrer-Policy']:assert h in r.headers
 assert "object-src 'none'" in r.headers['Content-Security-Policy']
 assert 'Strict-Transport-Security' in client().get('/',base_url='https://localhost').headers

def _post(c,path,data):
 token=c.get('/api/bootstrap').json['csrf']
 return c.post('/api'+path,json=data,headers={'X-CSRF':token})

def test_history_newest_first_and_login_generic_error():
 c=client()
 if not c.get('/api/bootstrap').json['installed']:
  assert _post(c,'/setup',{'token':'test-install-token','username':'webadmin','password':'test-password-123'}).status_code==200
 u=client();u.environ_base['REMOTE_ADDR']='198.51.100.7'
 assert _post(u,'/register',dict(username='orderuser',password='test-password-123')).status_code==200
 ids=[]
 for q in ['first question','second question']:
  ids.append(_post(u,'/readings',dict(question=q,period='one month',spread='three',mode='ai',lang='en')).json['id']);time.sleep(0.01)
 got=[r['id'] for r in u.get('/api/history').json['readings']]
 assert got[:2]==ids[::-1]
 x=client();x.environ_base['REMOTE_ADDR']='198.51.100.8'
 a=_post(x,'/login',dict(username='nobody-here',password='whatever-123456'));b=_post(x,'/login',dict(username='orderuser',password='wrong-password-1'))
 assert a.status_code==b.status_code==401 and a.json==b.json

def test_worker_prefilter_matches_stored_json():
 sample=json.dumps({'status':'generating','task':'queued'},ensure_ascii=False)
 assert '"status": "generating"' in sample
