import os
os.environ['START_WORKER']='0'
from app import DATA,engine,unseal,create_engine,get
p=DATA/'database.pending'
if not p.exists():raise SystemExit('No staged database configuration')
url=unseal(p.read_text())['url'];candidate=create_engine(url,connect_args={'connect_timeout':5})
with engine.connect() as a,candidate.connect() as b:
 if get(a,'instance')!=get(b,'instance'):raise SystemExit('Instance mismatch; refusing switch')
p.replace(DATA/'database.enc')
print('Database configuration applied. Restart the app service now.')
