import asyncio
import subprocess

from bot.control import BTN_LOGS, BTN_START, BTN_STATUS, BTN_STOP, ControlPanel, tail_lines
from bot.heartbeat import Heartbeat
from bot.http import TransportError
from bot.notifier import TelegramNotifier
from bot.watchdog import Supervisor
from tests.helpers import FakeTransport

CHAT = 42


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ notifier


def test_notifier_without_credentials_does_nothing():
    transport = FakeTransport()
    notifier = TelegramNotifier(None, None, transport)
    assert run(notifier.send("hi")) is False
    assert transport.requests == []


def test_notifier_sends_to_the_configured_chat():
    transport = FakeTransport()
    transport.queue(200, {"ok": True, "result": {}})
    notifier = TelegramNotifier("123:TOKEN", CHAT, transport)

    assert run(notifier.send("hello")) is True
    assert transport.requests[0]["url"].endswith("/bot123:TOKEN/sendMessage")
    assert b'"chat_id": 42' in transport.requests[0]["data"]


def test_notifier_never_raises_on_failure():
    transport = FakeTransport()
    transport.queue_error(TransportError("ClientConnectionError"))
    transport.queue(500, {"ok": False, "description": "oops"})
    notifier = TelegramNotifier("123:TOKEN", CHAT, transport)

    assert run(notifier.send("a")) is False
    assert run(notifier.send("b")) is False


# --------------------------------------------------------------------- panel


class FakeRunner:
    def __init__(self):
        self.running = False

    def start(self):
        was = self.running
        self.running = True
        return not was

    async def stop(self):
        was = self.running
        self.running = False
        return was

    def status_text(self):
        return "status-text"


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, text, keyboard=None):
        self.sent.append((text, keyboard))
        return True


def message(text, chat=CHAT):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}


def make_panel(tmp_path):
    runner, notifier = FakeRunner(), RecordingNotifier()
    panel = ControlPanel(notifier, runner, chat_id=CHAT, log_file=tmp_path / "bot.log")
    return panel, runner, notifier


def test_buttons_drive_the_runner(tmp_path):
    panel, runner, notifier = make_panel(tmp_path)

    assert run(panel.handle_update(message(BTN_START))) == "start"
    assert runner.running is True
    assert run(panel.handle_update(message(BTN_STATUS))) == "status"
    assert notifier.sent[-1][0] == "status-text"
    assert run(panel.handle_update(message(BTN_STOP))) == "stop"
    assert runner.running is False
    assert run(panel.handle_update(message("/start"))) == "menu"
    assert notifier.sent[-1][1] is not None  # keyboard attached


def test_messages_from_other_chats_are_ignored(tmp_path):
    panel, runner, notifier = make_panel(tmp_path)
    assert run(panel.handle_update(message(BTN_START, chat=999))) is None
    assert runner.running is False
    assert notifier.sent == []


def test_logs_button_returns_the_tail_of_the_log(tmp_path):
    panel, _, notifier = make_panel(tmp_path)
    (tmp_path / "bot.log").write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")

    run(panel.handle_update(message(BTN_LOGS)))

    text = notifier.sent[-1][0]
    assert "line 99" in text and "line 84" not in text  # only the last 15 lines


def test_tail_lines_handles_missing_and_empty_files(tmp_path):
    assert "пуст" in tail_lines(tmp_path / "missing.log")
    (tmp_path / "empty.log").write_text("", encoding="utf-8")
    assert "пуст" in tail_lines(tmp_path / "empty.log")


# ------------------------------------------------------------------ watchdog


class FakeProc:
    def __init__(self):
        self.code = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class Env:
    """Fake clock + spawn so supervisor tests run instantly."""

    def __init__(self):
        self.now = 0.0
        self.procs = []
        self.sleeps = []
        self.age = 0.0

    def spawn(self, command):
        proc = FakeProc()
        self.procs.append(proc)
        return proc

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def supervisor(self, **kwargs):
        return Supervisor(
            ["bot"],
            lambda: self.age,
            spawn=self.spawn,
            clock=self.clock,
            sleep=self.sleep,
            **kwargs,
        )


def test_supervisor_starts_then_leaves_a_healthy_bot_alone():
    env = Env()
    sup = env.supervisor()
    assert sup.step() == "started"
    env.now = 200
    env.age = 3
    assert sup.step() == "ok"
    assert len(env.procs) == 1


def test_supervisor_restarts_a_crashed_bot_with_growing_delay():
    env = Env()
    sup = env.supervisor(restart_delay=5)
    sup.step()
    env.procs[-1].code = 1
    assert sup.step() == "crashed"
    env.procs[-1].code = 1
    assert sup.step() == "crashed"
    assert env.sleeps == [5, 10]  # exponential backoff
    assert len(env.procs) == 3


def test_supervisor_kills_a_hung_bot_with_a_stale_heartbeat():
    env = Env()
    sup = env.supervisor(grace=60, stale_after=120)
    sup.step()
    env.now = 100
    env.age = 500  # no heartbeat for a long time
    assert sup.step() == "stale"
    assert env.procs[0].terminated is True
    assert len(env.procs) == 2


def test_supervisor_gives_a_new_process_time_before_judging_it():
    env = Env()
    sup = env.supervisor(grace=60)
    sup.step()
    env.now = 10
    env.age = None  # no heartbeat yet, but still inside the grace period
    assert sup.step() == "ok"


def test_supervisor_resets_backoff_after_a_long_healthy_run():
    env = Env()
    sup = env.supervisor(restart_delay=5, healthy_after=300)
    sup.step()
    env.procs[-1].code = 1
    sup.step()  # delay 5 -> next is 10
    env.now += 1000  # ran for a long time
    env.procs[-1].code = 1
    sup.step()
    assert env.sleeps[-1] == 5  # reset, not 10


# ----------------------------------------------------------------- heartbeat


def test_heartbeat_age(tmp_path):
    clock = {"now": 1000.0}
    beat = Heartbeat(tmp_path / "state" / "hb.txt", clock=lambda: clock["now"])
    assert beat.age() is None
    beat.beat()
    clock["now"] = 1030.0
    assert beat.age() == 30.0
