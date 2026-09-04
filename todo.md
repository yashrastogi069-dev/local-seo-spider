# Implementation Checklist

- [x] Record research-backed crawler controls and audit rules.
- [x] Build an explicit authorization acknowledgement that blocks crawling until accepted.
- [x] Implement local FastAPI, SQLite, Playwright, and HTMX application components.
- [x] Respect robots.txt, host scope, rate limits, canonicals, nofollow, redirects, and crawl caps.
- [x] Store repeated authorized crawls locally and surface comparison-ready histories.
- [x] Add marketing-oriented content inventory signals: title, description, headings, rendered text word count, image alternatives, schema types, and internal-link context.
- [x] Add a local content-opportunity view that aggregates evidence-backed metadata gaps and duplicate editorial signals without collecting third-party keyword or backlink datasets.
- [x] Detect and explain the requested technical SEO issues with evidence and remediation notes.
- [x] Export pages and issues to CSV plus a self-contained HTML audit report.
- [x] Add validation, safe filenames, loading/empty/success/recoverable-error states, and graceful fallback behavior.
- [x] Write focused unit and end-to-end tests, run them, and document the exact local setup and backup workflow.
- [x] Create a private GitHub repository and push only validated source and documentation; keep .env, local crawl data, exports, and environments excluded.
- [x] Exclude unpermissioned crawling, web-scale data harvesting, credential capture, and automated production-site changes.
- [x] Restart the development service and verify the local preview is reachable.
- [x] Review and improve the Field Manual interface with design and accessibility guidance.
- [x] Run comprehensive functional, export, security-boundary, and responsive interface verification.
- [x] Confirm the private GitHub repository is current after the validation update.
- [x] Provide a step-by-step explanation of the completed crawler and validation results.
- [x] Measure rendered text and status-color contrast against their actual surfaces and correct any verified failures.
- [x] Complete the standards-focused refinement and verification pass, then synchronize the final state to the private GitHub repository.
- [x] Research diverse authorized-site crawler failure modes and translate them into recoverable local controls.
- [x] Add robust retries, response-size protection, content-type handling, and non-stalling crawl status behavior.
- [x] Validate the hardened crawler against local adversarial fixtures for robots, timeouts, redirects, invalid HTML, non-HTML, and rendering failures.
- [x] Push the validated reliability hardening to the private GitHub repository.
- [x] Review persistent workload guidance and assess a locally controlled queue design for authorized crawl jobs.
- [x] Implement and test only the queueing improvements that preserve local-first storage, permission gating, and bounded crawl behavior.
- [x] Add a durable SQLite job ledger with queued, running, paused, retryable, completed, and failed states for authorized crawl jobs.
- [x] Add one-worker dispatch, bounded retry scheduling, circuit-breaker pauses, and operator-controlled resume behavior.
- [x] Expose clear local job-state and resume controls in the Field Manual interface.
- [x] Test durable job recovery and existing audit behavior, then synchronize the implementation to private GitHub.
- [x] Add and validate a Windows Command Prompt launcher and document its first-run commands.
- [x] Run `run-local.cmd` in an actual Windows CMD environment and fix any Windows-specific path, quoting, venv, pip, or Playwright issues.
- [x] Add a focused validation step or CI check for future changes.
- [x] Decide whether a `.bat` alias adds value beyond the validated `run-local.cmd`, and document the simplest Windows launch path.
- [x] Fix Windows launcher output to show `http://127.0.0.1:<port>/` instead of the bind address `http://0.0.0.0:<port>/`, and add regression coverage.
- [x] Define the local-first knowledge-crawler data model and RAG grounding rules.
- [x] Extract crawl content into citation-preserving, searchable knowledge chunks.
- [x] Add SQLite FTS5 retrieval with URL, heading, crawl, and evidence provenance.
- [x] Add a question-answering interface that abstains when evidence is insufficient.
- [x] Add crawl-to-knowledge indexing, refresh, comparison, and recoverable error states.
- [x] Document and test a narrow automation boundary for future n8n-style workflows without unsafe site mutations.
- [x] Run end-to-end retrieval and grounding tests, update documentation, and synchronize the feature to private GitHub.
- [x] Add an explicit reindex/refresh action for existing completed crawls with success and error states.
- [x] Implement knowledge comparison between completed crawls, including changed evidence chunks.
- [x] Add recoverable knowledge-index loading, empty, and failure states with tests.
- [x] Bind the Unix launcher to loopback as well so the local knowledge API is not exposed to the LAN by default.
- [x] Push the completed knowledge and RAG changes to private GitHub and verify local and remote SHAs match.
- [x] Add explicit loading states for question and reindex HTMX actions and test them.
- [x] Add a dedicated empty-index state when a completed crawl has zero searchable knowledge chunks and test it.
- [x] Push the completed knowledge/RAG changes to private GitHub and record matching local and remote SHAs (`cce4b1c917cbb62809e18206e897632f3c1616de`).
- [x] Define the expanded end-to-end website/document crawler contract, local data model, and privacy boundaries.
- [x] Expand authorized acquisition and parsing for HTML, rendered DOM, PDFs, text resources, and unsupported-content evidence with explicit limits; image OCR remains a documented partial-support boundary.
- [x] Build a complete local knowledge corpus with provenance, versioning, refresh, and crawl comparison.
- [x] Validate end-to-end retrieval and answer grounding before adding generative RAG.
- [x] Design and implement hybrid lexical/vector RAG with local embeddings, chunking, vector storage, reranking, and citations.
- [x] Add optional local Sentence Transformers embedding installation and model metadata without changing the offline default.
- [x] Add optional local answer synthesis with strict evidence-only prompting and deterministic fallback.
- [x] Add agentic RAG planning, confidence, abstention, evaluation, and recovery controls.
- [x] Add retrieval evaluation fixtures and confidence calibration against grounded and unrelated questions.
- [x] Design and implement safe n8n-like nodes, triggers, workflow runs, and local database adapters after the RAG layer is stable.
- [x] Add a manual workflow trigger and a crawl-completed local trigger with bounded execution.
- [x] Add workflow activation, trigger filtering, and run-history recovery states.
- [x] Expose bounded workflow run history through a read-only local API for recovery and inspection.
- [x] Run full adversarial tests, document exact local usage, and synchronize every milestone to private GitHub (`322f20962e723527094bf866aa190376a4f46794`).
- [x] Audit the current crawler against target-field extraction, static/dynamic acquisition, Pydantic validation, storage formats, and concurrency modes.
- [x] Add configurable target-field extraction profiles with provenance and bounded static/dynamic behavior.
- [x] Add Pydantic-validated extraction and export models plus JSON/JSONL/CSV/SQLite storage paths.
- [x] Add selectable coroutine, threaded, and multiprocessing execution modes with bounded resource controls.
- [x] Add local UI/configuration controls and document when each concurrency mode is appropriate.
- [x] Add adversarial and performance regression coverage, update documentation, and synchronize the advanced scraping milestone to private GitHub (`9b211641b2fa855b049f721bb5dcbf133c37914c`).
- [x] Add a CI-safe executor performance/concurrency regression assertion that protects bounded parallel work without flaky wall-clock thresholds.
- [x] Push the post-validation performance-coverage update to private GitHub and verify local and remote SHAs match (`8492fdab1ac702b9fdf4385488e212e13be6ffe6`).
- [x] Add data collection, cleaning, normalization, and Pydantic-validated processing pipelines for crawl records and target fields.
- [x] Add bounded recursive traversal for normalized links, discovered API entry points, and target-data extraction while preserving host, robots, cap, and permission boundaries.
- [x] Add OCR for images and image-only PDFs with OCR confidence and explicit derived-evidence provenance.
- [x] Add a safe Windows backup command for local SQLite data, exports, and non-secret configuration.
- [x] Add an executor benchmark report covering serial, threaded, coroutine, and multiprocessing modes without flaky thresholds.
- [x] Strengthen rate control and HTTP error handling with transparent user-agent policy and Retry-After-aware bounded recovery.
- [x] Document the parsing library stack and validate static and dynamic parsing behavior with adversarial fixtures.
- [x] Validate all additions, update documentation, checkpoint, and push the complete milestone to private GitHub.
- [x] Document serial, thread, async, and process executor trade-offs and safe use cases in README/docs.
- [x] Test that FastAPI accepts and persists per-crawl executor and extraction-profile fields.

- [x] Fix irrelevant hybrid retrieval and random answers by tracing query tokenization, chunk ranking, answer context assembly, and confidence/abstention gates.
- [x] Add regression tests for exact-fact retrieval, distractor documents, citation correctness, and unsupported-question abstention.
- [x] Validate RAG fixes with the full test suite and an end-to-end crawl/query smoke test.
- [x] Save and synchronize the grounded RAG fix to the private GitHub repository.

- [x] Complete the remaining data processing, normalization, and recursive URL/API traversal milestone.
- [x] Add bounded OCR for images and image-only PDFs with derived-evidence provenance.
- [x] Add safe Windows-native backup tooling and a reproducible executor benchmark report.
- [x] Add Retry-After-aware rate control, transparent User-Agent documentation, and HTTP recovery tests.
- [x] Run the full validation suite, update usage documentation, checkpoint, and push the completed milestone to private GitHub.

- [x] Add Pydantic validation for normalized page/crawl processing outputs and test end-to-end normalized persistence.
- [x] Extend recursive traversal to inspect returned JSON/text payloads for same-host URL/API references under robots and caps.
- [x] Capture OCR confidence/quality metadata in derived evidence and test image/PDF provenance.
- [x] Include local export files in safe backups while excluding secrets and transient SQLite journals.
- [x] Harden benchmark input scope and validate a generated JSON report artifact.
- [x] Add explicit parser-stack documentation and adversarial static/dynamic parsing tests.

- [x] Replace default hash-vector retrieval with a configurable real local semantic embedding provider and explicit model/index metadata.
- [x] Improve complex-query decomposition, semantic reranking, diversity, and evidence thresholds for grounded answers.
- [x] Add an optional post-retrieval LLM synthesis layer with strict citation-only prompting, structured output validation, timeout, and deterministic fallback.
- [x] Add end-to-end RAG quality tests for semantic paraphrases, multi-hop questions, distractors, citations, abstention, and LLM failure fallback.
- [x] Document setup, model installation, privacy boundaries, and exact commands for the semantic RAG and LLM layers.

- [x] Review the northstar GitHub repository and relevant open-source crawler/RAG patterns for safe, reusable design ideas.
- [x] Replace the default hash-vector path with a real local semantic embedding workflow and model/index lifecycle.
- [x] Upgrade structure-aware chunking, query decomposition, hybrid retrieval, reranking, diversity, and multi-hop evidence assembly.
- [x] Add an optional final LLM layer with strict evidence-only prompting, citation validation, timeout, and deterministic fallback.
- [x] Add end-to-end quality tests for semantic paraphrases, complex questions, distractors, citations, abstention, and LLM failure.
- [x] Checkpoint and synchronize the upgraded crawler/RAG milestone to the private GitHub repository.

- [x] Make real local semantic embeddings the active default and never silently downgrade configured semantic mode to hash vectors.
- [x] Add dense-first retrieval with candidate expansion, score calibration, source diversity, and explicit lexical-complement diagnostics.
- [x] Add structure-aware chunk metadata and complex-query evidence-set assembly for multi-part and multi-hop questions.
- [x] Enforce final-answer citation validation and deterministic abstention when semantic evidence is weak or contradictory.
- [x] Add quality evaluation for paraphrases, exact facts, multi-part questions, distractors, unsupported queries, and LLM failures.
- [x] Run full validation, checkpoint, and synchronize the upgraded semantic RAG implementation to private GitHub.

- [x] Update the end-to-end crawl test to wait for the durable semantic index completion after crawl completion, while preserving visible recovery behavior when indexing is unavailable.

- [x] Implement and test source-diversity controls plus explicit lexical-versus-semantic diagnostic metadata in retrieval results.
- [x] Add regression coverage and retrieval evidence-set assembly for multi-part and multi-hop questions.
- [x] Add contradictory-evidence detection and safe abstention behavior with tests.
- [x] Save a new recoverable checkpoint and push/verify the semantic-RAG upgrade on private GitHub after these gaps are closed.

- [x] Add true crawl-to-index-to-retrieve-to-answer tests for semantic paraphrases, distractor pages, citation validation, abstention, and LLM fallback.
- [x] Assert hybrid retrieval exposes semantic score, lexical-match, term-coverage, and fusion diagnostics.
- [x] Implement explicit bounded multi-hop evidence assembly with hop provenance and regression coverage.
- [x] Save a new recoverable checkpoint and push/verify the semantic-RAG upgrade after all quality gaps pass.

- [x] Add a true background-worker-path crawl-to-index-to-answer regression using the real semantic provider, including paraphrase retrieval, distractor rejection, abstention, and LLM fallback.

- [x] Assert end-to-end semantic retrieval excludes the distractor page from the supported answer evidence and citations.

- [x] Add structured JSON response validation for optional LLM synthesis, including answer and citation fields with safe freeform fallback handling.
- [x] Add a true worker-path end-to-end multi-hop evidence test across indexed supporting pages.
- [x] Add a full crawl/index/retrieve test proving malformed or uncited LLM output is rejected.

- [x] Add a worker-path end-to-end semantic RAG test where supporting facts live across multiple indexed pages and verify answer assembly plus hop provenance.
- [x] Add a crawl-to-index-to-retrieve malformed structured-LLM fallback regression through the application path.

- [x] Assert the multi-hop end-to-end answer text itself combines both indexed facts, not only their citations and hop metadata.
