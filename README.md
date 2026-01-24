# Kikusan

Search and download music from YouTube Music with lyrics.

## Features

- **Search & Download**: Search YouTube Music and download audio in OPUS/MP3/FLAC format
- **Playlist Support**: Download entire playlists from YouTube Music, YouTube, and Spotify
- **Quick Download**: Search and download first match with a single command
- **Automatic Lyrics**: Fetch and embed synchronized lyrics from lrclib.net (LRC format)
- **Web Interface**: Modern web UI with search, download, theme toggle, and format selection
- **Docker Support**: Easy deployment with Docker and docker-compose
- **Plugin System**: Extensible architecture for custom music sources
- **Scheduled Sync**: Automated playlist monitoring with cron scheduling
- **M3U Playlists**: Automatic playlist file generation for downloads
- **Hooks**: Run custom commands when events occur (e.g., import playlists to Navidrome)

## Usecase

I use navidrome as my music server. The music is located on a NAS and mounted into the navidrome container (read-only).
Kikusan syncs my youtube music and spotify playlists shared mount and creates local m3u playlists. If kikusan has a discovery playlist configured (sync=True), songs which were removed from the upstream playlist get also removed from navidrome. There are some exceptions: They won't get removed if the songs are referenced by another playlist or starred in navidrome or in the `keep` playlist. Navidrome imports those playlist daily. Then I use [symfonium](https://play.google.com/store/apps/details?id=app.symfonik.music.player) to access my music via subsonic api.

## Plugin System

Kikusan supports plugins for syncing music from various sources beyond standard playlists:

**Built-in Plugins:**

- **`listenbrainz`** - Weekly recommendations from listenbrainz.org
  - Required: `user` (listenbrainz username)
  - Optional: `recommendation_type` (weekly-exploration, weekly-jams)

- **`rss`** - Generic RSS/Atom feed parser for music podcasts, blogs, etc.
  - Required: `url` (RSS/Atom feed URL)
  - Optional: `artist_field`, `title_field`, `timeout`, `user_agent`

- **`reddit`** - Fetch songs from music subreddits (r/listentothis, r/Music, r/IndieHeads, etc.)
  - Required: `subreddit` (subreddit name)
  - Optional: `sort` (hot/new/top/rising), `time_filter`, `limit`, `min_score`

- **`billboard`** - Fetch songs from Billboard charts (hot-100, pop-songs, etc.)
  - Required: `chart_name` (e.g., 'hot-100', 'pop-songs')
  - Optional: `date` (YYYY-MM-DD), `year` (for year-end charts), `limit`

**Usage:**

```bash
# List available plugins
kikusan plugins list

# Run a plugin once
kikusan plugins run listenbrainz --config '{"user": "myuser"}'
kikusan plugins run reddit --config '{"subreddit": "listentothis", "limit": 25}'
kikusan plugins run billboard --config '{"chart_name": "hot-100", "limit": 50}'

# Schedule in cron.yaml
# See cron.example.yaml for configuration examples
```

**Creating Third-Party Plugins:**

See [`examples/third-party-plugin/`](examples/third-party-plugin/) for a complete example of creating your own plugin. Plugins are distributed as Python packages and automatically discovered via entry points.

## Installation

```bash
uv sync
```

## Usage

### CLI

```bash
# Search for music
kikusan search "Bohemian Rhapsody"

# Download by video ID
kikusan download bSnlKl_PoQU

# Download by URL
kikusan download --url "https://music.youtube.com/watch?v=bSnlKl_PoQU"

# Search and download first match
kikusan download --query "Bohemian Rhapsody Queen"

# Download entire playlist (YouTube Music, YouTube, or Spotify)
kikusan download --url "https://music.youtube.com/playlist?list=..."
kikusan download --url "https://open.spotify.com/playlist/..."

# Custom filename format
kikusan download bSnlKl_PoQU --filename "%(title)s"

# Options
kikusan download bSnlKl_PoQU --output ~/Music --format mp3
```

### Web Interface

```bash
kikusan web
# Open http://localhost:8000
```

**Features:**

- Search YouTube Music with real-time results
- Download individual tracks with format selection (OPUS/MP3/FLAC)
- Dark/light theme toggle with automatic system preference detection
- View counts displayed for each track
- Responsive design for mobile and desktop

### Scheduled Sync (Cron)

Automatically monitor and sync playlists or plugins on a schedule:

```bash
# Run continuously with cron.yaml configuration
kikusan cron

# Run all syncs once and exit
kikusan cron --once

# Use custom config file
kikusan cron --config /path/to/cron.yaml
```

Create a `cron.yaml` file to configure:

- **Playlists**: YouTube Music, YouTube, or Spotify playlists
- **Plugins**: Listenbrainz, Reddit, Billboard, RSS feeds
- **Schedule**: Standard cron expressions (e.g., "0 9 \* \* \*" for daily at 9am)
- **Sync Mode**: Keep or delete files when removed from source

See `cron.example.yaml` for detailed configuration examples.

### Notifications

Kikusan can send push notifications via [Gotify](https://gotify.net/) for scheduled sync operations:

- **Summary notifications only** - One notification per sync operation, not per track
- **Includes download/skip/fail counts** - See results at a glance
- **Optional** - Gracefully disabled if not configured
- **Non-blocking** - Notification failures don't stop downloads

**Setup:**

1. Install a Gotify server or use an existing instance
2. Create an application token in Gotify
3. Set environment variables:
   ```bash
   export GOTIFY_URL="https://push.example.com"
   export GOTIFY_TOKEN="your-app-token"
   ```

**Notifications are sent for:**

- Scheduled playlist syncs (via `kikusan cron`)
- Scheduled plugin syncs (via `kikusan cron`)

Notifications are **not** sent for CLI operations or web UI downloads, as these are interactive and the user already sees the results.

### Navidrome Protection

Prevent deletion of songs during sync if they are starred or in a designated playlist in Navidrome:

**Features:**

- Protect songs starred/favorited in Navidrome (via Symfonium or other Subsonic clients)
- Protect songs in a designated "keep" playlist
- Real-time API checks during each sync operation
- Gracefully disabled if not configured
- Fails safe: keeps files if Navidrome is unreachable

**Setup:**

1. Configure environment variables:

   ```bash
   export NAVIDROME_URL="https://music.example.com"
   export NAVIDROME_USER="your-username"
   export NAVIDROME_PASSWORD="your-password"
   export NAVIDROME_KEEP_PLAYLIST="keep"  # optional, defaults to "keep"
   ```

2. Star songs in your Subsonic client (Symfonium, DSub, etc.) or add them to your "keep" playlist

3. When kikusan syncs playlists with `sync: true`, protected songs won't be deleted even if removed from the source playlist

**Behavior:**

- Checks both starred songs AND songs in the keep playlist
- Protected files are skipped during deletion with detailed logging
- Works alongside existing cross-playlist/plugin reference protection
- Minimal performance impact (~3 API calls per sync operation)

**Example workflow:**

1. Sync YouTube Music playlist with `sync: true`
2. Song gets removed from YouTube Music playlist
3. You've starred the song in Symfonium (synced to Navidrome)
4. Kikusan detects the star and keeps the file on disk
5. File remains available in Navidrome/Symfonium

### Hooks

Hooks allow you to run custom commands when certain events occur during sync operations. This is useful for integrating with external systems like Navidrome.

**Supported Events:**

- `playlist_updated`: Triggered when an M3U playlist is created or updated
- `sync_completed`: Triggered after every sync operation (success or failure)

**Configuration:**

Add a `hooks` section to your `cron.yaml`:

```yaml
hooks:
  # Import playlist to Navidrome when updated
  - event: playlist_updated
    command: |
      curl -X POST \
        -H "Content-Type: audio/x-mpegurl" \
        -H "X-ND-Authorization: Bearer ${NAVIDROME_TOKEN}" \
        --data-binary @"${KIKUSAN_PLAYLIST_PATH}" \
        "${NAVIDROME_URL}/api/playlist"
    timeout: 30  # seconds (default: 60)

  # Log sync results
  - event: sync_completed
    command: echo "Sync: ${KIKUSAN_PLAYLIST_NAME}" >> /var/log/sync.log
    run_on_error: true  # Run even if sync failed (default: false)
```

**Environment Variables:**

Hooks receive context via environment variables:

| Variable               | Description                                    |
| ---------------------- | ---------------------------------------------- |
| `KIKUSAN_EVENT`        | Event type (playlist_updated, sync_completed)  |
| `KIKUSAN_PLAYLIST_NAME`| Name of the playlist/plugin                    |
| `KIKUSAN_PLAYLIST_PATH`| Absolute path to the M3U file (if exists)      |
| `KIKUSAN_SYNC_TYPE`    | Type: "playlist" or "plugin"                   |
| `KIKUSAN_DOWNLOADED`   | Number of tracks downloaded                    |
| `KIKUSAN_SKIPPED`      | Number of tracks skipped                       |
| `KIKUSAN_DELETED`      | Number of tracks deleted                       |
| `KIKUSAN_FAILED`       | Number of tracks that failed                   |
| `KIKUSAN_SUCCESS`      | "true" or "false"                              |

**Navidrome Integration Example:**

To automatically import playlists to Navidrome using its [playlist import API](https://github.com/navidrome/navidrome/pull/2273):

1. Set environment variables:
   ```bash
   export NAVIDROME_URL="https://music.example.com"
   export NAVIDROME_TOKEN="your-api-token"
   ```

2. Add hook to `cron.yaml`:
   ```yaml
   hooks:
     - event: playlist_updated
       command: |
         curl -X POST \
           -H "Content-Type: audio/x-mpegurl" \
           -H "X-ND-Authorization: Bearer ${NAVIDROME_TOKEN}" \
           --data-binary @"${KIKUSAN_PLAYLIST_PATH}" \
           "${NAVIDROME_URL}/api/playlist"
   ```

### Docker

```bash
docker compose up -d
# Open http://localhost:8000
```

## Configuration

### Environment Variables

| Variable                      | Default                           | Description                                    |
| ----------------------------- | --------------------------------- | ---------------------------------------------- |
| `KIKUSAN_DOWNLOAD_DIR`        | `./downloads`                     | Download directory                             |
| `KIKUSAN_AUDIO_FORMAT`        | `opus`                            | Audio format (opus, mp3, flac)                 |
| `KIKUSAN_FILENAME_TEMPLATE`   | `%(artist,uploader)s - %(title)s` | Filename template (yt-dlp format)              |
| `KIKUSAN_ORGANIZATION_MODE`   | `flat`                            | File organization mode (flat, album)           |
| `KIKUSAN_USE_PRIMARY_ARTIST`  | `false`                           | Use primary artist for folders (true, false)   |
| `KIKUSAN_WEB_PORT`            | `8000`                            | Web server port                                |
| `KIKUSAN_WEB_PLAYLIST`        | `None`                            | M3U playlist name for web downloads (optional) |
| `KIKUSAN_CORS_ORIGINS`        | `*`                               | CORS allowed origins (comma-separated)         |
| `KIKUSAN_COOKIE_MODE`         | `auto`                            | Cookie usage: auto, always, or never           |
| `KIKUSAN_COOKIE_RETRY_DELAY`  | `1.0`                             | Delay in seconds before retrying with cookies  |
| `KIKUSAN_LOG_COOKIE_USAGE`    | `true`                            | Log cookie usage statistics (true, false)      |
| `SPOTIFY_CLIENT_ID`           | `None`                            | Spotify API client ID (for Spotify playlists)  |
| `SPOTIFY_CLIENT_SECRET`       | `None`                            | Spotify API client secret (optional)           |
| `GOTIFY_URL`                  | `None`                            | Gotify server URL for notifications (optional) |
| `GOTIFY_TOKEN`                | `None`                            | Gotify application token (optional)            |
| `NAVIDROME_URL`               | `None`                            | Navidrome server URL for protection (optional) |
| `NAVIDROME_USER`              | `None`                            | Navidrome username (optional)                  |
| `NAVIDROME_PASSWORD`          | `None`                            | Navidrome password (optional)                  |
| `NAVIDROME_KEEP_PLAYLIST`     | `keep`                            | Playlist name for protection (optional)        |
| `YT_DLP_COOKIE_FILE`          | `None`                            | Path to cookies.txt file for yt-dlp (optional) |

### Cookie Authentication

Kikusan supports two methods for providing cookies to yt-dlp:

1. **Web UI Upload** (Recommended):
   - Open the web UI
   - Click the settings icon (⚙️) in the header
   - Upload your cookies.txt file
   - The file is stored securely at `.kikusan/cookies.txt`

2. **Environment Variable**:
   ```bash
   export YT_DLP_COOKIE_FILE=/path/to/cookies.txt
   ```

**Priority**: Web-uploaded cookies take precedence over environment variable.

**Exporting Cookies**:
- Chrome/Edge: Install "Get cookies.txt LOCALLY" extension
- Firefox: Install "cookies.txt" extension
- See [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) for detailed instructions

### File Organization

Kikusan supports two file organization modes:

#### Flat Mode (Default)

All files stored in the download directory with the filename template:

```
downloads/
├── Queen - Bohemian Rhapsody.opus
├── Pink Floyd - Comfortably Numb.opus
└── ...
```

#### Album Mode

Files organized by artist and album with automatic metadata extraction:

```
downloads/
├── Queen/
│   ├── 1975 - A Night at the Opera/
│   │   ├── 01 - Death on Two Legs.opus
│   │   ├── 11 - Bohemian Rhapsody.opus
│   │   └── 12 - God Save the Queen.opus
│   └── 1991 - Innuendo/
│       ├── 01 - Innuendo.opus
│       └── 06 - The Show Must Go On.opus
└── Pink Floyd/
    └── 1979 - The Wall/
        ├── 01 - In the Flesh.opus
        └── 26 - Outside the Wall.opus
```

**Enable album mode:**

```bash
export KIKUSAN_ORGANIZATION_MODE=album
```

**Behavior:**

- **Full metadata**: `Artist/Year - Album/NN - Track.ext`
- **Missing track number**: `Artist/Year - Album/Track.ext`
- **Missing album**: `Artist/Track.ext`
- **Path sanitization**: Invalid filesystem characters are automatically removed

**Multi-Artist Handling:**

By default, album mode uses the full artist string from metadata:
- `Queen feat. David Bowie` → folder: `Queen feat. David Bowie/`
- `Artist1, Artist2` → folder: `Artist1, Artist2/`

To use only the primary artist for cleaner folder organization:

```bash
export KIKUSAN_USE_PRIMARY_ARTIST=true
```

This extracts the main artist (before separators) for folder names:
- `Queen feat. David Bowie` → folder: `Queen/`
- `Artist1, Artist2` → folder: `Artist1/`
- `Artist & Guest` → folder: `Artist/`

Supported separators (in priority order): ` feat. `, ` ft. `, ` featuring `, ` with `, ` & `, `, `

The full artist metadata is still preserved in the audio file tags.

**Notes:**

- Album mode is opt-in; flat mode remains the default for backward compatibility
- Primary artist extraction is optional (disabled by default)
- Existing files are not reorganized when switching modes
- New downloads will use the selected organization mode
- File existence checking works in both modes to prevent duplicates

### State Files & Playlists

Kikusan tracks downloaded files and generates M3U playlists automatically:

- **State Files**: Stored in `{download_dir}/.kikusan/state/` (for playlists) and `{download_dir}/.kikusan/plugin_state/` (for plugins)
- **M3U Playlists**: Generated at `{download_dir}/{name}.m3u` for each sync configuration

## CLI Reference

This section documents all CLI commands and their options.

### Global Options

These options apply to all commands:

| Option                  | Env Variable                | Description                                                  |
| ----------------------- | --------------------------- | ------------------------------------------------------------ |
| `--cookie-mode`         | `KIKUSAN_COOKIE_MODE`       | Cookie usage: `auto` (retry on auth errors), `always`, `never`. Default: `auto` |
| `--cookie-retry-delay`  | `KIKUSAN_COOKIE_RETRY_DELAY`| Delay in seconds before retrying with cookies. Default: `1.0` |
| `--no-log-cookie-usage` | (inverse of `KIKUSAN_LOG_COOKIE_USAGE`) | Disable logging of cookie usage statistics   |
| `--version`             | -                           | Show version and exit                                        |

### kikusan search

Search for music on YouTube Music.

```bash
kikusan search "query" [OPTIONS]
```

| Option          | Description                        |
| --------------- | ---------------------------------- |
| `-l, --limit`   | Maximum number of results (default: 10) |

### kikusan download

Download a track by video ID, URL, or search query.

```bash
kikusan download [VIDEO_ID] [OPTIONS]
```

| Option                                       | Env Variable                | Description                                      |
| -------------------------------------------- | --------------------------- | ------------------------------------------------ |
| `-u, --url`                                  | -                           | YouTube, YouTube Music, or Spotify URL           |
| `-q, --query`                                | -                           | Search query (downloads first match)             |
| `-o, --output`                               | `KIKUSAN_DOWNLOAD_DIR`      | Output directory                                 |
| `-f, --format`                               | `KIKUSAN_AUDIO_FORMAT`      | Audio format: `opus`, `mp3`, `flac`. Default: `opus` |
| `-n, --filename`                             | `KIKUSAN_FILENAME_TEMPLATE` | Filename template (yt-dlp format)                |
| `--no-lyrics`                                | -                           | Skip fetching lyrics                             |
| `-p, --add-to-playlist`                      | -                           | Add downloaded track(s) to M3U playlist          |
| `--organization-mode`                        | `KIKUSAN_ORGANIZATION_MODE` | File organization: `flat` or `album`. Default: `flat` |
| `--use-primary-artist/--no-use-primary-artist` | `KIKUSAN_USE_PRIMARY_ARTIST` | Use only primary artist for folder names in album mode |

### kikusan web

Start the web interface.

```bash
kikusan web [OPTIONS]
```

| Option                                       | Env Variable                | Description                                      |
| -------------------------------------------- | --------------------------- | ------------------------------------------------ |
| `--host`                                     | -                           | Host to bind to. Default: `0.0.0.0`              |
| `-p, --port`                                 | `KIKUSAN_WEB_PORT`          | Port to listen on. Default: `8000`               |
| `--cors-origins`                             | `KIKUSAN_CORS_ORIGINS`      | CORS allowed origins (comma-separated or `*`). Default: `*` |
| `--web-playlist`                             | `KIKUSAN_WEB_PLAYLIST`      | M3U playlist name for web downloads (optional)   |
| `--organization-mode`                        | `KIKUSAN_ORGANIZATION_MODE` | File organization: `flat` or `album`. Default: `flat` |
| `--use-primary-artist/--no-use-primary-artist` | `KIKUSAN_USE_PRIMARY_ARTIST` | Use only primary artist for folder names in album mode |

### kikusan cron

Run continuous playlist sync based on cron.yaml.

```bash
kikusan cron [OPTIONS]
```

| Option                                       | Env Variable                | Description                                      |
| -------------------------------------------- | --------------------------- | ------------------------------------------------ |
| `-c, --config`                               | -                           | Path to cron configuration file. Default: `cron.yaml` |
| `-o, --output`                               | `KIKUSAN_DOWNLOAD_DIR`      | Override download directory                      |
| `--once`                                     | -                           | Run all playlists once and exit (skip scheduling) |
| `-f, --format`                               | `KIKUSAN_AUDIO_FORMAT`      | Audio format: `opus`, `mp3`, `flac`. Default: `opus` |
| `--organization-mode`                        | `KIKUSAN_ORGANIZATION_MODE` | File organization: `flat` or `album`. Default: `flat` |
| `--use-primary-artist/--no-use-primary-artist` | `KIKUSAN_USE_PRIMARY_ARTIST` | Use only primary artist for folder names in album mode |

### kikusan plugins list

List all available plugins.

```bash
kikusan plugins list
```

No options.

### kikusan plugins run

Run a plugin sync once (without cron.yaml).

```bash
kikusan plugins run PLUGIN_NAME --config '{"key": "value"}' [OPTIONS]
```

| Option                                       | Env Variable                | Description                                      |
| -------------------------------------------- | --------------------------- | ------------------------------------------------ |
| `-c, --config`                               | -                           | Plugin config as JSON string (required)          |
| `-o, --output`                               | `KIKUSAN_DOWNLOAD_DIR`      | Download directory                               |
| `-f, --format`                               | `KIKUSAN_AUDIO_FORMAT`      | Audio format: `opus`, `mp3`, `flac`. Default: `opus` |
| `--organization-mode`                        | `KIKUSAN_ORGANIZATION_MODE` | File organization: `flat` or `album`. Default: `flat` |
| `--use-primary-artist/--no-use-primary-artist` | `KIKUSAN_USE_PRIMARY_ARTIST` | Use only primary artist for folder names in album mode |

## Authentication

kikusan does not use any kind of authentication. If you need to secure it, I suggest to use **Caddy** with **authelia**. This caddy config works for me:

```Caddy
(authelia_forwarder) {
  forward_auth http://192.168.1.10:9091 {
    uri /api/authz/forward-auth
    copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
  }
}

kikusan.foobar.test {
  import authelia_forwarder
  reverse_proxy http://192.168.1.11:8007
}
```

## Requirements

- Python 3.12+
- ffmpeg (for audio processing)
