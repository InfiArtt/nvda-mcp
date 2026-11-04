from webIds import domNodeIdFromRuntimeId


def test_dom_node_id_is_the_last_part_of_a_chromium_runtime_id():
    # As read from the Claude app (Electron) with IAccessibleEx.GetRuntimeId.
    assert domNodeIdFromRuntimeId([3, 7, 4, 3921]) == 3921
    assert domNodeIdFromRuntimeId((3, 7, 4, 1)) == 1


def test_other_runtime_ids_give_none():
    assert domNodeIdFromRuntimeId(None) is None
    assert domNodeIdFromRuntimeId([]) is None
    assert domNodeIdFromRuntimeId([42, 7, 4, 3921]) is None
    assert domNodeIdFromRuntimeId([3, 7, 4]) is None
    assert domNodeIdFromRuntimeId([3, 7, 4, 0]) is None
