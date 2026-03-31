from subprocess import TimeoutExpired

from modules.ImageMagickInterface import ImageMagickInterface


class _TimeoutProcess:
    def __init__(self) -> None:
        self.communicate_calls = 0
        self.kill_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def communicate(self, timeout=None):  # pylint: disable=unused-argument
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise TimeoutExpired(cmd="convert", timeout=60)
        return b"done", b"killed"

    def kill(self) -> None:
        self.kill_called = True


class _SuccessProcess:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def communicate(self, timeout=None):  # pylint: disable=unused-argument
        return b"success", b""

    def kill(self) -> None:
        return None


def test_run_kills_process_and_collects_output_after_timeout(monkeypatch) -> None:
    process = _TimeoutProcess()

    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: process)

    interface = ImageMagickInterface(timeout=1)
    stdout, stderr = interface.run("convert input.jpg output.jpg")

    assert process.kill_called is True
    assert process.communicate_calls == 2
    assert stdout == b"done"
    assert stderr == b"killed"


def test_run_timeout_log_includes_operation_and_truncated_command(
    monkeypatch, caplog
) -> None:
    process = _TimeoutProcess()
    long_command = "convert " + ("verylongsegment " * 40)

    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: process)
    caplog.set_level("ERROR", logger="tcm")

    interface = ImageMagickInterface(timeout=7)
    interface.run(long_command, operation="card_render")

    error_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
    assert any("operation=card_render" in message for message in error_messages)
    assert any("timeout=7s" in message for message in error_messages)
    assert any('command="' in message and "..." in message for message in error_messages)


def test_run_warns_once_after_repeated_timeouts(monkeypatch, caplog) -> None:
    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: _TimeoutProcess())
    caplog.set_level("WARNING", logger="tcm")

    interface = ImageMagickInterface(timeout=1)
    for _ in range(4):
        interface.run("convert input output", operation="card_render")

    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert len([m for m in warning_messages if "imagemagick.timeout" in m]) == 1


def test_get_text_dimensions_uses_text_metrics_operation(monkeypatch) -> None:
    interface = ImageMagickInterface()
    operations = []

    def _fake_run_get_output(self, command, *, operation=None, **kwargs):  # pylint: disable=unused-argument
        operations.append(operation)
        return "Metrics: width: 10 height: 20 ascent: 12 descent: -4"

    monkeypatch.setattr(ImageMagickInterface, "run_get_output", _fake_run_get_output)

    dimensions = interface.get_text_dimensions(['label:"Test"'])

    assert dimensions.width == 10
    assert dimensions.height == 8
    assert operations == ["text_metrics"]


def test_run_retries_after_timeout_then_succeeds(monkeypatch, caplog) -> None:
    processes = [_TimeoutProcess(), _SuccessProcess()]

    def _fake_popen(*args, **kwargs):  # pylint: disable=unused-argument
        return processes.pop(0)

    monkeypatch.setattr("modules.ImageMagickInterface.Popen", _fake_popen)
    caplog.set_level("DEBUG", logger="tcm")

    interface = ImageMagickInterface(timeout=1)
    stdout, stderr = interface.run(
        "convert input output",
        operation="svg_convert",
        retries=1,
        retry_backoff_seconds=0,
        retry_on_timeout=True,
    )

    assert stdout == b"success"
    assert stderr == b""
    retry_logs = [record.message for record in caplog.records if "Retrying ImageMagick command" in record.message]
    assert len(retry_logs) == 1


def test_run_timeout_exhaustion_after_max_retries(monkeypatch, caplog) -> None:
    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: _TimeoutProcess())
    caplog.set_level("ERROR", logger="tcm")

    interface = ImageMagickInterface(timeout=1)
    interface.run(
        "convert input output",
        operation="svg_convert",
        retries=2,
        retry_backoff_seconds=0,
        retry_on_timeout=True,
    )

    error_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
    assert len([m for m in error_messages if "timed out" in m]) == 1
    assert any("retries exhausted" in message and "attempts=3" in message for message in error_messages)


def test_run_does_not_retry_when_disabled(monkeypatch, caplog) -> None:
    process = _TimeoutProcess()
    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: process)
    caplog.set_level("DEBUG", logger="tcm")

    interface = ImageMagickInterface(timeout=1)
    interface.run(
        "convert input output",
        operation="svg_convert",
        retries=2,
        retry_backoff_seconds=0,
        retry_on_timeout=False,
    )

    retry_logs = [record.message for record in caplog.records if "Retrying ImageMagick command" in record.message]
    assert process.communicate_calls == 2
    assert retry_logs == []


def test_run_aggregates_timeout_logs_and_emits_summary_after_window(monkeypatch, caplog) -> None:
    caplog.set_level("INFO", logger="tcm")

    processes = [_TimeoutProcess(), _TimeoutProcess(), _SuccessProcess()]

    def _fake_popen(*args, **kwargs):  # pylint: disable=unused-argument
        return processes.pop(0)

    monkeypatch.setattr("modules.ImageMagickInterface.Popen", _fake_popen)

    time_values = iter((100.0, 101.0, 110.0, 111.0, 170.0))
    monkeypatch.setattr("modules.ImageMagickInterface.monotonic", lambda: next(time_values))

    interface = ImageMagickInterface(timeout=9)
    interface.run("convert input output", operation="text_metrics")
    interface.run("convert input output", operation="text_metrics")
    interface.run("convert different output", operation="other_operation")

    timeout_errors = [
        record.message
        for record in caplog.records
        if record.levelname == "ERROR" and "ImageMagick command timed out" in record.message
    ]
    summaries = [
        record.message
        for record in caplog.records
        if record.levelname in {"INFO", "WARNING"} and "ImageMagick timeouts:" in record.message
    ]

    assert len(timeout_errors) == 1
    assert "operation=text_metrics" in timeout_errors[0]
    assert len(summaries) == 1
    assert "2 occurrences for text_metrics" in summaries[0]
    assert "timeout=9s" in summaries[0]
