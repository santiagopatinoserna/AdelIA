from adelia.workers.chunker import (
    ChunkConfig,
    ChunkOutput,
    chunk_hierarchical,
    count_tokens,
)


def test_count_tokens_returns_positive_int_for_nonempty_text():
    assert count_tokens("hello world") > 0


def test_count_tokens_empty_returns_zero():
    assert count_tokens("") == 0


def test_chunk_hierarchical_short_text_yields_single_small_chunk():
    text = "Short note. Patient is well."
    config = ChunkConfig(small_size=300, parent_size=1500, overlap=50)
    result = chunk_hierarchical(text, config)
    assert isinstance(result, ChunkOutput)
    assert len(result.small_chunks) == 1
    assert len(result.parent_chunks) == 1
    assert result.small_chunks[0].content == text
    assert result.small_chunks[0].parent_index == 0


def test_chunk_hierarchical_long_text_produces_multiple_small_and_parent_chunks():
    paragraph = "The patient presented with fever and cough. " * 50  # ~400 tokens-ish
    text = "\n\n".join(paragraph for _ in range(20))  # ~8000 tokens
    config = ChunkConfig(small_size=300, parent_size=1500, overlap=50)
    result = chunk_hierarchical(text, config)
    assert len(result.small_chunks) > 5
    assert len(result.parent_chunks) >= 2
    # Each small chunk has a parent_index pointing to a valid parent
    for sc in result.small_chunks:
        assert 0 <= sc.parent_index < len(result.parent_chunks)


def test_chunk_hierarchical_respects_small_size_limit():
    text = "lorem ipsum dolor sit amet " * 200  # ~1000 tokens
    config = ChunkConfig(small_size=100, parent_size=500, overlap=10)
    result = chunk_hierarchical(text, config)
    for sc in result.small_chunks:
        assert count_tokens(sc.content) <= config.small_size + config.overlap


def test_chunk_hierarchical_overlap_creates_continuity():
    """Adjacent small chunks should overlap by config.overlap tokens (best effort)."""
    text = " ".join(f"word{i}" for i in range(500))  # 500 distinct words
    config = ChunkConfig(small_size=50, parent_size=200, overlap=10)
    result = chunk_hierarchical(text, config)
    assert len(result.small_chunks) >= 2
    # Adjacent chunks share at least the overlap window of words
    first = result.small_chunks[0].content.split()
    second = result.small_chunks[1].content.split()
    common = set(first[-15:]) & set(second[:15])
    assert len(common) > 0, "no overlap found between adjacent chunks"


def test_chunk_hierarchical_metadata_includes_token_count_and_offsets():
    text = "Hello world. " * 30
    config = ChunkConfig(small_size=20, parent_size=100, overlap=5)
    result = chunk_hierarchical(text, config)
    for sc in result.small_chunks:
        assert sc.token_count > 0
        assert sc.start_char >= 0
        assert sc.end_char > sc.start_char
        assert sc.end_char <= len(text)


def test_chunk_hierarchical_entity_aware_metadata():
    """Small chunks should carry entity_ids that fall within their char range."""
    text = "The patient has Metformin 500mg. They also take Lisinopril."
    config = ChunkConfig(small_size=50, parent_size=200, overlap=5)
    # Simulated entity char-range map: entity_id -> (start_char, end_char)
    entity_ranges = {
        "ent-metformin": (16, 30),    # "Metformin 500mg"
        "ent-lisinopril": (48, 58),   # "Lisinopril"
    }
    result = chunk_hierarchical(text, config, entity_ranges=entity_ranges)
    # At least one chunk should mention metformin entity, at least one lisinopril
    all_entity_ids = set()
    for sc in result.small_chunks:
        all_entity_ids.update(sc.entity_ids)
    assert "ent-metformin" in all_entity_ids
    assert "ent-lisinopril" in all_entity_ids
