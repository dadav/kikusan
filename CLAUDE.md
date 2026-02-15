# Project description

Kikusan is a tool to search and download music from youtube music. It must use yt-dlp in the background. It must be usable through CLI and also have a web app (subcommand "web"). The web app should be really simple, but must support search functionality. It should be deployable with docker and have an example docker-compose file. It must add lyrics via lrc files to the downloaded files (via https://lrclib.net/).

## Features

### Web UI

- Search functionality with results display
  - **URL Support**: Paste YouTube Music URLs directly into search bar
    - Single track URLs: `https://music.youtube.com/watch?v=VIDEO_ID`
    - Playlist URLs: `https://music.youtube.com/playlist?list=PLAYLIST_ID`
    - Also supports `youtube.com` and `youtu.be` URL variants
    - Playlist URLs return ALL tracks (no 20-result limit like text search)
    - Results displayed in same format as text search
    - **Radio playlist handling**: Radio playlists (IDs starting with `RDAM`) are not supported due to different API structure
      - URLs with both video and radio playlist (e.g., `?v=VIDEO_ID&list=RDAM...`) fall back to returning just the video
      - Radio-only playlist URLs return clear error: "Radio playlists are not supported"
      - Protection implemented in both `parse_youtube_url()` and `get_playlist_tracks()`
  - Backend auto-detects URL vs text query using `parse_youtube_url()` in `search.py`
  - URL metadata fetched via ytmusicapi: `get_track_from_video_id()` for singles, `get_playlist_tracks()` for playlists
  - **Deezer playlist URL support**: `https://www.deezer.com/playlist/{id}` (also localized paths like `/us/playlist/{id}`)
    - Deezer tracks are resolved to YouTube Music via search (`"{title} {artist}"`) so the UI can queue/download them through existing `video_id` flow
    - Implemented in `api_search()` using `kikusan/deezer.py`
  - **Playlist progress streaming (web UI)**:
    - Playlist searches use Server-Sent Events to show progress (matching `x/y` tracks for Deezer, resolved count for YouTube playlists)
    - Endpoint: `GET /api/search/playlist/stream?q=...` in `kikusan/web/app.py`
    - Frontend uses `EventSource` with `progress`, `complete`, and `failure` events in `kikusan/web/templates/index.html`
    - Test coverage: `tests/test_web_search_playlist_stream.py`
- View counts displayed for each song (e.g., "1.9B views", "47M views")
  - View counts are retrieved from ytmusicapi search results (no additional API calls needed)
  - Displayed alongside duration in the track metadata section
- Download button for each track
- Dark/light theme toggle
- Version display in header (dynamically loaded from `pyproject.toml` via `importlib.metadata`)
- **Explore tab**: Browse moods, genres, and music charts from YouTube Music
  - Three-level navigation: Categories -> Playlists -> Tracks (with breadcrumb nav)
  - Mood/genre categories displayed as clickable grid cards
  - Charts with country selector (11 countries + global)
  - View counts displayed for chart tracks and playlist tracks (when available from API)
  - Play preview button and Copy URL button on all explore track listings (charts and playlists)
  - Duration displayed alongside view counts in chart track metadata
  - "Download All" buttons for bulk queueing of playlist tracks and chart tracks
  - "Cron" button (+ Cron) on charts header and mood/genre breadcrumb for copying cron.yaml config snippets to clipboard
    - Charts: generates `type: charts` config with selected country, sync, schedule, and limit
    - Moods: generates `type: mood` config with category params, sync, and schedule
    - Sanitizes category titles into valid cron config keys (lowercase, alphanumeric + dashes)
    - Clipboard copy with "Copied!" feedback and fallback for older browsers
    - CSS: `.cron-btn` (standard) and `.cron-btn-inline` (breadcrumb variant) in `style.css`
    - JS: `generateCronYaml()` and `copyCronConfig()` in embedded script
  - Reuses existing download queue infrastructure (`/api/queue/add`)
- **Downloads tab**: View and manage the M3U download playlist from the web UI
  - Tab is conditionally shown only when `KIKUSAN_WEB_PLAYLIST` is configured (checked via `/api/playlist/status`)
  - Displays track list with metadata (title, artist, album, duration) extracted via mutagen
  - Falls back to path-based parsing when mutagen metadata is unavailable
  - "Save" link per track to download the file to the browser (reuses `/api/download-file/` endpoint)
  - "Remove" button per track to remove from playlist (does not delete audio file from disk)
  - Missing files shown with dashed border and "File missing" label
  - Auto-refreshes when a download job completes (detected via existing SSE stream)
  - Multi-user aware: each user sees their own playlist via `effective_playlist_name()`
  - API endpoints: `GET /api/playlist/status`, `GET /api/playlist/tracks`, `DELETE /api/playlist/tracks`
  - Metadata extraction runs in thread pool executor to avoid blocking async event loop
  - CSS classes: `.downloads-section`, `.downloads-header`, `.downloads-empty`, `.downloads-list`, `.track-missing`, `.track-missing-label`, `.remove-btn`
  - JS functions: `checkPlaylistStatus()`, `loadDownloads()`, `renderDownloads()`, `handleRemoveTrack()`
  - Helpers: `_extract_track_info()` (mutagen + path fallback), `_parse_track_info_from_path()` (flat + album mode)
  - Playlist read/remove functions: `read_m3u()`, `remove_from_m3u()` in `kikusan/playlist.py`
- **Multi-user playlist support**: When `KIKUSAN_MULTI_USER=true` (or `--multi-user` flag), parses the `Remote-User` header (set by reverse proxy SSO like Authelia) and prefixes the M3U playlist name with the username (e.g., `alice-webplaylist.m3u`)
  - Opt-in: requires `KIKUSAN_MULTI_USER=true` env var or `--multi-user` CLI flag
  - Falls back to shared playlist when header is absent or feature is disabled
  - Username sanitization: only `[a-zA-Z0-9._-]` allowed, max 64 chars
  - Implementation: `_get_remote_user()` in `kikusan/web/app.py`, `Config.effective_playlist_name()` in `kikusan/config.py`
  - Playlist name is resolved at request time and stored on `DownloadJob.playlist_name` for queue-based downloads

### Sync Safety Features

- **Cross-Reference Protection**: When `sync=True` for a playlist/plugin, songs are only deleted from disk if they are not referenced by any other playlist or plugin
- Implementation in `kikusan/reference_checker.py`: Scans all playlist and plugin state files before deletion
- Each deletion operation checks both `.kikusan/state/*.json` (playlists) and `.kikusan/plugin_state/*.json` (plugins)
- Songs are removed from the current playlist/plugin state even if the file is preserved due to other references

- **Navidrome Protection**: Prevents deletion of songs starred in Navidrome or in designated "keep" playlist
- Real-time API checks during sync operations via Subsonic API
- Batch caching for performance (fetches once per sync, not per file)
- Two-tier matching: path-based (fast/accurate) + metadata-based (fallback)
- Fail-safe behavior: keeps files if Navidrome is unreachable
- Opt-in via environment variables: NAVIDROME_URL, NAVIDROME_USER, NAVIDROME_PASSWORD, NAVIDROME_KEEP_PLAYLIST

### Filename Length Safety

- Filenames are truncated to `MAX_FILENAME_BYTES` (200 bytes) to prevent `[Errno 36] File name too long` errors
- Two layers of protection:
  1. **yt-dlp level**: `trim_file_name` option in `_get_ydl_opts()` and `_compute_filename()` truncates rendered filenames
  2. **Path component level**: `_sanitize_path_component()` truncates directory names (artist, album) in album mode
- `_truncate_to_bytes()` handles UTF-8 safely (never splits multi-byte characters)
- The constant `MAX_FILENAME_BYTES` is defined in `kikusan/config.py`

### Video Type Filtering

- YouTube Music categorizes content by video type:
  - **ATV** (`MUSIC_VIDEO_TYPE_ATV`): Audio Track Video - high quality audio, uploaded by artist
  - **OMV** (`MUSIC_VIDEO_TYPE_OMV`): Official Music Video - actual video from artist
  - **OFFICIAL_SOURCE_MUSIC** (`MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC`): Official but not single track (compilations)
  - **UGC** (`MUSIC_VIDEO_TYPE_UGC`): User Generated Content
- Default: Only ATV + OMV tracks are included in playlist and chart results
- Opt-in for UGC: `KIKUSAN_ALLOW_UGC=true` env var or `--allow-ugc` CLI flag
- Filtering applies in contexts where `videoType` is available: `get_playlist_tracks()`, `get_charts()`
- NOT filtered in contexts where `videoType` is structurally absent: text search (`filter="songs"`), album tracks, yt-dlp flat extract
- Tracks without a `videoType` field (null) pass through unfiltered
- Explicit single video downloads by ID/URL always work regardless of type
- Implementation: `is_allowed_video_type()` helper and `ALLOWED_VIDEO_TYPES` frozenset in `kikusan/search.py`
- `Track` and `ChartTrack` dataclasses have `video_type: str | None = None` field
- Web UI: All tracks shown (pass `allow_ugc=True`), UGC/OFFICIAL_SOURCE tracks display a "UGC" badge via `isUgcVideoType()` JS helper and `.ugc-badge` CSS class
- `TrackResponse` and `ChartTrackResponse` include `video_type: str | None = None` field
- Cron explore sync reads `allow_ugc` from config and passes to `get_charts()`/`get_playlist_tracks()`
- Test coverage: `tests/test_video_type.py`

### Unavailable Video Cooldown

- When a video returns "Video unavailable" during download, the video ID is recorded with a timestamp
- Subsequent sync/download attempts skip that video until the cooldown period expires
- Storage: `.kikusan/unavailable.json` - maps video_id to failure record (timestamp, error, title, artist)
- Default cooldown: 168 hours (7 days), configurable via `KIKUSAN_UNAVAILABLE_COOLDOWN_HOURS` env var or `--unavailable-cooldown` CLI flag
- Set cooldown to 0 to disable the feature entirely
- Only "Video unavailable" errors trigger cooldown (not auth errors, network errors, etc.)
- Integrated into ALL download paths:
  - `kikusan/download.py`: `download()` (single video - checks cooldown + records on failure), `_download_single()` (URL-based single track), `_download_playlist()` (playlist entries), `download_url()` (URL info extraction)
  - `kikusan/cron/sync.py`: `download_new_tracks()` (additional pre-check before calling `download()`)
  - `kikusan/plugins/sync.py`: `_download_songs()` (additional pre-check before calling `download()`)
- `UnavailableCooldownError`: Custom exception raised by `download()` when a video is on cooldown, caught by CLI for user-friendly output
- `_extract_video_id_from_url()`: Helper to extract video ID from YouTube URLs for recording in `download_url()` path
- Implementation in `kikusan/unavailable.py`: Pattern matching, JSON persistence with atomic writes, cooldown logic
- Corrupted unavailable files are backed up and reset (same pattern as state files)

### Architecture Notes

- `kikusan/search.py`: Uses ytmusicapi to search and explore YouTube Music
  - Search: `search()`, `search_albums()`, `get_album_tracks()` — song/album search with view_count extraction
  - Explore: `get_mood_categories()`, `get_mood_playlists()`, `get_charts()`, `get_playlist_tracks()` — mood/genre browsing and chart data
  - `get_mood_playlists()`: Has fallback parsing (`_get_mood_playlists_fallback()`) for when ytmusicapi crashes with KeyError on `musicTwoRowItemRenderer`. Some mood/genre categories return mixed content: some sections contain playlist items (`musicTwoRowItemRenderer`) while others contain song items (`musicResponsiveListItemRenderer`). The fallback manually parses the raw YouTube Music API response, skipping incompatible sections and handling individual item parse failures gracefully.
  - `get_mood_playlists()` normalizes playlist `author` payloads from ytmusicapi/fallback to a stable `str | None` (`_normalize_mood_playlist_author`) to avoid API response validation errors.
  - `get_charts()`: ytmusicapi returns `videos` as a list of playlist references (not individual tracks) and `artists` as a flat list. The function fetches tracks from the first working video playlist via `get_playlist()`, with fallback to subsequent playlists if one fails (e.g. album-style IDs like `OLAK5uy_...` are not fetchable via `get_playlist`).
  - `ChartTrack` includes `view_count` (str|None) and `duration_seconds` (int) with a `duration_display` property (MM:SS format), extracted from playlist data in `get_charts()`
  - Metadata: `get_song_metadata()` — fetches clean title/artist/album/duration from `YTMusic().get_song()` and `get_watch_playlist()` for lyrics lookup enhancement
  - `SongMetadata` dataclass: title, artist, album (optional), duration_seconds — used by `lyrics.py` for lrclib.net lookups
  - `_get_album_from_watch_playlist()`: Extracts album name from watch playlist (not available in `get_song()` videoDetails)
  - `_get_metadata_from_watch_playlist()`: Full fallback when `get_song()` returns incomplete videoDetails
  - Data classes: `Track`, `Album`, `MoodCategory`, `MoodSection`, `MoodPlaylist`, `ChartTrack`, `ChartArtist`, `Charts`, `SongMetadata`
- `kikusan/web/app.py`: FastAPI backend with search, download, and explore endpoints
  - `/api/search` supports Deezer playlist URLs in addition to YouTube URLs and text queries
- `kikusan/deezer.py`: Native Deezer playlist integration
  - URL detection: `is_deezer_url()`
  - Playlist track fetch: `get_tracks_from_url()` / `get_playlist_tracks()`
  - Uses Deezer REST playlist pagination (`/playlist/{id}/tracks?index=&limit=`) to avoid per-track API calls
  - `DeezerQuotaError` maps Deezer API code `4` ("Quota limit exceeded") to explicit temporary failure handling
  - Maps Deezer track metadata (`title`, `artist`, `contributors`, `album`, `duration`) into `DeezerTrack`
- `kikusan/cli.py`:
  - `download --url` supports Deezer playlists (first level) via shared external-source download flow (`_download_external_url`)
- `kikusan/cron/sync.py`:
  - `fetch_current_tracks()` now dispatches Deezer URLs to `_fetch_deezer_tracks()` (Deezer -> YouTube Music resolution)
- `kikusan/cron/config.py`:
  - `validate_url()` accepts Deezer playlist URLs
  - Explore endpoints: `GET /api/explore/moods`, `GET /api/explore/mood-playlists`, `GET /api/explore/charts`, `GET /api/explore/playlist/{playlist_id}/tracks`
- `kikusan/web/templates/index.html`: Single-page frontend with embedded JavaScript (Songs, Albums, Explore tabs)
- `kikusan/web/static/style.css`: Responsive CSS with dark/light themes, explore grid layouts
- `kikusan/reference_checker.py`: Cross-playlist/plugin reference checking for safe file deletion
  - Includes metadata extraction using mutagen
  - Navidrome protection checks via batch caching
  - Fail-safe deletion logic (keeps files on errors)
- `kikusan/navidrome.py`: Subsonic API client for Navidrome integration
  - Token-based authentication (MD5 hash per Subsonic API spec)
  - Fetches starred songs and playlist contents
  - Two-tier song matching (path-based + metadata-based)
  - Environment-based configuration: NAVIDROME_URL, NAVIDROME_USER, NAVIDROME_PASSWORD
- `kikusan/cron/sync.py`: Playlist synchronization with reference-aware deletion and Navidrome protection
- `kikusan/cron/explore_sync.py`: Explore (charts/moods/genres) synchronization for cron mode
  - `sync_explore()`: Main entry point, reuses `download_new_tracks`, `remove_old_tracks`, `update_m3u_playlist` from `sync.py`. Applies `limit` truncation after fetching tracks (before compare/download).
  - `fetch_explore_tracks()`: Routes to `_fetch_chart_tracks()` or `_fetch_mood_tracks()` based on type
  - `_fetch_chart_tracks()`: Fetches tracks from YouTube Music charts via `get_charts()`
  - `_fetch_mood_tracks()`: Fetches tracks from a specific playlist (if `playlist_id` is set) or from all playlists in the category (if `playlist_id` is not set, legacy behavior). Accepts optional `playlist_id` parameter to target a single playlist instead of fetching all playlists in the mood/genre category.
  - State is stored using the same `PlaylistState` model in `.kikusan/state/`
  - All safety features apply: cross-reference protection, Navidrome protection, unavailable cooldown
- `kikusan/cron/config.py`: Cron configuration loading with support for `playlists`, `plugins`, `explore`, and `hooks` sections
  - `ExploreConfig`: Dataclass for explore entries (type, country, params, playlist_id, sync, schedule, limit)
  - `playlist_id` field: Optional for mood type entries - when set, only tracks from that specific playlist are synced instead of all playlists in the category
  - `validate_country_code()`: Validates ISO 3166-1 Alpha-2 country codes
- `kikusan/plugins/sync.py`: Plugin synchronization with reference-aware deletion and Navidrome protection
- `kikusan/hooks.py`: Generic hook system for running commands on events
  - Supports `playlist_updated` and `sync_completed` events
  - Configured via `hooks` section in `cron.yaml`
  - Passes context data via environment variables (KIKUSAN\_\*)
  - Supports timeout and run_on_error options
- `kikusan/cron/scheduler.py`: Orchestrates sync jobs (playlists, plugins, explore) and triggers hooks after completion
  - `_schedule_explore()` / `_explore_sync_job()`: Schedule and execute explore sync jobs
  - `sync_all_once()`: Runs all playlists, plugins, and explore sources once immediately
- `kikusan/lyrics.py`: Lyrics fetching from lrclib.net with multi-strategy lookup
  - `get_lyrics_for_video()`: Primary function — fetches clean metadata from ytmusicapi, then tries multiple lrclib.net strategies:
    1. Exact match (`/api/get`) with ytmusicapi metadata (clean title/artist/duration)
    2. Search (`/api/search`) with ytmusicapi metadata (fuzzy match, includes album)
    3. Cleaned metadata retry (strips parentheticals from title, secondary artists from artist)
    4. Exact match (`/api/get`) with yt-dlp fallback metadata (original behavior)
    5. Cleaned yt-dlp metadata retry
  - `_clean_title()`: Strips trailing parenthetical/bracketed suffixes (e.g., "(Radio Edit)", "[Official Video]") iteratively
  - `_clean_artist()`: Extracts primary artist from multi-artist strings by splitting on comma, semicolon, feat/ft/featuring
  - `_try_cleaned_lookup()`: Applies both cleaning functions and retries exact + search (only if cleaning changed something)
  - `get_lyrics()`: Original function preserved for backward compatibility, delegates to `_get_lyrics_exact()`
  - `_search_lyrics()`: Uses `/api/search` endpoint with duration-based filtering (3s tolerance)
  - `save_lyrics()`: Saves LRC file alongside audio file
  - The ytmusicapi metadata enhancement dramatically improves lyrics hit rate because yt-dlp often extracts metadata from video titles (e.g., "Artist - Song (Official Video)") rather than clean music metadata
- `kikusan/download.py`: Core download logic with unavailable video protection
  - `download()`: Single video download with cooldown check at entry and error recording on failure
  - `UnavailableCooldownError`: Raised when video is on cooldown (avoids hitting YouTube)
  - `_extract_video_id_from_url()`: Extracts video ID from YouTube URLs for error recording
  - All download paths (`download()`, `_download_single()`, `download_url()`, `_download_playlist()`) record unavailable errors
  - **Format Selection Optimization**: `_get_ydl_opts()` uses intelligent format selector `bestaudio[ext={format}]/bestaudio[acodec*={format}]/bestaudio/best` to prefer audio streams that already match the desired codec (e.g., native opus from YouTube Music), avoiding unnecessary transcoding and preserving quality (inspired by guillevc/yubal@f5d7ee9)
- `kikusan/unavailable.py`: Unavailable video cooldown management
  - Tracks video IDs that returned "Video unavailable" errors
  - JSON persistence in `.kikusan/unavailable.json` with atomic writes
  - Configurable cooldown period (default: 168 hours / 7 days)
  - Pattern matching for unavailable-specific errors (distinct from auth/network errors)
  - Functions: `is_unavailable_error()`, `record_unavailable()`, `is_on_cooldown()`, `clear_expired()`
- `kikusan/replaygain.py`: ReplayGain/R128 loudness normalization tagging via `rsgain`
  - `is_rsgain_available() -> bool`: Checks `shutil.which("rsgain")`, result cached via `@lru_cache`
  - `apply_replaygain(audio_path, audio_format) -> bool`: Runs `rsgain custom -q -s i [-o r] <file>`
  - For Opus files, uses `-o r` flag for RFC 7845 R128 output gain tags
  - Non-fatal: logs warnings on failure (timeout, missing binary, exit code), returns False
  - 300-second timeout on subprocess
  - Opt-in via `KIKUSAN_REPLAYGAIN=true` env var or `--replaygain` CLI flag
  - Requires external `rsgain` binary (installed in Docker image via Debian package `rsgain`)
  - Called as post-processing step after lyrics in all download paths (`download()`, `_download_single()`, `_download_playlist()`)
  - `apply_replaygain` parameter threaded through: `download.py`, `queue.py`, `cron/sync.py`, `plugins/sync.py`, `cli.py`
- `kikusan/tagging.py`: Tag existing audio files with lyrics and ReplayGain (no re-download)
  - `extract_metadata(file_path) -> FileMetadata | None`: Extracts title, artist, album, duration via mutagen
  - `collect_audio_files(directory) -> list[Path]`: Recursive walk for `.opus`, `.mp3`, `.flac` files
  - `tag_file()`: Per-file processing — lyrics lookup (exact + search + cleaned fallback) and ReplayGain application
  - `tag_directory()`: Main entry point — processes all files with stats tracking
  - `_has_replaygain_tags()`: Checks for existing ReplayGain tags (format-specific: R128_TRACK_GAIN for Opus, REPLAYGAIN_TRACK_GAIN for MP3/FLAC)
  - Lyrics: reuses `get_lyrics()`, `_search_lyrics()`, and `_try_cleaned_lookup()` from `lyrics.py` (no video_id needed)
  - ReplayGain: reuses `apply_replaygain()` from `replaygain.py` as-is
  - Skips files that already have `.lrc` sidecar files (for lyrics)
  - Skips files that already have ReplayGain tags (for ReplayGain)
  - Non-fatal per-file errors with `TagStats` summary at end
  - Data classes: `FileMetadata`, `TagStats` (includes skipped counters for both lyrics and ReplayGain)

### CI/CD

- `.github/workflows/publish.yml`: Single workflow handles all release automation
  - Triggers: tag push (`v*`), release event (`published`), workflow_dispatch
  - `build` job: Builds Python package (sdist + wheel) using `python -m build`, uploads as artifact
  - `create-release` job: Creates GitHub Release with auto-generated release notes, attaches built artifacts. Only runs on tag push events (guarded by `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`)
  - `publish` job: Publishes to PyPI using trusted publishing (OIDC, `id-token: write`)
  - `build-and-push-image` job: Builds and pushes Docker image to `ghcr.io/dadav/kikusan` (tagged with version + `latest`)
- All GitHub Actions are pinned by commit SHA with version comments (e.g., `@sha # v6`)
- Release workflow: Push a `v*` tag to trigger build -> create release -> publish to PyPI -> push Docker image
- `softprops/action-gh-release` (v2) creates the GitHub Release with `generate_release_notes: true`
- Renovate (`renovate.json`) manages dependency updates

### CLI Flags

All major configuration variables have corresponding CLI flags:

**Global flags (apply to all subcommands):**

- `--cookie-mode`: Cookie usage mode (auto, always, never)
- `--cookie-retry-delay`: Delay before retrying with cookies
- `--no-log-cookie-usage`: Disable cookie usage logging
- `--unavailable-cooldown`: Hours to wait before retrying unavailable videos (0 = disabled, default: 168)

**download command:**

- `--organization-mode`: File organization (flat, album)
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names
- `--replaygain / --no-replaygain`: Apply ReplayGain/R128 loudness normalization tags (env: `KIKUSAN_REPLAYGAIN`)
- `--allow-ugc / --no-allow-ugc`: Include UGC tracks in playlist/chart results (env: `KIKUSAN_ALLOW_UGC`)

**web command:**

- `--cors-origins`: CORS allowed origins
- `--web-playlist`: M3U playlist name for web downloads
- `--multi-user / --no-multi-user`: Enable per-user M3U playlists via Remote-User header (env: `KIKUSAN_MULTI_USER`)
- `--replaygain / --no-replaygain`: Apply ReplayGain/R128 loudness normalization tags (env: `KIKUSAN_REPLAYGAIN`)
- `--allow-ugc / --no-allow-ugc`: Include UGC tracks in playlist/chart results (env: `KIKUSAN_ALLOW_UGC`)

**cron command:**

- `--format`: Audio format
- `--organization-mode`: File organization
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names
- `--replaygain / --no-replaygain`: Apply ReplayGain/R128 loudness normalization tags (env: `KIKUSAN_REPLAYGAIN`)
- Supports `explore` section in `cron.yaml` for syncing charts and moods/genres:
  - `type: charts` with optional `country` (ISO 3166-1 Alpha-2, default ZZ)
  - `type: mood` with required `params` (from `explore moods` command)
    - Optional `playlist_id` (str): Target a specific playlist instead of all playlists in the category. Get playlist IDs from `kikusan explore mood-playlists <PARAMS>` command.
  - Each entry has `sync` (bool) and `schedule` (cron expression)
  - Optional `limit` (int, default 0 = no limit): Maximum number of tracks to sync. Tracks are truncated from the end, preserving the top-ranked entries (e.g., `limit: 10` keeps the top 10 chart tracks).
  - State stored in `.kikusan/state/` using same format as playlist state

**plugins run command:**

- `--format`: Audio format
- `--organization-mode`: File organization
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names
- `--replaygain / --no-replaygain`: Apply ReplayGain/R128 loudness normalization tags (env: `KIKUSAN_REPLAYGAIN`)

**tag command:**

- `<directory>`: Directory to recursively process (required argument)
- `--lyrics/--no-lyrics`: Fetch and save lyrics from lrclib.net (default: enabled)
- `--replaygain/--no-replaygain`: Apply ReplayGain/R128 tags via rsgain (default: enabled)
- `--dry-run`: Preview what would be done without making changes

**explore command group:**

- `explore moods` — list available mood & genre categories
- `explore mood-playlists <PARAMS>` — list playlists for a category (PARAMS from `explore moods`)
  - `--download/-d`: Download all tracks from all playlists in the category
  - `--output/-o`: Output directory
  - `--format/-f`: Audio format (opus, mp3, flac)
  - `--add-to-playlist/-p`: Add to M3U playlist
  - `--allow-ugc/--no-allow-ugc`: Include UGC tracks (default: exclude)
- `explore charts` — show current music charts
  - `--country/-c <CODE>`: ISO 3166-1 Alpha-2 country code (default: ZZ for global)
  - `--download/-d`: Download all chart tracks
  - `--output/-o`: Output directory
  - `--format/-f`: Audio format (opus, mp3, flac)
  - `--add-to-playlist/-p`: Add to M3U playlist
  - `--allow-ugc/--no-allow-ugc`: Include UGC tracks (default: exclude)

CLI flags take precedence over environment variables. Options with `envvar` attribute automatically read from the corresponding environment variable if not specified on the command line.
