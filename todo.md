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
