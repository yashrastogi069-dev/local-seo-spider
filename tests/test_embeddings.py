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


def test_unknown_embedding_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        build_embedding_provider("unknown")
