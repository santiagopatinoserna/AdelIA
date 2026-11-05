from unittest.mock import patch
from uuid import uuid4
from adelia.agent.suggestions import build_suggestions, ProfileState

async def test_incomplete_profile_yields_question_card():
    state = ProfileState(has_dob=False, unprocessed_docs=0, stale_briefing=False, is_child=True)
    with patch("adelia.agent.suggestions._gather_state", return_value=state):
        cards_out = await build_suggestions(user_id=uuid4(), profile_id=None)
    assert any(c["type"] == "question" and c["payload"]["field"] == "date_of_birth" for c in cards_out)

async def test_unprocessed_docs_yields_action_card():
    state = ProfileState(has_dob=True, unprocessed_docs=2, stale_briefing=False, is_child=False)
    with patch("adelia.agent.suggestions._gather_state", return_value=state):
        cards_out = await build_suggestions(user_id=uuid4(), profile_id=None)
    assert any(c["type"] == "action" for c in cards_out)


async def test_diary_cards_need_a_configured_bot():
    """No TELEGRAM_BOT_TOKEN → no 'Enlazar'/'¿Cómo ha ido hoy?' cards (the bot would be dead)."""
    off = ProfileState(has_dob=True, unprocessed_docs=0, stale_briefing=False, is_child=False,
                       telegram_linked=False, diary_today=False, telegram_enabled=False)
    with patch("adelia.agent.suggestions._gather_state", return_value=off):
        cards_out = await build_suggestions(user_id=uuid4(), profile_id=None)
    intents = {a["intent"] for c in cards_out for a in c["actions"]}
    assert not intents & {"link_telegram", "daily_diary"}
    assert any(c["payload"].get("title") == "Todo al día" for c in cards_out)

    on = ProfileState(has_dob=True, unprocessed_docs=0, stale_briefing=False, is_child=False,
                      telegram_linked=False, diary_today=False, telegram_enabled=True)
    with patch("adelia.agent.suggestions._gather_state", return_value=on):
        cards_out = await build_suggestions(user_id=uuid4(), profile_id=None)
    card = next(c for c in cards_out if any(a["intent"] == "link_telegram" for a in c["actions"]))
    assert card["payload"]["title"] == "Diario por Telegram"


async def _all_cards(locale: str) -> list[dict]:
    """Every suggestion a state can produce, in one locale."""
    states = [
        ProfileState(has_dob=False, unprocessed_docs=2, stale_briefing=True, is_child=True,
                     telegram_linked=False, diary_today=False, telegram_enabled=True),
        ProfileState(has_dob=True, unprocessed_docs=0, stale_briefing=False, is_child=True,
                     telegram_linked=True, diary_today=False, telegram_enabled=True),
        ProfileState(has_dob=True, unprocessed_docs=0, stale_briefing=False, is_child=True),
    ]
    out: list[dict] = []
    for state in states:
        with patch("adelia.agent.suggestions._gather_state", return_value=state):
            out += await build_suggestions(user_id=uuid4(), profile_id=None, locale=locale)
    return out


def _words(cards_out: list[dict]) -> list[str]:
    texts = []
    for c in cards_out:
        p = c["payload"]
        texts += [p.get("title"), p.get("body"), p.get("prompt")]
        texts += [a["label"] for a in c["actions"]]
    return [t for t in texts if t]


async def test_suggestions_speak_her_language():
    """The router passed `locale` and the cards ignored it: a French mother read
    "Diario por Telegram ... Enlazar" under every answer (RECORRIDO_POC.md)."""
    es = _words(await _all_cards("es"))
    assert "Diario por Telegram" in es
    for locale in ("en", "fr"):
        other = _words(await _all_cards(locale))
        assert len(other) == len(es)
        assert not set(other) & set(es), (locale, set(other) & set(es))
    fr = _words(await _all_cards("fr"))
    assert "Journal sur Telegram" in fr
    # An unknown locale falls back to Spanish, the app's default.
    assert _words(await _all_cards("de")) == es
