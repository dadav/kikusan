"""APScheduler management for cron jobs."""

import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from kikusan.config import get_config
from kikusan.cron.config import CronConfig, load_config
from kikusan.cron.sync import sync_playlist
from kikusan.hooks import HookContext, HookRunner

logger = logging.getLogger(__name__)


class CronScheduler:
    """Manages cron-based playlist synchronization."""

    def __init__(self, config_path: Path, download_dir: Path | None = None):
        """
        Initialize the cron scheduler.

        Args:
            config_path: Path to cron.yaml configuration
            download_dir: Optional override for download directory
        """
        self.config_path = config_path
        self.cron_config: CronConfig | None = None
        self.scheduler: BackgroundScheduler | None = None
        self.download_dir = download_dir
        self.hook_runner: HookRunner | None = None

        # Load main config for defaults
        main_config = get_config()
        if not self.download_dir:
            self.download_dir = main_config.download_dir

        self.audio_format = main_config.audio_format
        self.filename_template = main_config.filename_template
        self.organization_mode = main_config.organization_mode
        self.use_primary_artist = main_config.use_primary_artist

    def load_configuration(self) -> None:
        """Load and validate cron configuration."""
        logger.info("Loading configuration from: %s", self.config_path)
        self.cron_config = load_config(self.config_path)
        self.hook_runner = HookRunner(self.cron_config.hooks)

    def start(self) -> None:
        """Start the scheduler."""
        if not self.cron_config:
            self.load_configuration()

        logger.info("Starting cron scheduler")

        self.scheduler = BackgroundScheduler()

        # Discover plugins
        from kikusan.plugins.registry import discover_plugins

        discover_plugins()

        # Schedule each playlist
        for playlist_name, playlist_config in self.cron_config.playlists.items():
            self._schedule_playlist(playlist_config)

        # Schedule each plugin
        for plugin_name, plugin_config in self.cron_config.plugins.items():
            self._schedule_plugin(plugin_config)

        self.scheduler.start()
        logger.info("Scheduler started successfully")

    def _schedule_playlist(self, playlist_config) -> None:
        """
        Schedule a playlist for synchronization.

        Args:
            playlist_config: Playlist configuration
        """
        trigger = CronTrigger.from_crontab(playlist_config.schedule)

        self.scheduler.add_job(
            func=self._sync_job,
            trigger=trigger,
            args=[playlist_config],
            id=playlist_config.name,
            name=f"Sync {playlist_config.name}",
            replace_existing=True,
        )

        logger.info(
            "Scheduled playlist '%s' with cron: %s",
            playlist_config.name,
            playlist_config.schedule,
        )

    def _sync_job(self, playlist_config) -> None:
        """
        Job function to sync a playlist.

        This is called by APScheduler on schedule.

        Args:
            playlist_config: Playlist configuration
        """
        result = None
        success = False

        try:
            result = sync_playlist(
                playlist_config=playlist_config,
                download_dir=self.download_dir,
                audio_format=self.audio_format,
                filename_template=self.filename_template,
                organization_mode=self.organization_mode,
                use_primary_artist=self.use_primary_artist,
            )
            success = True

            from kikusan.notifications import send_sync_notification

            send_sync_notification(
                name=playlist_config.name,
                sync_type="playlist",
                result=result,
                success=True,
            )
        except Exception as e:
            logger.error("Sync job failed for %s: %s", playlist_config.name, e)

            from kikusan.notifications import send_sync_notification

            send_sync_notification(
                name=playlist_config.name,
                sync_type="playlist",
                result=None,
                success=False,
                error=str(e),
            )

        # Run hooks after sync
        self._run_sync_hooks(
            playlist_name=playlist_config.name,
            sync_type="playlist",
            result=result,
            success=success,
        )

    def _schedule_plugin(self, plugin_config) -> None:
        """
        Schedule a plugin for synchronization.

        Args:
            plugin_config: Plugin configuration
        """
        trigger = CronTrigger.from_crontab(plugin_config.schedule)

        self.scheduler.add_job(
            func=self._plugin_sync_job,
            trigger=trigger,
            args=[plugin_config],
            id=f"plugin_{plugin_config.name}",
            name=f"Plugin sync: {plugin_config.name}",
            replace_existing=True,
        )

        logger.info(
            "Scheduled plugin '%s' (%s) with cron: %s",
            plugin_config.name,
            plugin_config.type,
            plugin_config.schedule,
        )

    def _plugin_sync_job(self, plugin_config) -> None:
        """
        Job function to sync a plugin.

        This is called by APScheduler on schedule.

        Args:
            plugin_config: Plugin configuration
        """
        result = None
        success = False

        try:
            from kikusan.plugins.base import PluginConfig
            from kikusan.plugins.registry import get_plugin
            from kikusan.plugins.sync import sync_plugin_instance

            # Get plugin instance
            plugin_class = get_plugin(plugin_config.type)
            plugin = plugin_class()

            # Create config
            cfg = PluginConfig(
                name=plugin_config.name,
                download_dir=self.download_dir,
                audio_format=self.audio_format,
                filename_template=self.filename_template,
                config=plugin_config.config,
                organization_mode=self.organization_mode,
                use_primary_artist=self.use_primary_artist,
            )

            # Run sync
            result = sync_plugin_instance(plugin, cfg, sync_mode=plugin_config.sync)
            success = True

            from kikusan.notifications import send_sync_notification

            send_sync_notification(
                name=plugin_config.name,
                sync_type="plugin",
                result=result,
                success=True,
            )

        except Exception as e:
            logger.error("Plugin sync job failed for %s: %s", plugin_config.name, e)

            from kikusan.notifications import send_sync_notification

            send_sync_notification(
                name=plugin_config.name,
                sync_type="plugin",
                result=None,
                success=False,
                error=str(e),
            )

        # Run hooks after sync
        self._run_sync_hooks(
            playlist_name=plugin_config.name,
            sync_type="plugin",
            result=result,
            success=success,
        )

    def _run_sync_hooks(
        self,
        playlist_name: str,
        sync_type: str,
        result,
        success: bool,
    ) -> None:
        """Run hooks after a sync operation.

        Args:
            playlist_name: Name of the playlist/plugin
            sync_type: Type of sync ("playlist" or "plugin")
            result: Sync result object (SyncResult)
            success: Whether the sync was successful
        """
        if not self.hook_runner:
            return

        # Build M3U path
        m3u_path = self.download_dir / f"{playlist_name}.m3u"

        # Extract counts from result
        downloaded = 0
        skipped = 0
        deleted = 0
        failed = 0

        if result:
            downloaded = getattr(result, "downloaded", 0)
            skipped = getattr(result, "skipped", 0)
            deleted = getattr(result, "deleted", 0)
            failed = getattr(result, "failed", 0)

        # Run playlist_updated hooks if M3U exists
        if m3u_path.exists():
            context = HookContext(
                event="playlist_updated",
                playlist_name=playlist_name,
                playlist_path=m3u_path,
                sync_type=sync_type,
                downloaded=downloaded,
                skipped=skipped,
                deleted=deleted,
                failed=failed,
                success=success,
            )
            self.hook_runner.run_hooks(context)

        # Run sync_completed hooks
        context = HookContext(
            event="sync_completed",
            playlist_name=playlist_name,
            playlist_path=m3u_path if m3u_path.exists() else None,
            sync_type=sync_type,
            downloaded=downloaded,
            skipped=skipped,
            deleted=deleted,
            failed=failed,
            success=success,
        )
        self.hook_runner.run_hooks(context)

    def sync_all_once(self) -> None:
        """Sync all playlists and plugins once immediately."""
        if not self.cron_config:
            self.load_configuration()

        # Discover plugins
        from kikusan.plugins.registry import discover_plugins

        discover_plugins()

        logger.info("Syncing all playlists and plugins once")

        for playlist_config in self.cron_config.playlists.values():
            self._sync_job(playlist_config)

        for plugin_config in self.cron_config.plugins.values():
            self._plugin_sync_job(plugin_config)

        logger.info("All playlists and plugins synced")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self.scheduler:
            logger.info("Stopping scheduler...")
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def run_forever(self) -> None:
        """
        Run the scheduler indefinitely with signal handling.

        Blocks until SIGTERM or SIGINT is received.
        """
        # Setup signal handlers for graceful shutdown
        def handle_shutdown(signum, frame):
            logger.info("Received shutdown signal (%s), stopping...", signum)
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

        # Start scheduler
        self.start()

        logger.info("Cron scheduler running. Press Ctrl+C to stop.")

        # Keep the main thread alive
        try:
            while True:
                # Sleep indefinitely, signals will wake us up
                signal.pause()
        except (KeyboardInterrupt, SystemExit):
            self.stop()
