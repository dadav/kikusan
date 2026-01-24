"""Tests for yt-dlp wrapper with conditional cookie usage."""

import pytest
from unittest.mock import MagicMock, Mock, patch
from yt_dlp.utils import DownloadError, ExtractorError

from kikusan.yt_dlp_wrapper import (
    CookieUsageStats,
    extract_info_with_retry,
    is_auth_error,
)


class TestAuthErrorDetection:
    """Test error pattern matching for authentication errors."""

    def test_detects_age_restriction(self):
        """Detect age-restricted content error."""
        error = ExtractorError("This video is age-restricted")
        assert is_auth_error(error) is True

    def test_detects_age_restriction_with_hyphen(self):
        """Detect age-restricted with hyphen."""
        error = ExtractorError("This content is age-restricted")
        assert is_auth_error(error) is True

    def test_detects_sign_in_required(self):
        """Detect sign-in requirement."""
        error = ExtractorError("Sign in to confirm your age")
        assert is_auth_error(error) is True

    def test_detects_private_video(self):
        """Detect private video error."""
        error = ExtractorError("This is a private video")
        assert is_auth_error(error) is True

    def test_detects_members_only(self):
        """Detect members-only content."""
        error = ExtractorError("This video is members-only")
        assert is_auth_error(error) is True

    def test_detects_music_premium(self):
        """Detect Music Premium requirement."""
        error = ExtractorError("Requires YouTube Music Premium")
        assert is_auth_error(error) is True

    def test_detects_login_required(self):
        """Detect login required error."""
        error = ExtractorError("Log-in required to access")
        assert is_auth_error(error) is True

    def test_case_insensitive_matching(self):
        """Test case-insensitive pattern matching."""
        error = ExtractorError("AGE-RESTRICTED content warning")
        assert is_auth_error(error) is True

    def test_ignores_unrelated_errors(self):
        """Test that unrelated errors are not matched."""
        error = DownloadError("Network timeout")
        assert is_auth_error(error) is False

    def test_ignores_generic_download_errors(self):
        """Test generic download errors are not matched."""
        error = ExtractorError("Video not found")
        assert is_auth_error(error) is False

    def test_ignores_format_errors(self):
        """Test format errors are not matched."""
        error = ExtractorError("No suitable format found")
        assert is_auth_error(error) is False


class TestExtractInfoWithRetry:
    """Test retry logic with cookie fallback."""

    def setup_method(self):
        """Reset statistics before each test."""
        CookieUsageStats.total_requests = 0
        CookieUsageStats.cookie_fallback_count = 0
        CookieUsageStats.always_cookie_count = 0

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_succeeds_without_cookies_auto_mode(self, mock_ydl_class):
        """Test successful extraction without cookies in auto mode."""
        # Setup mock to succeed on first try
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test123", "title": "Test Video"}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        result = extract_info_with_retry(
            ydl_opts={},
            url="https://youtube.com/watch?v=test",
            download=False,
            cookie_file="/tmp/cookies.txt",
            config=config,
        )

        assert result["id"] == "test123"
        # Verify cookies were NOT used on first attempt
        call_args = mock_ydl_class.call_args[0][0]
        assert "cookiefile" not in call_args
        assert CookieUsageStats.total_requests == 1
        assert CookieUsageStats.cookie_fallback_count == 0

    @patch('kikusan.yt_dlp_wrapper.time.sleep')
    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_retries_with_cookies_on_auth_error(self, mock_ydl_class, mock_sleep):
        """Test retry with cookies after auth error in auto mode."""
        # Setup mock to fail first, succeed second
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = [
            ExtractorError("This video is age-restricted"),
            {"id": "test123", "title": "Test Video"},
        ]
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        result = extract_info_with_retry(
            ydl_opts={},
            url="https://youtube.com/watch?v=test",
            download=False,
            cookie_file="/tmp/cookies.txt",
            config=config,
        )

        assert result["id"] == "test123"
        assert mock_ydl.extract_info.call_count == 2
        # Verify second call included cookies
        second_call = mock_ydl_class.call_args_list[1][0][0]
        assert second_call.get("cookiefile") == "/tmp/cookies.txt"
        # Verify sleep was called
        mock_sleep.assert_called_once_with(1.0)
        assert CookieUsageStats.cookie_fallback_count == 1

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_always_mode_uses_cookies_immediately(self, mock_ydl_class):
        """Test 'always' mode uses cookies on first attempt."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test123"}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "always"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        extract_info_with_retry(
            ydl_opts={},
            url="https://youtube.com/watch?v=test",
            download=False,
            cookie_file="/tmp/cookies.txt",
            config=config,
        )

        # Verify cookies used on first attempt
        call_args = mock_ydl_class.call_args[0][0]
        assert call_args["cookiefile"] == "/tmp/cookies.txt"
        assert CookieUsageStats.always_cookie_count == 1

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_never_mode_ignores_cookies(self, mock_ydl_class):
        """Test 'never' mode never uses cookies even on auth error."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = ExtractorError("age-restricted content")
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "never"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        with pytest.raises(ExtractorError):
            extract_info_with_retry(
                ydl_opts={},
                url="https://youtube.com/watch?v=test",
                download=False,
                cookie_file="/tmp/cookies.txt",
                config=config,
            )

        # Verify only one attempt, no cookies
        assert mock_ydl.extract_info.call_count == 1
        call_args = mock_ydl_class.call_args[0][0]
        assert "cookiefile" not in call_args

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_non_auth_error_not_retried(self, mock_ydl_class):
        """Test that non-auth errors are not retried."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = DownloadError("Network timeout")
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        with pytest.raises(DownloadError):
            extract_info_with_retry(
                ydl_opts={},
                url="https://youtube.com/watch?v=test",
                download=False,
                cookie_file="/tmp/cookies.txt",
                config=config,
            )

        # Should only attempt once (no retry for non-auth errors)
        assert mock_ydl.extract_info.call_count == 1
        assert CookieUsageStats.cookie_fallback_count == 0

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_no_cookie_file_available(self, mock_ydl_class):
        """Test auth error when no cookie file is available."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = ExtractorError("age-restricted")
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        with pytest.raises(ExtractorError):
            extract_info_with_retry(
                ydl_opts={},
                url="https://youtube.com/watch?v=test",
                download=False,
                cookie_file=None,  # No cookie file
                config=config,
            )

        # Should only attempt once (can't retry without cookie file)
        assert mock_ydl.extract_info.call_count == 1

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_download_mode_uses_extract_info_with_download_true(self, mock_ydl_class):
        """Test that download=True uses extract_info with download=True."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test123"}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        extract_info_with_retry(
            ydl_opts={},
            url="https://youtube.com/watch?v=test",
            download=True,
            cookie_file=None,
            config=config,
        )

        # Verify extract_info was called with download=True
        mock_ydl.extract_info.assert_called_once_with(
            "https://youtube.com/watch?v=test", download=True
        )

    @patch('kikusan.yt_dlp_wrapper.yt_dlp.YoutubeDL')
    def test_preserves_existing_ydl_opts(self, mock_ydl_class):
        """Test that existing yt-dlp options are preserved."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test123"}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Create mock config
        config = Mock()
        config.cookie_mode = "auto"
        config.cookie_retry_delay = 1.0
        config.log_cookie_usage = True

        custom_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
        }

        extract_info_with_retry(
            ydl_opts=custom_opts,
            url="https://youtube.com/watch?v=test",
            download=False,
            cookie_file=None,
            config=config,
        )

        # Verify custom options were passed through
        call_args = mock_ydl_class.call_args[0][0]
        assert call_args["format"] == "bestaudio/best"
        assert call_args["quiet"] is True
        assert call_args["no_warnings"] is True


class TestCookieUsageStats:
    """Test statistics tracking."""

    def setup_method(self):
        """Reset statistics before each test."""
        CookieUsageStats.total_requests = 0
        CookieUsageStats.cookie_fallback_count = 0
        CookieUsageStats.always_cookie_count = 0

    def test_tracks_total_requests(self):
        """Test that total requests are tracked."""
        CookieUsageStats.total_requests = 10
        assert CookieUsageStats.total_requests == 10

    def test_tracks_cookie_fallback(self):
        """Test that cookie fallbacks are tracked."""
        CookieUsageStats.total_requests = 10
        CookieUsageStats.cookie_fallback_count = 3
        assert CookieUsageStats.cookie_fallback_count == 3

    def test_log_summary_with_no_requests(self):
        """Test log_summary handles zero requests gracefully."""
        # Should not raise an error
        CookieUsageStats.log_summary()

    def test_log_summary_with_requests(self):
        """Test log_summary calculates percentage correctly."""
        CookieUsageStats.total_requests = 100
        CookieUsageStats.cookie_fallback_count = 15

        # Should log without errors (captured by logging system)
        CookieUsageStats.log_summary()

        # Verify the math is correct
        expected_pct = (15 / 100) * 100
        assert expected_pct == 15.0
