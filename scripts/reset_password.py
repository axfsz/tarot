import os,getpass,hashlib
os.environ['START_WORKER']='0'
from app import engine,get,put,audit,generate_password_hash
username=input('Username: ').strip()
uid=hashlib.sha256(username.lower().encode()).hexdigest()[:32]
password=getpass.getpass('New password (12+ characters): ')
if len(password)<12:raise SystemExit('Password too short')
if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ')
with engine.begin() as c:
 u=get(c,'user:'+uid)
 if not u:raise SystemExit('User not found')
 u['version']=u.get('version',0)+1;u['password']=generate_password_hash(password);put(c,'user:'+uid,'user',uid,u);audit(c,'server-operator','password.reset',uid)
print('Password updated. Existing sessions have been revoked.')
