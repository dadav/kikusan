"""Tests for video type filtering."""

import os
from unittest.mock import MagicMock, patch

import pytest

from kikusan.config import Config
from kikusan.search import (
    ALLOWED_VIDEO_TYPES,
    VIDEO_TYPE_ATV,
    VIDEO_TYPE_OFFICIAL_SOURCE,
    VIDEO_TYPE_OMV,
    VIDEO_TYPE_UGC,
    Charts,
    ChartTrack,
    Track,
    get_charts,
    get_playlist_tracks,
    get_track_from_video_id,
    is_allowed_video_type,
)


class TestIsAllowedVideoType:
    """Test is_allowed_video_type() helper."""

    def test_atv_is_allowed(self):
        assert is_allowed_video_type(VIDEO_TYPE_ATV) is True

    def test_omv_is_allowed(self):
        assert is_allowed_video_type(VIDEO_TYPE_OMV) is True

    def test_ugc_is_excluded_by_default(self):
        assert is_allowed_video_type(VIDEO_TYPE_UGC) is False

    def test_official_source_is_excluded_by_default(self):
        assert is_allowed_video_type(VIDEO_TYPE_OFFICIAL_SOURCE) is False

    def test_none_is_excluded(self):
        assert is_allowed_video_type(None) is False

    def test_none_excluded_even_with_allow_ugc(self):
        assert is_allowed_video_type(None, allow_ugc=True) is False

    def test_ugc_allowed_with_flag(self):
        assert is_allowed_video_type(VIDEO_TYPE_UGC, allow_ugc=True) is True

    def test_official_source_allowed_with_flag(self):
        assert is_allowed_video_type(VIDEO_TYPE_OFFICIAL_SOURCE, allow_ugc=True) is True

    def test_atv_still_allowed_with_flag(self):
        assert is_allowed_video_type(VIDEO_TYPE_ATV, allow_ugc=True) is True

    def test_omv_still_allowed_with_flag(self):
        assert is_allowed_video_type(VIDEO_TYPE_OMV, allow_ugc=True) is True

    def test_unknown_type_is_excluded(self):
        assert is_allowed_video_type("MUSIC_VIDEO_TYPE_UNKNOWN") is False

    def test_unknown_type_excluded_even_with_allow_ugc(self):
        assert is_allowed_video_type("MUSIC_VIDEO_TYPE_UNKNOWN", allow_ugc=True) is False

    def test_allowed_video_types_frozenset(self):
        assert VIDEO_TYPE_ATV in ALLOWED_VIDEO_TYPES
        assert VIDEO_TYPE_OMV in ALLOWED_VIDEO_TYPES
        assert VIDEO_TYPE_UGC not in ALLOWED_VIDEO_TYPES


class TestGetPlaylistTracksVideoTypeFiltering:
    """Test that get_playlist_tracks() filters by video type."""

    def _make_playlist_response(self, tracks):
        return {"title": "Test Playlist", "tracks": tracks}

    def _make_track_item(self, video_id, title, video_type=None):
        item = {
            "videoId": video_id,
            "title": title,
            "artists": [{"name": "Artist"}],
            "album": None,
            "duration": "3:00",
            "thumbnails": [],
        }
        if video_type is not None:
            item["videoType"] = video_type
        return item

    @patch("kikusan.search.YTMusic")
    def test_filters_ugc_tracks(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_playlist.return_value = self._make_playlist_response([
            self._make_track_item("v1", "Official", VIDEO_TYPE_ATV),
            self._make_track_item("v2", "UGC Upload", VIDEO_TYPE_UGC),
            self._make_track_item("v3", "Music Video", VIDEO_TYPE_OMV),
        ])

        tracks = get_playlist_tracks("test_playlist")
        assert len(tracks) == 2
        assert tracks[0].video_id == "v1"
        assert tracks[1].video_id == "v3"

    @patch("kikusan.search.YTMusic")
    def test_includes_ugc_with_allow_ugc(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_playlist.return_value = self._make_playlist_response([
            self._make_track_item("v1", "Official", VIDEO_TYPE_ATV),
            self._make_track_item("v2", "UGC Upload", VIDEO_TYPE_UGC),
        ])

        tracks = get_playlist_tracks("test_playlist", allow_ugc=True)
        assert len(tracks) == 2

    @patch("kikusan.search.YTMusic")
    def test_filters_official_source(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_playlist.return_value = self._make_playlist_response([
            self._make_track_item("v1", "ATV", VIDEO_TYPE_ATV),
            self._make_track_item("v2", "Compilation", VIDEO_TYPE_OFFICIAL_SOURCE),
        ])

        tracks = get_playlist_tracks("test_playlist")
        assert len(tracks) == 1
        assert tracks[0].video_id == "v1"

    @patch("kikusan.search.YTMusic")
    def test_includes_tracks_without_video_type(self, mock_ytmusic_cls):
        """Tracks without videoType field should pass through (no filtering)."""
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_playlist.return_value = self._make_playlist_response([
            self._make_track_item("v1", "No Type"),  # no videoType key
            self._make_track_item("v2", "ATV", VIDEO_TYPE_ATV),
        ])

        tracks = get_playlist_tracks("test_playlist")
        assert len(tracks) == 2

    @patch("kikusan.search.YTMusic")
    def test_video_type_stored_on_track(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_playlist.return_value = self._make_playlist_response([
            self._make_track_item("v1", "ATV Track", VIDEO_TYPE_ATV),
        ])

        tracks = get_playlist_tracks("test_playlist")
        assert tracks[0].video_type == VIDEO_TYPE_ATV


class TestGetChartsVideoTypeFiltering:
    """Test that get_charts() filters by video type."""

    @patch("kikusan.search.YTMusic")
    def test_filters_ugc_chart_tracks(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_charts.return_value = {
            "videos": [
                {"title": "Charts", "playlistId": "PL_test", "thumbnails": []},
            ],
            "artists": [],
        }
        mock_yt.get_playlist.return_value = {
            "title": "Charts",
            "tracks": [
                {
                    "videoId": "v1",
                    "title": "Official",
                    "artists": [{"name": "A"}],
                    "thumbnails": [],
                    "videoType": VIDEO_TYPE_ATV,
                },
                {
                    "videoId": "v2",
                    "title": "UGC",
                    "artists": [{"name": "B"}],
                    "thumbnails": [],
                    "videoType": VIDEO_TYPE_UGC,
                },
            ],
        }

        charts = get_charts("US")
        assert len(charts.tracks) == 1
        assert charts.tracks[0].video_id == "v1"

    @patch("kikusan.search.YTMusic")
    def test_includes_ugc_chart_tracks_with_flag(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_charts.return_value = {
            "videos": [
                {"title": "Charts", "playlistId": "PL_test", "thumbnails": []},
            ],
            "artists": [],
        }
        mock_yt.get_playlist.return_value = {
            "title": "Charts",
            "tracks": [
                {
                    "videoId": "v1",
                    "title": "Official",
                    "artists": [{"name": "A"}],
                    "thumbnails": [],
                    "videoType": VIDEO_TYPE_ATV,
                },
                {
                    "videoId": "v2",
                    "title": "UGC",
                    "artists": [{"name": "B"}],
                    "thumbnails": [],
                    "videoType": VIDEO_TYPE_UGC,
                },
            ],
        }

        charts = get_charts("US", allow_ugc=True)
        assert len(charts.tracks) == 2

    @patch("kikusan.search.YTMusic")
    def test_video_type_stored_on_chart_track(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_charts.return_value = {
            "videos": [
                {"title": "Charts", "playlistId": "PL_test", "thumbnails": []},
            ],
            "artists": [],
        }
        mock_yt.get_playlist.return_value = {
            "title": "Charts",
            "tracks": [
                {
                    "videoId": "v1",
                    "title": "Track",
                    "artists": [{"name": "A"}],
                    "thumbnails": [],
                    "videoType": VIDEO_TYPE_OMV,
                },
            ],
        }

        charts = get_charts()
        assert charts.tracks[0].video_type == VIDEO_TYPE_OMV


class TestGetTrackFromVideoIdVideoType:
    """Test that get_track_from_video_id() extracts musicVideoType."""

    @patch("kikusan.search.YTMusic")
    def test_extracts_music_video_type(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_song.return_value = {
            "videoDetails": {
                "videoId": "abc123abcde",
                "title": "Test Song",
                "author": "Test Artist",
                "lengthSeconds": "200",
                "thumbnail": {"thumbnails": []},
                "viewCount": "1000",
                "musicVideoType": VIDEO_TYPE_ATV,
            }
        }

        track = get_track_from_video_id("abc123abcde")
        assert track.video_type == VIDEO_TYPE_ATV

    @patch("kikusan.search.YTMusic")
    def test_video_type_none_when_missing(self, mock_ytmusic_cls):
        mock_yt = MagicMock()
        mock_ytmusic_cls.return_value = mock_yt
        mock_yt.get_song.return_value = {
            "videoDetails": {
                "videoId": "abc123abcde",
                "title": "Test Song",
                "author": "Test Artist",
                "lengthSeconds": "200",
                "thumbnail": {"thumbnails": []},
                "viewCount": "1000",
            }
        }

        track = get_track_from_video_id("abc123abcde")
        assert track.video_type is None


class TestConfigAllowUgc:
    """Test allow_ugc configuration."""

    def test_default_is_false(self):
        with patch.dict(os.environ, {}, clear=False):
            # Ensure KIKUSAN_ALLOW_UGC is not set
            os.environ.pop("KIKUSAN_ALLOW_UGC", None)
            config = Config.from_env()
            assert config.allow_ugc is False

    def test_true_from_env(self):
        with patch.dict(os.environ, {"KIKUSAN_ALLOW_UGC": "true"}):
            config = Config.from_env()
            assert config.allow_ugc is True

    def test_one_from_env(self):
        with patch.dict(os.environ, {"KIKUSAN_ALLOW_UGC": "1"}):
            config = Config.from_env()
            assert config.allow_ugc is True

    def test_yes_from_env(self):
        with patch.dict(os.environ, {"KIKUSAN_ALLOW_UGC": "yes"}):
            config = Config.from_env()
            assert config.allow_ugc is True

    def test_false_from_env(self):
        with patch.dict(os.environ, {"KIKUSAN_ALLOW_UGC": "false"}):
            config = Config.from_env()
            assert config.allow_ugc is False


class TestExploreSyncAllowUgc:
    """Test that explore sync passes allow_ugc to search functions."""

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync.get_charts")
    def test_fetch_chart_tracks_passes_allow_ugc(self, mock_get_charts, mock_get_config):
        from kikusan.cron.explore_sync import _fetch_chart_tracks

        mock_get_charts.return_value = Charts(country="US", tracks=[], artists=[])

        _fetch_chart_tracks("US", allow_ugc=True)
        mock_get_charts.assert_called_once_with("US", allow_ugc=True)

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync.get_playlist_tracks")
    def test_fetch_mood_tracks_passes_allow_ugc_to_specific_playlist(
        self, mock_playlist_tracks, mock_get_config,
    ):
        from kikusan.cron.explore_sync import _fetch_mood_tracks

        mock_playlist_tracks.return_value = []

        _fetch_mood_tracks("params", playlist_id="PL123", allow_ugc=True)
        mock_playlist_tracks.assert_called_once_with("PL123", allow_ugc=True)

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync.get_playlist_tracks")
    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_fetch_mood_tracks_passes_allow_ugc_to_all_playlists(
        self, mock_mood_playlists, mock_playlist_tracks, mock_get_config,
    ):
        from kikusan.cron.explore_sync import _fetch_mood_tracks
        from kikusan.search import MoodPlaylist

        mock_mood_playlists.return_value = [
            MoodPlaylist(playlist_id="PL1", title="P1", thumbnail_url=None, author=None),
        ]
        mock_playlist_tracks.return_value = []

        _fetch_mood_tracks("params", allow_ugc=True)
        mock_playlist_tracks.assert_called_once_with("PL1", allow_ugc=True)

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync._fetch_chart_tracks")
    def test_fetch_explore_tracks_passes_config_allow_ugc(
        self, mock_fetch_charts, mock_get_config,
    ):
        from kikusan.cron.config import ExploreConfig
        from kikusan.cron.explore_sync import fetch_explore_tracks

        mock_config = MagicMock()
        mock_config.allow_ugc = True
        mock_get_config.return_value = mock_config
        mock_fetch_charts.return_value = []

        config = ExploreConfig(
            name="charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        fetch_explore_tracks(config)
        mock_fetch_charts.assert_called_once_with("US", allow_ugc=True)
