from dataclasses import dataclass, field

import tiktoken

# Use cl100k encoding (GPT-3.5/4/4o); good enough for token-budget estimation.
# We are not optimizing for any specific LLM token budget — the goal is
# predictable, reproducible chunk sizes.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODING.encode(text))


@dataclass(frozen=True)
class ChunkConfig:
    small_size: int = 350
    parent_size: int = 1500
    overlap: int = 50


@dataclass
class SmallChunk:
    content: str
    chunk_index: int
    parent_index: int
    token_count: int
    start_char: int
    end_char: int
    entity_ids: list[str] = field(default_factory=list)


@dataclass
class ParentChunk:
    content: str
    parent_index: int
    token_count: int
    start_char: int
    end_char: int


@dataclass
class ChunkOutput:
    small_chunks: list[SmallChunk]
    parent_chunks: list[ParentChunk]


def _split_by_token_window(text: str, target_tokens: int, overlap_tokens: int) -> list[tuple[str, int, int]]:
    """Split text into windows of ~target_tokens tokens with overlap_tokens overlap.

    Returns list of (chunk_text, start_char, end_char). Uses a precomputed
    token-to-char offset map built by incrementally decoding each token's
    prefix — robust against repeating substrings and unicode drift.
    """
    if not text:
        return []
    tokens = _ENCODING.encode(text)
    if len(tokens) <= target_tokens:
        return [(text, 0, len(text))]

    # Build char-offset map: char_offsets[i] = char position where token i starts.
    # char_offsets[len(tokens)] = end of text (sentinel).
    # Runs once per call, O(n_tokens). Robust against repeating substrings.
    char_offsets: list[int] = []
    running = 0
    for i in range(len(tokens)):
        char_offsets.append(running)
        running += len(_ENCODING.decode([tokens[i]]))
    char_offsets.append(running)

    chunks: list[tuple[str, int, int]] = []
    step = max(1, target_tokens - overlap_tokens)
    for start_tok in range(0, len(tokens), step):
        end_tok = min(start_tok + target_tokens, len(tokens))
        window_tokens = tokens[start_tok:end_tok]
        window_text = _ENCODING.decode(window_tokens)
        start_char = char_offsets[start_tok]
        end_char = char_offsets[end_tok]
        chunks.append((window_text, start_char, end_char))
        if end_tok == len(tokens):
            break
    return chunks


def chunk_hierarchical(
    text: str,
    config: ChunkConfig | None = None,
    entity_ranges: dict[str, tuple[int, int]] | None = None,
) -> ChunkOutput:
    """Hierarchical chunker producing small + parent chunks.

    Args:
        text: source text (post-OCR or post-transcription).
        config: chunk size config; defaults to ChunkConfig().
        entity_ranges: optional map of entity_id -> (start_char, end_char)
            in the source text. When provided, each small chunk gets an
            entity_ids list of entities that overlap its char range.

    Returns:
        ChunkOutput with small_chunks (300-400 token slices) and parent_chunks
        (1500 token spans). Each small chunk has parent_index pointing into
        parent_chunks for context expansion at retrieval time.
    """
    cfg = config or ChunkConfig()
    ranges = entity_ranges or {}

    parent_windows = _split_by_token_window(text, cfg.parent_size, overlap_tokens=0)
    parent_chunks: list[ParentChunk] = []
    for i, (chunk_text, sc, ec) in enumerate(parent_windows):
        parent_chunks.append(
            ParentChunk(
                content=chunk_text,
                parent_index=i,
                token_count=count_tokens(chunk_text),
                start_char=sc,
                end_char=ec,
            )
        )

    if not parent_chunks:
        return ChunkOutput(small_chunks=[], parent_chunks=[])

    small_chunks: list[SmallChunk] = []
    for parent_idx, parent in enumerate(parent_chunks):
        small_windows = _split_by_token_window(
            parent.content, cfg.small_size, overlap_tokens=cfg.overlap
        )
        for j, (chunk_text, sc_local, ec_local) in enumerate(small_windows):
            sc_global = parent.start_char + sc_local
            ec_global = parent.start_char + ec_local
            entity_ids = [
                eid
                for eid, (e_start, e_end) in ranges.items()
                if e_start < ec_global and e_end > sc_global
            ]
            small_chunks.append(
                SmallChunk(
                    content=chunk_text,
                    chunk_index=len(small_chunks),
                    parent_index=parent_idx,
                    token_count=count_tokens(chunk_text),
                    start_char=sc_global,
                    end_char=ec_global,
                    entity_ids=entity_ids,
                )
            )

    return ChunkOutput(small_chunks=small_chunks, parent_chunks=parent_chunks)
