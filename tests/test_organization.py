"""Unit tests for album organization mode."""

import pytest
from pathlib import Path
from kikusan.download import _sanitize_path_component, _get_output_path, _get_primary_artist


class TestSanitizePathComponent:
    """Test path sanitization for directory names."""

    def test_removes_invalid_chars(self):
        """Test that invalid filesystem characters are removed."""
        assert _sanitize_path_component('Artist<>:"|?*Name') == "ArtistName"

    def test_replaces_slashes(self):
        """Test that slashes are replaced with dashes."""
        assert _sanitize_path_component("AC/DC") == "AC-DC"
        assert _sanitize_path_component("Artist\\Name") == "Artist-Name"

    def test_strips_whitespace_and_dots(self):
        """Test that leading/trailing whitespace and dots are stripped."""
        assert _sanitize_path_component("  Artist  ") == "Artist"
        assert _sanitize_path_component("...Artist...") == "Artist"
        assert _sanitize_path_component("  .Artist.  ") == "Artist"

    def test_returns_unknown_for_empty(self):
        """Test that empty strings return 'Unknown'."""
        assert _sanitize_path_component("") == "Unknown"
        assert _sanitize_path_component("   ") == "Unknown"
        assert _sanitize_path_component("...") == "Unknown"


class TestGetOutputPath:
    """Test output path calculation for different organization modes."""

    def test_flat_mode(self):
        """Test flat mode uses filename template."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Test Album",
            "release_year": 2024,
            "track_number": 5,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "flat")
        assert result == "/downloads/%(artist)s - %(title)s.%(ext)s"

    def test_album_mode_full_metadata(self):
        """Test album mode with all metadata present."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Test Album",
            "release_year": 2024,
            "track_number": 5,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Artist/2024 - Test Album/05 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_no_track_number(self):
        """Test album mode without track number."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Test Album",
            "release_year": 2024,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Artist/2024 - Test Album/%(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_no_year(self):
        """Test album mode without release year."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Test Album",
            "track_number": 3,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Artist/Test Album/03 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_no_album(self):
        """Test album mode without album info (artist folder only)."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Artist/%(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_no_artist_uses_uploader(self):
        """Test album mode uses uploader when artist is missing."""
        output_dir = Path("/downloads")
        info = {
            "uploader": "Test Uploader",
            "album": "Test Album",
            "release_year": 2024,
            "track_number": 2,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Uploader/2024 - Test Album/02 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_sanitizes_artist_name(self):
        """Test that artist names are sanitized for filesystem."""
        output_dir = Path("/downloads")
        info = {
            "artist": "AC/DC",
            "album": "Back in Black",
            "release_year": 1980,
            "track_number": 1,
            "title": "Hells Bells",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/AC-DC/1980 - Back in Black/01 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_sanitizes_album_name(self):
        """Test that album names are sanitized for filesystem."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Album: The Best?",
            "release_year": 2024,
            "track_number": 1,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Test Artist/2024 - Album The Best/01 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_unknown_artist_fallback(self):
        """Test fallback to 'Unknown Artist' when no artist/uploader."""
        output_dir = Path("/downloads")
        info = {
            "album": "Test Album",
            "release_year": 2024,
            "track_number": 1,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        expected = "/downloads/Unknown Artist/2024 - Test Album/01 - %(title)s.%(ext)s"
        assert result == expected

    def test_album_mode_track_number_zero_padding(self):
        """Test that track numbers are zero-padded to 2 digits."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Test Artist",
            "album": "Test Album",
            "track_number": 3,
            "title": "Test Title",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album")
        assert "/03 - %(title)s.%(ext)s" in result

        # Test double digit
        info["track_number"] = 15
        result = _get_output_path(output_dir, info, filename_template, "album")
        assert "/15 - %(title)s.%(ext)s" in result


class TestGetPrimaryArtist:
    """Test primary artist extraction from multi-artist strings."""

    def test_comma_separated(self):
        """Test comma-separated artists."""
        assert _get_primary_artist("Queen, David Bowie") == "Queen"
        assert _get_primary_artist("Artist1, Artist2, Artist3") == "Artist1"

    def test_ampersand_separated(self):
        """Test ampersand-separated artists."""
        assert _get_primary_artist("Artist1 & Artist2") == "Artist1"
        assert _get_primary_artist("The Beatles & Elton John") == "The Beatles"

    def test_featuring(self):
        """Test 'featuring' and 'feat.' patterns."""
        assert _get_primary_artist("Artist feat. Guest") == "Artist"
        assert _get_primary_artist("Artist ft. Guest") == "Artist"
        assert _get_primary_artist("Artist featuring Guest") == "Artist"

    def test_with(self):
        """Test 'with' pattern."""
        assert _get_primary_artist("Artist with Guest") == "Artist"

    def test_single_artist(self):
        """Test single artist (no separator)."""
        assert _get_primary_artist("Queen") == "Queen"
        assert _get_primary_artist("The Beatles") == "The Beatles"

    def test_priority_order(self):
        """Test that separators are processed in priority order."""
        # 'feat.' should be found before ', '
        assert _get_primary_artist("Artist1 feat. Artist2, Artist3") == "Artist1"
        # '&' should be found before ', '
        assert _get_primary_artist("Artist1 & Artist2, Artist3") == "Artist1"

    def test_whitespace_handling(self):
        """Test that whitespace is properly handled."""
        assert _get_primary_artist("  Artist  ") == "Artist"
        assert _get_primary_artist("Artist1  &  Artist2") == "Artist1"

    def test_case_sensitivity(self):
        """Test that matching is case-sensitive (lowercase separators)."""
        # These should work (lowercase separators)
        assert _get_primary_artist("Artist feat. Guest") == "Artist"
        # Capital letters in separator should NOT match (no separator found)
        assert _get_primary_artist("Artist FEAT. Guest") == "Artist FEAT. Guest"


class TestGetOutputPathWithPrimaryArtist:
    """Test output path generation with use_primary_artist=True."""

    def test_primary_artist_flat_mode(self):
        """Test that flat mode ignores use_primary_artist."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Queen feat. David Bowie",
            "title": "Under Pressure",
        }
        filename_template = "%(artist)s - %(title)s"

        # Flat mode should ignore use_primary_artist
        result_false = _get_output_path(output_dir, info, filename_template, "flat", use_primary_artist=False)
        result_true = _get_output_path(output_dir, info, filename_template, "flat", use_primary_artist=True)
        assert result_false == result_true

    def test_primary_artist_album_mode(self):
        """Test that album mode uses primary artist when enabled."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Queen feat. David Bowie",
            "album": "Greatest Hits",
            "release_year": 1981,
            "track_number": 5,
        }
        filename_template = "%(artist)s - %(title)s"

        # Without primary artist
        result_without = _get_output_path(output_dir, info, filename_template, "album", use_primary_artist=False)
        assert "Queen feat. David Bowie" in result_without

        # With primary artist
        result_with = _get_output_path(output_dir, info, filename_template, "album", use_primary_artist=True)
        assert result_with == "/downloads/Queen/1981 - Greatest Hits/05 - %(title)s.%(ext)s"

    def test_comma_separated_artists(self):
        """Test comma-separated multi-artist handling."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Artist1, Artist2",
            "album": "Collaboration",
            "release_year": 2024,
            "track_number": 1,
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album", use_primary_artist=True)
        assert result == "/downloads/Artist1/2024 - Collaboration/01 - %(title)s.%(ext)s"

    def test_primary_artist_no_album(self):
        """Test primary artist extraction when no album info."""
        output_dir = Path("/downloads")
        info = {
            "artist": "Queen & David Bowie",
            "title": "Test",
        }
        filename_template = "%(artist)s - %(title)s"

        result = _get_output_path(output_dir, info, filename_template, "album", use_primary_artist=True)
        assert result == "/downloads/Queen/%(title)s.%(ext)s"
