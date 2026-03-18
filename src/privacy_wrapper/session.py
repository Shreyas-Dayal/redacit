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

import threading
from dataclasses import dataclass, field


@dataclass
class PrivacySession:
    """
    Accumulates the placeholder → original mapping across multiple chat turns.

    Existing entries are never overwritten — if the same placeholder appears
    in two consecutive calls the first value is preserved, ensuring consistency.

    Thread-safe: all mutations are protected by an internal lock so a single
    session can safely be shared across concurrent requests.
    """

    mapping: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, new_mapping: dict[str, str]) -> None:
        """Merge new_mapping into the session; existing keys are not changed."""
        with self._lock:
            for placeholder, original in new_mapping.items():
                self.mapping.setdefault(placeholder, original)

    def clear(self) -> None:
        """Reset the session mapping (call between independent conversations)."""
        with self._lock:
            self.mapping.clear()

    def __len__(self) -> int:
        return len(self.mapping)

    def __repr__(self) -> str:
        return f"PrivacySession({len(self)} entries)"
