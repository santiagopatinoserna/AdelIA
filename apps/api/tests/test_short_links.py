"""Short links for the social networks: /r/<code> (2026-11-08).

The community plan (research/comunidad/ESTRATEGIA.md, UTM section) puts a
link with UTM parameters in every bio and every piece, and rules out
third-party shorteners because they add their own tracking. This table is
our own: one code per network for the bio, one per piece (g01 to g10), each
resolving to the landing with the UTM values of that plan. What is pinned:
the codes, the UTM scheme (lowercase, no accents, the piece ids of
GUIONES_PRIMEROS_10.md) and that a counter row can always hold the event.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest

from adelia.models import FunnelCounter
from adelia.services import short_links

PIECES = {
    "g01": "g01_origen",
    "g02": "g02_fiebre3m",
    "g03": "g03_regurgita",
    "g04": "g04_suenoseguro",
    "g05": "g05_verdura",
    "g06": "g06_dientes",
    "g07": "g07_bronquiolitis",
    "g08": "g08_ac_cifras",
    "g09": "g09_grabar",
    "g10": "g10_abstencion",
}
BIOS = {"ig": "instagram", "tt": "tiktok", "yt": "youtube", "fb": "facebook"}
UTM_VALUE = re.compile(r"^[a-z0-9_]+$")


def _utm(location: str) -> dict[str, str]:
    parts = urlsplit(location)
    assert parts.scheme == "" and parts.netloc == "", "a path on our own site, never a host"
    return {k: v[0] for k, v in parse_qs(parts.query).items()}


def test_one_code_per_network_bio_and_one_per_piece():
    assert set(short_links.LINKS) == set(BIOS) | set(PIECES)


@pytest.mark.parametrize("code,network", sorted(BIOS.items()))
def test_a_bio_code_names_its_network(code, network):
    location = short_links.location(short_links.resolve(code))
    assert urlsplit(location).path == "/es"
    assert _utm(location) == {
        "utm_source": network, "utm_medium": "bio",
        "utm_campaign": "lanzamiento_2026_11", "utm_content": "perfil",
    }


@pytest.mark.parametrize("code,content", sorted(PIECES.items()))
def test_a_piece_code_carries_its_piece_id(code, content):
    location = short_links.location(short_links.resolve(code))
    assert urlsplit(location).path == "/es"
    assert _utm(location) == {
        "utm_source": "redes", "utm_medium": "social",
        "utm_campaign": "lanzamiento_2026_11", "utm_content": content,
    }


def test_every_utm_value_is_lowercase_without_accents():
    for code in short_links.LINKS:
        for value in _utm(short_links.location(short_links.resolve(code))).values():
            assert UTM_VALUE.match(value), (code, value)


def test_codes_are_read_the_way_people_type_them():
    assert short_links.resolve("G02") == short_links.resolve("g02")
    assert short_links.resolve(" ig ") == short_links.resolve("ig")


@pytest.mark.parametrize("code", ["", "g11", "nope", "g02_fiebre3m", "x" * 500, "../es", "ig?x=1"])
def test_an_unknown_code_resolves_to_nothing(code):
    assert short_links.resolve(code) is None


def test_every_event_fits_the_counter_row_and_is_on_the_allowlist():
    width = FunnelCounter.__table__.c.event.type.length
    for code in short_links.LINKS:
        event = short_links.event(short_links.resolve(code))
        assert len(event) <= width
        assert event in short_links.EVENTS
    assert len(short_links.EVENTS) == len(short_links.LINKS)
