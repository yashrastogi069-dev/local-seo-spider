# Local SQLite Job Ledger

## Purpose

The job ledger makes an authorized crawl request durable before execution begins. It replaces transient request-local scheduling with one local worker that claims one approved crawl job at a time. SQLite remains the sole source of truth: no broker, external queue, cluster, proxy service, or distributed worker is required.

## State model

| State | Meaning | Permitted transition |
| --- | --- | --- |
| `queued` | An approved crawl is waiting for the local worker. | `running`, `paused` |
| `running` | The sole local worker has claimed the job. | `completed`, `retryable`, `paused` |
| `retryable` | An unexpected worker-level error occurred; the job will only be attempted after a bounded delay. | `running`, `paused` |
| `paused` | The operator paused the job or the circuit breaker opened after repeated worker-level failures. | `queued` via explicit resume |
| `completed` | Crawl evidence and issues were persisted. | Terminal |
| `failed` | A non-retryable job configuration or persistence error was recorded. | `queued` via explicit resume after operator review |

The worker records each claim attempt, claim time, scheduled retry time, and explanatory error/pause reason. On application startup, an interrupted `running` job becomes `retryable` instead of being left permanently active. It may then be claimed by the single local worker.

## Recovery controls

Only unexpected worker-level exceptions invoke the retry schedule. Normal per-page HTTP and rendering failures remain evidence in a completed crawl; they do not restart the entire crawl. Retry delays are conservative and bounded. After the configured maximum number of attempts, the job enters `paused` with a circuit-breaker reason and cannot restart until the operator selects **Resume locally**.

The worker is deliberately global-singleton and serial: only one job can be running, and each job already constrains itself to one normalized authorized host, a request delay, a URL cap, a redirect limit, and robots-aware discovery. This prevents one local operator from accidentally turning the audit tool into a high-rate multi-target crawler.

## Operator interaction

The crawl ledger shows queue position, attempts, next retry time, and the most recent recovery reason. The operator can pause only work that has not yet been claimed and can explicitly resume a paused, retryable, or failed job. Resume returns the job to the local queue; it does not create a new target or loosen the original ownership acknowledgement or crawl settings.
