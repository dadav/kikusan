"""FastAPI web application for Kikusan."""

import asyncio
import json
import re
import urllib.parse
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from kikusan import __version__
from kikusan.config import get_config
from kikusan.download import download
from kikusan.playlist import add_to_m3u, read_m3u, remove_from_m3u
from kikusan.queue import QueueManager
from kikusan.search import search
from kikusan.yt_dlp_wrapper import extract_info_with_retry

app = FastAPI(title="Kikusan", description="Search and download music from YouTube Music")

# Configure CORS
config = get_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global queue manager
queue_manager: QueueManager | None = None

# Setup templates and static files
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(templates_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_SAFE_USERNAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def _get_remote_user(http_request: Request, config) -> str | None:
    """Extract and sanitize Remote-User header. Returns None if multi-user disabled or header absent."""
    if not config.multi_user:
        return None
    raw = http_request.headers.get("Remote-User")
    if not raw:
        return None
    sanitized = _SAFE_USERNAME_RE.sub("_", raw.strip())[:64]
    return sanitized if sanitized else None


@app.on_event("startup")
async def startup_event():
    """Initialize queue manager on startup."""
    global queue_manager
    queue_manager = QueueManager()
    await queue_manager.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop queue manager on shutdown."""
    if queue_manager:
        await queue_manager.stop()


class DownloadRequest(BaseModel):
    """Request body for download endpoint."""

    video_id: str
    title: str
    artist: str
    artists: list[str] | None = None
    audio_format: str = "opus"


class DownloadResponse(BaseModel):
    """Response body for download endpoint."""

    success: bool
    message: str
    file_path: str | None = None
    file_name: str | None = None


class TrackResponse(BaseModel):
    """Track data for API responses."""

    video_id: str
    title: str
    artist: str
    artists: list[str]
    album: str | None
    duration: str
    thumbnail_url: str | None
    view_count: str | None
    video_type: str | None = None


def _track_to_response(track) -> TrackResponse:
    """Convert a Track-like object into a TrackResponse."""
    return TrackResponse(
        video_id=track.video_id,
        title=track.title,
        artist=track.artist,
        artists=track.artists,
        album=track.album,
        duration=track.duration_display,
        thumbnail_url=track.thumbnail_url,
        view_count=track.view_count,
        video_type=getattr(track, "video_type", None),
    )


def _sse_event(event: str, payload: dict) -> str:
    """Format a Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


class SearchResponse(BaseModel):
    """Response body for search endpoint."""

    query: str
    results: list[TrackResponse]


class AlbumResponse(BaseModel):
    """Album data for API responses."""

    browse_id: str
    title: str
    artist: str
    year: int | None
    track_count: int | None
    thumbnail_url: str | None


class AlbumSearchResponse(BaseModel):
    """Response body for album search endpoint."""

    query: str
    results: list[AlbumResponse]


class AlbumTracksResponse(BaseModel):
    """Response body for album tracks endpoint."""

    browse_id: str
    album_title: str
    tracks: list[TrackResponse]


class StreamUrlResponse(BaseModel):
    """Response for stream URL endpoint."""

    video_id: str
    url: str
    expires_in: int
    is_hls: bool = False


class MoodCategoryResponse(BaseModel):
    """A mood/genre category."""
    title: str
    params: str

class MoodSectionResponse(BaseModel):
    """A section of mood/genre categories."""
    title: str
    categories: list[MoodCategoryResponse]

class MoodPlaylistResponse(BaseModel):
    """A playlist from a mood/genre category."""
    playlist_id: str
    title: str
    thumbnail_url: str | None
    author: str | None

class ChartTrackResponse(BaseModel):
    """A chart track."""
    video_id: str
    title: str
    artist: str
    artists: list[str]
    album: str | None
    thumbnail_url: str | None
    rank: str | None
    trend: str | None
    view_count: str | None = None
    duration: str | None = None
    video_type: str | None = None

class ChartArtistResponse(BaseModel):
    """A chart artist."""
    browse_id: str
    title: str
    thumbnail_url: str | None
    rank: str | None
    trend: str | None

class ChartsResponse(BaseModel):
    """Charts response."""
    country: str
    tracks: list[ChartTrackResponse]
    artists: list[ChartArtistResponse]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main search page."""
    return templates.TemplateResponse(request=request, name="index.html", context={"version": __version__})


@app.get("/api/search", response_model=SearchResponse)
async def api_search(q: str = Query(..., min_length=1, description="Search query or supported URL (YouTube Music, YouTube, Deezer playlist)")):
    """Search for music on YouTube Music or fetch tracks from a supported URL."""
    import logging
    logger = logging.getLogger(__name__)

    from kikusan.deezer import DeezerQuotaError
    from kikusan.deezer import get_tracks_from_url as get_deezer_tracks_from_url
    from kikusan.deezer import is_deezer_url
    # Import URL handling functions from search module
    from kikusan.search import parse_youtube_url, get_track_from_video_id, get_playlist_tracks

    if is_deezer_url(q):
        # Deezer playlist URL -> resolve each Deezer track to YouTube Music
        try:
            deezer_tracks = get_deezer_tracks_from_url(q)
        except DeezerQuotaError as e:
            logger.warning("Deezer quota exceeded for '%s': %s", q, e)
            raise HTTPException(
                status_code=503,
                detail=str(e),
            )
        except Exception as e:
            logger.error("Deezer fetch failed for '%s': %s", q, e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch Deezer playlist: {str(e)}",
            )

        if not deezer_tracks:
            raise HTTPException(
                status_code=404,
                detail="Deezer playlist is empty or unavailable",
            )

        results = []
        for dz_track in deezer_tracks:
            yt_results = search(dz_track.search_query, limit=1)
            if yt_results:
                results.append(yt_results[0])
            else:
                logger.warning(
                    "No YouTube Music match for Deezer track: %s - %s",
                    dz_track.artist,
                    dz_track.name,
                )

        if not results:
            raise HTTPException(
                status_code=404,
                detail="No Deezer tracks could be matched on YouTube Music",
            )
    else:
        # Check if query is a YouTube URL
        url_info = parse_youtube_url(q)

        if url_info:
            # Handle URL input
            try:
                if url_info['type'] == 'video':
                    # Single track from video_id
                    track = get_track_from_video_id(url_info['id'])
                    results = [track]
                elif url_info['type'] == 'playlist':
                    # All tracks from playlist (no limit)
                    # Pass allow_ugc=True so web UI can show all tracks with UGC badge
                    results = get_playlist_tracks(url_info['id'], allow_ugc=True)
                    if not results:
                        raise HTTPException(
                            status_code=404,
                            detail="Playlist is empty or unavailable"
                        )
                elif url_info['type'] == 'unsupported_radio':
                    raise HTTPException(
                        status_code=400,
                        detail="Radio playlists are not supported. Please use a regular playlist or single track URL."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Unsupported URL type"
                    )
            except ValueError as e:
                # Video/playlist not found
                logger.warning("URL fetch failed for '%s': %s", q, e)
                raise HTTPException(
                    status_code=404,
                    detail=f"Video or playlist not found: {str(e)}"
                )
            except HTTPException:
                # Re-raise HTTPException as-is
                raise
            except Exception as e:
                logger.error("URL fetch failed for '%s': %s", q, e)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch from URL: {str(e)}"
                )
        else:
            # Handle regular text search (existing logic)
            try:
                results = search(q, limit=20)
            except Exception as e:
                logger.error("Search failed for query '%s': %s", q, e)
                raise HTTPException(
                    status_code=500,
                    detail=f"Search failed: {str(e)}"
                )

    return SearchResponse(
        query=q,
        results=[_track_to_response(track) for track in results],
    )


@app.get("/api/search/playlist/stream")
async def api_search_playlist_stream(
    request: Request,
    q: str = Query(..., min_length=1, description="Playlist URL (YouTube Music, YouTube, Deezer)"),
):
    """Stream playlist search progress and results via SSE."""
    import logging

    logger = logging.getLogger(__name__)

    from kikusan.deezer import DeezerQuotaError
    from kikusan.deezer import get_tracks_from_url as get_deezer_tracks_from_url
    from kikusan.deezer import is_deezer_url
    from kikusan.search import get_playlist_tracks, parse_youtube_url, search as yt_search

    async def event_generator():
        try:
            if is_deezer_url(q):
                yield _sse_event(
                    "progress",
                    {
                        "stage": "fetching",
                        "message": "Fetching Deezer playlist tracks...",
                    },
                )

                try:
                    deezer_tracks = await asyncio.to_thread(get_deezer_tracks_from_url, q)
                except DeezerQuotaError as e:
                    logger.warning("Deezer quota exceeded for '%s': %s", q, e)
                    yield _sse_event("failure", {"message": str(e)})
                    return
                except Exception as e:
                    logger.error("Deezer fetch failed for '%s': %s", q, e)
                    yield _sse_event(
                        "failure",
                        {"message": f"Failed to fetch Deezer playlist: {str(e)}"},
                    )
                    return

                if not deezer_tracks:
                    yield _sse_event(
                        "failure",
                        {"message": "Deezer playlist is empty or unavailable"},
                    )
                    return

                total = len(deezer_tracks)
                processed = 0
                matched = 0
                results = []

                yield _sse_event(
                    "progress",
                    {
                        "stage": "matching",
                        "total": total,
                        "processed": processed,
                        "matched": matched,
                    },
                )

                for dz_track in deezer_tracks:
                    if await request.is_disconnected():
                        return

                    processed += 1
                    try:
                        yt_results = await asyncio.to_thread(
                            yt_search, dz_track.search_query, 1
                        )
                    except Exception as e:
                        logger.warning(
                            "Search failed for Deezer track '%s - %s': %s",
                            dz_track.artist,
                            dz_track.name,
                            e,
                        )
                        yt_results = []

                    if yt_results:
                        results.append(yt_results[0])
                        matched += 1

                    yield _sse_event(
                        "progress",
                        {
                            "stage": "matching",
                            "total": total,
                            "processed": processed,
                            "matched": matched,
                        },
                    )

                if not results:
                    yield _sse_event(
                        "failure",
                        {"message": "No Deezer tracks could be matched on YouTube Music"},
                    )
                    return

                payload_results = [_track_to_response(track).dict() for track in results]
                yield _sse_event(
                    "complete",
                    {
                        "results": payload_results,
                        "total": len(payload_results),
                    },
                )
                return

            url_info = parse_youtube_url(q)
            if not url_info:
                yield _sse_event(
                    "failure",
                    {"message": "Only playlist URLs are supported for streaming search"},
                )
                return

            if url_info["type"] == "unsupported_radio":
                yield _sse_event(
                    "failure",
                    {
                        "message": "Radio playlists are not supported. Please use a regular playlist or single track URL.",
                    },
                )
                return

            if url_info["type"] != "playlist":
                yield _sse_event(
                    "failure",
                    {"message": "Only playlist URLs are supported for streaming search"},
                )
                return

            yield _sse_event(
                "progress",
                {
                    "stage": "fetching",
                    "message": "Fetching playlist tracks...",
                },
            )

            try:
                # Pass allow_ugc=True so web UI can show all tracks with UGC badge
                tracks = await asyncio.to_thread(get_playlist_tracks, url_info["id"], True)
            except ValueError as e:
                yield _sse_event("failure", {"message": str(e)})
                return
            except Exception as e:
                logger.error("Playlist fetch failed for '%s': %s", q, e)
                yield _sse_event(
                    "failure", {"message": f"Failed to fetch playlist: {str(e)}"}
                )
                return

            if not tracks:
                yield _sse_event(
                    "failure", {"message": "Playlist is empty or unavailable"}
                )
                return

            payload_results = [_track_to_response(track).dict() for track in tracks]
            yield _sse_event(
                "progress",
                {
                    "stage": "resolved",
                    "total": len(payload_results),
                    "processed": len(payload_results),
                    "matched": len(payload_results),
                    "message": f"Found {len(payload_results)} tracks",
                },
            )
            yield _sse_event(
                "complete",
                {
                    "results": payload_results,
                    "total": len(payload_results),
                },
            )
        except Exception as e:
            logger.error("Playlist streaming search failed for '%s': %s", q, e)
            yield _sse_event(
                "failure", {"message": f"Playlist search failed: {str(e)}"}
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/search/albums", response_model=AlbumSearchResponse)
async def api_search_albums(q: str = Query(..., min_length=1)):
    """Search YouTube Music for albums."""
    from kikusan.search import search_albums
    import logging

    logger = logging.getLogger(__name__)

    try:
        results = search_albums(q, limit=20)
    except Exception as e:
        logger.error("Album search failed for query '%s': %s", q, e)
        raise HTTPException(
            status_code=500,
            detail=f"Album search failed: {str(e)}"
        )

    return AlbumSearchResponse(
        query=q,
        results=[AlbumResponse(**album.__dict__) for album in results],
    )


@app.get("/api/album/{browse_id}/tracks", response_model=AlbumTracksResponse)
async def api_get_album_tracks(browse_id: str):
    """Get all tracks for an album."""
    from kikusan.search import get_album_tracks
    import logging

    logger = logging.getLogger(__name__)

    try:
        tracks = get_album_tracks(browse_id)
        if not tracks:
            raise HTTPException(status_code=404, detail="No tracks found for this album")

        return AlbumTracksResponse(
            browse_id=browse_id,
            album_title=tracks[0].album if tracks else "Unknown Album",
            tracks=[_track_to_response(track) for track in tracks],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get album tracks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download", response_model=DownloadResponse)
async def api_download(request: DownloadRequest, http_request: Request):
    """Download a track by video ID."""
    config = get_config()

    # Validate format
    valid_formats = ['opus', 'mp3', 'flac']
    audio_format = request.audio_format.lower()
    if audio_format not in valid_formats:
        return DownloadResponse(
            success=False,
            message=f"Invalid format. Must be one of: {', '.join(valid_formats)}",
        )

    try:
        audio_path = download(
            video_id=request.video_id,
            output_dir=config.download_dir,
            audio_format=audio_format,
            filename_template=config.filename_template,
            fetch_lyrics=True,
            organization_mode=config.organization_mode,
            use_primary_artist=config.use_primary_artist,
            cookie_file=config.cookie_file_path,
            artists=request.artists,
        )

        # Add to playlist if configured
        remote_user = _get_remote_user(http_request, config)
        playlist_name = config.effective_playlist_name(remote_user)
        if audio_path and playlist_name:
            add_to_m3u([audio_path], playlist_name, config.download_dir)

        return DownloadResponse(
            success=True,
            message=f"Downloaded: {request.title} - {request.artist} ({audio_format.upper()})",
            file_path=str(audio_path) if audio_path else None,
            file_name=audio_path.name if audio_path else None,
        )

    except Exception as e:
        return DownloadResponse(
            success=False,
            message=f"Download failed: {str(e)}",
        )


@app.get("/api/download-file/{file_path:path}")
async def download_file(file_path: str):
    """Serve downloaded file for browser download."""
    config = get_config()
    file_path = urllib.parse.unquote(file_path)
    requested_path = Path(file_path)

    try:
        # Normalize relative paths from different callers:
        # - M3U entries: "Artist - Song.opus"
        # - Queue jobs in some setups: "downloads/Artist - Song.opus"
        # Both should resolve to config.download_dir / "<entry>"
        if not requested_path.is_absolute():
            download_dir_name = config.download_dir.name
            if requested_path.parts and requested_path.parts[0] == download_dir_name:
                requested_path = Path(*requested_path.parts[1:])
            requested_path = config.download_dir / requested_path

        abs_requested = requested_path.resolve()
        abs_download_dir = config.download_dir.resolve()

        # Security: ensure path is within download_dir
        try:
            abs_requested.relative_to(abs_download_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not abs_requested.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if not abs_requested.is_file():
            raise HTTPException(status_code=400, detail="Not a file")

        return FileResponse(
            path=abs_requested,
            filename=abs_requested.name,
            media_type='application/octet-stream'
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to serve file")


@app.get("/api/stream-url/{video_id}", response_model=StreamUrlResponse)
async def get_stream_url(video_id: str):
    """Get direct stream URL for a video using yt-dlp."""
    config = get_config()
    try:
        youtube_url = f"https://music.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
        }

        info = extract_info_with_retry(
            ydl_opts=ydl_opts,
            url=youtube_url,
            download=False,
            cookie_file=config.cookie_file_path,
            config=config,
        )

        # Extract direct audio URL
        if 'url' in info:
            stream_url = info['url']
        elif 'formats' in info:
            audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none']
            if audio_formats:
                audio_formats.sort(key=lambda f: f.get('abr', 0), reverse=True)
                stream_url = audio_formats[0]['url']
            else:
                raise HTTPException(status_code=404, detail="No audio stream found")
        else:
            raise HTTPException(status_code=404, detail="No stream URL available")

        is_hls = info.get('protocol', '') == 'm3u8_native' or '.m3u8' in stream_url

        return StreamUrlResponse(
            video_id=video_id,
            url=stream_url,
            expires_in=21600,
            is_hls=is_hls,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stream URL: {str(e)}")


@app.get("/api/preview/{video_id}")
async def preview_audio(video_id: str):
    """Stream audio through the server to avoid CORS issues with HLS streams.

    Uses yt-dlp to resolve the stream URL, then ffmpeg to remux HLS into
    a fragmented MP4 that the browser can play progressively.
    """
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")

    config = get_config()
    youtube_url = f"https://music.youtube.com/watch?v={video_id}"

    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
        }
        info = extract_info_with_retry(
            ydl_opts=ydl_opts,
            url=youtube_url,
            download=False,
            cookie_file=config.cookie_file_path,
            config=config,
        )

        if 'url' in info:
            stream_url = info['url']
        elif 'formats' in info:
            audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none']
            if audio_formats:
                audio_formats.sort(key=lambda f: f.get('abr', 0), reverse=True)
                stream_url = audio_formats[0]['url']
            else:
                raise HTTPException(status_code=404, detail="No audio stream found")
        else:
            raise HTTPException(status_code=404, detail="No stream URL available")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stream URL: {str(e)}")

    # Convert HLS stream to MP3 via ffmpeg for browser playback
    cmd = [
        'ffmpeg',
        '-i', stream_url,
        '-vn',
        '-f', 'mp3',
        '-ab', '128k',
        '-loglevel', 'error',
        'pipe:1',
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream_audio():
        try:
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                process.kill()

    return StreamingResponse(stream_audio(), media_type="audio/mpeg")


# Queue endpoints


class QueueAddRequest(BaseModel):
    """Request to add a job to the queue."""

    video_id: str
    title: str
    artist: str
    artists: list[str] | None = None
    audio_format: str = "opus"


class QueueAddAlbumRequest(BaseModel):
    """Request to add an album to the queue."""

    browse_id: str
    album_title: str
    artist: str
    audio_format: str = "opus"


class QueueAddResponse(BaseModel):
    """Response after adding a job."""

    job_id: str
    status: str


@app.post("/api/queue/add", response_model=QueueAddResponse)
async def add_to_queue(request: QueueAddRequest, http_request: Request):
    """Add a download job to the queue."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    # Validate format
    valid_formats = ["opus", "mp3", "flac"]
    audio_format = request.audio_format.lower()
    if audio_format not in valid_formats:
        raise HTTPException(
            status_code=400, detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}"
        )

    config = get_config()
    remote_user = _get_remote_user(http_request, config)
    playlist_name = config.effective_playlist_name(remote_user)

    job_id = await queue_manager.add_job(
        video_id=request.video_id,
        title=request.title,
        artist=request.artist,
        format=audio_format,
        artists=request.artists,
        playlist_name=playlist_name,
    )

    return QueueAddResponse(job_id=job_id, status="queued")


@app.post("/api/queue/add-album")
async def add_album_to_queue(request: QueueAddAlbumRequest, http_request: Request):
    """Add all tracks from an album to the download queue."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    from kikusan.search import get_album_tracks
    import logging

    logger = logging.getLogger(__name__)

    try:
        tracks = get_album_tracks(request.browse_id)
        if not tracks:
            raise HTTPException(status_code=404, detail="No tracks found for this album")

        # Validate format
        valid_formats = ["opus", "mp3", "flac"]
        audio_format = request.audio_format.lower()
        if audio_format not in valid_formats:
            raise HTTPException(
                status_code=400, detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}"
            )

        config = get_config()
        remote_user = _get_remote_user(http_request, config)
        playlist_name = config.effective_playlist_name(remote_user)

        job_ids = []
        for track in tracks:
            job_id = await queue_manager.add_job(
                video_id=track.video_id,
                title=track.title,
                artist=track.artist,
                format=audio_format,
                artists=track.artists,
                playlist_name=playlist_name,
            )
            job_ids.append(job_id)

        logger.info("Queued %d tracks from album: %s", len(job_ids), request.album_title)
        return {
            "job_ids": job_ids,
            "track_count": len(job_ids),
            "message": f"Added {len(job_ids)} tracks to queue"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to queue album: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/queue/jobs")
async def list_queue_jobs():
    """List all jobs in the queue."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    jobs = await queue_manager.list_jobs()
    return {"jobs": [job.to_dict() for job in jobs]}


@app.delete("/api/queue/{job_id}")
async def remove_queue_job(job_id: str):
    """Remove or clear a job from the queue."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    success = await queue_manager.remove_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or cannot be removed")

    return {"success": True}


@app.get("/api/queue/stream")
async def stream_queue_updates(request: Request):
    """Server-Sent Events endpoint for real-time queue updates."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    async def event_generator():
        """Generate SSE events for queue updates."""
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Get current jobs
                jobs = await queue_manager.list_jobs()
                jobs_data = [job.to_dict() for job in jobs]

                # Send update via SSE
                yield f"data: {json.dumps(jobs_data)}\n\n"

                # Wait before next update
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/queue/stats")
async def get_queue_stats():
    """Get queue statistics."""
    if not queue_manager:
        raise HTTPException(status_code=500, detail="Queue manager not initialized")

    return await queue_manager.get_stats()


# Explore endpoints

@app.get("/api/explore/moods")
async def api_explore_moods():
    """Get mood & genre categories."""
    from kikusan.search import get_mood_categories
    import logging
    logger = logging.getLogger(__name__)

    try:
        sections = get_mood_categories()
        return [
            MoodSectionResponse(
                title=s.title,
                categories=[MoodCategoryResponse(title=c.title, params=c.params) for c in s.categories],
            )
            for s in sections
        ]
    except Exception as e:
        logger.error("Failed to get mood categories: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get mood categories: {str(e)}")


@app.get("/api/explore/mood-playlists")
async def api_explore_mood_playlists(params: str = Query(..., description="Category params from moods endpoint")):
    """Get playlists for a mood/genre category."""
    from kikusan.search import get_mood_playlists
    import logging
    logger = logging.getLogger(__name__)

    try:
        playlists = get_mood_playlists(params)
        return [
            MoodPlaylistResponse(
                playlist_id=p.playlist_id,
                title=p.title,
                thumbnail_url=p.thumbnail_url,
                author=p.author,
            )
            for p in playlists
        ]
    except Exception as e:
        logger.error("Failed to get mood playlists: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get mood playlists: {str(e)}")


@app.get("/api/explore/charts")
async def api_explore_charts(country: str = Query("ZZ", description="ISO 3166-1 Alpha-2 country code")):
    """Get current music charts."""
    from kikusan.search import get_charts
    import logging
    logger = logging.getLogger(__name__)

    # Validate country code format
    if not re.match(r"^[A-Z]{2}$", country):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid country code '{country}': must be a 2-letter uppercase ISO 3166-1 Alpha-2 code (e.g., 'US', 'GB', 'ZZ')"
        )

    try:
        # Pass allow_ugc=True so web UI can show all tracks with UGC badge
        charts = get_charts(country, allow_ugc=True)
        return ChartsResponse(
            country=charts.country,
            tracks=[
                ChartTrackResponse(
                    video_id=t.video_id,
                    title=t.title,
                    artist=t.artist,
                    artists=t.artists,
                    album=t.album,
                    thumbnail_url=t.thumbnail_url,
                    rank=t.rank,
                    trend=t.trend,
                    view_count=t.view_count,
                    duration=t.duration_display,
                    video_type=t.video_type,
                )
                for t in charts.tracks
            ],
            artists=[
                ChartArtistResponse(
                    browse_id=a.browse_id,
                    title=a.title,
                    thumbnail_url=a.thumbnail_url,
                    rank=a.rank,
                    trend=a.trend,
                )
                for a in charts.artists
            ],
        )
    except Exception as e:
        logger.error("Failed to get charts: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get charts: {str(e)}")


@app.get("/api/explore/playlist/{playlist_id}/tracks")
async def api_explore_playlist_tracks(playlist_id: str):
    """Get tracks from a YouTube Music playlist (mood/genre playlist)."""
    from kikusan.search import get_playlist_tracks
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Pass allow_ugc=True so web UI can show all tracks with UGC badge
        tracks = get_playlist_tracks(playlist_id, allow_ugc=True)
        return {
            "playlist_id": playlist_id,
            "tracks": [_track_to_response(track) for track in tracks],
        }
    except ValueError as e:
        logger.warning("Playlist unavailable: %s", e)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to get playlist tracks: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get playlist tracks: {str(e)}")


# Cookie management endpoints
@app.post("/api/settings/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    """Upload cookies.txt file for yt-dlp authentication."""
    # Validate file
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="File must be a .txt file")

    # Read file content
    content = await file.read()
    if len(content) > 1024 * 1024:  # 1MB limit
        raise HTTPException(status_code=400, detail="File too large (max 1MB)")

    # Validate file encoding and content
    try:
        content_str = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text")

    # Validate Netscape cookie file format
    lines = content_str.strip().split('\n')
    has_valid_cookies = False

    for line in lines:
        # Skip empty lines and comments
        if not line.strip() or line.startswith('#'):
            continue

        # Cookie lines should have 7 tab-separated fields
        parts = line.split('\t')
        if len(parts) == 7:
            has_valid_cookies = True
            break

    if not has_valid_cookies:
        raise HTTPException(
            status_code=400,
            detail="Invalid cookie file format. Expected Netscape format with tab-separated values"
        )

    # Create .kikusan directory if it doesn't exist
    kikusan_dir = Path(".kikusan")
    kikusan_dir.mkdir(exist_ok=True)

    # Write cookie file
    cookie_path = kikusan_dir / "cookies.txt"
    cookie_path.write_bytes(content)
    cookie_path.chmod(0o600)  # Secure permissions

    return {
        "success": True,
        "message": "Cookie file uploaded successfully",
        "path": str(cookie_path)
    }


@app.get("/api/settings/cookies/status")
async def get_cookie_status():
    """Check if cookies are configured."""
    config = get_config()
    cookie_path = config.cookie_file_path

    if cookie_path:
        path = Path(cookie_path)
        return {
            "configured": True,
            "source": "uploaded" if ".kikusan/cookies.txt" in cookie_path else "environment",
            "path": cookie_path,
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else 0
        }
    else:
        return {
            "configured": False,
            "source": None,
            "path": None,
            "exists": False
        }


@app.delete("/api/settings/cookies")
async def delete_cookies():
    """Delete uploaded cookie file."""
    cookie_path = Path(".kikusan/cookies.txt")
    if cookie_path.exists():
        cookie_path.unlink()
        return {"success": True, "message": "Cookie file deleted"}
    else:
        raise HTTPException(status_code=404, detail="No uploaded cookie file found")


# Playlist (Downloads tab) endpoints


def _extract_track_info(entry_path: str, download_dir: Path) -> dict:
    """Extract track metadata from an audio file using mutagen, with path-based fallback."""
    full_path = download_dir / entry_path
    file_exists = full_path.exists()

    info = {
        "entry_path": entry_path,
        "title": "",
        "artist": "",
        "album": None,
        "duration": None,
        "file_exists": file_exists,
    }

    # Try mutagen metadata extraction
    if file_exists:
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(full_path)
            if audio:
                title = audio.get("title", [])
                artist = audio.get("artist", []) or audio.get("ARTISTS", []) or audio.get("artists", [])
                album = audio.get("album", [])

                info["title"] = str(title[0]) if isinstance(title, list) and title else str(title) if title else ""
                info["artist"] = str(artist[0]) if isinstance(artist, list) and artist else str(artist) if artist else ""
                info["album"] = str(album[0]) if isinstance(album, list) and album else str(album) if album else None

                if audio.info and hasattr(audio.info, "length") and audio.info.length:
                    total_seconds = int(audio.info.length)
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    info["duration"] = f"{minutes}:{seconds:02d}"
        except Exception:
            pass

    # Fallback to path parsing if metadata is incomplete
    if not info["title"]:
        title, artist = _parse_track_info_from_path(entry_path)
        info["title"] = title
        if not info["artist"]:
            info["artist"] = artist

    return info


def _parse_track_info_from_path(entry_path: str) -> tuple[str, str]:
    """Parse title and artist from file path.

    Handles:
      - Flat mode: "Artist - Title.opus"
      - Album mode: "Artist/Album/01 - Title.opus"
    """
    p = Path(entry_path)
    stem = p.stem
    parts = p.parts

    # Album mode: Artist/Album/TrackNum - Title.ext
    if len(parts) >= 3:
        artist = parts[0]
        # Strip leading track number pattern like "01 - "
        title = stem
        if " - " in title:
            title = title.split(" - ", 1)[1]
        return title, artist

    # Flat mode: Artist - Title.ext
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()

    return stem, ""


@app.get("/api/playlist/status")
async def api_playlist_status(http_request: Request):
    """Check if playlist feature is enabled for the current user."""
    config = get_config()
    remote_user = _get_remote_user(http_request, config)
    playlist_name = config.effective_playlist_name(remote_user)
    return {"enabled": playlist_name is not None}


@app.get("/api/playlist/tracks")
async def api_playlist_tracks(http_request: Request):
    """List tracks in the user's download playlist with metadata."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    config = get_config()
    remote_user = _get_remote_user(http_request, config)
    playlist_name = config.effective_playlist_name(remote_user)

    if not playlist_name:
        raise HTTPException(status_code=404, detail="Playlist not configured")

    entries = read_m3u(playlist_name, config.download_dir)
    loop = asyncio.get_event_loop()

    # Extract metadata in thread pool to avoid blocking the event loop
    tracks = []
    for entry in entries:
        info = await loop.run_in_executor(None, _extract_track_info, entry, config.download_dir)
        tracks.append(info)

    return {"tracks": tracks, "total": len(tracks), "playlist_name": playlist_name}


@app.delete("/api/playlist/tracks")
async def api_playlist_remove_track(entry_path: str = Query(..., description="Exact M3U entry to remove"), http_request: Request = None):
    """Remove a track entry from the playlist (does not delete the audio file)."""
    config = get_config()
    remote_user = _get_remote_user(http_request, config)
    playlist_name = config.effective_playlist_name(remote_user)

    if not playlist_name:
        raise HTTPException(status_code=404, detail="Playlist not configured")

    removed = remove_from_m3u(entry_path, playlist_name, config.download_dir)
    if not removed:
        raise HTTPException(status_code=404, detail="Entry not found in playlist")

    return {"success": True, "message": "Track removed from playlist"}
