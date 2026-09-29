"""Database access for the publisher worker (same database as the web app)."""
import os, json, hashlib, base64, hmac
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, Table, Column, String, Text, MetaData, select, insert, update
from . import core

DATA = Path(os.getenv('DATA_DIR', '/data'))          # the web app's volume (read-only here)
SECRET = os.getenv('APP_SECRET') or ((DATA / 'secret').read_text().strip() if (DATA / 'secret').exists() else '')
crypt = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest())) if SECRET else None


def _url():
    f = DATA / 'database.enc'
    if f.exists() and crypt:
        return json.loads(crypt.decrypt(f.read_text().encode()))['url']
    return os.getenv('DATABASE_URL', f'sqlite:///{DATA}/app.db')


URL = _url()
engine = create_engine(URL, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False, 'timeout': 30}} if URL.startswith('sqlite') else {}))
meta = MetaData()
records = Table('records', meta, Column('id', String(80), primary_key=True), Column('kind', String(40), index=True),
                Column('owner', String(80), index=True), Column('payload', Text, nullable=False))
jobs = core.table(meta)
meta.create_all(engine)


def get(c, id):
    r = c.execute(select(records.c.payload).where(records.c.id == id)).scalar()
    return json.loads(r) if r else None


def put(c, id, kind, owner, data):
    value = json.dumps(data, ensure_ascii=False)
    if get(c, id) is not None:
        c.execute(update(records).where(records.c.id == id).values(payload=value))
    else:
        c.execute(insert(records).values(id=id, kind=kind, owner=owner, payload=value))


def settings_tz(c):
    """Studio time zone from the (encrypted) settings record."""
    v = get(c, 'settings')
    try:
        return json.loads(crypt.decrypt(v['encrypted'].encode())).get('timezone') or 'Asia/Kuala_Lumpur'
    except Exception:
        return 'Asia/Kuala_Lumpur'


def token():
    """Shared secret for app → worker calls on the private compose network."""
    return hmac.new(SECRET.encode(), b'publisher-api', hashlib.sha256).hexdigest()
