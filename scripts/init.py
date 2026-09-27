from pathlib import Path
import secrets
p=Path('.env')
if p.exists():raise SystemExit('.env exists; not overwritten.')
p.write_text('\n'.join([f'POSTGRES_PASSWORD={secrets.token_hex(24)}',f'APP_SECRET={secrets.token_urlsafe(48)}',f'SETUP_TOKEN={secrets.token_urlsafe(24)}','APP_PORT=8080','COOKIE_SECURE=0','']))
p.chmod(0o600)
print('Created .env. Read SETUP_TOKEN locally to initialize admin. Do not share this file.')
