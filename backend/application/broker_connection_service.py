from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BrokerConnectionView:
    connection_id: str
    user_id: str
    broker_type: str
    login_masked: str
    server: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "user_id": self.user_id,
            "broker_type": self.broker_type,
            "login_masked": self.login_masked,
            "server": self.server,
            "status": self.status,
        }


class BrokerCredentialVault:
    """
    Minimal authenticated-encryption-like vault for Day 117 tests using only
    Python stdlib. Production deployment should bind this interface to a real
    secret manager/KMS. Plaintext credentials are never persisted.
    """

    def __init__(self, master_key: bytes) -> None:
        if not isinstance(master_key, bytes) or len(master_key) < 32:
            raise ValueError("credential_master_key_too_short")
        self._key = hashlib.sha256(master_key).digest()

    def seal(self, plaintext: str) -> str:
        nonce = os.urandom(16)
        raw = plaintext.encode("utf-8")
        stream = self._stream(nonce, len(raw))
        cipher = bytes(a ^ b for a, b in zip(raw, stream))
        tag = hmac.new(self._key, nonce + cipher, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")

    def open(self, token: str) -> str:
        try:
            blob = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("credential_ciphertext_invalid") from exc
        if len(blob) < 48:
            raise RuntimeError("credential_ciphertext_invalid")
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        expected = hmac.new(self._key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise RuntimeError("credential_integrity_failed")
        stream = self._stream(nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")

    def _stream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(
                hmac.new(
                    self._key,
                    nonce + counter.to_bytes(8, "big"),
                    hashlib.sha256,
                ).digest()
            )
            counter += 1
        return bytes(out[:length])


class BrokerConnectionService:
    """
    User-scoped broker connection configuration.

    Backend stores encrypted credentials and delegates connection checks to an
    injected Bot Core gateway. It never imports MetaTrader5 or calls MT5 APIs.
    """

    def __init__(self, *, vault: BrokerCredentialVault, bot_core: Any) -> None:
        self.vault = vault
        self.bot_core = bot_core
        self._records: dict[str, dict[str, Any]] = {}

    def create_mt5(
        self,
        *,
        user_id: str,
        login: str,
        password: str,
        server: str,
    ) -> BrokerConnectionView:
        user_id = str(user_id).strip()
        login = str(login).strip()
        password = str(password)
        server = str(server).strip()

        if not user_id or not login or not password or not server:
            raise ValueError("mt5_credentials_incomplete")

        connection_id = "mt5_" + hashlib.sha256(
            f"{user_id}:{login}:{server}".encode("utf-8")
        ).hexdigest()[:24]

        secret = self.vault.seal(json.dumps({
            "login": login,
            "password": password,
            "server": server,
        }))

        self._records[connection_id] = {
            "connection_id": connection_id,
            "user_id": user_id,
            "broker_type": "MT5",
            "login_masked": self._mask(login),
            "server": server,
            "status": "UNVERIFIED",
            "secret": secret,
        }
        return self.get(user_id=user_id, connection_id=connection_id)

    def test_connection(
        self,
        *,
        user_id: str,
        connection_id: str,
    ) -> BrokerConnectionView:
        record = self._owned(user_id, connection_id)
        credentials = json.loads(self.vault.open(record["secret"]))

        result = self.bot_core.test_broker_connection(
            user_id=user_id,
            broker_type="MT5",
            credentials=credentials,
        )
        record["status"] = "VERIFIED" if bool(result.get("ok")) else "FAILED"
        return self._view(record)

    def get(self, *, user_id: str, connection_id: str) -> BrokerConnectionView:
        return self._view(self._owned(user_id, connection_id))

    def stored_record_for_test(self, connection_id: str) -> dict[str, Any]:
        return dict(self._records[connection_id])

    def _owned(self, user_id: str, connection_id: str) -> dict[str, Any]:
        record = self._records.get(connection_id)
        if record is None or record["user_id"] != user_id:
            raise PermissionError("broker_connection_not_found")
        return record

    @staticmethod
    def _view(record: dict[str, Any]) -> BrokerConnectionView:
        return BrokerConnectionView(
            connection_id=record["connection_id"],
            user_id=record["user_id"],
            broker_type=record["broker_type"],
            login_masked=record["login_masked"],
            server=record["server"],
            status=record["status"],
        )

    @staticmethod
    def _mask(login: str) -> str:
        if len(login) <= 4:
            return "*" * len(login)
        return "*" * (len(login) - 4) + login[-4:]
