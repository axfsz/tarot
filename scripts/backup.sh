#!/bin/sh
set -eu
mkdir -p backups
chmod 700 backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
umask 077
docker compose exec -T db pg_dump -U tarot -d tarot -Fc > "backups/tarot-$stamp.dump"
echo "Database backup: backups/tarot-$stamp.dump"
echo 'Also back up .env and app_data securely; APP_SECRET is required to decrypt settings.'
