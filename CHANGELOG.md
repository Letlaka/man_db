# Changelog

All notable changes to this project will be documented in this file.

## [0.1.3]

### Added

- `CHANGELOG.md`
- `pytest` and `pytest-django` in development dependencies and package extras
- Local Docker Compose integration testing for PostgreSQL 14, 15, 16, 17, and 18 with matching `pg_dump` and `pg_restore` clients
- Integration assertions that verify the configured PostgreSQL server and client major versions
- PostgreSQL integration test suite for create, ping, backup, and restore flows
- A separate CI workflow that runs on pushes and pull requests
- GitHub repository metadata and contribution files under `.github`, including the PR template, security policy, and code ownership file

### Changed

- Package metadata now reports version `0.1.3`
- Supported Python versions are documented as 3.13
- Local development instructions now install the dev extra
- GitHub Actions now runs the integration suite against PostgreSQL 14 through 18 instead of a single PostgreSQL version
- The README now documents the CI trigger behavior and release tag flow

### Fixed

- Version sourcing now follows installed package metadata instead of a hardcoded string
- `reset` now drops the database before deleting migration files
- `force_delete_database()` now requires `confirmed=True`
- Cross-platform test paths and Windows executable detection coverage

### Security

- `pg_dump` and `pg_restore` now use a temporary `.pgpass` file instead of exporting `PGPASSWORD`
- GitHub Actions are pinned to commit SHAs
- TestPyPI publishing only runs for release-candidate tags

## [0.1.2]

### Added

- Support for Django 5.2 and later.

### Changed

- Relaxed the Django dependency from `Django>=5.2,<6.0` to `Django>=5.2`.
- Removed the overly specific `Framework :: Django :: 5.2` classifier.
- Updated the README wording to match the supported Django range.

## [0.1.1]

### Added

- Package and project rename to `django-postgres-man-db`.

### Changed

- Updated the README install commands to use the published package name.
- Updated the publish workflow URLs to point at the renamed package.

## [0.1.0]

### Added

- Initial release
- `create`, `drop`, `reset`, `ping`, `backup`, and `restore` management commands
- Dual management command entry points: `man_db` and `mandb`
- Structured logging with `structlog`
