"""The desktop launcher (opticore/desktop.py): when the program ends, where it finds the user interface, the browser
choice. The packaged program itself is checked by its --self-test in the release workflow."""

from __future__ import annotations

import socket

import pytest

from opticore import desktop
from opticore.desktop import BYE_GRACE_S, FIRST_CONTACT_S, SILENCE_S, Lifetime


def test_lifetime_waits_for_the_first_window_then_follows_the_heartbeat():
    life = Lifetime()
    t0 = life.started
    assert not life.should_stop(t0 + FIRST_CONTACT_S - 1)  # the window may take a while to open
    assert life.should_stop(t0 + FIRST_CONTACT_S + 1)  # no window ever came
    life.last_beat = t0 + 5
    assert not life.should_stop(t0 + 5 + SILENCE_S - 1)
    assert life.should_stop(t0 + 5 + SILENCE_S + 1)  # the window went away without saying goodbye


def test_goodbye_ends_the_program_unless_a_reload_beats_again():
    life = Lifetime()
    life.beat()
    life.bye()
    assert not life.should_stop(life.bye_at + BYE_GRACE_S - 1)
    assert life.should_stop(life.bye_at + BYE_GRACE_S + 1)
    life.beat()  # a reload: the new page beats within the grace period
    assert life.bye_at is None and not life.should_stop(life.last_beat + BYE_GRACE_S + 1)


def test_ui_dir_prefers_the_environment_and_needs_an_index(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTICORE_UI_DIR", str(tmp_path))
    found = desktop.ui_dir()
    assert found != tmp_path  # no index.html there yet
    (tmp_path / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
    assert desktop.ui_dir() == tmp_path


def test_browser_none_opens_nothing(monkeypatch):
    calls = []
    monkeypatch.setenv("OPTICORE_BROWSER", "none")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: calls.append(url))
    desktop.open_window("http://127.0.0.1:1/")
    assert calls == []


def test_port_check_sees_a_listening_socket():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert not desktop._port_free(port)
        assert not desktop._ping(port, timeout=0.5)  # something listens, but it is not OptiCore Studio


@pytest.mark.parametrize("argv", [["--help"]])
def test_command_line_help(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        desktop.main(argv)
    assert exc.value.code == 0 and "--self-test" in capsys.readouterr().out
