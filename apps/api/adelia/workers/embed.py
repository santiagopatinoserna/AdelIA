from mistralai.client.sdk import Mistral

from adelia.config import settings


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Mistral's mistral-embed model (1024-dim).

    Args:
        texts: list of input strings.

    Returns:
        List of 1024-dim float vectors aligned 1:1 with input texts. Empty
        list for empty input (no API call).

    Raises:
        RuntimeError: if MISTRAL_API_KEY is not configured. Configuration
            error — do NOT retry; alert.
        mistralai.SDKError: on API failure (transient — caller may retry
            with backoff).
    """
    if not texts:
        return []
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    client = Mistral(api_key=settings.mistral_api_key)
    response = await client.embeddings.create_async(
        model="mistral-embed",
        inputs=texts,
    )
    return [item.embedding for item in response.data]
