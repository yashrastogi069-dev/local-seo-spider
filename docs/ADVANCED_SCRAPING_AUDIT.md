# Advanced Scraping Capability Audit

## Baseline

The current project already has a bounded, permission-gated crawler rather than an unrestricted scraping system. It uses direct HTTP retrieval for source documents, Playwright for one rendered browser inspection per page, BeautifulSoup-based signal extraction, SQLite persistence, and CSV/self-contained HTML exports.

| Requested capability | Baseline status | Upgrade required |
| --- | --- | --- |
| Static web page extraction | Implemented for SEO signals, links, images, structured data, source HTML, and rendered text | Add operator-defined target fields and richer structured output |
| Dynamic web page extraction | Implemented through bounded Playwright DOM rendering | Add configurable selector profiles; keep browser actions read-only and bounded |
| Dynamic data extraction | Partial | Add selectors for CSS, XPath, attribute, text, and JSON-LD paths; do not execute arbitrary scripts |
| Target-field extraction | Not yet profile-driven | Add validated extraction profiles with per-field evidence and missing-field states |
| Pydantic validation | Not yet the primary record boundary; dataclasses are used | Introduce Pydantic v2 models at input/extraction/export boundaries while preserving SQLite compatibility |
| Storage layer | SQLite is implemented; CSV and self-contained HTML exports are implemented | Add JSON and JSONL exports and a format-neutral validated export model |
| Coroutines | Not implemented for crawl execution | Add bounded async HTTP executor for I/O-heavy static crawling |
| Multithreading | Not implemented for crawl execution | Add bounded thread executor for blocking/browser-compatible work |
| Multiprocessing | Not implemented for crawl execution | Add opt-in process executor for CPU-heavy parsing/embedding/export work; never use it to bypass site limits |
| Robots, host scope, caps, delays, retries | Implemented and must remain enforced in every executor | Add shared policy context and tests across execution modes |
| Images and image-only PDFs | Explicitly reported as partial/unsupported | Keep explicit notes unless a separately installed local OCR pipeline is enabled |

## Design decisions

The upgrade will use **capability profiles**, not arbitrary code injection. A profile names target fields and describes bounded selectors or structured-data paths. Every extracted value is accompanied by selector, URL, content type, and extraction status evidence. Missing values are represented as missing, not inferred.

Concurrency changes will be selectable per crawl but remain bounded by the existing URL cap, request delay, retry limit, response-size limit, and host scope. A higher worker count must never remove the per-host politeness policy. Playwright rendering will remain isolated because browser contexts are stateful and expensive; static HTTP work is the first candidate for asynchronous concurrency.

Storage will remain local-first. SQLite remains the system of record. JSON and JSONL are portable interchange formats, CSV is spreadsheet-friendly, and HTML remains the human-readable report. No external queue, hosted vector database, telemetry service, or third-party data harvesting is required.
