from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class UserRuntimeScope:
    """
    Stable namespace for all user-owned runtime resources.

    No secret credentials are stored here. The scope only creates deterministic
    isolation keys used by backend/runtime orchestration.
    """
    user_id: str

    def __post_init__(self) -> None:
        if not str(self.user_id).strip():
            raise ValueError("user_id_required")

    @property
    def namespace(self) -> str:
        digest = hashlib.sha256(
            self.user_id.strip().encode("utf-8")
        ).hexdigest()[:20]
        return f"user_scope_{digest}"

    def strategy_key(self, strategy_id: str) -> str:
        return self._key("strategy", strategy_id)

    def backtest_key(self, backtest_id: str) -> str:
        return self._key("backtest", backtest_id)

    def bot_key(self, bot_instance_id: str) -> str:
        return self._key("bot", bot_instance_id)

    def runtime_key(self, bot_instance_id: str) -> str:
        return self._key("runtime", bot_instance_id)

    def broker_config_key(self, bot_instance_id: str) -> str:
        return self._key("broker_config", bot_instance_id)

    def _key(self, kind: str, resource_id: str) -> str:
        resource_id = str(resource_id).strip()
        if not resource_id:
            raise ValueError(f"{kind}_id_required")
        return f"{self.namespace}:{kind}:{resource_id}"
