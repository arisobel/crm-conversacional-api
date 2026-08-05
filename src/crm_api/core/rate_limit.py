"""Limitador de tentativas em janela deslizante.

Estado em processo. Ele contém pulverização de credenciais contra uma única
instância, mas **não** substitui o bloqueio por conta em `users.locked_until`,
que é o controle que atravessa réplicas e reinícios. Se o serviço passar a rodar
com mais de uma réplica, este limitador precisa migrar para um armazenamento
compartilhado.
"""

import time
from collections import defaultdict, deque

_MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        threshold = now - self._window_seconds
        while hits and hits[0] <= threshold:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def allow(self, key: str) -> bool:
        """Registra uma tentativa e diz se ela pode prosseguir."""
        now = time.monotonic()
        if len(self._hits) > _MAX_TRACKED_KEYS:
            self._collect(now)

        hits = self._prune(key, now)
        if len(hits) >= self._max_attempts:
            return False
        hits.append(now)
        self._hits[key] = hits
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _collect(self, now: float) -> None:
        threshold = now - self._window_seconds
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and hits[0] <= threshold:
                hits.popleft()
            if not hits:
                del self._hits[key]
