from __future__ import annotations

import logging
import re
import sys

log = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    text = re.sub(r"<a href=\"([^\"]+)\">([^<]*)</a>", r"\2 \1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


class Notifier:
    name = "base"

    def send(self, text: str, subject: str = "m2kira") -> bool:  # pragma: no cover
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    name = "console"

    def send(self, text: str, subject: str = "m2kira") -> bool:
        out = strip_html(text)
        try:
            print(f"\n===== {subject} =====\n{out}\n", flush=True)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((f"\n===== {subject} =====\n{out}\n").encode("utf-8", "replace"))
        return True


class MultiNotifier(Notifier):
    name = "multi"

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def send(self, text: str, subject: str = "m2kira") -> bool:
        ok = False
        for n in self.notifiers:
            try:
                ok = n.send(text, subject) or ok
            except Exception as exc:
                log.error("bildirim (%s) başarısız: %s", n.name, exc)
        return ok
