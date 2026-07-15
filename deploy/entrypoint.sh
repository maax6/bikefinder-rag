#!/bin/bash
# Space boot: unpack the shipped PGDATA on first start (the Space disk is
# ephemeral, so every cold boot goes through this — it's a tar extract,
# not a restore, precisely so boots stay fast), start postgres locally,
# then hand the process over to the Gradio app.
set -euo pipefail

PGDATA=/var/lib/postgresql/data

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Unpacking database ($(du -h /opt/pgdata.tar.gz | cut -f1) archive)..."
    mkdir -p "$PGDATA"
    tar xzf /opt/pgdata.tar.gz -C "$PGDATA"
    rm -f "$PGDATA"/postmaster.pid
    chown -R postgres:postgres "$PGDATA"
    chmod 700 "$PGDATA"
fi

su postgres -c "pg_ctl -D $PGDATA -o '-c listen_addresses=localhost' -w -t 120 start"

echo "Postgres up: $(su postgres -c "psql -U bikefinder -d bikefinder -tAc 'SELECT count(*) FROM motorcycles'") motorcycles."

exec /venv/bin/python /app/src/bikefinder_rag/app.py
