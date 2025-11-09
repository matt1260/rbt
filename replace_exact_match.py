import os
import sys
import psycopg2

"""
Simple script to replace exact matches of words
in the joseph_aseneth.aseneth table (english column).

Connection order of preference:
1) DATABASE_URL env var (postgres://user:pass@host:port/db)
2) Individual env vars: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
   Defaults: rbt / current user / "" / localhost / 5432

Usage:
  python aseneth_replace_he_is_adding.py
"""


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    # Fallback to individual env vars (similar to other local scripts)
    dbname = os.getenv("DB_NAME", "rbt")
    dbuser = os.getenv("DB_USER", os.getenv("USER", ""))
    dbpass = os.getenv("DB_PASSWORD", "")
    dbhost = os.getenv("DB_HOST", "localhost")
    dbport = os.getenv("DB_PORT", "5432")

    if not dbuser:
        print("ERROR: Neither DATABASE_URL nor DB_USER provided.\n"
              "Set DATABASE_URL or DB_* env vars (DB_NAME/USER/PASSWORD/HOST/PORT).")
        sys.exit(1)

    return psycopg2.connect(dbname=dbname, user=dbuser, password=dbpass, host=dbhost, port=dbport)


def main():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure we are operating in the joseph_aseneth schema
                cur.execute("SET search_path TO joseph_aseneth")

                target = "He is Adding"
                replacement = "He Adds"

                # Preview count
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM aseneth
                    WHERE english LIKE %s
                    """,
                    (f"%{target}%",)
                )
                (to_update_count,) = cur.fetchone()
                print(f"Rows containing '{target}': {to_update_count}")

                # Perform targeted update on english column (substring replace)
                cur.execute(
                    """
                    UPDATE aseneth
                    SET english = REPLACE(english, %s, %s)
                    WHERE english LIKE %s
                    """,
                    (target, replacement, f"%{target}%")
                )
                updated = cur.rowcount
                print(f"Updated rows: {updated}")

                # Commit is automatic with context manager on success
    except psycopg2.Error as e:
        print("PostgreSQL error:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
