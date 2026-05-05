"""
Manages AWS temporary credentials via STS GetSessionToken with MFA.
"""

from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .exceptions import STSError

logger = logging.getLogger(__name__)

_DEFAULT_DURATION = 43200  # 12 hours


@dataclass
class TempCredentials:
    """AWS temporary credentials returned by STS."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime


class TemporaryCredentialsManager:
    """Fetches and stores AWS temporary credentials using STS and MFA."""

    def __init__(self, profile: Optional[str] = None):
        session = boto3.Session(profile_name=profile)
        self._sts = session.client('sts')
        self._iam = session.client('iam')
        self._profile = profile

    def get_mfa_serial(self) -> str:
        """Return the serial number of the first MFA device for the current IAM user."""
        try:
            resp = self._iam.list_mfa_devices()
        except (BotoCoreError, ClientError) as e:
            raise STSError(f'Failed to list MFA devices: {e}') from e
        devices = resp.get('MFADevices', [])
        if not devices:
            raise STSError(
                'No MFA device found for current IAM user. '
                'Pass --mfa-serial to specify the ARN explicitly.'
            )
        return devices[0]['SerialNumber']

    def get_temp_credentials(
        self,
        mfa_token: str,
        mfa_serial: Optional[str] = None,
        duration: int = _DEFAULT_DURATION,
    ) -> TempCredentials:
        """Call STS GetSessionToken and return temporary credentials.

        If mfa_serial is not provided, it is auto-detected via IAM.
        """
        if mfa_serial is None:
            mfa_serial = self.get_mfa_serial()
        logger.info(f'Requesting temporary credentials (duration={duration}s) ...')
        try:
            resp = self._sts.get_session_token(
                DurationSeconds=duration,
                SerialNumber=mfa_serial,
                TokenCode=mfa_token,
            )
        except (BotoCoreError, ClientError) as e:
            raise STSError(f'Failed to get session token: {e}') from e
        raw = resp['Credentials']
        return TempCredentials(
            access_key_id=raw['AccessKeyId'],
            secret_access_key=raw['SecretAccessKey'],
            session_token=raw['SessionToken'],
            expiration=raw['Expiration'],
        )

    def save_credentials(
        self,
        creds: TempCredentials,
        target_profile: str,
        credentials_path: Optional[Path] = None,
    ) -> Path:
        """Write temporary credentials to the AWS credentials file under target_profile.

        Existing profiles in the credentials file are preserved.
        """
        if credentials_path is None:
            credentials_path = Path.home() / '.aws' / 'credentials'
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        cp = configparser.ConfigParser()
        if credentials_path.exists():
            cp.read(credentials_path, encoding='utf-8')

        if target_profile not in cp:
            cp[target_profile] = {}
        cp[target_profile]['aws_access_key_id'] = creds.access_key_id
        cp[target_profile]['aws_secret_access_key'] = creds.secret_access_key
        cp[target_profile]['aws_session_token'] = creds.session_token

        with credentials_path.open('w', encoding='utf-8') as f:
            cp.write(f)

        logger.info(f'Credentials saved to [{target_profile}] in {credentials_path}')
        return credentials_path
