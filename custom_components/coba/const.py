from __future__ import annotations

DOMAIN = "coba"

# Config / options keys
CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEBUG = "debug"

# Defaults
DEFAULT_SCAN_INTERVAL_MINUTES = 15
MIN_SCAN_INTERVAL_MINUTES = 5

# Number of upcoming courses to expose
UPCOMING_COURSES = 5

# Keywords used to auto-discover the portal sections from the menu links.
# Values are accent-insensitive, lowercase. The first link whose text contains
# one of these tokens is used for the matching section.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "messages": ("messagerie", "message", "courrier", "boite", "boîte"),
    "notes": (
        "resultat",
        "résultat",
        "note",
        "evaluation",
        "évaluation",
        "bulletin",
        "rendement",
    ),
    "cours": ("horaire", "cours", "agenda", "calendrier", "emploi du temps"),
    "suivi": ("suivi", "intervention", "discipline", "encadrement"),
}
