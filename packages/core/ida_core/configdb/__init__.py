"""The database as the source of truth for configuration (admin console, AD-6).

``tables``   the ORM (registered on ``ida_core.db.Base``)
``seed``     ``ensure_seeded``: YAML -> rows, once, under an advisory lock
``reader``   rows -> the same documents the YAML loaders produce
``cli``      ``python -m ida_core.configdb diff|import``

⚠ Keep this ``__init__`` import-free: ``ida_core.db`` imports ``tables`` while
it is itself being imported, so anything here that imported ``ida_core.db``
back would be a cycle.
"""
