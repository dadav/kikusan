"""Job queue manager for async downloads with real-time progress tracking."""

import asyncio
import logging
import uuid
from asyncio import Queue, Task
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from kikusan.config import get_config
from kikusan.download import download
from kikusan.playlist import add_to_m3u

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Download job status states."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadJob:
    """Download job with progress tracking."""

    id: str
    video_id: str
    title: str
    artist: str
    format: str
    status: JobStatus
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    error: Optional[str] = None
    file_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert job to dict for JSON serialization."""
        return {
            "id": self.id,
            "video_id": self.video_id,
            "title": self.title,
            "artist": self.artist,
            "format": self.format,
            "status": self.status.value,
            "progress": self.progress,
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class QueueManager:
    """Manages download job queue with async worker."""

    def __init__(self):
        """Initialize queue manager."""
        self.queue: Queue[DownloadJob] = Queue()
        self.jobs: dict[str, DownloadJob] = {}
        self.worker_task: Optional[Task] = None
        self._running = False

    async def start(self):
        """Start the background worker."""
        if self._running:
            return
        self._running = True
        self.worker_task = asyncio.create_task(self._worker())
        logger.info("Queue manager started")

    async def stop(self):
        """Stop the background worker gracefully."""
        self._running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Queue manager stopped")

    async def add_job(self, video_id: str, title: str, artist: str, format: str = "opus") -> str:
        """
        Add a download job to the queue.

        Args:
            video_id: YouTube video ID
            title: Track title
            artist: Track artist
            format: Audio format (opus, mp3, flac)

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        job = DownloadJob(
            id=job_id,
            video_id=video_id,
            title=title,
            artist=artist,
            format=format,
            status=JobStatus.QUEUED,
        )
        self.jobs[job_id] = job
        await self.queue.put(job)
        logger.info("Added job to queue: %s - %s (id=%s)", artist, title, job_id)
        return job_id

    async def _worker(self):
        """Background worker that processes jobs from the queue."""
        logger.info("Worker started")
        while self._running:
            try:
                # Get job from queue with timeout
                try:
                    job = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Process the job
                await self._process_job(job)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Worker error: %s", e)

        logger.info("Worker stopped")

    async def _process_job(self, job: DownloadJob):
        """
        Process a single download job.

        Args:
            job: The job to process
        """
        logger.info("Processing job: %s - %s (id=%s)", job.artist, job.title, job.id)
        job.status = JobStatus.DOWNLOADING
        config = get_config()

        def progress_callback(progress_data: dict):
            """Update job progress from yt-dlp hook."""
            job.progress = progress_data.get("percent", 0.0)
            job.speed = progress_data.get("speed", "")
            job.eta = progress_data.get("eta", "")

        try:
            # Run download in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            audio_path = await loop.run_in_executor(
                None,
                lambda: download(
                    video_id=job.video_id,
                    output_dir=config.download_dir,
                    audio_format=job.format,
                    filename_template=config.filename_template,
                    fetch_lyrics=True,
                    progress_callback=progress_callback,
                    organization_mode=config.organization_mode,
                    use_primary_artist=config.use_primary_artist,
                    cookie_file=config.cookie_file_path,
                ),
            )

            # Add to playlist if configured
            if audio_path and config.web_playlist_name:
                await loop.run_in_executor(
                    None, lambda: add_to_m3u([audio_path], config.web_playlist_name, config.download_dir)
                )

            job.status = JobStatus.COMPLETED
            job.file_path = str(audio_path) if audio_path else None
            job.completed_at = datetime.now()
            job.progress = 100.0
            logger.info("Job completed: %s - %s (id=%s)", job.artist, job.title, job.id)

        except Exception as e:
            logger.exception("Job failed: %s - %s (id=%s): %s", job.artist, job.title, job.id, e)
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now()

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        """
        Get a job by ID.

        Args:
            job_id: The job ID

        Returns:
            The job or None if not found
        """
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[DownloadJob]:
        """
        List all jobs ordered by creation time (newest first).

        Returns:
            List of jobs
        """
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def remove_job(self, job_id: str) -> bool:
        """
        Remove a job from the queue or clear if completed/failed.

        Args:
            job_id: The job ID to remove

        Returns:
            True if removed, False if not found
        """
        job = self.jobs.get(job_id)
        if not job:
            return False

        # Can only remove queued jobs or clear completed/failed
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            del self.jobs[job_id]
            logger.info("Cleared job: %s (id=%s)", job.status.value, job_id)
            return True
        elif job.status == JobStatus.QUEUED:
            # TODO: Implement removal from queue (requires queue modification)
            # For now, just mark as failed
            job.status = JobStatus.FAILED
            job.error = "Cancelled by user"
            logger.info("Cancelled job: %s (id=%s)", job_id)
            return True

        return False

    def get_stats(self) -> dict:
        """
        Get queue statistics.

        Returns:
            Dict with queue stats
        """
        queued = sum(1 for j in self.jobs.values() if j.status == JobStatus.QUEUED)
        downloading = sum(1 for j in self.jobs.values() if j.status == JobStatus.DOWNLOADING)
        completed = sum(1 for j in self.jobs.values() if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in self.jobs.values() if j.status == JobStatus.FAILED)

        return {
            "total": len(self.jobs),
            "queued": queued,
            "downloading": downloading,
            "completed": completed,
            "failed": failed,
        }
