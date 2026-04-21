from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CACHE_VERSION = "v1"


def cache_root() -> Path:
    return Path.home() / ".cache" / "logwright"


def cache_key(
    *,
    repo_id: str,
    sha: str,
    provider: str,
    model: str,
    style_signature: str,
) -> str:
    payload = f"{CACHE_VERSION}|{repo_id}|{sha}|{provider}|{model}|{style_signature}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheStore:
    def __init__(self) -> None:
        self.root = cache_root()

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / CACHE_VERSION / namespace / f"{key}.json"

    def load(self, namespace: str, key: str) -> dict[str, Any] | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, namespace: str, key: str, payload: dict[str, Any]) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
