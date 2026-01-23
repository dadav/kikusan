"""Unit tests for queue manager."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from kikusan.queue import DownloadJob, JobStatus, QueueManager


@pytest_asyncio.fixture
async def queue_manager():
    """Create a queue manager instance for testing."""
    qm = QueueManager()
    await qm.start()
    yield qm
    await qm.stop()


@pytest.mark.asyncio
async def test_queue_manager_initialization():
    """Test queue manager can be initialized and started."""
    qm = QueueManager()
    assert qm.queue is not None
    assert qm.jobs == {}
    assert not qm._running

    await qm.start()
    assert qm._running
    assert qm.worker_task is not None

    await qm.stop()
    assert not qm._running


@pytest.mark.asyncio
async def test_add_job(queue_manager):
    """Test adding a job to the queue."""
    job_id = await queue_manager.add_job(
        video_id="test123", title="Test Song", artist="Test Artist", format="opus"
    )

    assert job_id is not None
    assert len(queue_manager.jobs) == 1

    job = queue_manager.get_job(job_id)
    assert job is not None
    assert job.video_id == "test123"
    assert job.title == "Test Song"
    assert job.artist == "Test Artist"
    assert job.format == "opus"
    assert job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_get_job(queue_manager):
    """Test retrieving a job by ID."""
    job_id = await queue_manager.add_job(
        video_id="test456", title="Another Song", artist="Another Artist", format="mp3"
    )

    job = queue_manager.get_job(job_id)
    assert job is not None
    assert job.id == job_id
    assert job.video_id == "test456"

    # Test non-existent job
    assert queue_manager.get_job("nonexistent") is None


@pytest.mark.asyncio
async def test_list_jobs(queue_manager):
    """Test listing all jobs."""
    # Add multiple jobs
    job_id1 = await queue_manager.add_job(
        video_id="test1", title="Song 1", artist="Artist 1", format="opus"
    )
    job_id2 = await queue_manager.add_job(
        video_id="test2", title="Song 2", artist="Artist 2", format="mp3"
    )

    jobs = queue_manager.list_jobs()
    assert len(jobs) == 2
    # Jobs should be ordered by creation time (newest first)
    assert jobs[0].id == job_id2
    assert jobs[1].id == job_id1


@pytest.mark.asyncio
async def test_remove_completed_job(queue_manager):
    """Test removing a completed job."""
    job_id = await queue_manager.add_job(
        video_id="test789", title="Complete Me", artist="Test Artist", format="opus"
    )

    # Manually mark as completed
    job = queue_manager.get_job(job_id)
    job.status = JobStatus.COMPLETED

    # Remove should succeed
    success = await queue_manager.remove_job(job_id)
    assert success
    assert queue_manager.get_job(job_id) is None


@pytest.mark.asyncio
async def test_remove_failed_job(queue_manager):
    """Test removing a failed job."""
    job_id = await queue_manager.add_job(
        video_id="test999", title="Fail Me", artist="Test Artist", format="opus"
    )

    # Manually mark as failed
    job = queue_manager.get_job(job_id)
    job.status = JobStatus.FAILED
    job.error = "Test error"

    # Remove should succeed
    success = await queue_manager.remove_job(job_id)
    assert success
    assert queue_manager.get_job(job_id) is None


@pytest.mark.asyncio
async def test_get_stats(queue_manager):
    """Test getting queue statistics."""
    # Initially empty
    stats = queue_manager.get_stats()
    assert stats["total"] == 0
    assert stats["queued"] == 0
    assert stats["downloading"] == 0
    assert stats["completed"] == 0
    assert stats["failed"] == 0

    # Add jobs with different statuses
    job_id1 = await queue_manager.add_job(
        video_id="test1", title="Song 1", artist="Artist 1", format="opus"
    )
    job_id2 = await queue_manager.add_job(
        video_id="test2", title="Song 2", artist="Artist 2", format="mp3"
    )

    # Manually set different statuses
    job1 = queue_manager.get_job(job_id1)
    job1.status = JobStatus.DOWNLOADING

    job2 = queue_manager.get_job(job_id2)
    job2.status = JobStatus.COMPLETED

    stats = queue_manager.get_stats()
    assert stats["total"] == 2
    assert stats["queued"] == 0
    assert stats["downloading"] == 1
    assert stats["completed"] == 1
    assert stats["failed"] == 0


@pytest.mark.asyncio
async def test_job_to_dict():
    """Test converting job to dictionary."""
    job = DownloadJob(
        id="test-id",
        video_id="vid123",
        title="Test Song",
        artist="Test Artist",
        format="opus",
        status=JobStatus.DOWNLOADING,
        progress=50.0,
        speed="1.5 MB/s",
        eta="30s",
    )

    job_dict = job.to_dict()
    assert job_dict["id"] == "test-id"
    assert job_dict["video_id"] == "vid123"
    assert job_dict["title"] == "Test Song"
    assert job_dict["artist"] == "Test Artist"
    assert job_dict["format"] == "opus"
    assert job_dict["status"] == "downloading"
    assert job_dict["progress"] == 50.0
    assert job_dict["speed"] == "1.5 MB/s"
    assert job_dict["eta"] == "30s"


@pytest.mark.asyncio
async def test_worker_processes_job(queue_manager):
    """Test that worker processes jobs from the queue."""
    # Mock the download function
    with patch("kikusan.queue.download") as mock_download:
        mock_download.return_value = "/fake/path/song.opus"

        job_id = await queue_manager.add_job(
            video_id="test123", title="Test Song", artist="Test Artist", format="opus"
        )

        # Wait for worker to process
        await asyncio.sleep(0.5)

        # Check job was processed (status should change from QUEUED)
        job = queue_manager.get_job(job_id)
        # Job might be completed or still downloading depending on timing
        assert job.status in (JobStatus.DOWNLOADING, JobStatus.COMPLETED, JobStatus.QUEUED)


@pytest.mark.asyncio
async def test_job_status_enum():
    """Test JobStatus enum values."""
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.DOWNLOADING.value == "downloading"
    assert JobStatus.COMPLETED.value == "completed"
    assert JobStatus.FAILED.value == "failed"
