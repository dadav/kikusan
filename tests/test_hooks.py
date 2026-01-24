"""Tests for the hook system."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from kikusan.hooks import (
    HookConfig,
    HookContext,
    HookRunner,
    parse_hooks_config,
)


class TestHookConfig:
    """Tests for HookConfig dataclass."""

    def test_default_values(self):
        hook = HookConfig(event="playlist_updated", command="echo test")
        assert hook.event == "playlist_updated"
        assert hook.command == "echo test"
        assert hook.timeout == 60
        assert hook.run_on_error is False

    def test_custom_values(self):
        hook = HookConfig(
            event="sync_completed",
            command="custom command",
            timeout=30,
            run_on_error=True,
        )
        assert hook.event == "sync_completed"
        assert hook.command == "custom command"
        assert hook.timeout == 30
        assert hook.run_on_error is True


class TestHookContext:
    """Tests for HookContext dataclass."""

    def test_default_values(self):
        ctx = HookContext(event="playlist_updated")
        assert ctx.event == "playlist_updated"
        assert ctx.playlist_name is None
        assert ctx.playlist_path is None
        assert ctx.sync_type is None
        assert ctx.downloaded == 0
        assert ctx.skipped == 0
        assert ctx.deleted == 0
        assert ctx.failed == 0
        assert ctx.success is True

    def test_to_env_basic(self):
        ctx = HookContext(event="playlist_updated")
        env = ctx.to_env()
        assert env["KIKUSAN_EVENT"] == "playlist_updated"
        assert env["KIKUSAN_DOWNLOADED"] == "0"
        assert env["KIKUSAN_SUCCESS"] == "true"

    def test_to_env_full(self):
        ctx = HookContext(
            event="sync_completed",
            playlist_name="favorites",
            playlist_path=Path("/music/favorites.m3u"),
            sync_type="playlist",
            downloaded=5,
            skipped=2,
            deleted=1,
            failed=0,
            success=True,
        )
        env = ctx.to_env()
        assert env["KIKUSAN_EVENT"] == "sync_completed"
        assert env["KIKUSAN_PLAYLIST_NAME"] == "favorites"
        assert env["KIKUSAN_PLAYLIST_PATH"] == "/music/favorites.m3u"
        assert env["KIKUSAN_SYNC_TYPE"] == "playlist"
        assert env["KIKUSAN_DOWNLOADED"] == "5"
        assert env["KIKUSAN_SKIPPED"] == "2"
        assert env["KIKUSAN_DELETED"] == "1"
        assert env["KIKUSAN_FAILED"] == "0"
        assert env["KIKUSAN_SUCCESS"] == "true"

    def test_to_env_extra(self):
        ctx = HookContext(
            event="playlist_updated",
            extra={"custom_key": "custom_value", "number": 42},
        )
        env = ctx.to_env()
        assert env["KIKUSAN_CUSTOM_KEY"] == "custom_value"
        assert env["KIKUSAN_NUMBER"] == "42"

    def test_to_env_failure(self):
        ctx = HookContext(event="sync_completed", success=False)
        env = ctx.to_env()
        assert env["KIKUSAN_SUCCESS"] == "false"


class TestHookRunner:
    """Tests for HookRunner class."""

    def test_no_hooks(self):
        runner = HookRunner()
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert results == []

    def test_no_matching_hooks(self):
        hooks = [HookConfig(event="sync_completed", command="echo test")]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert results == []

    def test_run_simple_hook(self):
        hooks = [HookConfig(event="playlist_updated", command="echo hello")]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        hook, success, output = results[0]
        assert success is True
        assert "hello" in output

    def test_hook_receives_env_vars(self):
        hooks = [
            HookConfig(
                event="playlist_updated",
                command='echo "Name: $KIKUSAN_PLAYLIST_NAME"',
            )
        ]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated", playlist_name="test-playlist")
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        _, success, output = results[0]
        assert success is True
        assert "Name: test-playlist" in output

    def test_hook_failure(self):
        hooks = [HookConfig(event="playlist_updated", command="exit 1")]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        _, success, _ = results[0]
        assert success is False

    def test_hook_timeout(self):
        hooks = [
            HookConfig(event="playlist_updated", command="sleep 10", timeout=1)
        ]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        _, success, output = results[0]
        assert success is False
        assert "timed out" in output.lower()

    def test_skip_hook_on_error(self):
        hooks = [HookConfig(event="sync_completed", command="echo test", run_on_error=False)]
        runner = HookRunner(hooks)
        ctx = HookContext(event="sync_completed", success=False)
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        _, success, output = results[0]
        assert success is False
        assert "Skipped" in output

    def test_run_hook_on_error(self):
        hooks = [HookConfig(event="sync_completed", command="echo test", run_on_error=True)]
        runner = HookRunner(hooks)
        ctx = HookContext(event="sync_completed", success=False)
        results = runner.run_hooks(ctx)
        assert len(results) == 1
        _, success, output = results[0]
        assert success is True
        assert "test" in output

    def test_multiple_hooks_same_event(self):
        hooks = [
            HookConfig(event="playlist_updated", command="echo first"),
            HookConfig(event="playlist_updated", command="echo second"),
        ]
        runner = HookRunner(hooks)
        ctx = HookContext(event="playlist_updated")
        results = runner.run_hooks(ctx)
        assert len(results) == 2
        outputs = [output for _, _, output in results]
        assert any("first" in o for o in outputs)
        assert any("second" in o for o in outputs)


class TestParseHooksConfig:
    """Tests for parse_hooks_config function."""

    def test_empty_config(self):
        hooks = parse_hooks_config(None)
        assert hooks == []

        hooks = parse_hooks_config([])
        assert hooks == []

    def test_valid_config(self):
        data = [
            {"event": "playlist_updated", "command": "echo test"},
            {
                "event": "sync_completed",
                "command": "custom script",
                "timeout": 30,
                "run_on_error": True,
            },
        ]
        hooks = parse_hooks_config(data)
        assert len(hooks) == 2
        assert hooks[0].event == "playlist_updated"
        assert hooks[0].command == "echo test"
        assert hooks[0].timeout == 60  # default
        assert hooks[0].run_on_error is False  # default
        assert hooks[1].event == "sync_completed"
        assert hooks[1].timeout == 30
        assert hooks[1].run_on_error is True

    def test_missing_event(self):
        data = [{"command": "echo test"}]
        with pytest.raises(ValueError, match="missing required field: event"):
            parse_hooks_config(data)

    def test_missing_command(self):
        data = [{"event": "playlist_updated"}]
        with pytest.raises(ValueError, match="missing required field: command"):
            parse_hooks_config(data)

    def test_invalid_event(self):
        data = [{"event": "invalid_event", "command": "echo test"}]
        with pytest.raises(ValueError, match="invalid event"):
            parse_hooks_config(data)

    def test_invalid_timeout(self):
        data = [{"event": "playlist_updated", "command": "echo test", "timeout": -1}]
        with pytest.raises(ValueError, match="timeout must be a positive integer"):
            parse_hooks_config(data)

    def test_invalid_run_on_error(self):
        data = [{"event": "playlist_updated", "command": "echo test", "run_on_error": "yes"}]
        with pytest.raises(ValueError, match="run_on_error must be a boolean"):
            parse_hooks_config(data)

    def test_not_dict(self):
        data = ["not a dict"]
        with pytest.raises(ValueError, match="must be a dictionary"):
            parse_hooks_config(data)

    def test_empty_command(self):
        data = [{"event": "playlist_updated", "command": "   "}]
        with pytest.raises(ValueError, match="must be a non-empty string"):
            parse_hooks_config(data)
