"""
Deployment configuration — loaded from ebdeploy.yml or environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .exceptions import ConfigError

_REQUIRED = [
    "app_name",
    "environment",
    "s3_bucket",
    "s3_prefix",
    "aws_region",
]


@dataclass
class DeployConfig:
    # AWS / EB
    app_name: str = ""
    environment: str = ""
    s3_bucket: str = ""
    s3_prefix: str = ""          # e.g. "d-sights/stage/danone" → s3://<bucket>/<project>/<env>/<client>/
    aws_region: str = "us-east-1"
    aws_profile: Optional[str] = None
    mfa_serial: Optional[str] = None   # ARN of the MFA device, e.g. arn:aws:iam::123456789012:mfa/username

    # Archive
    archive_path: str = "deploy.zip"
    use_git_archive: bool = True   # False → zip including uncommitted changes
    clients_dir: str = "clients"   # directory that holds per-client subdirs

    # Exclusions when use_git_archive=False
    zip_exclude: list[str] = field(default_factory=lambda: [
        "*.git*", "__pycache__/*", "*.pyc", ".env", ".env.*",
        "*.egg-info/*", "dist/*", "build/*", ".venv/*", "venv/*",
    ])

    # Behaviour
    wait_for_ready: bool = True    # wait until EB environment becomes Ready
    wait_timeout: int = 600        # seconds
    poll_interval: int = 15        # seconds

    @classmethod
    def from_file(cls, path: str | Path = ".elasticbeanstalk/ebdeploy.yml") -> "DeployConfig":
        """Load configuration from a YAML file."""
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Configuration file not found: {p}")
        with p.open(encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls._from_dict(data)

    @classmethod
    def from_env(cls) -> "DeployConfig":
        """Load configuration from EB_* environment variables."""
        data = {
            "app_name":       os.getenv("EB_APP_NAME", ""),
            "environment":    os.getenv("EB_ENVIRONMENT", ""),
            "s3_bucket":      os.getenv("EB_S3_BUCKET", ""),
            "s3_prefix":      os.getenv("EB_S3_PREFIX", ""),
            "aws_region":     os.getenv("EB_AWS_REGION", "us-east-1"),
            "aws_profile":    os.getenv("EB_AWS_PROFILE"),
            "mfa_serial":     os.getenv("EB_MFA_SERIAL"),
            "use_git_archive": os.getenv("EB_USE_GIT_ARCHIVE", "true").lower() == "true",
            "wait_for_ready": os.getenv("EB_WAIT_FOR_READY", "true").lower() == "true",
            "wait_timeout":   int(os.getenv("EB_WAIT_TIMEOUT", "600")),
        }
        return cls._from_dict({k: v for k, v in data.items() if v not in (None, "")})

    @classmethod
    def auto(cls, path: str | Path = ".elasticbeanstalk/ebdeploy.yml") -> "DeployConfig":
        """Load from file (if present), then override with environment variables."""
        try:
            cfg = cls.from_file(path)
        except ConfigError:
            cfg = cls()

        env_cfg = cls.from_env()
        for f in cfg.__dataclass_fields__:
            env_val = getattr(env_cfg, f)
            default = cfg.__dataclass_fields__[f].default
            if env_val and env_val != default:
                setattr(cfg, f, env_val)
        return cfg

    @classmethod
    def _from_dict(cls, data: dict) -> "DeployConfig":
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def validate(self) -> None:
        """Raise ConfigError if any required field is missing."""
        missing = [k for k in _REQUIRED if not getattr(self, k)]
        if missing:
            raise ConfigError(
                f"Missing required configuration fields: {', '.join(missing)}\n"
                "Set them in ebdeploy.yml or via EB_* environment variables."
            )
