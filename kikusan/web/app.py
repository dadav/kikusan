"""FastAPI web application for Kikusan."""

import asyncio
import json
import urllib.parse
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from kikusan.config import get_config
from kikusan.download import download
from kikusan.playlist import add_to_m3u
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
    album: str | None
    duration: str
    thumbnail_url: str | None
    view_count: str | None


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main search page."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/search", response_model=SearchResponse)
async def api_search(q: str = Query(..., min_length=1, description="Search query")):
    """Search for music on YouTube Music."""
    results = search(q, limit=20)

    return SearchResponse(
        query=q,
        results=[
            TrackResponse(
                video_id=track.video_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration=track.duration_display,
                thumbnail_url=track.thumbnail_url,
                view_count=track.view_count,
            )
            for track in results
        ],
    )


@app.get("/api/search/albums", response_model=AlbumSearchResponse)
async def api_search_albums(q: str = Query(..., min_length=1)):
    """Search YouTube Music for albums."""
    from kikusan.search import search_albums

    results = search_albums(q, limit=20)
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
            tracks=[
                TrackResponse(
                    video_id=track.video_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration=track.duration_display,
                    thumbnail_url=track.thumbnail_url,
                    view_count=track.view_count,
                )
                for track in tracks
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get album tracks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download", response_model=DownloadResponse)
async def api_download(request: DownloadRequest):
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
        )

        # Add to playlist if configured
        if audio_path and config.web_playlist_name:
            add_to_m3u([audio_path], config.web_playlist_name, config.download_dir)

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
        abs_requested = requested_path.resolve()
        abs_download_dir = config.download_dir.resolve()

        # Security: ensure path is within download_dir
        if not str(abs_requested).startswith(str(abs_download_dir)):
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

        return StreamUrlResponse(
            video_id=video_id,
            url=stream_url,
            expires_in=21600
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stream URL: {str(e)}")


# Queue endpoints


class QueueAddRequest(BaseModel):
    """Request to add a job to the queue."""

    video_id: str
    title: str
    artist: str
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
async def add_to_queue(request: QueueAddRequest):
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

    job_id = await queue_manager.add_job(
        video_id=request.video_id,
        title=request.title,
        artist=request.artist,
        format=audio_format,
    )

    return QueueAddResponse(job_id=job_id, status="queued")


@app.post("/api/queue/add-album")
async def add_album_to_queue(request: QueueAddAlbumRequest):
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

        job_ids = []
        for track in tracks:
            job_id = await queue_manager.add_job(
                video_id=track.video_id,
                title=track.title,
                artist=track.artist,
                format=audio_format,
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

    jobs = queue_manager.list_jobs()
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
                jobs = queue_manager.list_jobs()
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

    return queue_manager.get_stats()


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

    # Basic validation - check for Netscape format
    content_str = content.decode('utf-8', errors='ignore')
    if '# Netscape HTTP Cookie File' not in content_str and '# HTTP Cookie File' not in content_str:
        # Allow files without header as they might still work
        pass

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
