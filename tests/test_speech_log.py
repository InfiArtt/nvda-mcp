import threading
import time

from speechLog import SpeechLog, sequenceToText


class FakeCommand:
    """Stands in for an NVDA speech command such as a pitch change."""


def test_sequence_to_text_drops_commands_and_normalises_whitespace():
    assert sequenceToText(["OK", FakeCommand(), " button ", "\n"]) == "OK button"


def test_since_returns_newer_entries_and_respects_limit():
    log = SpeechLog(maxEntries=10)
    for text in ("one", "two", "three"):
        log.add(text)
    assert [entry.text for entry in log.since(1)] == ["two", "three"]
    assert [entry.text for entry in log.since(0, limit=1)] == ["three"]
    assert log.lastId == 3


def test_empty_text_is_ignored_and_oldest_entries_are_dropped():
    log = SpeechLog(maxEntries=2)
    log.add("")
    for text in ("a", "b", "c"):
        log.add(text)
    assert [entry.id for entry in log.since(0)] == [2, 3]


def test_resize_keeps_newest_entries():
    log = SpeechLog(maxEntries=5)
    for text in "abcde":
        log.add(text)
    log.resize(2)
    assert [entry.text for entry in log.since(0)] == ["d", "e"]


def test_wait_for_quiet_returns_after_speech_settles():
    log = SpeechLog(maxEntries=10)

    def speak():
        for text in ("Save", "button"):
            time.sleep(0.05)
            log.add(text)

    threading.Thread(target=speak).start()
    started = time.monotonic()
    entries = log.waitForQuiet(afterId=0, settleSeconds=0.2, timeoutSeconds=5)
    assert [entry.text for entry in entries] == ["Save", "button"]
    assert time.monotonic() - started < 2


def test_wait_for_quiet_times_out_when_nothing_is_spoken():
    log = SpeechLog(maxEntries=10)
    started = time.monotonic()
    assert log.waitForQuiet(afterId=0, settleSeconds=0.1, timeoutSeconds=0.3) == []
    assert 0.25 < time.monotonic() - started < 2


def test_wait_for_counts_speech_already_recorded_after_the_id():
    log = SpeechLog(maxEntries=10)
    log.add("Downloads folder")
    log.add("Reply from Ana")
    match = log.waitFor(0, lambda text: "reply" in text.casefold(), timeoutSeconds=0.1)
    assert match is not None and match.id == 2


def test_wait_for_wakes_on_new_matching_speech_and_skips_others():
    log = SpeechLog(maxEntries=10)

    def speakLater():
        time.sleep(0.05)
        log.add("typing")
        log.add("Message sent")

    threading.Thread(target=speakLater).start()
    match = log.waitFor(log.lastId, lambda text: "sent" in text, timeoutSeconds=2)
    assert match is not None and match.text == "Message sent"


def test_wait_for_returns_none_after_timeout():
    log = SpeechLog(maxEntries=10)
    log.add("nothing relevant")
    started = time.monotonic()
    assert log.waitFor(0, lambda text: "reply" in text, timeoutSeconds=0.1) is None
    assert time.monotonic() - started < 1
