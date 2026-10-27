"""Client for the COBA "pedNet" school portal (portail scolaire).

There is no public API.  The client replays what a browser does, exactly like
the n8n workflow it was derived from:

  1. GET  ``login.coba``            -> session cookie + dynamic component id,
                                       ``__cpss`` token, ``data-param-refresh``.
  2. POST ``compo.coba?<param>``    -> credentials; the reply carries ``Item2``.
  3. GET  ``index.coba?<Item2>``    -> dashboard with ``lnk*`` menu links whose
                                       ``data-action`` holds the next ``param``.
  4. GET  ``compo.coba?<param>``    -> Travaux (grades), Courriels (messages),
                                       Horaire (schedule day).

Parsing is defensive: a section that cannot be read yields ``None`` values, it
never breaks the whole update.  Everything that depends on the portal HTML lives
in this module.
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import random
import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit

import aiohttp
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
}

_LETTER_GRADES = {"A": 95.0, "B": 85.0, "C": 75.0}
_PCT_RE = re.compile(r"\(([\d.,]+)\s*%\)")
_UNREAD_COUNT_RE = re.compile(r"\((\d+)\)")
_MONTHS = r"(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c)"
_DATE_RES = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}[:h]\d{2})?"),
    re.compile(
        rf"\d{{1,2}}\s+{_MONTHS}[a-zéûè]*\.?(?:\s+\d{{4}})?(?:\s+(?:à\s+)?\d{{1,2}}[:h]\d{{2}})?",
        re.I,
    ),
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}[:h]\d{2})?"),
    re.compile(r"(?:aujourd.hui|hier)(?:\s+(?:à\s+)?\d{1,2}[:h]\d{2})?", re.I),
)
_JOUR_RE = re.compile(r"\bjour\s*(?:du\s+cycle\s*)?[:#n°]*\s*(\d{1,2})\b", re.I)
_UNREAD_MARKER_RE = re.compile(
    r"non[-_ ]?lu|unread|nouveau|\bnew\b|ferm[ée]e?|closed", re.I
)
_BOLD_RE = re.compile(r"<(?:b|strong)\b|font-weight:\s*(?:bold|[6-9]00)", re.I)


class CobaError(Exception):
    """Base error for the COBA client."""


class CobaConnectionError(CobaError):
    """The portal could not be reached."""


class CobaAuthError(CobaError):
    """Authentication with the portal failed."""


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]*>", "", fragment)
    text = htmllib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(text: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(stripped.lower().split())


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _pct(text: str) -> float | None:
    """Percentage from ``85 / 100 (85,0 %)`` or a letter grade."""
    if "(" in text:
        match = _PCT_RE.search(text)
        return _to_float(match.group(1)) if match else None
    return _LETTER_GRADES.get(text.strip())


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


class CobaClient:
    """Session-based scraper for a pedNet portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        username: str,
        password: str,
        debug: bool = False,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._debug = debug
        parts = urlsplit(url.strip())
        if not parts.netloc:
            parts = urlsplit(f"https://{url.strip()}")
        origin = f"{parts.scheme or 'https'}://{parts.netloc}"
        idx = parts.path.lower().find("/pednet/")
        prefix = parts.path[: idx + len("/pednet")] if idx >= 0 else "/pedNet"
        self._base = f"{origin}{prefix}/"

    @property
    def login_url(self) -> str:
        return f"{self._base}login.coba"

    def _compo(self, param: str) -> str:
        return f"{self._base}compo.coba?{param}"

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        referer: str | None = None,
    ) -> str:
        headers = dict(_HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                return await resp.text()
        except aiohttp.ClientError as err:
            raise CobaConnectionError(str(err)) from err
        except TimeoutError as err:
            raise CobaConnectionError("timeout") from err

    # ------------------------------------------------------------------ #
    # Login
    # ------------------------------------------------------------------ #
    async def login(self) -> str:
        """Log in and return the dashboard HTML."""
        # Always start from a clean cookie jar: one fresh session per poll.
        self._session.cookie_jar.clear()

        html = await self._request("GET", self.login_url)
        id_match = re.search(r"id=['\"]([A-Z0-9]+)__cpss['\"]", html)
        cpss_match = re.search(
            r"id=['\"][A-Z0-9]+__cpss['\"]\s+value=['\"]([^'\"]+)['\"]", html
        )
        param_match = re.search(r"data-param-refresh=['\"]([^'\"]+)['\"]", html)
        if not (id_match and cpss_match and param_match):
            raise CobaConnectionError("login_page_unrecognised")

        cid = id_match.group(1)
        post_url = self._compo(param_match.group(1))
        reply = await self._request(
            "POST",
            post_url,
            referer=post_url,
            data={
                f"{cid}_txtCodeUsager": self._username,
                f"{cid}_txtMotDePasse": self._password,
                f"{cid}__cpss": cpss_match.group(1),
                "__postcomponent": f"{cid}_btnConnecter",
                "__isautopb": "",
                "__addparam": "",
                "__id": cid,
                "__ts": str(random.random()),
                "__rootpage": cid,
            },
        )

        item2 = self._extract_item2(reply)
        if not item2:
            raise CobaAuthError("invalid_auth")

        dashboard = await self._request("GET", f"{self._base}index.coba?{item2}")
        if "txtMotDePasse" in dashboard:
            # We were bounced back to the login form.
            raise CobaAuthError("invalid_auth")
        return dashboard

    @staticmethod
    def _extract_item2(reply: str) -> str | None:
        try:
            payload = json.loads(reply)
            if isinstance(payload, dict) and payload.get("Item2"):
                return str(payload["Item2"])
        except ValueError:
            pass
        match = re.search(r"[\"']?Item2[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", reply)
        return match.group(1) if match else None

    # ------------------------------------------------------------------ #
    # Navigation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _link_param(soup: BeautifulSoup, *ids: str) -> str | None:
        """``param`` stored in the ``data-action`` of the first matching link."""
        for link_id in ids:
            node = soup.find(id=link_id)
            if node is None:
                continue
            holder = node if node.has_attr("data-action") else node.find(
                attrs={"data-action": True}
            )
            if holder is None:
                continue
            try:
                return json.loads(unquote(holder["data-action"])).get("param")
            except (ValueError, AttributeError):
                continue
        return None

    @staticmethod
    def _horaire_param(soup: BeautifulSoup) -> str | None:
        for node in soup.find_all(id=re.compile(r"^lnk", re.I)):
            if "horaire" in _norm(node.get_text(" ")) or "horaire" in node["id"].lower():
                try:
                    holder = node if node.has_attr("data-action") else node.find(
                        attrs={"data-action": True}
                    )
                    return json.loads(unquote(holder["data-action"])).get("param")
                except (ValueError, AttributeError, TypeError):
                    continue
        return None

    async def _section(self, param: str | None, name: str) -> str | None:
        if not param:
            return None
        try:
            html = await self._request("GET", self._compo(param))
        except CobaConnectionError as err:
            _LOGGER.warning("COBA: section %s unavailable: %s", name, err)
            return None
        if self._debug:
            _LOGGER.debug("COBA %s HTML (%d chars):\n%s", name, len(html), html)
        return html

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #
    async def async_get_data(self) -> dict[str, Any]:
        dashboard = await self.login()
        if self._debug:
            _LOGGER.debug("COBA dashboard HTML:\n%s", dashboard)
        soup = BeautifulSoup(dashboard, "html.parser")

        travaux = await self._section(
            self._link_param(soup, "lnkTRAVAUX"), "travaux"
        )
        courriels = await self._section(
            self._link_param(soup, "lnkCOURRIELS"), "courriels"
        )
        horaire = await self._section(self._horaire_param(soup), "horaire")

        return {
            "notes": self._parse_notes(travaux) if travaux else None,
            "messages": self._parse_messages(courriels) if courriels else None,
            "jour": self._parse_jour(dashboard, horaire),
        }

    # ------------------------------------------------------------------ #
    # Grades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_notes(html: str) -> dict[str, Any]:
        sections = html.split("<h4 class='ctitre'>")[1:]
        eleve_all: list[float] = []
        classe_all: list[float] = []
        courses: dict[str, dict[str, Any]] = {}

        for section in sections:
            nom = _clean(section.split("</h4>")[0])
            eleve: list[float] = []
            classe: list[float] = []
            total = 0
            for row in section.split("<tr class='grid3__row '")[1:]:
                cols = row.split("<td")

                def col(index: int) -> str:
                    if index >= len(cols) or ">" not in cols[index]:
                        return ""
                    return _clean(cols[index].split(">", 1)[1])

                if not col(3):
                    continue
                total += 1
                mine = _pct(col(7))
                avg = _pct(col(8))
                if mine is not None:
                    eleve.append(mine)
                if avg is not None:
                    classe.append(avg)

            eleve_all += eleve
            classe_all += classe
            if nom:
                courses[nom] = {
                    "moyenne_eleve": _mean(eleve),
                    "moyenne_classe": _mean(classe),
                    "evaluations_notees": len(eleve),
                    "evaluations": total,
                }

        return {
            "moyenne_eleve": _mean(eleve_all),
            "moyenne_classe": _mean(classe_all),
            "cours": courses,
        }

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_messages(html: str) -> dict[str, Any]:
        folder = None
        folder_match = re.search(
            r"<h3 class='courriels_menu ctitre'>(.*?)</h3>", html, re.S
        )
        if folder_match:
            folder = _clean(folder_match.group(1))

        messages: list[dict[str, Any]] = []
        explicit: list[bool] = []
        bold: list[bool] = []

        for row in html.split("<tr class='grid3__row '")[1:]:
            sender = re.search(r"<span class='libelle'>(.*?)</span>", row, re.S)
            subject = re.search(r"font-size:\s*12px[^>]*>(.*?)</span>", row, re.S)
            preview = re.search(r"word-break: break-all;[^>]*>(.*?)</span>", row, re.S)
            if not (sender or subject):
                continue

            row_end = row.split("</tr>")[0]
            head = row_end.split(">", 1)[0]
            tags = " ".join(re.findall(r"<img[^>]*>", row_end))
            explicit.append(bool(_UNREAD_MARKER_RE.search(head + " " + tags)))
            bold.append(bool(_BOLD_RE.search(row_end)))

            date = None
            for cell in row_end.split("<td")[1:]:
                text = _clean(cell.split(">", 1)[1]) if ">" in cell else ""
                for date_re in _DATE_RES:
                    found = date_re.search(text)
                    if found:
                        date = found.group(0).strip()
                        break
                if date:
                    break

            messages.append(
                {
                    "expediteur": _clean(sender.group(1)) if sender else None,
                    "sujet": _clean(subject.group(1)) if subject else None,
                    "apercu": _clean(preview.group(1)) if preview else None,
                    "date": date,
                }
            )

        # Unread detection: explicit markers first, else bold rows (only when
        # bold actually distinguishes rows), else the "(N)" shown on the folder.
        if any(explicit):
            flags = explicit
        elif any(bold) and not all(bold):
            flags = bold
        else:
            flags = [False] * len(messages)
        unread = sum(flags)
        if not unread and folder:
            count = _UNREAD_COUNT_RE.search(folder)
            if count:
                unread = int(count.group(1))
        for message, flag in zip(messages, flags):
            message["non_lu"] = flag

        return {
            "dossier": folder,
            "total": len(messages),
            "non_lus": unread,
            "dernier": messages[0] if messages else None,
            "messages": messages[:10],
        }

    # ------------------------------------------------------------------ #
    # Schedule day ("jour 6")
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_jour(dashboard: str, horaire: str | None) -> int | None:
        """Cycle day: look on the dashboard first, then on the schedule page."""
        for html in (dashboard, horaire):
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            # Prefer a highlighted / "current" element when several days show.
            for node in soup.find_all(
                class_=re.compile(r"courant|today|actif|active|selected|aujourd", re.I)
            ):
                match = _JOUR_RE.search(node.get_text(" ", strip=True))
                if match:
                    return int(match.group(1))
            match = _JOUR_RE.search(soup.get_text(" ", strip=True))
            if match:
                return int(match.group(1))
        return None
