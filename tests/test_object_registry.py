from objectRegistry import ObjectRegistry


def test_ids_stay_valid_through_later_searches():
    registry = ObjectRegistry(maxObjects=10)
    [chat_list] = registry.add(["Chat list"])
    rows = registry.add(["row 1", "row 2"])
    assert rows == [chat_list + 1, chat_list + 2]
    # Searching inside the list must not take the list's own id away.
    assert registry.get(chat_list) == "Chat list"
    assert registry.last == [(rows[0], "row 1"), (rows[1], "row 2")]


def test_old_ids_are_forgotten_not_reused():
    registry = ObjectRegistry(maxObjects=2)
    first = registry.add(["a", "b"])
    newer = registry.add(["c"])
    assert registry.get(first[0]) is None
    assert registry.isForgotten(first[0])
    assert registry.get(first[1]) == "b"
    assert newer == [3]
    assert not registry.isForgotten(99)
    assert registry.get(99) is None


def test_an_empty_search_leaves_no_last_results():
    registry = ObjectRegistry(maxObjects=5)
    registry.add(["a"])
    assert registry.add([]) == []
    assert registry.last == []
