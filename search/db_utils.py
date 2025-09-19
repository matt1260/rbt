import os
import psycopg2
from contextlib import contextmanager
from django.conf import settings
import dj_database_url

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
    conn = psycopg2.connect(
        host=config['HOST'],
        database=config['NAME'],
        user=config['USER'],
        password=config['PASSWORD'],
        port=config.get('PORT', 5432)
    )
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def execute_query(query, params=None, fetch=False):
    """Execute a single query with optional parameters"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        if fetch:
            if fetch == 'one':
                return cursor.fetchone()
            elif fetch == 'all':
                return cursor.fetchall()
        
        conn.commit()
        return cursor.rowcount if not fetch else None


def execute_many(query, params_list):
    """Execute query with multiple parameter sets"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount