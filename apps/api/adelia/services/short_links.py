"""Our own short links for the social networks: adelia.godi.ai/r/<code>.

The community plan (2026-11-08, research/comunidad/ESTRATEGIA.md, UTM
section) puts a link with UTM parameters in every bio and every piece, and
rules out bit.ly and the like because they add their own tracking, which
contradicts "no te rastreamos". A long UTM link does not fit a bio or a
story sticker, so this is the short form: apps/web/app/r/[code] asks the API
where a code goes, the API counts the click in funnel_counters (one integer
per day and code, no cookie, no identifier, services/funnel) and the web
redirects to the landing with the UTM values below.

The count is what tells which piece brings people when the visitor never
answers the analytics banner; with "Aceptar", services/analytics also keeps
the UTM values with her journey.

One code per network for the bio and one per piece. A piece code does not
know the network: the same g02 goes in the Instagram story, the TikTok
comment and the YouTube description, so its source is "redes" and each
network's own link statistics split it. A per-network piece link is one
more row here.

Values follow the plan: lowercase, no accents, the piece ids of
GUIONES_PRIMEROS_10.md. A code that is not here resolves to nothing and the
web sends the visitor to the landing without an error.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

#: The launch campaign of the plan; later ones are one per month (2026_12...).
CAMPAIGN = "lanzamiento_2026_11"

#: funnel_counters.event is a String(32): "link_" plus a short code fits.
EVENT_PREFIX = "link_"


@dataclass(frozen=True)
class ShortLink:
    code: str
    source: str
    medium: str
    content: str
    campaign: str = CAMPAIGN
    path: str = "/es"


def _bio(code: str, network: str) -> ShortLink:
    return ShortLink(code=code, source=network, medium="bio", content="perfil")


def _piece(code: str, content: str) -> ShortLink:
    return ShortLink(code=code, source="redes", medium="social", content=content)


LINKS: dict[str, ShortLink] = {
    link.code: link
    for link in (
        _bio("ig", "instagram"),
        _bio("tt", "tiktok"),
        _bio("yt", "youtube"),
        _bio("fb", "facebook"),
        _piece("g01", "g01_origen"),
        _piece("g02", "g02_fiebre3m"),
        _piece("g03", "g03_regurgita"),
        _piece("g04", "g04_suenoseguro"),
        _piece("g05", "g05_verdura"),
        _piece("g06", "g06_dientes"),
        _piece("g07", "g07_bronquiolitis"),
        _piece("g08", "g08_ac_cifras"),
        _piece("g09", "g09_grabar"),
        _piece("g10", "g10_abstencion"),
    )
}


def event(link: ShortLink) -> str:
    """Its row name in funnel_counters."""
    return f"{EVENT_PREFIX}{link.code}"


#: The only link events services/funnel.bump accepts: the allowlist is the
#: validation, as for "visit" and "start".
EVENTS: tuple[str, ...] = tuple(event(link) for link in LINKS.values())


def resolve(code: str | None) -> ShortLink | None:
    """The link for `code` as people type it (" G02" is g02), or None."""
    return LINKS.get((code or "").strip().lower())


def location(link: ShortLink) -> str:
    """A path on our own site with the UTM values, never another host."""
    return link.path + "?" + urlencode({
        "utm_source": link.source,
        "utm_medium": link.medium,
        "utm_campaign": link.campaign,
        "utm_content": link.content,
    })
