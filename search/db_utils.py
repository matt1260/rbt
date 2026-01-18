import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, List, Optional, Sequence, Tuple, Union, Literal, overload, Mapping

import dj_database_url
import psycopg2
from django.conf import settings


RowType = Tuple[Any, ...]
FetchMode = Optional[Literal['one', 'all']]
ParamsType = Optional[Union[Sequence[Any], Mapping[str, Any]]]


@overload
def execute_query(
    query: str,
    params: Optional[Sequence[Any]] = ...,
    fetch: Literal['one'] = ...,
) -> Optional[RowType]:
    ...


@overload
def execute_query(
    query: str,
    params: Optional[Sequence[Any]] = ...,
    fetch: Literal['all'] = ...,
) -> List[RowType]:
    ...


@overload
def execute_query(
    query: str,
    params: Optional[Sequence[Any]] = ...,
    fetch: None = ...,
) -> int:
    ...

def get_db_config():
    """Get database configuration from environment or settings"""
    if 'DATABASE_URL' in os.environ:
        return dj_database_url.parse(os.environ['DATABASE_URL'])
    else:
        return settings.DATABASES['default']

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    config = get_db_config()
    connect_timeout = int(os.getenv('DB_CONNECT_TIMEOUT', '5'))
    statement_timeout = int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '12000'))
    lock_timeout = int(os.getenv('DB_LOCK_TIMEOUT_MS', '5000'))
    app_name = os.getenv('DB_APP_NAME', 'rbt-web')
    options = config.get('OPTIONS') or config.get('options') or ''
    extra_opts = f"-c statement_timeout={statement_timeout} -c lock_timeout={lock_timeout} -c application_name={app_name}"
    if options:
        options = f"{options} {extra_opts}"
    else:
        options = extra_opts
    conn = psycopg2.connect(
        host=config.get('HOST') or config.get('host'),
        database=config.get('NAME') or config.get('dbname'),
        user=config.get('USER') or config.get('user'),
        password=config.get('PASSWORD') or config.get('password'),
        port=config.get('PORT', 5432),
        connect_timeout=connect_timeout,
        options=options
    )
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        raise e
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