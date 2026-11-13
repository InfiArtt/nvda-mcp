import builtins
import importlib
import sys

import accessCrypto
import pytest
from accessCrypto import AccessError, Handshake, newCode, normalizeCode, roomId


def pair(sharer_code, helper_code=None):
    sharer = Handshake(sharer_code, "sharer")
    helper = Handshake(helper_code or sharer_code, "helper")
    return sharer.finish(helper.publicKey), helper.finish(sharer.publicKey)


def test_codes_are_readable_and_accept_any_spacing_or_case():
    code = newCode()
    assert len(code) == 24 and code.count("-") == 4
    assert set(code.replace("-", "")) <= set(accessCrypto.CODE_ALPHABET)
    assert normalizeCode(code.lower().replace("-", " ")) == code.replace("-", "")
    for bad in ("", "K7Q4-9XMC", code + "A", code.replace(code[0], "0")):
        with pytest.raises(AccessError):
            normalizeCode(bad)


def test_room_id_is_stable_but_reveals_nothing_of_the_code():
    code = newCode()
    assert roomId(code) == roomId(code.lower()) and len(roomId(code)) == 32
    assert roomId(code) != roomId(newCode())
    assert code.replace("-", "") not in roomId(code)


def test_both_sides_talk_in_both_directions():
    sharer, helper = pair(newCode())
    assert sharer.fingerprint == helper.fingerprint
    assert helper.open(sharer.seal(b"focus: Send button")) == b"focus: Send button"
    assert sharer.open(helper.seal(b'{"method": "getFocus"}')) == b'{"method": "getFocus"}'
    assert helper.open(sharer.seal(b"")) == b""


def test_a_different_code_cannot_read_anything():
    sharer, helper = pair(newCode(), newCode())
    with pytest.raises(AccessError, match="wrong code"):
        helper.open(sharer.seal(b"secret screen"))


def test_ciphertext_does_not_contain_the_text():
    sharer, _helper = pair(newCode())
    assert b"secret screen" not in sharer.seal(b"secret screen")


def test_replayed_reordered_and_changed_messages_are_refused():
    sharer, helper = pair(newCode())
    first, second = sharer.seal(b"one"), sharer.seal(b"two")
    with pytest.raises(AccessError, match="reordered"):
        helper.open(second)
    assert helper.open(first) == b"one"
    with pytest.raises(AccessError, match="replayed"):
        helper.open(first)
    changed = bytearray(second)
    changed[-1] ^= 1
    with pytest.raises(AccessError, match="changed on the way"):
        helper.open(bytes(changed))


def test_a_side_cannot_decrypt_its_own_messages_reflected_back():
    sharer, _helper = pair(newCode())
    with pytest.raises(AccessError):
        sharer.open(sharer.seal(b"echo"))


def test_malformed_and_low_order_keys_are_refused():
    handshake = Handshake(newCode(), "helper")
    with pytest.raises(AccessError, match="malformed"):
        handshake.finish(b"short")
    with pytest.raises(AccessError, match="unusable"):
        Handshake(newCode(), "helper").finish(bytes(32))


def test_every_session_has_fresh_keys():
    code = newCode()
    first_sharer, _ = pair(code)
    second_sharer, second_helper = pair(code)
    with pytest.raises(AccessError):
        second_helper.open(first_sharer.seal(b"old session"))
    assert second_helper.open(second_sharer.seal(b"new")) == b"new"


def test_works_with_only_the_parts_of_cryptography_nvda_ships(monkeypatch):
    # NVDA ships X25519 but not the aead module; the Rust core has AES-GCM.
    real_import = builtins.__import__

    def without_aead(name, *args, **kwargs):
        if name == "cryptography.hazmat.primitives.ciphers.aead":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_aead)
    monkeypatch.delitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", raising=False)
    reloaded = importlib.reload(accessCrypto)
    try:
        assert "_rust" in reloaded.AESGCM.__module__ or "bindings" in repr(reloaded.AESGCM)
        sharer = reloaded.Handshake("K7Q4-9XMC-4TRW-PH3N-AD6F", "sharer")
        helper = reloaded.Handshake("K7Q4-9XMC-4TRW-PH3N-AD6F", "helper")
        assert helper.finish(sharer.publicKey).open(sharer.finish(helper.publicKey).seal(b"ok")) == b"ok"
    finally:
        monkeypatch.undo()
        importlib.reload(accessCrypto)


def test_hkdf_matches_rfc_5869_test_case_1():
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    expected = "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    assert accessCrypto.hkdf(ikm, salt, info, 42).hex() == expected
