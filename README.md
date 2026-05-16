 # man-db

`man_db` is a small, reusable Django app that provides management commands to manage PostgreSQL databases and backups. It was extracted from Letlaka/kasi_jobs and is intended to be dropped into Django projects that use Postgres.

## Features

- Management commands (two entry points: `man_db` and `mandb`) to perform common Postgres lifecycle tasks:
	- `create` — create the configured PostgreSQL database
	- `drop` — terminate connections and drop the database (destructive)
	- `reset` — delete local app migration files and drop the database (destructive)
	- `ping` — check that PostgreSQL is reachable
	- `backup` — create a `pg_dump` custom-format archive
	- `restore` — restore a `pg_restore` archive (destructive)

## Requirements

- Python >= 3.11
- Django >= 5.2
- `psycopg[binary]` and `structlog` (declared in `pyproject.toml`)
- `pg_dump` and `pg_restore` binaries available on `PATH` (or provided via env vars)

See `pyproject.toml` for package metadata and declared dependencies.

## Installation

Install into your project environment (editable install recommended for development):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then add `man_db` to your Django `INSTALLED_APPS`.

```py
# settings.py
INSTALLED_APPS = [
		# ...
		"man_db",
]
```

Ensure the `DATABASES[...]` entry you intend to manage uses the Postgres backend (`django.db.backends.postgresql`). The management commands read connection details from `settings.DATABASES`.

## Environment variables

- `PG_DUMP_PATH` — optional full path to the `pg_dump` executable. If unset, the command will try to find `pg_dump` on `PATH`.
- `PG_RESTORE_PATH` — optional full path to the `pg_restore` executable. If unset, the command will try to find `pg_restore` on `PATH`.
- `PGPASSWORD` — if your DB password is set in `DATABASES[...]`, the package will set `PGPASSWORD` in the subprocess environment for `pg_dump`/`pg_restore`.
- `SERVICE_NAME` / `ENVIRONMENT` — optional values used to bind contextvars for `structlog` (defaults: `man_db` / `local`).

## Usage

The package exposes two management command names that are equivalent:

```bash
python manage.py man_db <action> [options]
python manage.py mandb <action> [options]
```

Common examples:

```bash
# create the database
python manage.py man_db create

# check connectivity for a named DB alias
python manage.py man_db ping --database reporting

# create a backup (output dir, optional prefix)
python manage.py man_db backup --output-dir ./backups --prefix nightly

# restore from backup (destructive)
python manage.py man_db restore --backup ./backups/app_20260516_20260516_010203.dump --i-understand

# reset local migrations and drop DB (destructive, must pass --yes)
python manage.py man_db reset --yes
```

### Important flags

- `--yes` — required to confirm destructive actions (`drop`, `reset`).
- `--database` — Django database alias (default: `default`).
- `--output-dir` — directory to write backups to (default: `<BASE_DIR>/backups`).
- `--prefix` — optional filename prefix for backups (must be a single filename component).
- `--compression` — compression level for `pg_dump` custom format (0–9; default: 6).
- `--include-owner` — include original object owners and privileges in dumps/restores.
- `--backup` — path to the `.dump` archive to restore.
- `--create-db` — when restoring, create the DB from the archive (`-C` to `pg_restore`).
- `--jobs` — number of parallel jobs for `pg_restore` (default: 2).
- `--i-understand` — required to acknowledge destructive restore operations.

## Behavior notes

- Backup files are created with a timestamped filename. The implementation ensures generated backup paths cannot escape the requested `--output-dir`.
- Restore is destructive by default; the command refuses to run unless `--i-understand` is provided.
- `reset` deletes local migration files for apps inside your project root (using `BASE_DIR` if available, or a project-root heuristic) and then drops the configured database.

## Logging & events

Logging is implemented with `structlog`. Events are emitted with a `log_name` (Application, System, Audit) and an `event_code` (see `src/man_db/event_codes.py`). The package binds `SERVICE_NAME` and `ENVIRONMENT` context variables if present.

If you want to see or persist these structured logs, configure `structlog`/the stdlib logger in your project as you would normally.

## Running tests

The repository includes unit tests that use Django's test framework. To run tests locally:

```bash
python -m pip install -e .
python -m pytest -q
```

Tests rely on `DJANGO_SETTINGS_MODULE` being set to `tests.settings`, which the test modules set by default.

## Development and contributing

- Fork and open a PR with a clear description of the change.
- Keep changes focused and include tests for new behavior.
- Run the test suite before submitting: `python -m pytest`.

## License

This project is licensed under the MIT License (see `pyproject.toml`).

## Author

Letlaka

---

If you'd like, I can also add a short `USAGE.md` or expand the `pyproject.toml` metadata (authors, classifiers) and add a `CONTRIBUTING.md` template. Would you like that next?
