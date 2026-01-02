import logging
from types import SimpleNamespace

from webui import server


class _FailingTvManager:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.load_calls = 0

    def load(self) -> None:
        self.load_calls += 1
        raise self.exc


def test_startup_tasks_skip_when_tv_yaml_invalid(monkeypatch, caplog) -> None:
    context = SimpleNamespace(preference_parser=SimpleNamespace(use_tmdb=True, use_plex=True))
    tv_manager = _FailingTvManager(ValueError("bad yaml"))

    called = []

    def _unexpected_call(*_args, **_kwargs) -> None:
        called.append("called")

    monkeypatch.setattr(server, "backfill_tmdb_ids", _unexpected_call)
    monkeypatch.setattr(server, "backfill_rating_keys", _unexpected_call)
    monkeypatch.setattr(server, "backfill_episode_rating_keys", _unexpected_call)

    caplog.set_level(logging.WARNING, logger=server.logger.name)

    thread = server._run_startup_tasks_async(context, tv_manager)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert tv_manager.load_calls == 1
    assert called == []
    assert "tv.yml is invalid" in caplog.text
