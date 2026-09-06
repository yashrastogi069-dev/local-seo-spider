"""Local and hosted embedding providers for hybrid retrieval.

Supports:
- Hosted API providers (Google Gemini Embedding API)
- Future local providers (Sentence Transformers, Qwen, etc.)
- Deterministic hash provider for testing and offline diagnostics
- Provider health states, explicit fallback policies, and rich vector metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
import hashlib
import json
import math
import os
import random
import re
import time
from typing import Any, Protocol, Sequence

import httpx


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _redact_key(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


class ProviderHealth(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    TEMPORARY_FAILURE = "temporary_failure"
    MISCONFIGURED = "misconfigured"
    UNVERIFIED_LIVE = "unverified_live"


class FallbackPolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    FALLBACK_TO_HASH = "fallback_to_hash"
    BM25_ONLY = "bm25_only"
    AUTO = "auto"


class EmbeddingTaskType(str, Enum):
    DOCUMENT = "RETRIEVAL_DOCUMENT"
    QUERY = "RETRIEVAL_QUERY"
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    CLASSIFICATION = "CLASSIFICATION"
    CLUSTERING = "CLUSTERING"


@dataclass
class EmbeddingMetadata:
    """Rich provenance and configuration metadata for vector embeddings."""

    provider: str
    model: str
    dimension: int
    version: str = "1.0.0"
    task_type: str = EmbeddingTaskType.DOCUMENT.value
    preprocessing_version: str = "v1"
    created_at: str = field(default_factory=_now)
    chunk_id: int | None = None
    content_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "version": self.version,
            "task_type": self.task_type,
            "preprocessing_version": self.preprocessing_version,
            "created_at": self.created_at,
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
        }
        if self.extra:
            data.update(self.extra)
        return data


class EmbeddingProvider(Protocol):
    name: str
    provider_type: str
    model_name: str
    dimension: int
    health_status: ProviderHealth
    last_error: str

    def embed(self, text: str, task_type: str = EmbeddingTaskType.DOCUMENT.value) -> list[float]: ...

    def embed_batch(
        self, texts: Sequence[str], task_type: str = EmbeddingTaskType.DOCUMENT.value
    ) -> list[list[float]]: ...

    def get_metadata(self) -> dict[str, Any]: ...


@dataclass
class ProviderResolution:
    """Detailed resolution diagnostics explaining requested vs actual provider choices."""

    requested_provider: str
    actual_provider: str
    requested_model: str
    actual_model: str
    requested_dimension: int
    actual_dimension: int
    fallback_occurred: bool
    fallback_reason: str
    degraded_mode: bool
    health_status: ProviderHealth
    provider_instance: EmbeddingProvider


@dataclass(frozen=True)
class HashEmbeddingProvider:
    """Deterministic feature-hash embedding provider for unit tests and offline diagnostics.

    This provider generates normalized pseudo-random projection vectors based on Blake2b
    hashes of character/word n-grams. It does NOT provide deep neural semantic understanding.
    """

    dimension: int = 384
    name: str = "hash"
    provider_type: str = "hash"
    model_name: str = "hash"
    health_status: ProviderHealth = ProviderHealth.AVAILABLE
    last_error: str = ""

    def embed(self, text: str, task_type: str = EmbeddingTaskType.DOCUMENT.value) -> list[float]:
        terms = re.findall(r"[\w][\w'-]{1,}", text.lower())
        features = terms + [f"{left}_{right}" for left, right in zip(terms, terms[1:])]
        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "little") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_batch(
        self, texts: Sequence[str], task_type: str = EmbeddingTaskType.DOCUMENT.value
    ) -> list[list[float]]:
        return [self.embed(t, task_type=task_type) for t in texts]

    def get_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_type,
            "model": self.model_name,
            "dimension": self.dimension,
            "version": "1.0.0",
            "health_status": self.health_status.value,
        }


class NullEmbeddingProvider:
    """Empty provider for BM25-only lexical indexing mode."""

    name: str = "null"
    provider_type: str = "null"
    model_name: str = "null"
    dimension: int = 0
    health_status: ProviderHealth = ProviderHealth.AVAILABLE
    last_error: str = ""

    def embed(self, text: str, task_type: str = EmbeddingTaskType.DOCUMENT.value) -> list[float]:
        return []

    def embed_batch(
        self, texts: Sequence[str], task_type: str = EmbeddingTaskType.DOCUMENT.value
    ) -> list[list[float]]:
        return [[] for _ in texts]

    def get_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_type,
            "model": self.model_name,
            "dimension": 0,
            "version": "1.0.0",
            "health_status": self.health_status.value,
        }


class SentenceTransformersProvider:
    """Local neural semantic embedding using Sentence Transformers."""

    provider_type: str = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            self.health_status = ProviderHealth.UNAVAILABLE
            self.last_error = str(exc)
            raise RuntimeError(
                "Sentence Transformers is not installed. Use SPIDER_EMBEDDING_PROVIDER=hash or configure a hosted provider."
            ) from exc
        self.model_name = model_name
        self.name = f"sentence-transformers:{model_name}"
        self.last_error = ""
        try:
            self._model = SentenceTransformer(model_name)
            dimension_getter = getattr(
                self._model, "get_embedding_dimension", self._model.get_sentence_embedding_dimension
            )
            self.dimension = int(dimension_getter())
            self.health_status = ProviderHealth.AVAILABLE
        except Exception as exc:
            self.health_status = ProviderHealth.MISCONFIGURED
            self.last_error = str(exc)
            raise

    def embed(self, text: str, task_type: str = EmbeddingTaskType.DOCUMENT.value) -> list[float]:
        values = self._model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return [float(value) for value in values]

    def embed_batch(
        self, texts: Sequence[str], task_type: str = EmbeddingTaskType.DOCUMENT.value
    ) -> list[list[float]]:
        if not texts:
            return []
        values = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [[float(v) for v in row] for row in values]

    def get_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_type,
            "model": self.model_name,
            "dimension": self.dimension,
            "version": "1.0.0",
            "health_status": self.health_status.value,
        }


class GeminiEmbeddingProvider:
    """Hosted semantic embedding provider using the Google Gemini REST API.

    Features:
    - Uses Google Gemini Embedding API endpoints (e.g. text-embedding-004)
    - Sends credentials via header x-goog-api-key rather than query string
    - Redacts API keys from logs, metadata, error strings, and reprs
    - Bounded retries on 429/5xx with exponential backoff and jitter
    - Respects Retry-After header (integer seconds and HTTP-date)
    - Fail-closed without retry on 401/403 (AUTHENTICATION_FAILED)
    - Fail-closed without retry on 404 (MISCONFIGURED / invalid model)
    - Supports clean batching (batchEmbedContents up to 100 texts per request)
    """

    provider_type: str = "google"

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "text-embedding-004",
        dimension: int = 768,
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        batch_size: int = 64,
        client: httpx.Client | None = None,
    ) -> None:
        raw_key = api_key or os.getenv("SPIDER_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self._api_key = raw_key.strip()
        self.model_name = model_name.strip() or "text-embedding-004"
        # Normalize model identifier
        if self.model_name.startswith("models/"):
            self.model_resource = self.model_name
            self.model_name = self.model_name[len("models/"):]
        else:
            self.model_resource = f"models/{self.model_name}"
        self.dimension = max(8, min(4096, int(dimension)))
        self.name = f"google:{self.model_name}"
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, min(5, int(max_retries)))
        self.batch_size = max(1, min(100, int(batch_size)))
        self._custom_client = client
        self._client: httpx.Client | None = None
        self.last_error: str = ""
        self.last_latency_ms: float = 0.0

        if not self._api_key:
            self.health_status = ProviderHealth.MISCONFIGURED
            self.last_error = "Missing Gemini API key (configure GEMINI_API_KEY or SPIDER_GEMINI_API_KEY)."
        else:
            self.health_status = ProviderHealth.AVAILABLE

    def __repr__(self) -> str:
        return (
            f"GeminiEmbeddingProvider(model={self.model_name!r}, dimension={self.dimension}, "
            f"api_key={_redact_key(self._api_key)!r}, health={self.health_status.value!r})"
        )

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout_seconds,
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _parse_retry_after(self, response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()
        try:
            return float(header)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(header)
            return max(0.0, (dt - datetime.now(UTC)).total_seconds())
        except Exception:
            return None

    def _sanitize_error_msg(self, msg: str) -> str:
        if self._api_key and len(self._api_key) > 4:
            msg = msg.replace(self._api_key, _redact_key(self._api_key))
        return msg

    def embed(self, text: str, task_type: str = EmbeddingTaskType.DOCUMENT.value) -> list[float]:
        """Embed a single text string with resilient error handling and bounded retries."""
        results = self.embed_batch([text], task_type=task_type)
        return results[0] if results else [0.0] * self.dimension

    def embed_batch(
        self, texts: Sequence[str], task_type: str = EmbeddingTaskType.DOCUMENT.value
    ) -> list[list[float]]:
        """Embed a sequence of texts using Gemini batchEmbedContents with chunking and retries."""
        if not texts:
            return []

        if not self._api_key:
            self.health_status = ProviderHealth.MISCONFIGURED
            raise ValueError(self._sanitize_error_msg(self.last_error or "Missing Gemini API key."))

        all_results: list[list[float]] = []
        batch_chunks = [texts[i : i + self.batch_size] for i in range(0, len(texts), self.batch_size)]

        for chunk in batch_chunks:
            chunk_results = self._execute_batch_with_retry(chunk, task_type)
            all_results.extend(chunk_results)

        return all_results

    def _execute_batch_with_retry(
        self, chunk: Sequence[str], task_type: str
    ) -> list[list[float]]:
        url = f"{self.api_base_url}/{self.model_resource}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": self.model_resource,
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                }
                for text in chunk
            ]
        }

        attempts = 0
        backoff = 0.5

        while True:
            attempts += 1
            t0 = time.monotonic()
            try:
                client = self._get_client()
                # If custom client passed, make sure header is present
                headers = {"Content-Type": "application/json"}
                if "x-goog-api-key" not in client.headers:
                    headers["x-goog-api-key"] = self._api_key

                response = client.post(url, json=payload, headers=headers)
                self.last_latency_ms = (time.monotonic() - t0) * 1000.0

                if response.status_code == 200:
                    self.health_status = ProviderHealth.AVAILABLE
                    self.last_error = ""
                    data = response.json()
                    embeddings_data = data.get("embeddings", [])
                    values_list = [item.get("values", []) for item in embeddings_data]

                    # Pad or validate dimension
                    parsed: list[list[float]] = []
                    for vec in values_list:
                        floats = [float(x) for x in vec]
                        if floats:
                            self.dimension = len(floats)
                        parsed.append(floats)
                    return parsed

                # Handle HTTP Errors
                status_code = response.status_code
                error_body = self._sanitize_error_msg(response.text)

                if status_code in (401, 403):
                    self.health_status = ProviderHealth.AUTHENTICATION_FAILED
                    self.last_error = f"Gemini API authentication failed (HTTP {status_code}): {error_body}"
                    raise PermissionError(self.last_error)

                if status_code == 404:
                    self.health_status = ProviderHealth.MISCONFIGURED
                    self.last_error = f"Gemini model not found (HTTP 404): {self.model_resource}"
                    raise ValueError(self.last_error)

                if status_code == 429:
                    self.health_status = ProviderHealth.RATE_LIMITED
                    self.last_error = f"Gemini API rate limit exceeded (HTTP 429): {error_body}"
                    retry_after = self._parse_retry_after(response)
                    delay = retry_after if retry_after is not None else backoff
                elif status_code >= 500:
                    self.health_status = ProviderHealth.TEMPORARY_FAILURE
                    self.last_error = f"Gemini API server error (HTTP {status_code}): {error_body}"
                    delay = backoff
                else:
                    self.health_status = ProviderHealth.MISCONFIGURED
                    self.last_error = f"Gemini API error (HTTP {status_code}): {error_body}"
                    raise RuntimeError(self.last_error)

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                self.health_status = ProviderHealth.TEMPORARY_FAILURE
                self.last_error = f"Gemini network error ({type(exc).__name__}): {self._sanitize_error_msg(str(exc))}"
                delay = backoff

            if attempts > self.max_retries:
                raise RuntimeError(
                    f"Gemini API request failed after {attempts} attempts. Last status: {self.health_status.value}. Error: {self.last_error}"
                )

            # Jittered backoff delay
            jitter = random.uniform(0.8, 1.2)
            actual_delay = min(10.0, max(0.1, delay * jitter))
            time.sleep(actual_delay)
            backoff *= 2.0

    def get_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_type,
            "model": self.model_name,
            "dimension": self.dimension,
            "version": "1.0.0",
            "health_status": self.health_status.value,
            "last_error": self.last_error,
            "last_latency_ms": self.last_latency_ms,
            "api_key_configured": bool(self._api_key),
            "api_key_redacted": _redact_key(self._api_key),
        }


def resolve_embedding_provider(
    provider_name: str = "auto",
    model_name: str | None = None,
    dimension: int | None = None,
    api_key: str | None = None,
    fallback_policy: FallbackPolicy | str = FallbackPolicy.AUTO,
    settings: Any = None,
    client: httpx.Client | None = None,
) -> ProviderResolution:
    """Resolve and configure an EmbeddingProvider according to explicit fallback policies."""
    norm_policy = FallbackPolicy(fallback_policy) if isinstance(fallback_policy, str) else fallback_policy
    raw_provider = (provider_name or "").strip().lower()
    if not raw_provider and settings:
        raw_provider = getattr(settings, "embedding_provider", "auto").strip().lower()
    if not raw_provider:
        raw_provider = "auto"

    effective_model = (
        model_name
        or (getattr(settings, "embedding_model", "") if settings else "")
        or ("text-embedding-004" if raw_provider in {"google", "gemini"} else "sentence-transformers/all-MiniLM-L6-v2")
    )
    effective_dim = int(
        dimension
        or (getattr(settings, "embedding_dimension", 0) if settings else 0)
        or (768 if raw_provider in {"google", "gemini"} else 384)
    )
    effective_key = (
        api_key
        or (getattr(settings, "gemini_api_key", "") if settings else "")
        or os.getenv("SPIDER_GEMINI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    )

    # 1. BM25_ONLY policy
    if norm_policy == FallbackPolicy.BM25_ONLY:
        null_prov = NullEmbeddingProvider()
        return ProviderResolution(
            requested_provider=raw_provider,
            actual_provider="null",
            requested_model=effective_model,
            actual_model="null",
            requested_dimension=effective_dim,
            actual_dimension=0,
            fallback_occurred=True,
            fallback_reason="BM25_ONLY policy requested: vectors disabled",
            degraded_mode=True,
            health_status=ProviderHealth.AVAILABLE,
            provider_instance=null_prov,
        )

    # 2. Explicit Hash selection
    if raw_provider in {"hash", "offline"}:
        hash_prov = HashEmbeddingProvider(dimension=max(8, min(4096, effective_dim)))
        return ProviderResolution(
            requested_provider=raw_provider,
            actual_provider="hash",
            requested_model=effective_model,
            actual_model="hash",
            requested_dimension=effective_dim,
            actual_dimension=hash_prov.dimension,
            fallback_occurred=False,
            fallback_reason="",
            degraded_mode=False,
            health_status=ProviderHealth.AVAILABLE,
            provider_instance=hash_prov,
        )

    # 3. Explicit Google / Gemini selection
    if raw_provider in {"google", "gemini"}:
        if effective_key:
            gemini_prov = GeminiEmbeddingProvider(
                api_key=effective_key,
                model_name=effective_model,
                dimension=effective_dim,
                client=client,
            )
            return ProviderResolution(
                requested_provider=raw_provider,
                actual_provider="google",
                requested_model=effective_model,
                actual_model=gemini_prov.model_name,
                requested_dimension=effective_dim,
                actual_dimension=gemini_prov.dimension,
                fallback_occurred=False,
                fallback_reason="",
                degraded_mode=False,
                health_status=gemini_prov.health_status,
                provider_instance=gemini_prov,
            )
        # Key missing
        if norm_policy == FallbackPolicy.FAIL_CLOSED:
            raise ValueError(
                "Google Gemini embedding provider requires an API key (set GEMINI_API_KEY or SPIDER_GEMINI_API_KEY)."
            )
        # Fallback to hash under AUTO or FALLBACK_TO_HASH
        hash_prov = HashEmbeddingProvider(dimension=effective_dim)
        return ProviderResolution(
            requested_provider=raw_provider,
            actual_provider="hash",
            requested_model=effective_model,
            actual_model="hash",
            requested_dimension=effective_dim,
            actual_dimension=hash_prov.dimension,
            fallback_occurred=True,
            fallback_reason="Gemini API key missing; fell back to deterministic hash provider",
            degraded_mode=True,
            health_status=ProviderHealth.MISCONFIGURED,
            provider_instance=hash_prov,
        )

    # 4. Explicit Sentence Transformers selection
    if raw_provider in {"sentence-transformers", "sentence_transformers", "sbert"}:
        try:
            st_prov = SentenceTransformersProvider(model_name=effective_model)
            return ProviderResolution(
                requested_provider=raw_provider,
                actual_provider="sentence-transformers",
                requested_model=effective_model,
                actual_model=st_prov.model_name,
                requested_dimension=effective_dim,
                actual_dimension=st_prov.dimension,
                fallback_occurred=False,
                fallback_reason="",
                degraded_mode=False,
                health_status=st_prov.health_status,
                provider_instance=st_prov,
            )
        except (ImportError, RuntimeError) as exc:
            if norm_policy == FallbackPolicy.FAIL_CLOSED:
                raise
            hash_prov = HashEmbeddingProvider(dimension=effective_dim)
            return ProviderResolution(
                requested_provider=raw_provider,
                actual_provider="hash",
                requested_model=effective_model,
                actual_model="hash",
                requested_dimension=effective_dim,
                actual_dimension=hash_prov.dimension,
                fallback_occurred=True,
                fallback_reason=f"Sentence Transformers unavailable ({exc}); fell back to hash provider",
                degraded_mode=True,
                health_status=ProviderHealth.UNAVAILABLE,
                provider_instance=hash_prov,
            )

    # 5. AUTO Resolution
    if raw_provider == "auto":
        # Check hosted Gemini first
        if effective_key:
            gemini_prov = GeminiEmbeddingProvider(
                api_key=effective_key,
                model_name=effective_model if "embedding" in effective_model else "text-embedding-004",
                dimension=768 if effective_dim == 384 else effective_dim,
                client=client,
            )
            return ProviderResolution(
                requested_provider="auto",
                actual_provider="google",
                requested_model=effective_model,
                actual_model=gemini_prov.model_name,
                requested_dimension=effective_dim,
                actual_dimension=gemini_prov.dimension,
                fallback_occurred=False,
                fallback_reason="",
                degraded_mode=False,
                health_status=gemini_prov.health_status,
                provider_instance=gemini_prov,
            )
        # Check local sentence-transformers second
        try:
            import sentence_transformers  # noqa: F401

            st_prov = SentenceTransformersProvider(model_name=effective_model)
            return ProviderResolution(
                requested_provider="auto",
                actual_provider="sentence-transformers",
                requested_model=effective_model,
                actual_model=st_prov.model_name,
                requested_dimension=effective_dim,
                actual_dimension=st_prov.dimension,
                fallback_occurred=False,
                fallback_reason="",
                degraded_mode=False,
                health_status=st_prov.health_status,
                provider_instance=st_prov,
            )
        except (ImportError, RuntimeError):
            pass

        # Final auto fallback: hash provider
        hash_prov = HashEmbeddingProvider(dimension=effective_dim)
        return ProviderResolution(
            requested_provider="auto",
            actual_provider="hash",
            requested_model=effective_model,
            actual_model="hash",
            requested_dimension=effective_dim,
            actual_dimension=hash_prov.dimension,
            fallback_occurred=True,
            fallback_reason="Auto-resolution: no hosted API key and local model not installed; using hash provider",
            degraded_mode=True,
            health_status=ProviderHealth.AVAILABLE,
            provider_instance=hash_prov,
        )

    raise ValueError(f"Unknown embedding provider: {provider_name}")


def build_embedding_provider(
    provider: str = "hash",
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    dimension: int = 384,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    fallback_policy: FallbackPolicy | str = FallbackPolicy.FAIL_CLOSED,
) -> EmbeddingProvider:
    """Backward-compatible constructor returning an EmbeddingProvider instance."""
    normalized = (provider or "").strip().lower()
    # If explicitly "auto", use AUTO; if a specific provider is named, fail-closed by default
    effective_policy = FallbackPolicy.AUTO if normalized in {"auto", ""} else fallback_policy
    resolution = resolve_embedding_provider(
        provider_name=provider,
        model_name=model,
        dimension=dimension,
        api_key=api_key,
        fallback_policy=effective_policy,
        client=client,
    )
    return resolution.provider_instance


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors with dimension verification."""
    if len(left) != len(right) or not left:
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))
