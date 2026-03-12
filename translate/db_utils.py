import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, List, Optional, Sequence, Tuple, Union, Literal, overload, Mapping

import psycopg2
import psycopg2.extras
from django.conf import settings
from django.db import connection


RowType = Tuple[Any, ...]
FetchMode = Optional[Literal['one', 'all']]
ParamsType = Optional[Union[Sequence[Any], Mapping[str, Any]]]


@overload
def execute_query(
    query: str,
    params: ParamsType = ...,
    fetch: Literal['one'] = ...,
) -> Optional[RowType]:
    ...


@overload
def execute_query(
    query: str,
    params: ParamsType = ...,
    fetch: Literal['all'] = ...,
) -> List[RowType]:
    ...


@overload
def execute_query(
    query: str,
    params: ParamsType = ...,
    fetch: None = ...,
) -> int:
    ...

@contextmanager
def get_db_connection():
    """Context manager that yields Django's persistent database connection.

    Resets ``search_path`` to the default (``"$user", public``) on both
    entry and exit so that callers which temporarily switch schemas (e.g.
    ``SET LOCAL search_path TO joseph_aseneth``) cannot leak that setting
    into subsequent requests via Django's pooled connection.
    """
    # Use Django's connection pool instead of creating new psycopg2 connections
    statement_timeout = int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000'))
    lock_timeout = int(os.getenv('DB_LOCK_TIMEOUT_MS', '10000'))

    # Set timeouts and ensure default search_path for this session
    with connection.cursor() as cursor:
        cursor.execute(f"SET statement_timeout = {statement_timeout}")
        cursor.execute(f"SET lock_timeout = {lock_timeout}")
        # Ensure default schema resolution order on checkout (mirrors search/db_utils.py)
        cursor.execute('SET search_path TO "$user", public')

    try:
        yield connection
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        # Always restore default search_path on return so future callers
        # (e.g. Django session/auth ORM queries) find tables in `public`.
        try:
            with connection.cursor() as cursor:
                cursor.execute('RESET search_path')
        except Exception:
            pass

@contextmanager
def get_aseneth_connection():
    """Open a dedicated standalone psycopg2 connection scoped to the
    ``joseph_aseneth`` schema.

    This creates a **new** connection instead of reusing Django's pooled
    connection, so transactions or schema changes here never bleed into
    other Django ORM queries (sessions, auth, cache, etc.).
    """
    db_cfg = settings.DATABASES['default']
    conn = psycopg2.connect(
        host=db_cfg.get('HOST', 'localhost'),
        port=db_cfg.get('PORT', 5432) or 5432,
        user=db_cfg.get('USER', ''),
        password=db_cfg.get('PASSWORD', ''),
        dbname=db_cfg.get('NAME', ''),
        options='-c search_path=joseph_aseneth',
    )
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_judas_connection():
    """Open a dedicated standalone psycopg2 connection scoped to the
    ``gospel_of_judas`` schema.

    Like ``get_aseneth_connection``, this creates a **new** connection
    to avoid leaking schema changes into the Django ORM pool.
    """
    db_cfg = settings.DATABASES['default']
    conn = psycopg2.connect(
        host=db_cfg.get('HOST', 'localhost'),
        port=db_cfg.get('PORT', 5432) or 5432,
        user=db_cfg.get('USER', ''),
        password=db_cfg.get('PASSWORD', ''),
        dbname=db_cfg.get('NAME', ''),
        options='-c search_path=gospel_of_judas',
    )
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_query(
    query: str,
    params: ParamsType = None,
    fetch: FetchMode = None,
) -> Union[int, Optional[RowType], List[RowType]]:
    """Execute a single query with optional parameters and typed fetch modes."""

    if fetch not in (None, 'one', 'all'):
        raise ValueError("fetch must be None, 'one', or 'all'")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if params is not None:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        if fetch == 'one':
            result = cursor.fetchone()
            conn.commit()
            return result
        if fetch == 'all':
            result_list = cursor.fetchall()
            conn.commit()
            return result_list

        conn.commit()
        return cursor.rowcount

def execute_many(query, params_list):
    """Execute query with multiple parameter sets"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount


@lru_cache(maxsize=None)
def table_has_column(schema: str, table: str, column: str) -> bool:
    """Return True if the requested table column exists (cached per process)."""
    result = execute_query(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_name = %s
        );
        """,
        (schema, table, column),
        fetch='one'
    )
    return bool(result and result[0])