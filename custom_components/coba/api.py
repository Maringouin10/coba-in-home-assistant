"""Client for the COBA / ColNET student web portal.

There is no public/official API for COBA (the collegial management software by
Berger-Levrault, portals ColNET / PedNET).  This client therefore drives the
regular web portal the same way a browser would:

  1. GET  ``<base>/colnet/login.asp`` and auto-detect the login <form>.
  2. POST the credentials (carrying any hidden fields the form contains).
  3. Discover the section links (Messagerie / Résultats / Horaire / Suivi) from
     the post-login menu by matching link text — this keeps it working across
     the small layout differences between cégeps.
  4. Parse each section heuristically.

Everything that depends on the portal HTML lives in this single module so it can
be tuned easily against a real instance.  Parsing is intentionally defensive:
it never raises on unexpected markup, it just returns whatever it could extract
(plus the raw rows in the attributes) so the result can be refined later.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .const import SECTION_KEYWORDS, UPCOMING_COURSES

_LOGGER = logging.getLogger(__name__)

# The portal sits behind a WAF that rejects non-browser clients, so we present a
# realistic browser signature on every request.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
}

_TIME_RE = re.compile(r"\b(\d{1,2})\s*[:hH]\s*(\d{2})\b")
_ERROR_HINTS = (
    "invalide",
    "incorrect",
    "erreur",
    "mot de passe",
    "echec",
    "echoue",
    "refuse",
)


class CobaError(Exception):
    """Base error for the COBA client."""


class CobaConnectionError(CobaError):
    """The portal could not be reached."""


class CobaAuthError(CobaError):
    """Authentication with the portal failed (or the session expired)."""


def _norm(text: str | None) -> str:
    """Lowercase, accent-stripped, whitespace-collapsed text for matching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def _cell_text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _truncate(value: str, length: int = 255) -> str:
    value = value or ""
    return value if len(value) <= length else value[: length - 1] + "…"


class CobaClient:
    """Minimal session-based scraper for a ColNET portal."""

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
        self._base = self._normalize_base(url)
        self._authenticated = False
        self._menu_html: str | None = None
        self._menu_url: str | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def base_url(self) -> str:
        return self._base

    @property
    def login_url(self) -> str:
        return urljoin(self._base, "login.asp")

    async def login(self) -> None:
        """Authenticate against the portal, storing the session cookie."""
        html = await self._request("GET", self.login_url)
        soup = BeautifulSoup(html, "html.parser")
        form = self._find_login_form(soup)
        if form is None:
            # No password field on the page: either the layout is unknown or we
            # are somehow already authenticated.
            raise CobaAuthError("login_form_not_found")

        action_url = urljoin(self.login_url, form.get("action") or "login.asp")
        payload, user_field, pwd_field = self._build_login_payload(form)
        if not pwd_field:
            raise CobaAuthError("password_field_not_found")
        payload[pwd_field] = self._password
        if user_field:
            payload[user_field] = self._username

        result = await self._request(
            "POST", action_url, data=payload, referer=self.login_url
        )
        if self._looks_like_login(result):
            raise CobaAuthError("invalid_auth")

        self._authenticated = True
        self._menu_html = result
        self._menu_url = action_url
        if self._debug:
            _LOGGER.debug("COBA login OK, landing page %s chars", len(result))

    async def async_get_data(self) -> dict[str, Any]:
        """Return the parsed portal data, (re)authenticating as needed."""
        if not self._authenticated:
            await self.login()
        try:
            return await self._collect()
        except CobaAuthError:
            # Session probably expired — log in again once and retry.
            _LOGGER.debug("COBA session expired, re-authenticating")
            self._authenticated = False
            await self.login()
            return await self._collect()

    # ------------------------------------------------------------------ #
    # HTTP helpers
    # ------------------------------------------------------------------ #
    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: dict | None = None,
        referer: str | None = None,
    ) -> str:
        headers = dict(_DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with self._session.request(
                method, url, data=data, headers=headers, timeout=timeout
            ) as resp:
                if resp.status in (401, 403):
                    # 403 here, once logged in, usually means the session was
                    # dropped rather than a hard block.
                    raise CobaAuthError(f"http_{resp.status}")
                resp.raise_for_status()
                return await resp.text()
        except CobaError:
            raise
        except aiohttp.ClientError as err:
            raise CobaConnectionError(str(err)) from err

    # ------------------------------------------------------------------ #
    # Login parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _find_login_form(soup: BeautifulSoup):
        forms = soup.find_all("form")
        for form in forms:
            if form.find("input", attrs={"type": re.compile("password", re.I)}):
                return form
        return forms[0] if forms else None

    @staticmethod
    def _build_login_payload(form) -> tuple[dict[str, str], str | None, str | None]:
        """Collect all form inputs, returning (payload, user_field, pwd_field)."""
        payload: dict[str, str] = {}
        pwd_field: str | None = None
        text_candidates: list[str] = []

        for node in form.find_all(("input", "select", "textarea")):
            name = node.get("name")
            if not name:
                continue
            itype = (node.get("type") or "text").lower()
            if itype == "password":
                pwd_field = name
                payload[name] = ""
            elif itype in ("submit", "button", "image", "reset"):
                # ASP back-ends sometimes require the submit button's value.
                payload.setdefault(name, node.get("value") or "")
            elif itype in ("checkbox", "radio"):
                if node.has_attr("checked"):
                    payload[name] = node.get("value") or "on"
            else:
                payload[name] = node.get("value") or ""
                if itype in ("text", "email", "tel", "number", ""):
                    text_candidates.append(name)

        user_field = CobaClient._pick_user_field(text_candidates)
        return payload, user_field, pwd_field

    @staticmethod
    def _pick_user_field(candidates: list[str]) -> str | None:
        if not candidates:
            return None
        preferred = ("usager", "user", "code", "login", "courriel", "email", "da", "id")
        for token in preferred:
            for name in candidates:
                if token in _norm(name):
                    return name
        return candidates[0]

    @staticmethod
    def _looks_like_login(html: str) -> bool:
        """Heuristic: a page still showing a password box means login failed."""
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("input", attrs={"type": re.compile("password", re.I)}):
            return True
        return False

    # ------------------------------------------------------------------ #
    # Section discovery + collection
    # ------------------------------------------------------------------ #
    async def _collect(self) -> dict[str, Any]:
        links = await self._discover_sections()
        if self._debug:
            _LOGGER.debug("COBA discovered sections: %s", links)

        return {
            "base_url": self._base,
            "sections": links,
            "messages": await self._safe(self._parse_messages, links.get("messages")),
            "notes": await self._safe(self._parse_notes, links.get("notes")),
            "cours": await self._safe(self._parse_cours, links.get("cours")),
            "suivi": await self._safe(self._parse_suivi, links.get("suivi")),
        }

    async def _safe(
        self, parser: Callable[[BeautifulSoup, str], dict], url: str | None
    ) -> dict[str, Any]:
        """Fetch + parse a section, never raising on parse problems."""
        if not url:
            return {"available": False, "source_url": None}
        try:
            html = await self._request("GET", url, referer=self._menu_url)
        except CobaAuthError:
            raise
        except CobaError as err:
            _LOGGER.warning("COBA: could not fetch %s: %s", url, err)
            return {"available": False, "source_url": url, "error": str(err)}

        if self._debug:
            _LOGGER.debug("COBA %s -> %s chars", url, len(html))
        try:
            soup = BeautifulSoup(html, "html.parser")
            result = parser(soup, url)
            result.setdefault("available", True)
            result["source_url"] = url
            return result
        except Exception:  # noqa: BLE001 - parsing must never break the update
            _LOGGER.exception("COBA: failed to parse %s", url)
            return {"available": False, "source_url": url, "error": "parse_error"}

    async def _discover_sections(self) -> dict[str, str]:
        """Find section URLs by scanning the menu (following framesets once)."""
        if self._menu_html is None:
            self._menu_html = await self._request("GET", self.login_url)
            self._menu_url = self.login_url

        anchors = await self._gather_anchors(self._menu_html, self._menu_url, depth=2)

        found: dict[str, str] = {}
        for text, href in anchors:
            ntext = _norm(text)
            if not ntext:
                continue
            for section, tokens in SECTION_KEYWORDS.items():
                if section in found:
                    continue
                if any(_norm(tok) in ntext for tok in tokens):
                    found[section] = href
        return found

    async def _gather_anchors(
        self, html: str, page_url: str | None, depth: int
    ) -> list[tuple[str, str]]:
        """Collect (text, absolute_href) anchors, following <frame>/<iframe>."""
        base = page_url or self._base
        soup = BeautifulSoup(html, "html.parser")
        anchors: list[tuple[str, str]] = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
                continue
            anchors.append((_cell_text(a) or a.get("title", ""), urljoin(base, href)))

        if depth > 0:
            for frame in soup.find_all(("frame", "iframe")):
                src = frame.get("src")
                if not src:
                    continue
                frame_url = urljoin(base, src)
                try:
                    frame_html = await self._request(
                        "GET", frame_url, referer=base
                    )
                except CobaError:
                    continue
                anchors.extend(
                    await self._gather_anchors(frame_html, frame_url, depth - 1)
                )
        return anchors

    # ------------------------------------------------------------------ #
    # Section parsers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _table_rows(soup: BeautifulSoup) -> list[list[str]]:
        """Return the rows (lists of cell strings) of the richest table."""
        best: list[list[str]] = []
        for table in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells = [_cell_text(c) for c in tr.find_all(("td", "th"))]
                if any(c.strip() for c in cells):
                    rows.append(cells)
            # Prefer the table that actually looks like a data grid.
            if len(rows) > len(best):
                best = rows
        return best

    @staticmethod
    def _split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        if not rows:
            return [], []
        header = [_norm(c) for c in rows[0]]
        looks_like_header = any(
            tok in " ".join(header)
            for tok in ("date", "objet", "expediteur", "cours", "note", "type", "heure")
        )
        if looks_like_header:
            return header, rows[1:]
        return [], rows

    @staticmethod
    def _col(header: list[str], data_row: list[str], *tokens: str) -> str | None:
        for idx, name in enumerate(header):
            if any(tok in name for tok in tokens) and idx < len(data_row):
                value = data_row[idx].strip()
                if value:
                    return value
        return None

    def _parse_messages(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        header, rows = self._split_header(self._table_rows(soup))
        messages: list[dict[str, Any]] = []
        for row in rows:
            unread_flag = any(
                _norm(c) in ("nouveau", "non lu", "non-lu") for c in row
            )
            item = {
                "expediteur": self._col(header, row, "expediteur", "de", "auteur"),
                "objet": self._col(header, row, "objet", "sujet", "titre"),
                "date": self._col(header, row, "date", "recu", "reçu"),
                "non_lu": unread_flag,
            }
            if not any(item[k] for k in ("expediteur", "objet", "date")):
                # No mapped columns: keep the raw cells so it's still usable.
                item["raw"] = [c for c in row if c.strip()]
            messages.append(item)

        last = messages[0] if messages else None
        unread = sum(1 for m in messages if m.get("non_lu"))
        return {
            "count": len(messages),
            "unread": unread,
            "messages": messages[:20],
            "last": last,
        }

    def _parse_notes(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        header, rows = self._split_header(self._table_rows(soup))
        notes: list[dict[str, Any]] = []
        for row in rows:
            note = self._col(header, row, "note", "resultat", "résultat", "%")
            item = {
                "cours": self._col(header, row, "cours", "matiere", "discipline"),
                "evaluation": self._col(
                    header, row, "evaluation", "examen", "travail", "description"
                ),
                "note": note,
                "ponderation": self._col(header, row, "ponderation", "valeur", "sur"),
                "date": self._col(header, row, "date"),
            }
            if not any(item[k] for k in ("cours", "evaluation", "note")):
                item["raw"] = [c for c in row if c.strip()]
            notes.append(item)

        # "Latest" grade: prefer the last row carrying a numeric result.
        with_note = [n for n in notes if n.get("note")]
        last = with_note[-1] if with_note else (notes[-1] if notes else None)
        return {"count": len(notes), "notes": notes[:30], "last": last}

    def _parse_cours(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        header, rows = self._split_header(self._table_rows(soup))
        courses: list[dict[str, Any]] = []
        for row in rows:
            joined = " ".join(row)
            if not _TIME_RE.search(joined):
                # Schedule entries are expected to carry a time.
                continue
            item = {
                "cours": self._col(header, row, "cours", "titre", "activite")
                or next((c for c in row if len(c) > 3 and not _TIME_RE.search(c)), None),
                "debut": self._col(header, row, "debut", "heure", "de"),
                "fin": self._col(header, row, "fin", "a", "jusqu"),
                "date": self._col(header, row, "date", "jour"),
                "local": self._col(header, row, "local", "salle", "classe"),
                "enseignant": self._col(
                    header, row, "enseignant", "professeur", "prof"
                ),
            }
            if not any(item.values()):
                item = {"raw": [c for c in row if c.strip()]}
            courses.append(item)

        return {"count": len(courses), "next": courses[:UPCOMING_COURSES]}

    def _parse_suivi(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        header, rows = self._split_header(self._table_rows(soup))
        suivis: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "date": self._col(header, row, "date"),
                "type": self._col(header, row, "type", "categorie", "nature"),
                "description": self._col(
                    header, row, "description", "intervention", "motif", "objet"
                ),
                "consequence": self._col(
                    header, row, "consequence", "suite", "sanction"
                ),
                "intervenant": self._col(header, row, "intervenant", "par", "auteur"),
            }
            if not any(item.values()):
                item["raw"] = [c for c in row if c.strip()]
            suivis.append(item)

        last = suivis[0] if suivis else None
        return {"count": len(suivis), "suivis": suivis[:20], "last": last}
