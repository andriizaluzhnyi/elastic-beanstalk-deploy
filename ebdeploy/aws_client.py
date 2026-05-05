"""
Boto3 wrapper for S3 and Elastic Beanstalk.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .exceptions import EBError, S3Error

logger = logging.getLogger(__name__)

_EB_TERMINAL_STATES = {"Ready", "Terminated", "Degraded"}
_EB_HEALTHY_STATE = "Ready"


class AWSClient:
    def __init__(self, region: str, profile: Optional[str] = None):
        session = boto3.Session(
            region_name=region,
            profile_name=profile,
        )
        self._s3 = session.client("s3")
        self._eb = session.client("elasticbeanstalk")

    # ------------------------------------------------------------------ S3

    def upload_to_s3(self, local_path: Path, bucket: str, key: str) -> None:
        """Upload a file to S3."""
        logger.info(f"Uploading to s3://{bucket}/{key} ...")
        try:
            self._s3.upload_file(
                str(local_path),
                bucket,
                key,
                ExtraArgs={"ServerSideEncryption": "AES256"},
                Callback=_ProgressLogger(local_path.stat().st_size),
            )
            logger.info("✓ Upload complete")
        except (BotoCoreError, ClientError) as e:
            raise S3Error(f"Failed to upload to S3: {e}") from e

    # ------------------------------------------------------------------ EB

    def create_application_version(
        self,
        app_name: str,
        version_label: str,
        bucket: str,
        s3_key: str,
        description: str = "",
    ) -> None:
        """Register a new application version in EB."""
        logger.info(f"Creating EB application version '{version_label}' ...")
        try:
            self._eb.create_application_version(
                ApplicationName=app_name,
                VersionLabel=version_label,
                Description=description,
                SourceBundle={"S3Bucket": bucket, "S3Key": s3_key},
                AutoCreateApplication=False,
            )
            logger.info("✓ Application version created")
        except ClientError as e:
            raise EBError(
                f"Failed to create application version: {e}"
            ) from e

    def deploy_to_environment(
        self, app_name: str, environment: str, version_label: str
    ) -> None:
        """Deploy a version to an EB environment."""
        logger.info(
            f"Deploying '{version_label}' → environment '{environment}' ..."
        )
        try:
            self._eb.update_environment(
                ApplicationName=app_name,
                EnvironmentName=environment,
                VersionLabel=version_label,
            )
            logger.info("✓ Deployment initiated")
        except ClientError as e:
            raise EBError(f"Failed to deploy: {e}") from e

    def wait_for_environment(
        self,
        environment: str,
        version_label: str,
        timeout: int = 600,
        poll_interval: int = 15,
    ) -> None:
        """Poll until the environment reaches Ready with the expected version."""
        logger.info(
            f"Waiting for environment '{environment}' to become ready "
            f"(timeout={timeout}s) ..."
        )
        deadline = time.time() + timeout
        dots = 0
        while time.time() < deadline:
            try:
                resp = self._eb.describe_environments(
                    EnvironmentNames=[environment],
                    IncludeDeleted=False,
                )
                envs = resp.get("Environments", [])
                if not envs:
                    raise EBError(f"Environment '{environment}' not found")

                env = envs[0]
                status = env.get("Status", "")
                health = env.get("Health", "")
                current_version = env.get("VersionLabel", "")
                dots += 1
                logger.debug(
                    f"[{dots * poll_interval}s] Status={status} "
                    f"Health={health} Version={current_version}"
                )

                if (
                    status == _EB_HEALTHY_STATE
                    and current_version == version_label
                ):
                    logger.info(
                        f"✓ Environment is ready! Health={health}"
                    )
                    return

                if status in _EB_TERMINAL_STATES and status != _EB_HEALTHY_STATE:
                    raise EBError(
                        f"Environment entered state '{status}'. Deployment failed."
                    )

            except ClientError as e:
                logger.warning(f"Error polling EB: {e}")

            time.sleep(poll_interval)

        raise EBError(
            f"Timeout {timeout}s exceeded: environment '{environment}' "
            "did not become ready in time."
        )

    def get_environment_info(self, environment: str) -> dict:
        """Return the current state of the environment."""
        resp = self._eb.describe_environments(
            EnvironmentNames=[environment],
            IncludeDeleted=False,
        )
        envs = resp.get("Environments", [])
        if not envs:
            raise EBError(f"Environment '{environment}' not found")
        return envs[0]


class _ProgressLogger:
    """Upload progress callback for S3."""

    def __init__(self, total_bytes: int):
        self._total = total_bytes
        self._uploaded = 0

    def __call__(self, bytes_transferred: int) -> None:
        self._uploaded += bytes_transferred
        if self._total:
            pct = self._uploaded * 100 // self._total
            logger.debug(f"  Uploaded: {pct}%")
