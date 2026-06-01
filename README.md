# man-db

`man_db` is a small, reusable Django app that provides management commands to manage PostgreSQL databases and backups. It is intended to be dropped into Django projects that use Postgres.

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

For Django projects that consume a published release, install from PyPI:

```bash
uv add man-db
# or
pip install man-db
```

For local development from this repository, use an editable install:

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

## Publishing to PyPI

For app-to-app reuse, publish `man_db` as a normal wheel/sdist to PyPI instead of installing it from a Git URL. Consumers can then install it with `uv add man-db` or `pip install man-db` and no GitHub token is required.

This repository includes [.github/workflows/publish.yml](.github/workflows/publish.yml), which builds the package on tag pushes matching `v*` and publishes it to PyPI with Trusted Publishing.

One-time setup:

1. Create the PyPI project or register a pending Trusted Publisher for `man-db`.
2. In PyPI, configure the GitHub publisher for `Letlaka/man_db`, workflow `.github/workflows/publish.yml`, and environment `pypi`.
3. In GitHub, create an environment named `pypi` and optionally require manual approval for releases.

Release flow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

PyPI itself does not support private packages. If the distribution must remain private, use a private package index instead of `pypi.org`.

## Environment variables

- `PG_DUMP_PATH` — optional absolute path to the `pg_dump` executable. If unset, the command will look for `pg_dump` on `PATH`, but only from trusted executable directories.
- `PG_RESTORE_PATH` — optional absolute path to the `pg_restore` executable. If unset, the command will look for `pg_restore` on `PATH`, but only from trusted executable directories.
- `PGPASSWORD` — if your DB password is set in `DATABASES[...]`, the package will set `PGPASSWORD` in the subprocess environment for `pg_dump`/`pg_restore`.
- `SERVICE_NAME` / `ENVIRONMENT` — optional values used to bind contextvars for `structlog` (defaults: `man_db` / `local`).

## Optional Django settings

- `MAN_DB_TRUSTED_EXECUTABLE_DIRS` — iterable of trusted directories for `pg_dump` and `pg_restore` PATH fallback. Defaults to common system binary locations such as `/usr/bin`, `/usr/local/bin`, and `/usr/lib/postgresql`.
- `MAN_DB_RESET_APP_ALLOWLIST` — iterable of app labels allowed for `reset` migration deletion when `--apps` is not passed.

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
  ## Specifying the database name

  The management commands read database connection information from your Django project's `settings.DATABASES`. The important field for create/backup/restore actions is the `NAME` value under the database alias.

  Example `settings.py` (using environment variables is recommended for secrets):

  ```py
  import os

  DATABASES = {
   "default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("DB_NAME", "my_database_name"),
    "USER": os.environ.get("DB_USER", "app_user"),
    "PASSWORD": os.environ.get("DB_PASSWORD", "secret"),
    "HOST": os.environ.get("DB_HOST", "db.example"),
    "PORT": int(os.environ.get("DB_PORT", 5432)),
   },
   "analytics": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "analytics_db",
    "USER": "analytics_user",
    "PASSWORD": "secret",
    "HOST": "db.example",
    "PORT": 5432,
   },
  }
  ```

  How the commands select the database:

- Use the `--database` option to select a Django database *alias* (default: `default`). The command reads the `NAME` from that alias.
- Example: `python manage.py man_db create --database analytics` will attempt to create the database named by `DATABASES['analytics']['NAME']`.

  Important notes:

- The `create` action requires a non-empty `NAME`. If `DATABASES[alias]['NAME']` is empty the command will raise a `CommandError` and refuse to proceed.
- For `restore`, you may use `--create-db` to tell `pg_restore` to create the database from the archive; when `--create-db` is used the command allows an empty `NAME` because the archive can provide the database name.
- Keep credentials out of source by using `os.environ.get(...)` or a secrets manager in your `settings.py`.

## check connectivity for a named DB alias

python manage.py man_db ping --database reporting

## create a backup (output dir, optional prefix)

python manage.py man_db backup --output-dir ./backups --prefix nightly

## restore from backup (destructive)

python manage.py man_db restore --backup ./backups/app_20260516_20260516_010203.dump --i-understand

## reset scoped app migrations and drop DB (destructive, must pass --yes)

python manage.py man_db reset --yes --apps my_app another_app

```python

### Important flags

- `--yes` — required to confirm destructive actions (`drop`, `reset`).
- `--apps` — app labels whose migrations may be deleted during `reset`.
- `--database` — Django database alias (default: `default`).
- `--output-dir` — directory to write backups to (default: `<BASE_DIR>/backups`).
- `--prefix` — optional filename prefix for backups (must be a single filename component).
- `--compression` — compression level for `pg_dump` custom format (0–9; default: 6).
- `--include-owner` — include original object owners and privileges in dumps/restores.
- `--backup` — path to the `.dump` archive to restore.
- `--create-db` — when restoring, create the DB from the archive (`-C` to `pg_restore`).
- `--jobs` — number of parallel jobs for `pg_restore` (default: 2, maximum: local CPU count).
- `--i-understand` — required to acknowledge destructive restore operations.

## Behavior notes

- Backup files are created with a timestamped filename. The implementation ensures generated backup paths cannot escape the requested `--output-dir`.
- Backup and restore executable paths must be absolute executable files when provided through `PG_DUMP_PATH` or `PG_RESTORE_PATH`.
- PATH fallback for `pg_dump` and `pg_restore` is restricted to trusted executable directories.
- Restore is destructive by default; the command refuses to run unless `--i-understand` is provided.
- `restore` validates `--jobs` and rejects values outside `1..os.cpu_count()`.
- `reset` deletes migration files only for explicitly scoped app labels from `--apps` or `MAN_DB_RESET_APP_ALLOWLIST`, and then drops the configured database.

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
