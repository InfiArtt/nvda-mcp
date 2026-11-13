"""MCP Access end-to-end encryption: a session between the computer being helped and the helper's server.

The relay in between only forwards bytes. It learns a room id derived from the access code, never the code,
and cannot read or change what the two sides send. Each session agrees on fresh keys (X25519), so a code that
leaks after a session cannot decrypt it. Both sides mix the code into the keys, so a relay that does not know
the code cannot stand in the middle: the first message fails to decrypt and the session stops.

Only the parts of the cryptography package that NVDA ships are used: X25519, and AES in GCM mode.
HKDF is written here with hmac, since NVDA does not ship that module.
The add-on has the same code as accessCrypto.py in NVDA style; tests check that the two agree.
"""

import hashlib
import hmac
import os
import struct

# The Rust core is an extension module, not a package, so its parts are attributes.
try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
except ImportError:  # pragma: no cover - only when NVDA leaves the public module out
    from cryptography.hazmat.bindings._rust import openssl as _rustOpenssl

    X25519PrivateKey = _rustOpenssl.x25519.X25519PrivateKey
    X25519PublicKey = _rustOpenssl.x25519.X25519PublicKey

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # NVDA ships the Rust core but not this module.
    from cryptography.hazmat.bindings._rust import openssl as _rustOpenssl

    AESGCM = _rustOpenssl.aead.AESGCM

PROTOCOL = b"NVDA MCP Access 1"
# Letters that are hard to confuse when read aloud or typed: no 0/O, 1/I/L, 2/Z, 5/S, 8/B.
CODE_ALPHABET = "34679ACDEFGHJKMNPQRTUVWXY"
CODE_GROUPS = 5
CODE_GROUP_LENGTH = 4
# 20 characters of 25 letters: about 93 bits, far beyond guessing even offline.
CODE_LENGTH = CODE_GROUPS * CODE_GROUP_LENGTH
PUBLIC_KEY_LENGTH = 32
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
_NONCE_PREFIX = {"sharer": b"\x00\x00\x00\x01", "helper": b"\x00\x00\x00\x02"}


class AccessError(Exception):
    """The code is malformed, or a message was forged, replayed, reordered or too large."""


def _randomLetter() -> str:
    """A letter of CODE_ALPHABET, each equally likely.

    NVDA before 2026 does not ship the secrets module, so this draws from os.urandom, which it uses underneath,
    and skips bytes past the largest multiple of the alphabet's size so no letter comes up more often.
    """
    limit = 256 - 256 % len(CODE_ALPHABET)
    while True:
        byte = os.urandom(1)[0]
        if byte < limit:
            return CODE_ALPHABET[byte % len(CODE_ALPHABET)]


def newCode() -> str:
    """A fresh access code such as K7Q4-9XMC-4TRW-PH3N-AD6F."""
    letters = "".join(_randomLetter() for _index in range(CODE_LENGTH))
    return "-".join(letters[i : i + CODE_GROUP_LENGTH] for i in range(0, CODE_LENGTH, CODE_GROUP_LENGTH))


def normalizeCode(code: str) -> str:
    """The code's letters in upper case without spaces or dashes, as typed or pasted.

    :raises AccessError: When it is not a whole access code.
    """
    letters = "".join(char for char in code.upper() if char not in " -\t\r\n")
    if len(letters) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in letters):
        raise AccessError(
            f"An access code has {CODE_LENGTH} letters and digits, such as K7Q4-9XMC-4TRW-PH3N-AD6F."
        )
    return letters


def hkdf(keyMaterial: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """HKDF with SHA-256 (RFC 5869)."""
    prk = hmac.new(salt or bytes(32), keyMaterial, hashlib.sha256).digest()
    output = b""
    block = b""
    counter = 1
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def roomId(code: str) -> str:
    """What the relay matches the two sides by. It cannot be turned back into the code."""
    return hkdf(normalizeCode(code).encode("ascii"), PROTOCOL, b"room", 16).hex()


class Handshake:
    """One side's half of agreeing on session keys.

    :param role: "sharer" for the computer being helped, "helper" for the helper's server.
    """

    def __init__(self, code: str, role: str) -> None:
        if role not in _NONCE_PREFIX:
            raise ValueError(f"Unknown role {role!r}")
        self.role = role
        self._secret = hkdf(normalizeCode(code).encode("ascii"), PROTOCOL, b"secret", 32)
        self._private = X25519PrivateKey.generate()
        self.publicKey = self._private.public_key().public_bytes_raw()

    def finish(self, peerPublicKey: bytes) -> "Session":
        """Combine the peer's public key with ours and the code into this session's keys."""
        if len(peerPublicKey) != PUBLIC_KEY_LENGTH:
            raise AccessError("The other side sent a malformed key.")
        try:
            shared = self._private.exchange(X25519PublicKey.from_public_bytes(peerPublicKey))
        except ValueError:
            # A low-order point gives an all-zero secret; X25519 implementations refuse it.
            raise AccessError("The other side sent an unusable key.")
        sharerKey, helperKey = (
            (self.publicKey, peerPublicKey) if self.role == "sharer" else (peerPublicKey, self.publicKey)
        )
        transcript = hashlib.sha256(PROTOCOL + sharerKey + helperKey).digest()
        keys = hkdf(shared, self._secret, b"keys" + transcript, 64)
        self._secret = b""
        return Session(self.role, keys[:32], keys[32:], transcript)


class Session:
    """Encrypts what one side sends and decrypts what it receives, each message once and in order."""

    def __init__(self, role: str, sharerToHelper: bytes, helperToSharer: bytes, transcript: bytes) -> None:
        other = "helper" if role == "sharer" else "sharer"
        sendKey, receiveKey = (
            (sharerToHelper, helperToSharer) if role == "sharer" else (helperToSharer, sharerToHelper)
        )
        self._send = AESGCM(sendKey)
        self._receive = AESGCM(receiveKey)
        self._sendPrefix = _NONCE_PREFIX[role]
        self._receivePrefix = _NONCE_PREFIX[other]
        self._sendCounter = 0
        self._receiveCounter = 0
        self._associated = transcript
        #: Both sides compute the same value; show its start to compare by ear if in doubt.
        self.fingerprint = hashlib.sha256(b"fingerprint" + transcript).hexdigest()[:8].upper()

    def seal(self, plaintext: bytes) -> bytes:
        if len(plaintext) > MAX_MESSAGE_BYTES:
            raise AccessError("The message is too large to send.")
        counter = self._sendCounter
        self._sendCounter += 1
        nonce = self._sendPrefix + struct.pack(">Q", counter)
        return struct.pack(">Q", counter) + self._send.encrypt(nonce, plaintext, self._associated)

    def open(self, message: bytes) -> bytes:
        if len(message) > MAX_MESSAGE_BYTES + 24:
            raise AccessError("The message is too large.")
        if len(message) < 8 + 16:
            raise AccessError("The message is too short.")
        (counter,) = struct.unpack(">Q", message[:8])
        if counter != self._receiveCounter:
            raise AccessError("A message was replayed, dropped or reordered.")
        nonce = self._receivePrefix + message[:8]
        try:
            plaintext = self._receive.decrypt(nonce, message[8:], self._associated)
        except Exception:  # noqa: BLE001 - cryptography raises InvalidTag
            raise AccessError("A message could not be decrypted: wrong code, or it was changed on the way.")
        self._receiveCounter += 1
        return plaintext
