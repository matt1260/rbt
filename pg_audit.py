#!/usr/bin/env python3
"""
Postgres audit script for Railway diagnostics.
Reports:
- Largest tables (total, table, indexes)
- Top sequential scan tables
- Cache hit ratio
- Active connections
- Key memory settings
- Top queries (pg_stat_statements, if enabled)
"""

import os
import sys
from pathlib import Path

import dj_database_url
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


def get_db_config():
    # Load .env from project root if present
    base_dir = Path(__file__).resolve().parent
    env_path = base_dir / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

    if 'DATABASE_URL' in os.environ:
        return dj_database_url.parse(os.environ['DATABASE_URL'])
    print('ERROR: DATABASE_URL not set', file=sys.stderr)
    sys.exit(1)


def connect():
    config = get_db_config()
    return psycopg2.connect(
        host=config.get('HOST') or config.get('host'),
        database=config.get('NAME') or config.get('dbname'),
        user=config.get('USER') or config.get('user'),
        password=config.get('PASSWORD') or config.get('password'),
        port=config.get('PORT', 5432)
    )


def fetchall(cur, query, params=None):
    cur.execute(query, params or [])
    return cur.fetchall()


def main():
    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        print('\n== Largest tables (top 20) ==')
        rows = fetchall(cur, """
            SELECT schemaname,
                   relname,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                   pg_total_relation_size(relid) AS total_bytes,
                   pg_size_pretty(pg_relation_size(relid)) AS table_size,
                   pg_size_pretty(pg_indexes_size(relid)) AS index_size
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY total_bytes DESC
            LIMIT 20;
        """)
        for r in rows:
            print(f"{r['schemaname']}.{r['relname']}: total={r['total_size']} table={r['table_size']} idx={r['index_size']}")

        print('\n== Top sequential scan tables (top 20) ==')
        rows = fetchall(cur, """
            SELECT schemaname,
                   relname,
                   seq_scan,
                   idx_scan,
                   n_live_tup,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size
            FROM pg_catalog.pg_stat_user_tables
            ORDER BY seq_scan DESC
            LIMIT 20;
        """)
        for r in rows:
            print(f"{r['schemaname']}.{r['relname']}: seq={r['seq_scan']} idx={r['idx_scan']} rows={r['n_live_tup']} size={r['total_size']}")

        print('\n== Cache hit ratio ==')
        rows = fetchall(cur, """
            SELECT
                CASE WHEN sum(blks_hit + blks_read) = 0 THEN 0
                     ELSE round(100.0 * sum(blks_hit) / sum(blks_hit + blks_read), 2)
                END AS hit_ratio
            FROM pg_stat_database;
        """)
        if rows:
            print(f"Cache hit ratio: {rows[0]['hit_ratio']}%")

        print('\n== Active connections ==')
        rows = fetchall(cur, """
            SELECT state, count(*) AS count
            FROM pg_stat_activity
            GROUP BY state
            ORDER BY count DESC;
        """)
        for r in rows:
            print(f"{r['state'] or 'unknown'}: {r['count']}")

        print('\n== Memory settings ==')
        rows = fetchall(cur, """
            SELECT name, setting, unit
            FROM pg_settings
            WHERE name IN (
                'shared_buffers',
                'work_mem',
                'maintenance_work_mem',
                'effective_cache_size'
            )
            ORDER BY name;
        """)
        for r in rows:
            unit = f" {r['unit']}" if r.get('unit') else ''
            print(f"{r['name']}: {r['setting']}{unit}")

        print('\n== pg_stat_statements (if enabled) ==')
        ext = fetchall(cur, "SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements' LIMIT 1;")
        if ext:
            rows = fetchall(cur, """
                SELECT query,
                       calls,
                       round(total_time::numeric, 2) AS total_ms,
                       round(mean_time::numeric, 2) AS mean_ms
                FROM pg_stat_statements
                ORDER BY total_time DESC
                LIMIT 10;
            """)
            for r in rows:
                query = (r['query'] or '').replace('\n', ' ').strip()
                print(f"calls={r['calls']} total_ms={r['total_ms']} mean_ms={r['mean_ms']} :: {query[:160]}")
        else:
            print('pg_stat_statements not enabled')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
