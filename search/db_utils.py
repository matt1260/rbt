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
    """Context manager that yields Django's persistent database connection.

    Statement/lock timeouts are configured at connection-creation time via
    Django's DATABASES['OPTIONS'] setting to avoid per-call round-trips.
    Resets ``search_path`` on exit so schema changes don't leak across requests
    when Django's DB connections are pooled.
    """
    try:
        yield connection
    finally:
        # Reset search_path so schema changes don't leak into subsequent requests.
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
import time

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


# --- Render-cache invalidation ------------------------------------------
# A cached chapter render is built from data (verses + footnotes) that a
# background translation job may be writing at the same moment. Deleting the
# cache key when that job finishes is not enough on its own: a render that
# STARTED before the job finished can reach its cache-set AFTER the delete and
# put pre-translation (English) content back, where it then serves until the
# entry expires -- the "I translated the chapter but it's still English" bug.
#
# So invalidation also stamps a timestamp, and renders write through
# safe_cache_set_if_fresh(), which drops the write if an invalidation landed
# while the render was in flight.

_INVALIDATION_TTL = 7 * 24 * 60 * 60  # outlives any plausible in-flight render


def _invalidation_key(cache_key):
    return f'{cache_key}__invalidated_at'


def cache_invalidated_at(cache_key):
    """Unix time of the last invalidation of `cache_key` (0.0 if none recorded)."""
    try:
        return float(safe_cache_get(_invalidation_key(cache_key), 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def invalidate_cached_render(cache_key):
    """Drop a cached render and record when, so a render already in flight can't
    overwrite it with content built before this invalidation."""
    deleted = safe_cache_delete(cache_key)
    safe_cache_set(_invalidation_key(cache_key), time.time(), _INVALIDATION_TTL)
    return deleted


def safe_cache_set_if_fresh(cache_key, value, started_at, timeout=None):
    """safe_cache_set() that no-ops when `cache_key` was invalidated after
    `started_at` -- i.e. when the value being written is already stale."""
    if started_at is not None and cache_invalidated_at(cache_key) > started_at:
        logger_verbose.debug('Skipping stale cache write for key=%s', cache_key)
        return False
    return safe_cache_set(cache_key, value, timeout)