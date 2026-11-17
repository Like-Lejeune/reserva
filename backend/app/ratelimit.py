"""Limite de tentatives, contre le forçage de mots de passe et l'abus des envois de codes.

Compteurs en mémoire, par fenêtre glissante : suffisant tant que l'application tourne sur un
seul processus. Avec plusieurs processus ou serveurs, déplacer ces compteurs dans Redis.

Derrière Nginx, lancer uvicorn avec --proxy-headers pour que l'adresse vue soit celle du
visiteur et non celle du proxy.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    """Pour les tests."""
    _hits.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def _recent(key: str, window_s: int) -> deque[float]:
    q = _hits[key]
    cutoff = time.monotonic() - window_s
    while q and q[0] < cutoff:
        q.popleft()
    return q


def hit(key: str, limit: int, window_s: int) -> None:
    """Compte une tentative ; lève 429 si la limite de la fenêtre est dépassée."""
    q = _recent(key, window_s)
    if len(q) >= limit:
        wait = max(1, int(q[0] + window_s - time.monotonic()) // 60 + 1)
        raise HTTPException(429, f"Trop de tentatives. Réessayez dans {wait} minute(s).")
    q.append(time.monotonic())


def blocked(key: str, limit: int, window_s: int) -> bool:
    """Vrai si la limite est déjà atteinte, sans compter de tentative."""
    return len(_recent(key, window_s)) >= limit


def record(key: str) -> None:
    """Compte un échec (mot de passe faux) sans vérifier la limite."""
    _hits[key].append(time.monotonic())


def clear(key: str) -> None:
    _hits.pop(key, None)
