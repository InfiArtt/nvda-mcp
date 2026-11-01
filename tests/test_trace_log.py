from traceLog import TraceLog, attributeNearbySpeech


def test_entries_have_ids_kinds_and_can_be_filtered():
    log = TraceLog(maxEntries=10)
    assert log.add("beep", hz=440, lengthMs=50) == 1
    log.add("braille", text="OK btn")
    log.add("beep", hz=880, lengthMs=50)
    assert log.lastId == 3
    assert [entry["id"] for entry in log.since(1)] == [2, 3]
    assert [entry["hz"] for entry in log.since(0, kinds=["beep"])] == [440, 880]
    assert [entry["id"] for entry in log.since(0, limit=1)] == [3]
    assert log.since(0)[0]["kind"] == "beep"


def test_oldest_entries_are_dropped():
    log = TraceLog(maxEntries=2)
    for _ in range(3):
        log.add("speechCanceled")
    assert [entry["id"] for entry in log.since(0)] == [2, 3]


def _event(eventId, name, timestamp, before, after, spoken=None):
    event = {
        "id": eventId,
        "event": name,
        "timestamp": timestamp,
        "speechBeforeId": before,
        "speechAfterId": after,
    }
    if spoken:
        event["spoken"] = spoken
    return event


def _attribute(events, utterances):
    return attributeNearbySpeech(events, utterances, afterSeconds=1.5, beforeSeconds=0.5)


def test_speech_after_an_event_goes_to_the_latest_event_before_it():
    events = [_event(1, "nameChange", 10.0, 0, 0), _event(2, "valueChange", 10.5, 0, 0)]
    utterances = [
        {"id": 1, "timestamp": 10.7, "text": "Saved"},
        {"id": 2, "timestamp": 10.8, "text": "3 items"},
    ]
    result = _attribute(events, utterances)
    assert "spokenNearby" not in result[0]
    assert result[1]["spokenNearby"] == "Saved / 3 items"
    assert "spokenNearby" not in events[1], "the log's own entries must not change"


def test_speech_goes_to_a_live_region_rather_than_a_newer_name_change():
    events = [_event(1, "liveRegionChange", 10.0, 0, 0), _event(2, "nameChange", 10.1, 0, 0)]
    result = _attribute(events, [{"id": 1, "timestamp": 10.3, "text": "Using nvda"}])
    assert result[0]["spokenNearby"] == "Using nvda"
    assert "spokenNearby" not in result[1]


def test_live_region_speech_just_before_its_event_goes_to_it():
    # Browsers' live regions can be spoken a moment before NVDA handles their event.
    events = [_event(1, "nameChange", 10.0, 0, 0), _event(2, "liveRegionChange", 13.07, 1, 1)]
    result = _attribute(events, [{"id": 1, "timestamp": 13.05, "text": "Using nvda"}])
    assert result[1]["spokenNearby"] == "Using nvda"
    assert "spokenNearby" not in result[0]


def test_speech_during_an_event_or_long_after_is_not_attributed():
    events = [_event(1, "nameChange", 10.0, 0, 0), _event(2, "gainFocus", 11.0, 0, 1, spoken="OK button")]
    utterances = [
        {"id": 1, "timestamp": 10.9, "text": "OK button"},
        {"id": 2, "timestamp": 14.0, "text": "clock"},
    ]
    result = _attribute(events, utterances)
    assert all("spokenNearby" not in event for event in result)
