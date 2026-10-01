"""Address book API package.

Before anything imports sqlite3: turn off SQLite's memory statistics (DB-2).
The sqlite3 module uses a prebuilt libsqlite3 that keeps them on, so every
malloc and free takes a process-wide mutex and the reader threads serialize on
it. SQLite only accepts this setting before it initializes, and importing
sqlite3 initializes it, so this loads the library through the _sqlite3
extension's file (which doesn't import the module) and configures it first.
"""

import ctypes
import importlib.util
import logging

_SQLITE_OK = 0
_SQLITE_CONFIG_MEMSTATUS = 9

try:
    _origin = importlib.util.find_spec("_sqlite3").origin
    # Some builds (e.g. uv's standalone Pythons) compile _sqlite3 into the interpreter.
    _lib = ctypes.CDLL(None if _origin == "built-in" else _origin)
    _lib.sqlite3_config.restype = ctypes.c_int
    _rc = _lib.sqlite3_config(ctypes.c_int(_SQLITE_CONFIG_MEMSTATUS), ctypes.c_int(0))
except OSError as e:
    _rc = str(e)
if _rc != _SQLITE_OK:
    logging.getLogger("address_book").warning("could not disable SQLite memory statistics: %s", _rc)
