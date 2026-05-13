"""
Тести для ebdeploy.
"""

import configparser
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ebdeploy.archiver import _is_excluded, build_archive
from ebdeploy.config import DeployConfig
from ebdeploy.deployer import Deployer
from ebdeploy.exceptions import ConfigError, STSError
from ebdeploy.temp_creds import TempCredentials, TemporaryCredentialsManager


# ─────────────────────────── Config ─────────────────────────────────────────

class TestDeployConfig:
    def test_validate_missing_fields(self):
        cfg = DeployConfig()
        with pytest.raises(ConfigError, match="app_name"):
            cfg.validate()

    def test_validate_ok(self):
        cfg = DeployConfig(
            app_name="myapp",
            environment="myapp-stage",
            s3_bucket="my-bucket",
            s3_prefix="stage",
            aws_region="us-east-1",
        )
        cfg.validate()  # не має кидати

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("EB_APP_NAME", "test-app")
        monkeypatch.setenv("EB_ENVIRONMENT", "test-env")
        monkeypatch.setenv("EB_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("EB_S3_PREFIX", "test/prefix")
        monkeypatch.setenv("EB_AWS_REGION", "eu-west-1")

        cfg = DeployConfig.from_env()
        assert cfg.app_name == "test-app"
        assert cfg.aws_region == "eu-west-1"

    def test_from_env_mfa_serial(self, monkeypatch):
        monkeypatch.setenv("EB_MFA_SERIAL", "arn:aws:iam::123456789012:mfa/user")
        cfg = DeployConfig.from_env()
        assert cfg.mfa_serial == "arn:aws:iam::123456789012:mfa/user"

    def test_from_file(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myapp\n"
            "environment: myapp-stage\n"
            "s3_bucket: my-bucket\n"
            "s3_prefix: stage\n"
            "aws_region: us-east-1\n"
        )
        cfg = DeployConfig.from_file(yml)
        assert cfg.app_name == "myapp"
        assert cfg.s3_prefix == "stage"

    def test_from_file_mfa_serial(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myapp\n"
            "environment: myapp-stage\n"
            "s3_bucket: my-bucket\n"
            "s3_prefix: stage\n"
            "aws_region: us-east-1\n"
            "mfa_serial: arn:aws:iam::123456789012:mfa/user\n"
        )
        cfg = DeployConfig.from_file(yml)
        assert cfg.mfa_serial == "arn:aws:iam::123456789012:mfa/user"


# ─────────────────────────── Archiver ───────────────────────────────────────

class TestIsExcluded:
    def test_exact_match(self):
        assert _is_excluded(".env", [".env"])

    def test_glob_match(self):
        assert _is_excluded("__pycache__/x.pyc", ["__pycache__/*"])

    def test_no_match(self):
        assert not _is_excluded("app/main.py", ["*.pyc"])


class TestBuildArchive:
    def test_zip_directory(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("print('hello')")
        (src / "ignored.pyc").write_text("")
        out = tmp_path / "out.zip"

        with patch("ebdeploy.archiver.has_uncommitted_changes", return_value=True):
            result = build_archive(
                output_path=out,
                source_dir=src,
                use_git_archive=False,
                exclude_patterns=["*.pyc"],
            )

        assert result == out
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "app.py" in names
        assert "ignored.pyc" not in names


# ─────────────────────────── Deployer ───────────────────────────────────────

class TestDeployer:
    def _cfg(self) -> DeployConfig:
        return DeployConfig(
            app_name="myapp",
            environment="myapp-stage",
            s3_bucket="my-bucket",
            s3_prefix="stage",
            aws_region="us-east-1",
            wait_for_ready=False,
        )

    def test_dry_run(self, tmp_path):
        deployer = Deployer(self._cfg(), repo_dir=tmp_path)

        with (
            patch("ebdeploy.deployer.build_archive") as mock_archive,
            patch("ebdeploy.deployer.get_short_sha", return_value="abc1234"),
            patch("ebdeploy.deployer.get_branch", return_value="main"),
        ):
            mock_archive.return_value = tmp_path / "deploy.zip"
            version = deployer.deploy(dry_run=True)

        assert version.startswith("commit-abc1234")
        mock_archive.assert_called_once()

    def test_full_deploy(self, tmp_path):
        deployer = Deployer(self._cfg(), repo_dir=tmp_path)
        mock_aws = MagicMock()
        deployer._aws = mock_aws

        with (
            patch("ebdeploy.deployer.build_archive") as mock_archive,
            patch("ebdeploy.deployer.get_short_sha", return_value="deadbeef"),
            patch("ebdeploy.deployer.get_branch", return_value="main"),
        ):
            mock_archive.return_value = tmp_path / "deploy.zip"
            version = deployer.deploy()

        assert version.startswith("commit-deadbeef")
        mock_aws.upload_to_s3.assert_called_once()
        mock_aws.create_application_version.assert_called_once()
        mock_aws.deploy_to_environment.assert_called_once()


# ─────────────────────── TemporaryCredentialsManager ────────────────────────

def _make_manager(mock_sts, mock_iam, profile="myprofile"):
    """Helper: build TemporaryCredentialsManager with mocked boto3 clients."""
    mock_session = MagicMock()
    mock_session.client.side_effect = lambda svc, **kw: mock_sts if svc == "sts" else mock_iam
    with patch("ebdeploy.temp_creds.boto3.Session", return_value=mock_session):
        return TemporaryCredentialsManager(profile=profile)


class TestTemporaryCredentialsManager:
    def test_get_mfa_serial_success(self):
        mock_iam = MagicMock()
        mock_iam.list_mfa_devices.return_value = {
            "MFADevices": [{"SerialNumber": "arn:aws:iam::123456789012:mfa/user"}]
        }
        mgr = _make_manager(MagicMock(), mock_iam)
        assert mgr.get_mfa_serial() == "arn:aws:iam::123456789012:mfa/user"

    def test_get_mfa_serial_no_devices_raises(self):
        mock_iam = MagicMock()
        mock_iam.list_mfa_devices.return_value = {"MFADevices": []}
        mgr = _make_manager(MagicMock(), mock_iam)
        with pytest.raises(STSError, match="No MFA device"):
            mgr.get_mfa_serial()

    def test_get_temp_credentials_explicit_serial(self):
        expiration = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        mock_sts = MagicMock()
        mock_sts.get_session_token.return_value = {
            "Credentials": {
                "AccessKeyId": "ASIAIOSFODNN7EXAMPLE",
                "SecretAccessKey": "wJalrXUtnFEMI",
                "SessionToken": "AQoXnyc4",
                "Expiration": expiration,
            }
        }
        mgr = _make_manager(mock_sts, MagicMock())
        creds = mgr.get_temp_credentials(
            mfa_token="123456",
            mfa_serial="arn:aws:iam::123456789012:mfa/user",
        )
        assert creds.access_key_id == "ASIAIOSFODNN7EXAMPLE"
        assert creds.session_token == "AQoXnyc4"
        assert creds.expiration == expiration
        mock_sts.get_session_token.assert_called_once_with(
            DurationSeconds=43200,
            SerialNumber="arn:aws:iam::123456789012:mfa/user",
            TokenCode="123456",
        )

    def test_get_temp_credentials_auto_detects_serial(self):
        expiration = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        mock_sts = MagicMock()
        mock_sts.get_session_token.return_value = {
            "Credentials": {
                "AccessKeyId": "ASIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": expiration,
            }
        }
        mock_iam = MagicMock()
        mock_iam.list_mfa_devices.return_value = {
            "MFADevices": [{"SerialNumber": "arn:aws:iam::123:mfa/user"}]
        }
        mgr = _make_manager(mock_sts, mock_iam)
        mgr.get_temp_credentials(mfa_token="654321")
        mock_sts.get_session_token.assert_called_once_with(
            DurationSeconds=43200,
            SerialNumber="arn:aws:iam::123:mfa/user",
            TokenCode="654321",
        )

    def test_get_temp_credentials_sts_error(self):
        from botocore.exceptions import ClientError
        mock_sts = MagicMock()
        mock_sts.get_session_token.side_effect = ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": "bad token"}},
            "GetSessionToken",
        )
        mgr = _make_manager(mock_sts, MagicMock())
        with pytest.raises(STSError, match="Failed to get session token"):
            mgr.get_temp_credentials(
                mfa_token="000000",
                mfa_serial="arn:aws:iam::123:mfa/user",
            )

    def test_save_credentials_creates_file(self, tmp_path):
        creds_file = tmp_path / "credentials"
        creds = TempCredentials(
            access_key_id="ASIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI",
            session_token="AQoXnyc4",
            expiration=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        )
        mgr = _make_manager(MagicMock(), MagicMock())
        mgr.save_credentials(creds, "myprofile-temp", credentials_path=creds_file)

        cp = configparser.ConfigParser()
        cp.read(creds_file, encoding="utf-8")
        assert cp["myprofile-temp"]["aws_access_key_id"] == "ASIAIOSFODNN7EXAMPLE"
        assert cp["myprofile-temp"]["aws_secret_access_key"] == "wJalrXUtnFEMI"
        assert cp["myprofile-temp"]["aws_session_token"] == "AQoXnyc4"

    def test_save_credentials_preserves_other_profiles(self, tmp_path):
        creds_file = tmp_path / "credentials"
        creds_file.write_text(
            "[existing-profile]\naws_access_key_id = AKIAEXISTING\n",
            encoding="utf-8",
        )
        creds = TempCredentials(
            access_key_id="ASIANEW",
            secret_access_key="newsecret",
            session_token="newtoken",
            expiration=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        )
        mgr = _make_manager(MagicMock(), MagicMock())
        mgr.save_credentials(creds, "new-temp", credentials_path=creds_file)

        cp = configparser.ConfigParser()
        cp.read(creds_file, encoding="utf-8")
        assert cp["existing-profile"]["aws_access_key_id"] == "AKIAEXISTING"
        assert cp["new-temp"]["aws_access_key_id"] == "ASIANEW"

    def test_save_credentials_overwrites_existing_temp(self, tmp_path):
        creds_file = tmp_path / "credentials"
        creds_file.write_text(
            "[myprofile-temp]\naws_access_key_id = ASIAOLD\n",
            encoding="utf-8",
        )
        creds = TempCredentials(
            access_key_id="ASIANEW",
            secret_access_key="newsecret",
            session_token="newtoken",
            expiration=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        )
        mgr = _make_manager(MagicMock(), MagicMock())
        mgr.save_credentials(creds, "myprofile-temp", credentials_path=creds_file)

        cp = configparser.ConfigParser()
        cp.read(creds_file, encoding="utf-8")
        assert cp["myprofile-temp"]["aws_access_key_id"] == "ASIANEW"


# ─────────────────────── CLI — temp creds ───────────────────────────────────

class TestCLITempCreds:
    def _run(self, argv, mock_mgr):
        from ebdeploy.cli import main
        with (
            patch("ebdeploy.cli.TemporaryCredentialsManager", return_value=mock_mgr),
            patch("builtins.input", return_value="123456"),
        ):
            return main(argv)

    def _make_mock_mgr(self):
        expiration = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        mock_mgr = MagicMock()
        mock_mgr.get_mfa_serial.return_value = "arn:aws:iam::123:mfa/user"
        mock_mgr.get_temp_credentials.return_value = TempCredentials(
            access_key_id="ASIA...",
            secret_access_key="secret",
            session_token="token",
            expiration=expiration,
        )
        return mock_mgr

    def test_temp_creds_auto_detects_serial(self):
        mock_mgr = self._make_mock_mgr()
        result = self._run(["temp", "creds", "--profile", "myprofile"], mock_mgr)
        assert result == 0
        mock_mgr.get_mfa_serial.assert_called_once()
        mock_mgr.get_temp_credentials.assert_called_once()
        mock_mgr.save_credentials.assert_called_once()

    def test_temp_creds_explicit_serial_skips_autodetect(self):
        mock_mgr = self._make_mock_mgr()
        result = self._run(
            ["temp", "creds", "--profile", "myprofile", "--mfa-serial", "arn:aws:iam::123:mfa/user"],
            mock_mgr,
        )
        assert result == 0
        mock_mgr.get_mfa_serial.assert_not_called()

    def test_temp_creds_reads_serial_from_config(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myapp\nenvironment: myapp-stage\n"
            "s3_bucket: b\ns3_prefix: p\naws_region: us-east-1\n"
            "aws_profile: myprofile\n"
            "mfa_serial: arn:aws:iam::123:mfa/user\n"
        )
        mock_mgr = self._make_mock_mgr()
        from ebdeploy.cli import main
        with (
            patch("ebdeploy.cli.TemporaryCredentialsManager", return_value=mock_mgr),
            patch("builtins.input", return_value="123456"),
        ):
            result = main(["-c", str(yml), "temp", "creds"])
        assert result == 0
        mock_mgr.get_mfa_serial.assert_not_called()
        _, kwargs = mock_mgr.get_temp_credentials.call_args
        assert kwargs.get("mfa_serial") == "arn:aws:iam::123:mfa/user"

    def test_temp_creds_cli_serial_overrides_config(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myapp\nenvironment: myapp-stage\n"
            "s3_bucket: b\ns3_prefix: p\naws_region: us-east-1\n"
            "mfa_serial: arn:aws:iam::123:mfa/config-device\n"
        )
        mock_mgr = self._make_mock_mgr()
        from ebdeploy.cli import main
        with (
            patch("ebdeploy.cli.TemporaryCredentialsManager", return_value=mock_mgr),
            patch("builtins.input", return_value="123456"),
        ):
            result = main([
                "-c", str(yml), "temp", "creds",
                "--mfa-serial", "arn:aws:iam::123:mfa/cli-device",
            ])
        assert result == 0
        _, kwargs = mock_mgr.get_temp_credentials.call_args
        assert kwargs.get("mfa_serial") == "arn:aws:iam::123:mfa/cli-device"

    def test_temp_creds_uses_custom_duration(self):
        mock_mgr = self._make_mock_mgr()
        self._run(
            ["temp", "creds", "--profile", "p", "--mfa-serial", "arn:...", "--duration", "3600"],
            mock_mgr,
        )
        _, kwargs = mock_mgr.get_temp_credentials.call_args
        assert kwargs.get("duration") == 3600 or mock_mgr.get_temp_credentials.call_args[0][2] == 3600

    def test_temp_creds_saves_with_temp_suffix(self):
        mock_mgr = self._make_mock_mgr()
        self._run(["temp", "creds", "--profile", "myprofile"], mock_mgr)
        save_call = mock_mgr.save_credentials.call_args
        target_profile = save_call[0][1] if save_call[0] else save_call[1].get("target_profile")
        assert target_profile == "myprofile-temp"


# ─────────────────────────── CLI — init --reconfigure ───────────────────────

class TestCLIInit:
    def _run_init(self, argv, inputs, tmp_path):
        from ebdeploy.cli import main
        with patch("builtins.input", side_effect=inputs):
            return main(["-c", str(tmp_path / "ebdeploy.yml")] + argv)

    def test_init_creates_config(self, tmp_path):
        inputs = ["myproj", "myclient", "stage", "my-bucket", "eu-west-1", "", ""]
        result = self._run_init(["init"], inputs, tmp_path)
        assert result == 0
        yml = tmp_path / "ebdeploy.yml"
        assert yml.exists()
        content = yml.read_text(encoding="utf-8")
        assert "app_name: myproj-myclient" in content
        assert "environment: myproj-myclient-stage" in content
        assert "s3_prefix: myproj/stage/myclient" in content
        assert "s3_bucket: my-bucket" in content
        assert "aws_region: eu-west-1" in content

    def test_init_fails_if_exists_without_reconfigure(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text("app_name: old\n", encoding="utf-8")
        result = self._run_init(["init"], [], tmp_path)
        assert result == 1

    def test_reconfigure_keeps_previous_values_on_empty_input(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myproj-myclient\n"
            "environment: myproj-myclient-stage\n"
            "s3_bucket: old-bucket\n"
            "s3_prefix: myproj/stage/myclient\n"
            "aws_region: eu-west-1\n"
            "aws_profile: myprofile\n"
            "mfa_serial: arn:aws:iam::123:mfa/user\n",
            encoding="utf-8",
        )
        # Press Enter on all prompts → keep existing values
        inputs = ["", "", "", "", "", "", ""]
        result = self._run_init(["init", "--reconfigure"], inputs, tmp_path)
        assert result == 0
        content = yml.read_text(encoding="utf-8")
        assert "app_name: myproj-myclient" in content
        assert "s3_bucket: old-bucket" in content
        assert "aws_region: eu-west-1" in content
        assert "aws_profile: myprofile" in content
        assert "mfa_serial: arn:aws:iam::123:mfa/user" in content

    def test_reconfigure_overrides_specific_field(self, tmp_path):
        yml = tmp_path / "ebdeploy.yml"
        yml.write_text(
            "app_name: myproj-myclient\n"
            "environment: myproj-myclient-stage\n"
            "s3_bucket: old-bucket\n"
            "s3_prefix: myproj/stage/myclient\n"
            "aws_region: eu-west-1\n",
            encoding="utf-8",
        )
        # Only change bucket; keep everything else
        inputs = ["", "", "", "new-bucket", "", "", ""]
        result = self._run_init(["init", "--reconfigure"], inputs, tmp_path)
        assert result == 0
        content = yml.read_text(encoding="utf-8")
        assert "s3_bucket: new-bucket" in content
        assert "app_name: myproj-myclient" in content
        assert "aws_region: eu-west-1" in content
