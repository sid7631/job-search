# Database migrations & the SQLite → Postgres swap

The schema is owned by **Alembic**. SQLAlchemy models live in
`app/database/models.py`; the database URL comes from `DB_URL` in `.env`
(read by `app/config.py` and injected into Alembic by `alembic/env.py`).

## Everyday commands

Run from `backend/` (prefix with `uv run`):

```bash
alembic upgrade head                       # build / update the DB to the latest schema
alembic current                            # show the applied revision
alembic revision --autogenerate -m "msg"   # generate a migration after changing models
alembic downgrade -1                        # roll back one revision
```

## Why this swaps cleanly

- The URL is **not** hardcoded in `alembic.ini` — `env.py` pulls it from `DB_URL`,
  so the same migrations target SQLite or Postgres with no code change.
- Migrations use `render_as_batch=True`, so ALTER operations also work on SQLite.
- The `applications.status` enum is stored as a portable `VARCHAR(20)` + CHECK
  constraint (`native_enum=False`) rather than a native Postgres `ENUM` type — so
  there is no enum-type creation/ordering to manage during the swap.
- JSON columns map to SQLite `TEXT`-backed JSON and to Postgres `JSON` automatically.

## The exact swap (SQLite → Postgres)

1. Stand up a Postgres database and install the driver:

   ```bash
   uv add "psycopg[binary]"
   ```

2. Point `DB_URL` at Postgres in `.env`:

   ```dotenv
   # from
   DB_URL=sqlite:///./job_hunter.db
   # to
   DB_URL=postgresql+psycopg://user:password@host:5432/job_hunter
   ```

3. Re-run the migrations against the new database:

   ```bash
   uv run alembic upgrade head
   ```

That builds the full schema on Postgres. This is a schema swap, **not** a data
copy — for v1 (a single user, jobs re-collected daily) starting Postgres empty is
fine. If existing rows ever need to move, dump and load them separately (e.g. with
a one-off script or `pgloader`); the application code and migrations are unaffected.
