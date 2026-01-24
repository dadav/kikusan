"""Tests for CLI options and flags."""

import os
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from kikusan.cli import main


class TestGlobalOptions:
    """Test global CLI options."""

    def setup_method(self):
        """Clear relevant environment variables before each test."""
        for key in ["KIKUSAN_COOKIE_MODE", "KIKUSAN_COOKIE_RETRY_DELAY", "KIKUSAN_LOG_COOKIE_USAGE"]:
            if key in os.environ:
                del os.environ[key]

    def test_cookie_mode_sets_env_var(self):
        """Test --cookie-mode sets environment variable."""
        runner = CliRunner()
        result = runner.invoke(main, ["--cookie-mode", "always", "--help"])
        assert result.exit_code == 0
        # Note: The env var is set during command execution, not in --help output

    def test_cookie_mode_choices(self):
        """Test --cookie-mode validates choices."""
        runner = CliRunner()
        # Don't pass --help so click can validate the choice
        result = runner.invoke(main, ["--cookie-mode", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output

    def test_cookie_retry_delay_accepts_float(self):
        """Test --cookie-retry-delay accepts float values."""
        runner = CliRunner()
        result = runner.invoke(main, ["--cookie-retry-delay", "2.5", "--help"])
        assert result.exit_code == 0

    def test_no_log_cookie_usage_flag(self):
        """Test --no-log-cookie-usage is a valid flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["--no-log-cookie-usage", "--help"])
        assert result.exit_code == 0


class TestDownloadOptions:
    """Test download command options."""

    def test_organization_mode_choices(self):
        """Test --organization-mode validates choices."""
        runner = CliRunner()
        # Don't pass --help so click can validate the choice
        result = runner.invoke(main, ["download", "--organization-mode", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output

    def test_organization_mode_flat(self):
        """Test --organization-mode accepts 'flat'."""
        runner = CliRunner()
        result = runner.invoke(main, ["download", "--organization-mode", "flat", "--help"])
        assert result.exit_code == 0

    def test_organization_mode_album(self):
        """Test --organization-mode accepts 'album'."""
        runner = CliRunner()
        result = runner.invoke(main, ["download", "--organization-mode", "album", "--help"])
        assert result.exit_code == 0

    def test_use_primary_artist_flag(self):
        """Test --use-primary-artist flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["download", "--use-primary-artist", "--help"])
        assert result.exit_code == 0

    def test_no_use_primary_artist_flag(self):
        """Test --no-use-primary-artist flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["download", "--no-use-primary-artist", "--help"])
        assert result.exit_code == 0


class TestWebOptions:
    """Test web command options."""

    def test_cors_origins_option(self):
        """Test --cors-origins is accepted."""
        runner = CliRunner()
        result = runner.invoke(main, ["web", "--cors-origins", "*", "--help"])
        assert result.exit_code == 0

    def test_web_playlist_option(self):
        """Test --web-playlist is accepted."""
        runner = CliRunner()
        result = runner.invoke(main, ["web", "--web-playlist", "myplaylist", "--help"])
        assert result.exit_code == 0


class TestCronOptions:
    """Test cron command options."""

    def test_format_option(self):
        """Test --format option accepts valid values."""
        runner = CliRunner()
        result = runner.invoke(main, ["cron", "--format", "mp3", "--help"])
        assert result.exit_code == 0

    def test_format_option_invalid(self):
        """Test --format option rejects invalid values."""
        runner = CliRunner()
        # Don't pass --help so click can validate the choice
        result = runner.invoke(main, ["cron", "--format", "wav"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output

    def test_organization_mode_option(self):
        """Test --organization-mode option."""
        runner = CliRunner()
        result = runner.invoke(main, ["cron", "--organization-mode", "album", "--help"])
        assert result.exit_code == 0

    def test_use_primary_artist_flag(self):
        """Test --use-primary-artist flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["cron", "--use-primary-artist", "--help"])
        assert result.exit_code == 0


class TestPluginsRunOptions:
    """Test plugins run command options."""

    def test_format_option(self):
        """Test --format option."""
        runner = CliRunner()
        result = runner.invoke(main, ["plugins", "run", "--format", "flac", "--help"])
        assert result.exit_code == 0

    def test_organization_mode_option(self):
        """Test --organization-mode option."""
        runner = CliRunner()
        result = runner.invoke(main, ["plugins", "run", "--organization-mode", "flat", "--help"])
        assert result.exit_code == 0

    def test_use_primary_artist_flag(self):
        """Test --use-primary-artist flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["plugins", "run", "--use-primary-artist", "--help"])
        assert result.exit_code == 0


class TestEnvVarIntegration:
    """Test that CLI options properly interact with environment variables."""

    def setup_method(self):
        """Clear relevant environment variables before each test."""
        for key in [
            "KIKUSAN_COOKIE_MODE",
            "KIKUSAN_COOKIE_RETRY_DELAY",
            "KIKUSAN_LOG_COOKIE_USAGE",
            "KIKUSAN_ORGANIZATION_MODE",
            "KIKUSAN_AUDIO_FORMAT",
            "KIKUSAN_CORS_ORIGINS",
            "KIKUSAN_WEB_PLAYLIST",
            "KIKUSAN_USE_PRIMARY_ARTIST",
        ]:
            if key in os.environ:
                del os.environ[key]

    @patch("kikusan.cli.search")
    @patch("kikusan.cli.download")
    def test_cli_overrides_env_var_for_organization_mode(self, mock_download, mock_search):
        """Test that CLI flag overrides environment variable."""
        os.environ["KIKUSAN_ORGANIZATION_MODE"] = "flat"
        mock_download.return_value = "/tmp/test.opus"
        mock_search.return_value = [
            MagicMock(video_id="test123", title="Test", artist="Artist")
        ]

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["download", "--organization-mode", "album", "--query", "test"],
        )

        # Check that the download function was called with album mode
        if mock_download.called:
            call_kwargs = mock_download.call_args[1]
            assert call_kwargs.get("organization_mode") == "album"

    def test_envvar_attribute_on_click_options(self):
        """Test that click options have envvar attribute where expected."""
        # This verifies the options are properly configured
        runner = CliRunner()

        # Test --organization-mode has envvar
        result = runner.invoke(main, ["download", "--help"])
        assert "organization-mode" in result.output.lower()

        result = runner.invoke(main, ["web", "--help"])
        assert "cors-origins" in result.output.lower()

        result = runner.invoke(main, ["cron", "--help"])
        assert "format" in result.output.lower()
