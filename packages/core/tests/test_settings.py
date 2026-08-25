"""Tests for the DSN normalisation.

This is a REGRESSION TEST for a live outage, not a formality. The Composition
writes a plain `postgresql://` DSN into Vault; SQLAlchemy 2.x maps that to
psycopg2, which this image does not ship. The bug was partial and therefore
confusing: the Alembic initContainer normalised the scheme on its own, so
migrations ran green while the API could not connect at all.
"""

import pytest

from ida_core.settings import Settings


def test_bare_postgres_scheme_gets_an_explicit_driver():
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.sqlalchemy_url() == "postgresql+psycopg://u:p@h:5432/db"


def test_an_explicit_driver_is_left_alone():
    s = Settings(database_url="postgresql+psycopg://u:p@h:5432/db")
    assert s.sqlalchemy_url() == "postgresql+psycopg://u:p@h:5432/db"


def test_only_the_scheme_is_rewritten():
    # A password or dbname containing the literal scheme must not be mangled --
    # `replace(..., 1)` is what guarantees that, so pin it.
    s = Settings(database_url="postgresql://u:postgresql://x@h:5432/db")
    assert s.sqlalchemy_url() == "postgresql+psycopg://u:postgresql://x@h:5432/db"


def test_raw_accessor_does_not_rewrite():
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.require_database_url() == "postgresql://u:p@h:5432/db"


def test_missing_url_fails_loudly_with_where_to_look():
    s = Settings(database_url=None)
    with pytest.raises(RuntimeError, match="ESO"):
        s.sqlalchemy_url()
