from adelia.llm import get_mistral_client

# Mistral embeddings caps request size; large documents can chunk into
# hundreds of pieces. Batch to stay under the limit (v0.1.1 carry-over).
EMBED_BATCH_SIZE = 100



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
    client = get_mistral_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        response = await client.embeddings.create_async(
            model="mistral-embed",
            inputs=batch,
        )
        vectors.extend(item.embedding for item in response.data)
    return vectors
