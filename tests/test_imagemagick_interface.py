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


def test_run_kills_process_and_collects_output_after_timeout(monkeypatch) -> None:
    process = _TimeoutProcess()

    monkeypatch.setattr("modules.ImageMagickInterface.Popen", lambda *args, **kwargs: process)

    interface = ImageMagickInterface(timeout=1)
    stdout, stderr = interface.run("convert input.jpg output.jpg")

    assert process.kill_called is True
    assert process.communicate_calls == 2
    assert stdout == b"done"
    assert stderr == b"killed"
