"""Intelligent yt-dlp wrapper with conditional cookie usage.

This module wraps yt-dlp operations with smart retry logic that only uses
cookies when authentication is required (age-restricted, private content, etc.).
This prevents unnecessary cookie usage that could lead to account bans.

Responsibilities:
- Detect auth/age-restriction errors from yt-dlp
- Automatically retry with cookies when needed
- Log cookie usage for debugging
- Provide metrics on cookie necessity
"""

import logging
import re
import time
from typing import Any, Optional

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

logger = logging.getLogger(__name__)

# Patterns indicating authentication/cookies are required
# These are matched case-insensitively against exception messages
AUTH_REQUIRED_PATTERNS = [
    # Age restrictions
    r"age[- ]restricted",
    r"inappropriate.*content",
    r"sign in.*confirm.*age",
    r"content.*warning",
    # Authentication required
    r"sign in",
    r"log[- ]?in.*required",
    r"members[- ]only",
    r"private.*video",
    r"join.*channel",
    # Premium content
    r"premium.*members",
    r"music premium",
    r"requires.*payment",
    r"subscribers.*only",
    # Private/unlisted with auth
    r"granted.*access",
    r"unlisted.*video",
]


class CookieUsageStats:
    """Track cookie usage statistics for observability."""

    total_requests: int = 0
    cookie_fallback_count: int = 0
    always_cookie_count: int = 0

    @classmethod
    def log_summary(cls):
        """Log summary of cookie usage statistics."""
        if cls.total_requests == 0:
            return

        fallback_pct = (cls.cookie_fallback_count / cls.total_requests) * 100
        logger.info(
            "Cookie usage stats: %d/%d requests (%.1f%%) required cookie fallback",
            cls.cookie_fallback_count,
            cls.total_requests,
            fallback_pct,
        )


def is_auth_error(exception: Exception) -> bool:
    """Determine if exception indicates auth/cookies are needed.

    Args:
        exception: Exception raised by yt-dlp

    Returns:
        True if exception indicates cookies would help, False otherwise
    """
    # Get error message from exception
    error_msg = str(exception).lower()

    # Check each pattern
    for pattern in AUTH_REQUIRED_PATTERNS:
        if re.search(pattern, error_msg, re.IGNORECASE):
            logger.debug("Auth error detected with pattern '%s': %s", pattern, error_msg[:100])
            return True

    return False


def extract_info_with_retry(
    ydl_opts: dict[str, Any],
    url: str,
    download: bool = True,
    cookie_file: Optional[str] = None,
    config: Optional[Any] = None,
) -> dict[str, Any]:
    """Extract info with intelligent cookie fallback.

    This is the core wrapper function that replaces direct yt-dlp calls.
    It implements smart retry logic based on the configured cookie mode.

    Args:
        ydl_opts: Base yt-dlp options dict (without cookies)
        url: URL to extract/download
        download: Whether to download (True) or just extract info (False)
        cookie_file: Path to cookie file (if available)
        config: Config object with cookie_mode, cookie_retry_delay, etc.

    Returns:
        yt-dlp info dict

    Raises:
        DownloadError: If download fails
        ExtractorError: If extraction fails
        Exception: Other yt-dlp errors
    """
    # Import here to avoid circular dependency
    if config is None:
        from kikusan.config import get_config

        config = get_config()

    # Track statistics
    CookieUsageStats.total_requests += 1

    # Determine cookie usage based on mode
    cookie_mode = getattr(config, "cookie_mode", "auto")
    retry_delay = getattr(config, "cookie_retry_delay", 1.0)
    log_cookie_usage = getattr(config, "log_cookie_usage", True)

    # Mode: always - use cookies immediately
    if cookie_mode == "always":
        if log_cookie_usage:
            logger.debug("Cookie mode=always: Using cookies for all requests")
        CookieUsageStats.always_cookie_count += 1
        return _execute_ydl(ydl_opts, url, download, cookie_file, use_cookies=True)

    # Mode: never - never use cookies
    if cookie_mode == "never":
        if log_cookie_usage:
            logger.debug("Cookie mode=never: Never using cookies")
        return _execute_ydl(ydl_opts, url, download, cookie_file, use_cookies=False)

    # Mode: auto - try without cookies first, fallback on auth errors
    if log_cookie_usage:
        logger.debug("Cookie mode=auto: Trying without cookies first")

    try:
        # First attempt: no cookies
        return _execute_ydl(ydl_opts, url, download, cookie_file, use_cookies=False)

    except (ExtractorError, DownloadError) as e:
        # Check if this is an auth error that cookies might fix
        if not is_auth_error(e):
            # Not an auth error, re-raise
            raise

        # Auth error detected - retry with cookies
        if not cookie_file:
            logger.warning(
                "Auth error detected but no cookie file available: %s", str(e)[:100]
            )
            raise

        if log_cookie_usage:
            logger.info("Cookie fallback for: %s", url)
            logger.debug("Retrying with cookies after %.1fs delay", retry_delay)

        CookieUsageStats.cookie_fallback_count += 1

        # Wait before retrying
        time.sleep(retry_delay)

        # Retry with cookies
        return _execute_ydl(ydl_opts, url, download, cookie_file, use_cookies=True)


def _execute_ydl(
    ydl_opts: dict[str, Any],
    url: str,
    download: bool,
    cookie_file: Optional[str],
    use_cookies: bool,
) -> dict[str, Any]:
    """Execute yt-dlp with or without cookies.

    Args:
        ydl_opts: Base yt-dlp options
        url: URL to process
        download: Whether to download or just extract info
        cookie_file: Path to cookie file
        use_cookies: Whether to use cookies

    Returns:
        yt-dlp info dict
    """
    # Create options copy to avoid modifying input
    opts = ydl_opts.copy()

    # Add cookies if requested and available
    if use_cookies and cookie_file:
        opts["cookiefile"] = cookie_file

    # Execute yt-dlp
    with yt_dlp.YoutubeDL(opts) as ydl:
        if download:
            # Download and return info
            # Note: yt-dlp.download() returns error code, not info
            # We need to call extract_info with download=True
            info = ydl.extract_info(url, download=True)
        else:
            # Just extract info
            info = ydl.extract_info(url, download=False)

    return info
