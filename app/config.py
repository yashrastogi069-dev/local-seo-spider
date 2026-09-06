"""Local configuration; values are read from .env and never uploaded."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str
    default_url_cap: int
    max_url_cap: int
    default_delay_seconds: float
    request_timeout_seconds: float
    render_timeout_ms: int
    max_redirects: int
    max_document_bytes: int
    max_request_retries: int
    retry_backoff_seconds: float
    max_concurrent_crawls: int
    render_enabled: bool
    extraction_profile_path: Path | None = None
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_fallback_policy: str = "auto"
    gemini_api_key: str = ""
    embedding_batch_size: int = 64
    embedding_timeout_seconds: float = 30.0
    answer_provider: str = "evidence"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    answer_timeout_seconds: float = 45.0
    crawl_executor_mode: str = "serial"
    async_concurrency: int = 8
    thread_workers: int = 4
    process_workers: int = 2
    allow_private_crawls: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "local_seo_spider.sqlite3"

    @classmethod
    def from_environment(cls, base_dir: Path | None = None) -> "Settings":
        root = base_dir or Path.cwd()
        load_dotenv(root / ".env")
        configured_data_dir = Path(os.getenv("SPIDER_DATA_DIR", "./data"))
        data_dir = configured_data_dir if configured_data_dir.is_absolute() else root / configured_data_dir
        configured_profile = os.getenv("SPIDER_EXTRACTION_PROFILE_PATH", "").strip()
        gemini_key = os.getenv("SPIDER_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        configured_embedding_provider = os.getenv("SPIDER_EMBEDDING_PROVIDER", "").strip().lower()
        if not configured_embedding_provider:
            if gemini_key:
                configured_embedding_provider = "google"
            else:
                try:
                    import sentence_transformers  # noqa: F401
                    configured_embedding_provider = "sentence-transformers"
                except ImportError:
                    configured_embedding_provider = "hash"
        elif configured_embedding_provider in {"google", "gemini"}:
            pass
        elif configured_embedding_provider in {"sentence-transformers", "sentence_transformers", "sbert"}:
            try:
                import sentence_transformers  # noqa: F401
            except ImportError:
                configured_embedding_provider = "hash"
        elif configured_embedding_provider in {"hash", "offline"} and not _as_bool(os.getenv("SPIDER_ALLOW_HASH_EMBEDDING", "false")):
            if gemini_key:
                configured_embedding_provider = "google"
            else:
                try:
                    import sentence_transformers  # noqa: F401
                    configured_embedding_provider = "sentence-transformers"
                except ImportError:
                    configured_embedding_provider = "hash"

        default_model = "text-embedding-004" if configured_embedding_provider in {"google", "gemini"} else "sentence-transformers/all-MiniLM-L6-v2"
        configured_model = os.getenv("SPIDER_EMBEDDING_MODEL", default_model)
        default_dim = 768 if configured_embedding_provider in {"google", "gemini"} else 384
        configured_dim = int(os.getenv("SPIDER_EMBEDDING_DIMENSION", str(default_dim)))
        fallback_policy = os.getenv("SPIDER_EMBEDDING_FALLBACK_POLICY", "auto").strip().lower()
        batch_size = max(1, min(100, int(os.getenv("SPIDER_EMBEDDING_BATCH_SIZE", "64"))))
        emb_timeout = max(5.0, min(120.0, float(os.getenv("SPIDER_EMBEDDING_TIMEOUT_SECONDS", "30.0"))))

        profile_path = None if not configured_profile else (Path(configured_profile) if Path(configured_profile).is_absolute() else root / configured_profile)
        return cls(
            data_dir=data_dir.resolve(),
            user_agent=os.getenv("SPIDER_USER_AGENT", "LocalSEOSpider/0.1 (+local-authorized-audit)"),
            default_url_cap=int(os.getenv("SPIDER_DEFAULT_URL_CAP", "500")),
            max_url_cap=int(os.getenv("SPIDER_MAX_URL_CAP", "10000")),
            default_delay_seconds=float(os.getenv("SPIDER_DEFAULT_DELAY_SECONDS", "0.35")),
            request_timeout_seconds=float(os.getenv("SPIDER_REQUEST_TIMEOUT_SECONDS", "20")),
            render_timeout_ms=int(os.getenv("SPIDER_RENDER_TIMEOUT_SECONDS", "25000")),
            max_redirects=int(os.getenv("SPIDER_MAX_REDIRECTS", "8")),
            max_document_bytes=int(os.getenv("SPIDER_MAX_DOCUMENT_BYTES", "2097152")),
            max_request_retries=max(0, min(3, int(os.getenv("SPIDER_MAX_REQUEST_RETRIES", "2")))),
            retry_backoff_seconds=max(0.1, min(30.0, float(os.getenv("SPIDER_RETRY_BACKOFF_SECONDS", "0.5")))),
            max_concurrent_crawls=max(1, int(os.getenv("SPIDER_MAX_CONCURRENT_CRAWLS", "1"))),
            render_enabled=_as_bool(os.getenv("SPIDER_RENDER_ENABLED", "true")),
            extraction_profile_path=profile_path.resolve() if profile_path else None,
            embedding_provider=configured_embedding_provider,
            embedding_model=configured_model,
            embedding_dimension=max(8, min(4096, configured_dim)),
            embedding_fallback_policy=fallback_policy,
            gemini_api_key=gemini_key,
            embedding_batch_size=batch_size,
            embedding_timeout_seconds=emb_timeout,
            answer_provider=os.getenv("SPIDER_ANSWER_PROVIDER", "evidence"),
            ollama_url=os.getenv("SPIDER_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("SPIDER_OLLAMA_MODEL", "llama3.2"),
            answer_timeout_seconds=max(5.0, min(180.0, float(os.getenv("SPIDER_ANSWER_TIMEOUT_SECONDS", "45")))),
            crawl_executor_mode=os.getenv("SPIDER_CRAWL_EXECUTOR_MODE", "serial").strip().lower(),
            async_concurrency=max(1, min(32, int(os.getenv("SPIDER_ASYNC_CONCURRENCY", "8")))),
            thread_workers=max(1, min(16, int(os.getenv("SPIDER_THREAD_WORKERS", "4")))),
            process_workers=max(1, min(8, int(os.getenv("SPIDER_PROCESS_WORKERS", "2")))),
            allow_private_crawls=_as_bool(os.getenv("SPIDER_ALLOW_PRIVATE_CRAWLS", "false")),
        )
