# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-05-13

### Added

- `ebdeploy init --reconfigure`: each prompt now shows the current value in brackets; pressing Enter without input keeps the existing value.
- `ebdeploy init`: client name is now optional. Leaving it blank produces a client-less layout: `app_name = <project>`, `environment = <project>-<env>`, `s3_prefix = <project>/<env>`.
- Archive filtering by client: when a `clients/` directory exists in the repository, subdirectories that do not match the current client name are automatically excluded from the archive. Comparison is case-insensitive.
- New `clients_dir` config field (default: `"clients"`) to configure the name of the per-client directory when it differs from the default.

### Fixed

- Glob patterns containing `/` now work correctly on Windows. Path separators are normalised to forward slashes before pattern matching in `_is_excluded`.

## [0.1.0] - 2026-05-05

### Added

- `ebdeploy init` — interactive wizard to create `.elasticbeanstalk/ebdeploy.yml`.
- `ebdeploy init --reconfigure` — overwrite an existing configuration file.
- `ebdeploy deploy` — upload a versioned archive to S3 and deploy it to an Elastic Beanstalk environment. Supports `--version`, `--description`, and `--dry-run`.
- `ebdeploy status` — print the current state of the EB environment.
- `ebdeploy package` — build the deployment archive without deploying.
- `ebdeploy temp creds` — obtain short-lived AWS credentials via STS + MFA and save them to `~/.aws/credentials`.
- Configuration via `ebdeploy.yml` with override support from `EB_*` environment variables.
- `git archive` as the default archiving strategy, with automatic fallback to a directory zip when uncommitted changes are detected.
- `.ebignore` support: patterns listed in the file are excluded from the archive.
- Configurable wait loop that polls EB until the environment reaches the `Ready` state after deployment (`wait_for_ready`, `wait_timeout`, `poll_interval`).
- Global CLI flags: `-c / --config` to specify a custom config path, `-v / --verbose` for debug output.
- Per-command AWS overrides: `--profile`, `--region`, `--app-name`, `--environment`, `--s3-bucket`.

[Unreleased]: https://github.com/your-org/ebdeploy/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/your-org/ebdeploy/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/your-org/ebdeploy/releases/tag/v0.1.0
