"""Per-visitor game sessions and public-hosting guards for the web server.

Default behaviour (WARGAME_PUBLIC unset) keeps today's API; the only change is
that each browser cookie gets its own game dict instead of one shared global.
"""

from __future__ import annotations

import contextvars
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import MutableMapping
from http.cookies import SimpleCookie
from pathlib import Path

log = logging.getLogger("wargame.web")

COOKIE_NAME = "wg_session"
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


def new_game_state() -> dict:
    """Empty game dict. This is the shape every endpoint reads and writes."""
    return {
        "conn": None,
        "spec": None,
        "trace_id": None,
        "turn_log": [],
        "action_histories": {},
        "human_actor": None,
        "ai_actors": [],
        "mode": None,
        "db_path": None,
        "gm_session": None,
    }


def public_mode() -> bool:
    return os.environ.get("WARGAME_PUBLIC", "") == "1"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1, got {value}")
    return value


def max_sessions() -> int:
    return _int_env("WARGAME_MAX_SESSIONS", 40)


def session_ttl_seconds() -> float:
    return _int_env("WARGAME_SESSION_TTL_MIN", 120) * 60.0


def public_max_turns() -> int:
    return _int_env("WARGAME_PUBLIC_MAX_TURNS", 8)


def discard_game(state: dict, delete_db: bool) -> None:
    """Close a game's sqlite connection and (optionally) delete its db file."""
    conn = state.get("conn")
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            log.exception("closing game connection failed")
    db_path = state.get("db_path")
    if delete_db and db_path:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except FileNotFoundError:
                pass
            except OSError:
                log.exception("removing game db file failed")
    state["conn"] = None


class SessionStore:
    """Server-side sessions: id -> game dict, with max count and idle TTL.

    Only in public mode are db files deleted on eviction, because only there
    is the path server-chosen; otherwise a client-chosen db_path would be
    deleted.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict] = OrderedDict()  # sid -> {"game", "seen"}

    def __len__(self) -> int:
        return len(self._items)

    def _drop(self, sid: str) -> None:
        item = self._items.pop(sid)
        discard_game(item["game"], delete_db=public_mode())

    def _sweep_locked(self) -> None:
        cutoff = self._clock() - session_ttl_seconds()
        for sid in [s for s, it in self._items.items() if it["seen"] < cutoff]:
            self._drop(sid)

    def sweep(self) -> None:
        with self._lock:
            self._sweep_locked()

    def get(self, sid: str | None) -> tuple[str, dict, bool]:
        """Return (sid, game dict, created). Unknown or expired ids get a new session."""
        with self._lock:
            self._sweep_locked()
            if sid is not None and sid in self._items:
                item = self._items[sid]
                item["seen"] = self._clock()
                self._items.move_to_end(sid)
                return sid, item["game"], False
            limit = max_sessions()
            while len(self._items) >= limit:
                # Prefer evicting a visitor who never started a game, then the idlest.
                victim = next(
                    (s for s, it in self._items.items() if it["game"]["conn"] is None),
                    next(iter(self._items)),
                )
                self._drop(victim)
            new_sid = secrets.token_urlsafe(24)
            game = new_game_state()
            self._items[new_sid] = {"game": game, "seen": self._clock()}
            return new_sid, game, True

    def latest_game(self) -> dict | None:
        """Most recently used session's game, without touching its idle timer."""
        with self._lock:
            return next(reversed(self._items.values()))["game"] if self._items else None

    def close_all(self) -> None:
        with self._lock:
            for sid in list(self._items):
                self._drop(sid)


STORE = SessionStore()
_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("wg_game", default=None)
_fallback = new_game_state()  # used outside any HTTP request (tests, scripts)


class GameProxy(MutableMapping):
    """Dict-like view of the current visitor's game; same keys as new_game_state()."""

    def _d(self) -> dict:
        cur = _current.get()
        if cur is not None:
            return cur
        # Outside an HTTP request (tests, scripts): the most recently used
        # session, so `game` still shows what the last request did.
        latest = STORE.latest_game()
        return latest if latest is not None else _fallback

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __delitem__(self, k):
        del self._d()[k]

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())


game = GameProxy()


def _cookie_from_scope(scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"cookie":
            c = SimpleCookie()
            try:
                c.load(value.decode("latin-1"))
            except Exception:
                return None
            if COOKIE_NAME in c:
                return c[COOKIE_NAME].value
    return None


def _is_https(scope) -> bool:
    hdrs = {k.decode("latin-1").lower(): v.decode("latin-1").lower() for k, v in scope["headers"]}
    if scope.get("scheme") == "https":
        return True
    if hdrs.get("x-forwarded-proto", "").split(",")[0].strip() == "https":
        return True
    return '"https"' in hdrs.get("cf-visitor", "")


class SessionMiddleware:
    """Pure ASGI middleware: binds the visitor's game dict for the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sid, state, created = STORE.get(_cookie_from_scope(scope))
        secure = _is_https(scope)
        token = _current.set(state)

        started = False

        async def send_wrapper(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            if created and message["type"] == "http.response.start":
                cookie = f"{COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Lax"
                if secure:
                    cookie += "; Secure"
                message["headers"] = list(message.get("headers", [])) + [
                    (b"set-cookie", cookie.encode())
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if not public_mode() or started:
                raise
            # Public mode: log the real error here, send the visitor a plain sentence.
            log.exception("unhandled error serving %s", scope.get("path"))
            await send_wrapper({
                "type": "http.response.start", "status": 500,
                "headers": [(b"content-type", b"application/json")],
            })
            await send_wrapper({
                "type": "http.response.body",
                "body": b'{"detail":"Something went wrong on the server. Please try again."}',
            })
        finally:
            _current.reset(token)


def resolve_bundled_scenario(name: str) -> str:
    """Map a client-supplied scenario name to a bundled scenario file.

    Only bare names of files that sit directly in scenarios/ are accepted (with
    or without .yaml, or the UI's `scenarios/<name>.yaml`). The match is by
    lookup in the directory listing, never by joining client text into a path,
    and the resolved file must still be inside scenarios/ (no symlinks out).
    Raises ValueError with a plain-sentence message on refusal.
    """
    refusal = ValueError("That scenario is not available on this server.")
    if not isinstance(name, str) or not name or "\x00" in name:
        raise refusal
    if name.startswith("scenarios/"):
        name = name[len("scenarios/"):]
    if "/" in name or "\\" in name or name.startswith("."):
        raise refusal
    stem = name[:-5] if name.endswith(".yaml") else name
    root = SCENARIOS_DIR.resolve()
    available = {p.stem: p for p in SCENARIOS_DIR.glob("*.yaml")}
    match = available.get(stem)
    if match is None:
        raise refusal
    resolved = match.resolve()
    if resolved.parent != root:
        raise refusal
    return str(resolved)
