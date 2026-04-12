from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus
from savesync_bridge.ui.workers import (
    FetchCloudManifestWorker,
    PullWorker,
    PushWorker,
)


def _make_config() -> AppConfig:
    return AppConfig(
        drive_remote="gdrive",
        drive_root="test-root",
        backup_path="saves",
    )


def _make_manifest(game_id: str = "Hades") -> GameManifest:
    return GameManifest(
        game_id=game_id,
        host=Platform.WINDOWS,
        timestamp=datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC),
        hash="sha256:abc123",
        files=(
            SaveFile(
                path="Profile1.sav",
                size=1024,
                modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
            ),
        ),
    )


@pytest.fixture()
def engine(tmp_path: Path) -> SyncEngine:
    return SyncEngine(config=_make_config(), state_dir=tmp_path / "states")


# ---------------------------------------------------------------------------
# PushWorker concurrency tests
# ---------------------------------------------------------------------------


class TestPushWorker:
    def test_pushes_multiple_games_concurrently(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        game_ids = ["Hades", "Celeste", "Stardew Valley"]
        results_map = {
            gid: SyncResult(gid, SyncStatus.SYNCED)
            for gid in game_ids
        }

        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch.object(
                engine, "push",
                side_effect=lambda gid: results_map[gid],
            ),
        ):
            worker = PushWorker(engine, game_ids)

            collected: list[tuple[str, SyncResult]] = []
            worker.game_updated.connect(
                lambda gid, res: collected.append((gid, res)),
            )

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

        assert len(collected) == 3
        assert {gid for gid, _ in collected} == set(game_ids)
        assert all(r.status == SyncStatus.SYNCED for _, r in collected)

    def test_emits_error_on_exception(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        with patch.object(
            engine, "push",
            side_effect=RuntimeError("boom"),
        ):
            worker = PushWorker(engine, ["Hades"])
            errors: list[str] = []
            worker.error.connect(errors.append)

            with qtbot.waitSignal(worker.error, timeout=5000):
                worker.start()

        assert len(errors) == 1
        assert "boom" in errors[0]

    def test_single_game_push(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        expected = SyncResult("Hades", SyncStatus.SYNCED)
        with patch.object(engine, "push", return_value=expected):
            worker = PushWorker(
                engine, ["Hades"],
            )
            collected: list[tuple[str, SyncResult]] = []
            worker.game_updated.connect(
                lambda gid, res: collected.append((gid, res)),
            )

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

        assert collected == [("Hades", expected)]


# ---------------------------------------------------------------------------
# PullWorker concurrency tests
# ---------------------------------------------------------------------------


class TestPullWorker:
    def test_pulls_multiple_games_concurrently(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        specs = [
            ("Hades", _make_manifest("Hades"), None, None),
            ("Celeste", _make_manifest("Celeste"), None, None),
        ]

        def fake_pull(gid, manifest, **kw):
            return SyncResult(gid, SyncStatus.SYNCED)

        with patch.object(engine, "pull", side_effect=fake_pull):
            worker = PullWorker(engine, specs)
            collected: list[tuple[str, SyncResult]] = []
            worker.game_done.connect(
                lambda gid, res: collected.append((gid, res)),
            )

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

        assert len(collected) == 2
        assert {gid for gid, _ in collected} == {"Hades", "Celeste"}

    def test_passes_wine_context_to_engine(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        m = _make_manifest("Hades")
        prefix = "/home/deck/.local/share/Steam/steamapps/compatdata/1145360/pfx/drive_c"
        specs = [("Hades", m, prefix, "deck")]

        call_args: list[dict] = []

        def capture_pull(gid, manifest, **kw):
            call_args.append(kw)
            return SyncResult(gid, SyncStatus.SYNCED)

        with patch.object(engine, "pull", side_effect=capture_pull):
            worker = PullWorker(engine, specs, concurrency=1)

            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

        assert len(call_args) == 1
        assert call_args[0]["target_wine_prefix"] == prefix
        assert call_args[0]["target_wine_user"] == "deck"

    def test_emits_error_on_exception(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        specs = [
            ("Hades", _make_manifest("Hades"), None, None),
        ]
        with patch.object(
            engine, "pull",
            side_effect=RuntimeError("pull failed"),
        ):
            worker = PullWorker(engine, specs)
            errors: list[str] = []
            worker.error.connect(errors.append)

            with qtbot.waitSignal(worker.error, timeout=5000):
                worker.start()

        assert len(errors) == 1
        assert "pull failed" in errors[0]


# ---------------------------------------------------------------------------
# FetchCloudManifestWorker concurrency tests
# ---------------------------------------------------------------------------


class TestFetchCloudManifestWorker:
    def test_fetches_multiple_manifests_concurrently(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        manifests = {
            "Hades": _make_manifest("Hades"),
            "Celeste": _make_manifest("Celeste"),
            "Stardew": None,
        }

        with patch.object(
            engine, "get_cloud_manifest",
            side_effect=lambda gid: manifests[gid],
        ):
            worker = FetchCloudManifestWorker(
                engine, list(manifests.keys()),
            )
            collected: list[tuple[str, object]] = []
            worker.manifest_ready.connect(
                lambda gid, m: collected.append((gid, m)),
            )

            with qtbot.waitSignal(worker.all_done, timeout=5000):
                worker.start()

        assert len(collected) == 3
        result_map = {gid: m for gid, m in collected}
        assert result_map["Hades"] is not None
        assert result_map["Celeste"] is not None
        assert result_map["Stardew"] is None

    def test_single_game_fetch(
        self, qtbot, engine: SyncEngine,
    ) -> None:
        m = _make_manifest("Hades")
        with patch.object(
            engine, "get_cloud_manifest", return_value=m,
        ):
            worker = FetchCloudManifestWorker(
                engine, ["Hades"],
            )
            collected: list[tuple[str, object]] = []
            worker.manifest_ready.connect(
                lambda gid, m: collected.append((gid, m)),
            )

            with qtbot.waitSignal(worker.all_done, timeout=5000):
                worker.start()

        assert len(collected) == 1
        assert collected[0][0] == "Hades"
        assert collected[0][1].game_id == "Hades"
