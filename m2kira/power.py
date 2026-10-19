"""Windows: tarama sürerken bilgisayarın uykuya dönmesini engeller.

Görev Zamanlayıcı görevi uyku halindeki bilgisayarı (uyandırma zamanlayıcısıyla, yalnız şarjdayken) uyandırır;
tarama bitene kadar sistemin yeniden uykuya geçmemesi için SetThreadExecutionState kullanılır. Ekranı açmaz.
Süreç bitince istek kendiliğinden kalkar. Diğer platformlarda hiçbir şey yapmaz.
"""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake() -> Iterator[bool]:
    if sys.platform != "win32":
        yield False
        return
    ok = False
    try:
        import ctypes
        ok = bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    except Exception as exc:  # noqa: BLE001
        log.debug("SetThreadExecutionState kullanılamadı: %s", exc)
    try:
        yield ok
    finally:
        if ok:
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:  # noqa: BLE001
                pass
