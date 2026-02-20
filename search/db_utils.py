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
    """Context manager that yields Django's persistent database connection

    Ensures a safe default `search_path` is set when the connection is handed
    to callers and restores it when the context exits. This prevents
    session-level `SET search_path` calls from leaking into subsequent
    requests when Django's DB connections are pooled.
    """
    # Use Django's connection pool instead of creating new psycopg2 connections
    statement_timeout = int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000'))
    lock_timeout = int(os.getenv('DB_LOCK_TIMEOUT_MS', '10000'))

    # Set timeouts and ensure default search_path for this session
    with connection.cursor() as cursor:
        cursor.execute(f"SET statement_timeout = {statement_timeout}")
        cursor.execute(f"SET lock_timeout = {lock_timeout}")
        # Ensure default schema resolution order (user, public) on checkout
        cursor.execute("SET search_path TO \"$user\", public")

    try:
        yield connection
    finally:
        # Reset ephemeral session settings (especially search_path) so that
        # one request's schema changes do not affect other requests.
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO \"$user\", public")
        except Exception:
            # If reset fails, rollback to keep connection usable
            try:
                connection.rollback()
            except Exception:
                pass


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


# --- Safe cache helpers -------------------------------------------------
from django.core.cache import cache
from django.db import DatabaseError, ProgrammingError
import logging

logger_verbose = logging.getLogger("search.db_utils.verbose")

# If the DB cache table is missing in a given environment, repeated cache calls
# will raise ProgrammingError and can leave the DB connection in an aborted
# transaction state until rollback. Detect once and short-circuit subsequent
# cache operations for this process.
_db_cache_disabled_reason: str | None = None


def _maybe_disable_db_cache_from_exception(exc: Exception) -> bool:
    global _db_cache_disabled_reason
    if _db_cache_disabled_reason:
        return True

    msg = str(exc)
    if 'django_cache_table' in msg and ('does not exist' in msg or 'UndefinedTable' in msg):
        _db_cache_disabled_reason = msg
        logger_verbose.warning('DB cache disabled (missing table): %s', msg)
        return True

    return False

def safe_cache_get(key, default=None):
    """Safely get value from Django cache, handling DB cache failures gracefully."""
    if _db_cache_disabled_reason:
        return default
    try:
        return cache.get(key, default)
    except (DatabaseError, ProgrammingError, Exception) as e:
        _maybe_disable_db_cache_from_exception(e)
        logger_verbose.exception('safe_cache_get failed for key=%s: %s', key, e)
        try:
            connection.rollback()
            logger_verbose.debug('safe_cache_get: connection.rollback() executed')
        except Exception:
            logger_verbose.exception('safe_cache_get: rollback failed')
        return default


def safe_cache_set(key, value, timeout=None):
    """Safely set value in Django cache, handling DB cache failures gracefully."""
    if _db_cache_disabled_reason:
        return False
    try:
        cache.set(key, value, timeout)
        return True
    except (DatabaseError, ProgrammingError, Exception) as e:
        _maybe_disable_db_cache_from_exception(e)
        logger_verbose.exception('safe_cache_set failed for key=%s: %s', key, e)
        try:
            connection.rollback()
            logger_verbose.debug('safe_cache_set: connection.rollback() executed')
        except Exception:
            logger_verbose.exception('safe_cache_set: rollback failed')
        return False


def safe_cache_delete(key):
    if _db_cache_disabled_reason:
        return False
    try:
        cache.delete(key)
        return True
    except (DatabaseError, ProgrammingError, Exception) as e:
        _maybe_disable_db_cache_from_exception(e)
        logger_verbose.exception('safe_cache_delete failed for key=%s: %s', key, e)
        try:
            connection.rollback()
            logger_verbose.debug('safe_cache_delete: connection.rollback() executed')
        except Exception:
            logger_verbose.exception('safe_cache_delete: rollback failed')
        return False