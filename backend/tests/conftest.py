"""Test bootstrap.

Some hosts ship a stdlib `sqlite3` linked against an old libsqlite3 (missing
`sqlite3_deserialize`), which breaks import. If the bundled `pysqlite3` wheel is installed, use
it as a drop-in `sqlite3` so the in-memory test DB works regardless of the system library. A no-op
when stdlib sqlite3 is fine.
"""

import sys

try:  # pragma: no cover - environment shim
    import sqlite3  # noqa: F401
    import sqlite3.dbapi2  # noqa: F401
except Exception:  # noqa: BLE001
    try:
        import pysqlite3  # type: ignore

        sys.modules["sqlite3"] = pysqlite3
        sys.modules["sqlite3.dbapi2"] = pysqlite3.dbapi2
    except Exception:  # noqa: BLE001
        pass
