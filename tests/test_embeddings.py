import pytest

from app.embeddings import HashEmbeddingProvider, build_embedding_provider


def test_hash_embeddings_are_deterministic_and_normalized() -> None:
    provider = HashEmbeddingProvider(dimension=32)
    first = provider.embed("local policy evidence")
    second = provider.embed("local policy evidence")
    assert first == second
    assert len(first) == 32
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_hash_provider_is_the_offline_default() -> None:
    provider = build_embedding_provider("offline", dimension=16)
    assert provider.name == "hash"
    assert provider.dimension == 16


def test_real_semantic_provider_separates_paraphrase_from_unrelated_text() -> None:
    try:
        provider = build_embedding_provider("sentence-transformers")
    except (ImportError, RuntimeError, OSError) as exc:
        pytest.skip(f"semantic model unavailable in this environment: {exc}")
    query = provider.embed("How can I get my money back?")
    paraphrase = provider.embed("What is the refund process?")
    unrelated = provider.embed("The office is closed on public holidays.")
    from app.embeddings import cosine_similarity
    assert cosine_similarity(query, paraphrase) > cosine_similarity(query, unrelated)


def test_unknown_embedding_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        build_embedding_provider("unknown")
