"""
Main deployment orchestrator.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .archiver import build_archive
from .aws_client import AWSClient
from .config import DeployConfig
from .exceptions import DeployError
from .git_utils import get_branch, get_short_sha

logger = logging.getLogger(__name__)


class Deployer:
    """
    Orchestrates the full deployment cycle:
      1. Resolve version from git
      2. Build zip archive
      3. Upload to S3
      4. Register Application Version in EB
      5. Deploy to environment
      6. (Optional) Wait for Ready
    """

    def __init__(self, config: DeployConfig, repo_dir: str | Path = "."):
        self.config = config
        self.repo_dir = Path(repo_dir).resolve()
        self._aws: Optional[AWSClient] = None

    @property
    def aws(self) -> AWSClient:
        if self._aws is None:
            self._aws = AWSClient(
                region=self.config.aws_region,
                profile=self.config.aws_profile,
            )
        return self._aws

    # ------------------------------------------------------------------ public

    def deploy(
        self,
        version_label: Optional[str] = None,
        description: str = "",
        dry_run: bool = False,
    ) -> str:
        """
        Run a full deployment.

        Args:
            version_label: Version label. Defaults to short git SHA.
            description: Version description shown in the EB console.
            dry_run: Build the archive and print steps without touching AWS.

        Returns:
            The deployed version label.
        """
        self.config.validate()

        version_label = version_label or self._auto_version()
        branch = self._safe_branch()
        description = description or self._auto_description(branch)

        logger.info("=" * 60)
        logger.info(f"  App:         {self.config.app_name}")
        logger.info(f"  Environment: {self.config.environment}")
        logger.info(f"  Version:     {version_label}")
        logger.info(f"  Dry-run:     {dry_run}")
        logger.info("=" * 60)

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / self.config.archive_path

            # Step 1: build archive
            build_archive(
                output_path=archive_path,
                source_dir=self.repo_dir,
                use_git_archive=self.config.use_git_archive,
                exclude_patterns=self.config.zip_exclude,
            )

            s3_key = f"{self.config.s3_prefix}/{version_label}.zip".lstrip("/")

            if dry_run:
                logger.info("[DRY-RUN] Skipping AWS steps.")
                logger.info(f"  S3 key: s3://{self.config.s3_bucket}/{s3_key}")
                return version_label

            # Step 2: upload to S3
            self.aws.upload_to_s3(archive_path, self.config.s3_bucket, s3_key)

            # Step 3: EB Application Version
            self.aws.create_application_version(
                app_name=self.config.app_name,
                version_label=version_label,
                bucket=self.config.s3_bucket,
                s3_key=s3_key,
                description=description,
            )

            # Step 4: deploy
            self.aws.deploy_to_environment(
                app_name=self.config.app_name,
                environment=self.config.environment,
                version_label=version_label,
            )

            # Step 5: wait
            if self.config.wait_for_ready:
                self.aws.wait_for_environment(
                    environment=self.config.environment,
                    version_label=version_label,
                    timeout=self.config.wait_timeout,
                    poll_interval=self.config.poll_interval,
                )

        logger.info(f"✓ Deployment '{version_label}' completed successfully!")
        return version_label

    def status(self) -> dict:
        """Return the current state of the EB environment."""
        self.config.validate()
        return self.aws.get_environment_info(self.config.environment)

    def package(self, output_path: Optional[str] = None) -> Path:
        """Build the archive only, without deploying."""
        out = Path(output_path or self.config.archive_path)
        return build_archive(
            output_path=out,
            source_dir=self.repo_dir,
            use_git_archive=self.config.use_git_archive,
            exclude_patterns=self.config.zip_exclude,
        )

    # ------------------------------------------------------------------ private

    def _auto_version(self) -> str:
        """Format: commit-<short_sha>-YYYY-MM-DD-hhmmss  (e.g. commit-c72c6e6-2026-05-04-143000)"""
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        try:
            return f"commit-{get_short_sha(self.repo_dir)}-{ts}"
        except Exception:
            return f"commit-unknown-{ts}"

    def _safe_branch(self) -> str:
        try:
            return get_branch(self.repo_dir)
        except Exception:
            return "unknown"

    def _auto_description(self, branch: str) -> str:
        """Deploy 2024-04-17 14:30:00 | Branch: main | Commit: a1b2c3d"""
        import datetime
        try:
            short_sha = get_short_sha(self.repo_dir)
        except Exception:
            short_sha = "unknown"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"Deploy {ts} | Branch: {branch} | Commit: {short_sha}"
