"""
Multi-turn conversation session for consistent deanonymization.

Without a session, each chat() call has an independent placeholder mapping —
a placeholder introduced in turn 1 cannot be resolved in turn 5.

With a PrivacySession, the mapping accumulates across turns so any placeholder
created earlier in the conversation remains resolvable throughout.

Usage:
    session = PrivacySession()
    client  = PrivacyClient(session=session)

    client.chat("My name is Alice.")    # <PERSON_0> → Alice stored in session
    client.chat("What did I say?")      # LLM sees <PERSON_0>; Alice restored
    session.clear()                     # reset between independent conversations
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


@dataclass
class PrivacySession:
    """
    Accumulates the placeholder → original mapping across multiple chat turns.

    Existing entries are never overwritten — if the same placeholder appears
    in two consecutive calls the first value is preserved, ensuring consistency.

    Thread-safe: all mutations are protected by an internal lock so a single
    session can safely be shared across concurrent requests.

    Args:
        max_size: Maximum number of placeholder entries to keep. When exceeded,
                  the oldest entries are evicted (LRU). ``None`` (default) means
                  no limit.
    """

    mapping: dict[str, str] = field(default_factory=OrderedDict)
    max_size: int | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, new_mapping: dict[str, str]) -> None:
        """Merge new_mapping into the session; existing keys are not changed."""
        with self._lock:
            for placeholder, original in new_mapping.items():
                if placeholder not in self.mapping:
                    self.mapping[placeholder] = original
                else:
                    # Move existing key to end (most recently used)
                    self.mapping.move_to_end(placeholder)  # type: ignore[union-attr]

            if self.max_size is not None:
                while len(self.mapping) > self.max_size:
                    evicted_key, _ = self.mapping.popitem(last=False)  # type: ignore[call-arg]
                    _log.debug("Session evicted oldest entry: %s", evicted_key)

    def clear(self) -> None:
        """Reset the session mapping (call between independent conversations)."""
        with self._lock:
            self.mapping.clear()

    def __len__(self) -> int:
        return len(self.mapping)

    def __repr__(self) -> str:
        limit = f", max_size={self.max_size}" if self.max_size else ""
        return f"PrivacySession({len(self)} entries{limit})"
