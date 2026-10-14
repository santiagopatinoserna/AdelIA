from adelia.config import settings
from adelia.llm import get_mistral_client

# Mistral embeddings caps request size; large documents can chunk into
# hundreds of pieces. Batch to stay under the limit (v0.1.1 carry-over).
EMBED_BATCH_SIZE = 100



async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with Mistral's embedding model, settings.mistral_embed_model.

    The model is "mistral-embed", which returns 1024-dim vectors, and that size
    is baked into the `chunks` and `evidence_chunks` embedding columns
    (Vector(1024)). It is a setting only so the name is not buried in logic:
    changing it is NOT a config edit. A model with another dimension cannot be
    stored, and one with the same dimension is a different vector space that
    would silently corrupt retrieval against every vector already stored. The
    dimension lives in config.EMBEDDING_MODEL_DIMENSIONS, Settings rejects a
    name that is not in it, and tests/test_model_config.py checks it against
    the columns. Procedure: apps/api/docs/MODELOS.md.

    Args:
        texts: list of input strings.

    Returns:
        List of float vectors (settings.embedding_dimension long, 1024 today)
        aligned 1:1 with input texts. Empty list for empty input (no API call).

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
            model=settings.mistral_embed_model,
            inputs=batch,
        )
        vectors.extend(item.embedding for item in response.data)
    return vectors
