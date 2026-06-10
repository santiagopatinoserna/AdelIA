import pytest

from adelia.config import settings
from adelia.workers.embed import embed_texts


@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key")
async def test_embed_texts_returns_1024_dim_vectors():
    texts = [
        "Patient has type 2 diabetes.",
        "Metformin 500 mg twice daily.",
        "No known drug allergies.",
    ]
    vectors = await embed_texts(texts)

    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 1024
        assert all(isinstance(x, float) for x in v)


async def test_embed_texts_empty_input_returns_empty_list():
    """Empty input → empty list, no API call (no key required)."""
    assert await embed_texts([]) == []


async def test_embed_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY not set"):
        await embed_texts(["any text"])
