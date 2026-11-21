"""Ein kleiner Ringpuffer für VRC-Link-Vorgänge — nur für die Live-Ansicht der Debug-Konsole.

Alles nur im Speicher: die letzten paar hundert Einträge, nichts wird auf die Platte
geschrieben, nichts überlebt einen Neustart. Je Eintrag eine laufende Nummer, die Uhrzeit,
die Server-ID und ein kurzer Text. Die Konsole liest daraus, immer nach Server gefiltert -
ein Server-Admin sieht nur das Geschehen seines eigenen Servers, nie das eines anderen auf
derselben Installation.

Protokollieren darf den eigentlichen Vorgang nie stören: jeder Schreibzugriff ist in sich
abgefangen, ein Fehler hier bleibt folgenlos für die Verknüpfung, die gerade läuft.
"""
from __future__ import annotations

import threading
import time
from collections import deque

_MAX = 400
_puffer: "deque[dict]" = deque(maxlen=_MAX)
_lock = threading.Lock()
_zaehler = 0


def vrc_log(guild_id, text: str) -> None:
    """Einen VRC-Link-Vorgang vermerken. Billig, fehlertolerant, ohne guild_id landet er in
    keinem Server-Log (und ist damit für die Konsole unsichtbar)."""
    global _zaehler
    try:
        if guild_id is None or str(guild_id) == "":
            return
        with _lock:
            _zaehler += 1
            _puffer.append({
                "nr": _zaehler,
                "zeit": time.strftime("%H:%M:%S"),
                "guild": str(guild_id),
                "text": str(text)[:300],
            })
    except Exception:
        pass


def seit(guild_id, nach: int = 0, grenze: int = 60) -> list:
    """Die Einträge dieses Servers mit laufender Nummer größer als `nach`.

    Für das Polling der Live-Ansicht: beim ersten Abruf (nach=0) kommen die letzten paar als
    Kontext, danach nur noch das Neue.
    """
    gid = str(guild_id)
    try:
        with _lock:
            treffer = [e for e in _puffer if e["guild"] == gid and e["nr"] > nach]
        return treffer[-grenze:]
    except Exception:
        return []
