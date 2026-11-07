from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row},
)


@contextmanager
def transaction() -> Iterator[Connection]:
    """Borrow a pooled connection; commits on success, rolls back on error."""
    with pool.connection() as conn:
        yield conn
