import os

import psycopg
from pgvector.psycopg import register_vector


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ.get("POSTGRES_USER", "bikefinder"),
        password=os.environ.get("POSTGRES_PASSWORD", "bikefinder"),
        dbname=os.environ.get("POSTGRES_DB", "bikefinder"),
        autocommit=True,
    )
    register_vector(conn)
    return conn
