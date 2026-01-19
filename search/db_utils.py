import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, List, Optional, Sequence, Tuple, Union, Literal, overload, Mapping

from django.conf import settings
from django.db import connection


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

@contextmanager
def get_db_connection():
    """Context manager that yields Django's persistent database connection"""
    # Use Django's connection pool instead of creating new psycopg2 connections
    statement_timeout = int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000'))
    lock_timeout = int(os.getenv('DB_LOCK_TIMEOUT_MS', '10000'))
    
    # Set timeouts for this query session
    with connection.cursor() as cursor:
        cursor.execute(f"SET statement_timeout = {statement_timeout}")
        cursor.execute(f"SET lock_timeout = {lock_timeout}")
    
    try:
        yield connection
    except Exception as e:
        connection.rollback()
        raise e

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