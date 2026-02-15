"""Tests for explore sync functionality (charts/moods/genres cron sync)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kikusan.cron.config import ExploreConfig
from kikusan.cron.explore_sync import (
    _build_explore_url,
    _fetch_chart_tracks,
    _fetch_mood_tracks,
    fetch_explore_tracks,
    sync_explore,
)
from kikusan.cron.sync import SyncResult
from kikusan.search import ChartTrack, Charts, MoodPlaylist, Track


class TestFetchChartTracks:
    """Test _fetch_chart_tracks()."""

    @patch("kikusan.cron.explore_sync.get_charts")
    def test_returns_tracks(self, mock_get_charts):
        mock_get_charts.return_value = Charts(
            country="US",
            tracks=[
                ChartTrack(
                    video_id="abc123",
                    title="Hit Song",
                    artist="Artist A",
                    artists=["Artist A"],
                    album="Album X",
                    thumbnail_url=None,
                    rank="1",
                    trend=None,
                ),
                ChartTrack(
                    video_id="def456",
                    title="Another Hit",
                    artist="Artist B",
                    artists=["Artist B"],
                    album=None,
                    thumbnail_url=None,
                    rank="2",
                    trend=None,
                ),
            ],
            artists=[],
        )

        tracks = _fetch_chart_tracks("US")
        assert len(tracks) == 2
        assert tracks[0] == ("abc123", "Hit Song", "Artist A")
        assert tracks[1] == ("def456", "Another Hit", "Artist B")
        mock_get_charts.assert_called_once_with("US", allow_ugc=False)

    @patch("kikusan.cron.explore_sync.get_charts")
    def test_skips_empty_video_ids(self, mock_get_charts):
        mock_get_charts.return_value = Charts(
            country="ZZ",
            tracks=[
                ChartTrack(
                    video_id="abc123",
                    title="Good",
                    artist="A",
                    artists=["A"],
                    album=None,
                    thumbnail_url=None,
                    rank="1",
                    trend=None,
                ),
                ChartTrack(
                    video_id="",
                    title="Bad",
                    artist="B",
                    artists=["B"],
                    album=None,
                    thumbnail_url=None,
                    rank="2",
                    trend=None,
                ),
            ],
            artists=[],
        )

        tracks = _fetch_chart_tracks("ZZ")
        assert len(tracks) == 1
        assert tracks[0][0] == "abc123"

    @patch("kikusan.cron.explore_sync.get_charts")
    def test_empty_charts(self, mock_get_charts):
        mock_get_charts.return_value = Charts(country="ZZ", tracks=[], artists=[])

        tracks = _fetch_chart_tracks("ZZ")
        assert tracks == []

    @patch("kikusan.cron.explore_sync.get_charts")
    def test_api_error_returns_empty(self, mock_get_charts):
        mock_get_charts.side_effect = Exception("API error")

        tracks = _fetch_chart_tracks("US")
        assert tracks == []


class TestFetchMoodTracks:
    """Test _fetch_mood_tracks()."""

    @patch("kikusan.cron.explore_sync.get_playlist_tracks")
    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_returns_tracks_from_all_playlists(self, mock_mood_playlists, mock_playlist_tracks):
        mock_mood_playlists.return_value = [
            MoodPlaylist(playlist_id="PL1", title="Playlist 1", thumbnail_url=None, author=None),
            MoodPlaylist(playlist_id="PL2", title="Playlist 2", thumbnail_url=None, author=None),
        ]

        mock_playlist_tracks.side_effect = [
            [
                Track(video_id="vid1", title="Song 1", artist="A1", artists=["A1"], album=None, duration_seconds=200, thumbnail_url=None, view_count=None),
            ],
            [
                Track(video_id="vid2", title="Song 2", artist="A2", artists=["A2"], album=None, duration_seconds=180, thumbnail_url=None, view_count=None),
            ],
        ]

        tracks = _fetch_mood_tracks("ggMPOg1uX1J")
        assert len(tracks) == 2
        assert tracks[0] == ("vid1", "Song 1", "A1")
        assert tracks[1] == ("vid2", "Song 2", "A2")

    @patch("kikusan.cron.explore_sync.get_playlist_tracks")
    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_deduplicates_across_playlists(self, mock_mood_playlists, mock_playlist_tracks):
        """Test that tracks appearing in multiple playlists are deduplicated."""
        mock_mood_playlists.return_value = [
            MoodPlaylist(playlist_id="PL1", title="Playlist 1", thumbnail_url=None, author=None),
            MoodPlaylist(playlist_id="PL2", title="Playlist 2", thumbnail_url=None, author=None),
        ]

        shared_track = Track(
            video_id="shared_vid", title="Shared Song", artist="A1",
            artists=["A1"], album=None, duration_seconds=200,
            thumbnail_url=None, view_count=None,
        )

        mock_playlist_tracks.side_effect = [
            [shared_track],
            [
                shared_track,  # duplicate
                Track(video_id="unique_vid", title="Unique Song", artist="A2", artists=["A2"], album=None, duration_seconds=180, thumbnail_url=None, view_count=None),
            ],
        ]

        tracks = _fetch_mood_tracks("params")
        assert len(tracks) == 2
        video_ids = [t[0] for t in tracks]
        assert "shared_vid" in video_ids
        assert "unique_vid" in video_ids

    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_empty_mood_playlists(self, mock_mood_playlists):
        mock_mood_playlists.return_value = []

        tracks = _fetch_mood_tracks("params")
        assert tracks == []

    @patch("kikusan.cron.explore_sync.get_playlist_tracks")
    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_continues_on_playlist_error(self, mock_mood_playlists, mock_playlist_tracks):
        """Test that failing to fetch one playlist doesn't stop the others."""
        mock_mood_playlists.return_value = [
            MoodPlaylist(playlist_id="PL_bad", title="Bad", thumbnail_url=None, author=None),
            MoodPlaylist(playlist_id="PL_good", title="Good", thumbnail_url=None, author=None),
        ]

        mock_playlist_tracks.side_effect = [
            Exception("Failed to fetch"),
            [
                Track(video_id="vid1", title="Song", artist="A", artists=["A"], album=None, duration_seconds=200, thumbnail_url=None, view_count=None),
            ],
        ]

        tracks = _fetch_mood_tracks("params")
        assert len(tracks) == 1
        assert tracks[0][0] == "vid1"

    @patch("kikusan.cron.explore_sync.get_mood_playlists")
    def test_api_error_returns_empty(self, mock_mood_playlists):
        mock_mood_playlists.side_effect = Exception("API error")

        tracks = _fetch_mood_tracks("params")
        assert tracks == []


class TestFetchExploreTracks:
    """Test fetch_explore_tracks() routing."""

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync._fetch_chart_tracks")
    def test_routes_to_charts(self, mock_fetch_charts, mock_get_config):
        mock_config_obj = MagicMock()
        mock_config_obj.allow_ugc = False
        mock_get_config.return_value = mock_config_obj
        mock_fetch_charts.return_value = [("vid1", "Song", "Artist")]

        config = ExploreConfig(
            name="us-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        tracks = fetch_explore_tracks(config)
        assert tracks == [("vid1", "Song", "Artist")]
        mock_fetch_charts.assert_called_once_with("US", allow_ugc=False)

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync._fetch_mood_tracks")
    def test_routes_to_mood(self, mock_fetch_mood, mock_get_config):
        mock_config_obj = MagicMock()
        mock_config_obj.allow_ugc = False
        mock_get_config.return_value = mock_config_obj
        mock_fetch_mood.return_value = [("vid1", "Song", "Artist")]

        config = ExploreConfig(
            name="pop-moods", type="mood", sync=True,
            schedule="0 12 * * 0", params="ggMPOg1uX1J",
        )

        tracks = fetch_explore_tracks(config)
        assert tracks == [("vid1", "Song", "Artist")]
        mock_fetch_mood.assert_called_once_with("ggMPOg1uX1J", "", allow_ugc=False)

    @patch("kikusan.cron.explore_sync.get_config")
    @patch("kikusan.cron.explore_sync._fetch_mood_tracks")
    def test_routes_to_mood_with_playlist_id(self, mock_fetch_mood, mock_get_config):
        mock_config = MagicMock()
        mock_config.allow_ugc = False
        mock_get_config.return_value = mock_config
        mock_fetch_mood.return_value = [("vid1", "Song", "Artist")]

        config = ExploreConfig(
            name="pop-moods", type="mood", sync=True,
            schedule="0 12 * * 0", params="ggMPOg1uX1J",
            playlist_id="RDCLAK5uy_test123",
        )

        tracks = fetch_explore_tracks(config)
        assert tracks == [("vid1", "Song", "Artist")]
        mock_fetch_mood.assert_called_once_with("ggMPOg1uX1J", "RDCLAK5uy_test123", allow_ugc=False)

    def test_unknown_type_returns_empty(self):
        config = ExploreConfig(
            name="unknown", type="invalid", sync=True,
            schedule="0 6 * * *",
        )

        tracks = fetch_explore_tracks(config)
        assert tracks == []


class TestBuildExploreUrl:
    """Test _build_explore_url()."""

    def test_charts_url(self):
        config = ExploreConfig(
            name="us-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )
        assert _build_explore_url(config) == "explore:charts:US"

    def test_mood_url(self):
        config = ExploreConfig(
            name="pop", type="mood", sync=True,
            schedule="0 12 * * 0", params="ggMPOg1uX1J",
        )
        assert _build_explore_url(config) == "explore:mood:ggMPOg1uX1J"

    def test_mood_url_with_playlist_id(self):
        config = ExploreConfig(
            name="pop-playlist", type="mood", sync=True,
            schedule="0 12 * * 0", params="ggMPOg1uX1J",
            playlist_id="RDCLAK5uy_test123",
        )
        assert _build_explore_url(config) == "explore:mood:ggMPOg1uX1J:playlist:RDCLAK5uy_test123"


class TestSyncExplore:
    """Test sync_explore() end-to-end behavior."""

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_fresh_sync_downloads_all(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test first sync with no existing state downloads all tracks."""
        mock_fetch.return_value = [
            ("vid1", "Song 1", "Artist 1"),
            ("vid2", "Song 2", "Artist 2"),
        ]
        mock_load_state.return_value = None  # No existing state
        mock_compare.return_value = (
            [("vid1", "Song 1", "Artist 1"), ("vid2", "Song 2", "Artist 2")],
            [],  # no removed tracks
        )
        mock_download.return_value = {"downloaded": 2, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="us-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        assert isinstance(result, SyncResult)
        assert result.downloaded == 2
        assert result.skipped == 0
        assert result.deleted == 0
        assert result.failed == 0

        mock_fetch.assert_called_once_with(config)
        mock_update_m3u.assert_called_once()
        mock_save_state.assert_called_once()

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.remove_old_tracks")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_sync_with_deletions(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_remove, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test sync with sync=true removes old tracks."""
        from kikusan.cron.state import PlaylistState, TrackState

        mock_fetch.return_value = [("vid2", "New Song", "New Artist")]
        mock_load_state.return_value = PlaylistState(
            playlist_name="us-charts",
            url="explore:charts:US",
            last_check="2024-01-01T00:00:00",
            tracks=[
                TrackState(
                    video_id="vid1", title="Old Song", artist="Old Artist",
                    file_path="/tmp/old.opus", downloaded_at="2024-01-01T00:00:00",
                ),
            ],
        )
        removed_track = TrackState(
            video_id="vid1", title="Old Song", artist="Old Artist",
            file_path="/tmp/old.opus", downloaded_at="2024-01-01T00:00:00",
        )
        mock_compare.return_value = (
            [("vid2", "New Song", "New Artist")],
            [removed_track],
        )
        mock_download.return_value = {"downloaded": 1, "skipped": 0, "failed": 0}
        mock_remove.return_value = 1

        config = ExploreConfig(
            name="us-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        assert result.downloaded == 1
        assert result.deleted == 1
        mock_remove.assert_called_once()

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.remove_old_tracks")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_sync_false_skips_deletions(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_remove, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test sync with sync=false does not remove old tracks."""
        from kikusan.cron.state import PlaylistState, TrackState

        mock_fetch.return_value = [("vid2", "New", "New")]
        mock_load_state.return_value = PlaylistState(
            playlist_name="charts",
            url="explore:charts:US",
            last_check="2024-01-01T00:00:00",
            tracks=[
                TrackState(
                    video_id="vid1", title="Old", artist="Old",
                    file_path="/tmp/old.opus", downloaded_at="2024-01-01",
                ),
            ],
        )
        removed_track = TrackState(
            video_id="vid1", title="Old", artist="Old",
            file_path="/tmp/old.opus", downloaded_at="2024-01-01",
        )
        mock_compare.return_value = (
            [("vid2", "New", "New")],
            [removed_track],
        )
        mock_download.return_value = {"downloaded": 1, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="charts", type="charts", sync=False,
            schedule="0 6 * * *", country="US",
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        assert result.deleted == 0
        mock_remove.assert_not_called()

    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_no_tracks_returns_zero_result(self, mock_fetch, tmp_path):
        """Test that empty track list returns zero result."""
        mock_fetch.return_value = []

        config = ExploreConfig(
            name="empty-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        assert result.downloaded == 0
        assert result.skipped == 0
        assert result.deleted == 0
        assert result.failed == 0

    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_exception_returns_failed_result(self, mock_fetch, tmp_path):
        """Test that an exception returns a failed result instead of crashing."""
        mock_fetch.side_effect = Exception("Network error")

        config = ExploreConfig(
            name="broken", type="charts", sync=True,
            schedule="0 6 * * *", country="US",
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        assert result.failed == 1
        assert result.downloaded == 0


class TestSyncExploreLimit:
    """Test that the limit configuration truncates the track list."""

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_limit_truncates_tracks(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test that limit=2 only keeps the first 2 tracks."""
        all_tracks = [
            ("vid1", "Song 1", "Artist 1"),
            ("vid2", "Song 2", "Artist 2"),
            ("vid3", "Song 3", "Artist 3"),
            ("vid4", "Song 4", "Artist 4"),
            ("vid5", "Song 5", "Artist 5"),
        ]
        mock_fetch.return_value = all_tracks
        mock_load_state.return_value = None
        mock_compare.return_value = (
            [("vid1", "Song 1", "Artist 1"), ("vid2", "Song 2", "Artist 2")],
            [],
        )
        mock_download.return_value = {"downloaded": 2, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="de-top2", type="charts", sync=True,
            schedule="0 6 * * *", country="DE", limit=2,
        )

        result = sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        # compare_tracks should receive only the first 2 tracks
        compare_args = mock_compare.call_args[0]
        assert len(compare_args[0]) == 2
        assert compare_args[0][0][0] == "vid1"
        assert compare_args[0][1][0] == "vid2"

        assert result.downloaded == 2

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_limit_zero_means_no_limit(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test that limit=0 (default) passes all tracks through."""
        all_tracks = [
            ("vid1", "Song 1", "Artist 1"),
            ("vid2", "Song 2", "Artist 2"),
            ("vid3", "Song 3", "Artist 3"),
        ]
        mock_fetch.return_value = all_tracks
        mock_load_state.return_value = None
        mock_compare.return_value = (all_tracks, [])
        mock_download.return_value = {"downloaded": 3, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="all-charts", type="charts", sync=True,
            schedule="0 6 * * *", country="US", limit=0,
        )

        sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        # compare_tracks should receive all 3 tracks (no truncation)
        compare_args = mock_compare.call_args[0]
        assert len(compare_args[0]) == 3

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_limit_larger_than_tracks_passes_all(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test that limit > track count passes all tracks through."""
        all_tracks = [
            ("vid1", "Song 1", "Artist 1"),
            ("vid2", "Song 2", "Artist 2"),
        ]
        mock_fetch.return_value = all_tracks
        mock_load_state.return_value = None
        mock_compare.return_value = (all_tracks, [])
        mock_download.return_value = {"downloaded": 2, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="charts-100", type="charts", sync=True,
            schedule="0 6 * * *", country="US", limit=100,
        )

        sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        # compare_tracks should receive all 2 tracks (limit > count)
        compare_args = mock_compare.call_args[0]
        assert len(compare_args[0]) == 2

    @patch("kikusan.cron.explore_sync.save_state")
    @patch("kikusan.cron.explore_sync.update_m3u_playlist")
    @patch("kikusan.cron.explore_sync.download_new_tracks")
    @patch("kikusan.cron.explore_sync.compare_tracks")
    @patch("kikusan.cron.explore_sync.load_state")
    @patch("kikusan.cron.explore_sync.fetch_explore_tracks")
    def test_limit_one_keeps_only_first_track(
        self, mock_fetch, mock_load_state, mock_compare,
        mock_download, mock_update_m3u, mock_save_state, tmp_path,
    ):
        """Test that limit=1 keeps only the first (top) track."""
        all_tracks = [
            ("vid1", "Song 1", "Artist 1"),
            ("vid2", "Song 2", "Artist 2"),
            ("vid3", "Song 3", "Artist 3"),
        ]
        mock_fetch.return_value = all_tracks
        mock_load_state.return_value = None
        mock_compare.return_value = ([("vid1", "Song 1", "Artist 1")], [])
        mock_download.return_value = {"downloaded": 1, "skipped": 0, "failed": 0}

        config = ExploreConfig(
            name="top1", type="charts", sync=True,
            schedule="0 6 * * *", country="DE", limit=1,
        )

        sync_explore(
            explore_config=config,
            download_dir=tmp_path,
            audio_format="opus",
            filename_template="%(artist,uploader)s - %(title)s",
        )

        compare_args = mock_compare.call_args[0]
        assert len(compare_args[0]) == 1
        assert compare_args[0][0][0] == "vid1"
