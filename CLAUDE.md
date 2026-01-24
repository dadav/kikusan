# Project description

Kikusan is a tool to search and download music from youtube music. It must use yt-dlp in the background. It must be usable through CLI and also have a web app (subcommand "web"). The web app should be really simple, but must support search functionality. It should be deployable with docker and have an example docker-compose file. It must add lyrics via lrc files to the downloaded files (via https://lrclib.net/).

## Features

### Web UI
- Search functionality with results display
- View counts displayed for each song (e.g., "1.9B views", "47M views")
  - View counts are retrieved from ytmusicapi search results (no additional API calls needed)
  - Displayed alongside duration in the track metadata section
- Download button for each track
- Dark/light theme toggle

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

### Architecture Notes
- `kikusan/search.py`: Uses ytmusicapi to search YouTube Music, extracts view_count from search results
- `kikusan/web/app.py`: FastAPI backend with search and download endpoints
- `kikusan/web/templates/index.html`: Single-page frontend with embedded JavaScript
- `kikusan/web/static/style.css`: Responsive CSS with dark/light themes
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
- `kikusan/plugins/sync.py`: Plugin synchronization with reference-aware deletion and Navidrome protection
- `kikusan/hooks.py`: Generic hook system for running commands on events
  - Supports `playlist_updated` and `sync_completed` events
  - Configured via `hooks` section in `cron.yaml`
  - Passes context data via environment variables (KIKUSAN_*)
  - Supports timeout and run_on_error options
- `kikusan/cron/scheduler.py`: Orchestrates sync jobs and triggers hooks after completion

### CLI Flags
All major configuration variables have corresponding CLI flags:

**Global flags (apply to all subcommands):**
- `--cookie-mode`: Cookie usage mode (auto, always, never)
- `--cookie-retry-delay`: Delay before retrying with cookies
- `--no-log-cookie-usage`: Disable cookie usage logging

**download command:**
- `--organization-mode`: File organization (flat, album)
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names

**web command:**
- `--cors-origins`: CORS allowed origins
- `--web-playlist`: M3U playlist name for web downloads

**cron command:**
- `--format`: Audio format
- `--organization-mode`: File organization
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names

**plugins run command:**
- `--format`: Audio format
- `--organization-mode`: File organization
- `--use-primary-artist / --no-use-primary-artist`: Use primary artist for folder names

CLI flags take precedence over environment variables. Options with `envvar` attribute automatically read from the corresponding environment variable if not specified on the command line.
