"""Shared fixtures: Postgres contract tests run in a throwaway schema.

Pointing the gated tests at a shared database must never pollute it — the
first server-mode run was broken by exactly that. Each test gets a
uniquely-named schema on the configured database and the schema is dropped
whole in teardown, so fixture rows cannot outlive their test whatever it
does.
"""

import os
import uuid

import pytest


@pytest.fixture()
def pg_dsn():
    base = os.environ["REFINERY_DB_URL"]
    import psycopg

    schema = f"test_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(base, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    separator = "&" if "?" in base else "?"
    yield f"{base}{separator}options=-csearch_path%3D{schema}"
    admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    admin.close()
