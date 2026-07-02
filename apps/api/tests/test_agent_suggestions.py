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
