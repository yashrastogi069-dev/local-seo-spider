"""Reproducible local CSV and self-contained HTML audit exports."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from app.urltools import safe_filename


def _export_dir(data_dir: Path) -> Path:
    path = data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _base_name(crawl: dict[str, Any]) -> str:
    stamp = crawl["created_at"].replace(":", "").replace("+00:00", "Z")
    return safe_filename(f"seo-audit-{crawl['start_url']}-{stamp}")


def write_csv_exports(data_dir: Path, crawl: dict[str, Any], pages: list[dict[str, Any]], issues: list[dict[str, Any]]) -> tuple[Path, Path]:
    root = _export_dir(data_dir)
    base = _base_name(crawl)
    pages_path = root / f"{base}-pages.csv"
    issues_path = root / f"{base}-issues.csv"
    with pages_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["url", "final_url", "status_code", "content_type", "title", "description", "h1", "canonical", "meta_robots", "x_robots", "robots_allowed", "internal_inlinks", "rendered_word_count", "image_count", "images_missing_alt", "structured_data_types", "fetch_error", "render_error"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for page in pages:
            writer.writerow({
                "url": page["url"], "final_url": page["final_url"], "status_code": page["status_code"], "content_type": page["content_type"], "title": page["title"], "description": page["description"],
                "h1": " | ".join(page["headings"].get("h1", [])), "canonical": page["canonical"], "meta_robots": page["meta_robots"], "x_robots": page["x_robots"], "robots_allowed": page["robots_allowed"],
                "internal_inlinks": page["internal_inlinks"], "rendered_word_count": len(page["rendered_text"].split()), "image_count": len(page["images"]),
                "images_missing_alt": sum(not image.get("has_alt") or not image.get("alt", "").strip() for image in page["images"]),
                "structured_data_types": " | ".join(sorted({item for block in page["structured_data"] for item in block.get("types", [])})), "fetch_error": page["fetch_error"], "render_error": page["render_error"],
            })
    with issues_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["severity", "title", "url", "evidence", "remediation", "rule_key", "fingerprint"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(issues)
    return pages_path, issues_path


def write_html_report(data_dir: Path, crawl: dict[str, Any], pages: list[dict[str, Any]], issues: list[dict[str, Any]]) -> Path:
    root = _export_dir(data_dir)
    destination = root / f"{_base_name(crawl)}-report.html"
    severity_counts = {severity: sum(issue["severity"] == severity for issue in issues) for severity in ("critical", "high", "medium", "low")}
    def esc(value: Any) -> str:
        return html.escape(str(value or ""))
    issue_rows = "".join(
        f"<tr><td><span class='sev {esc(issue['severity'])}'>{esc(issue['severity'])}</span></td><td><strong>{esc(issue['title'])}</strong><br><small>{esc(issue['rule_key'])}</small></td><td class='url'>{esc(issue['url'])}</td><td>{esc(issue['evidence'])}</td><td>{esc(issue['remediation'])}</td></tr>" for issue in issues
    ) or "<tr><td colspan='5'>No issues were recorded.</td></tr>"
    page_rows = "".join(
        f"<tr><td class='url'>{esc(page['url'])}</td><td>{esc(page['status_code'])}</td><td>{esc(page['title'])}</td><td>{esc(page['canonical'])}</td><td>{esc(page['meta_robots'] or page['x_robots'])}</td></tr>" for page in pages
    ) or "<tr><td colspan='5'>No pages were recorded.</td></tr>"
    destination.write_text(f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Local SEO Spider audit</title><style>
    :root{{--ink:#182523;--paper:#f7f4ee;--spruce:#173d3a;--amber:#c96b16;--brick:#af3e37;--line:#d7d2c8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1440px;margin:auto;padding:44px 30px}}header{{border-bottom:4px solid var(--spruce);padding-bottom:22px;display:flex;justify-content:space-between;gap:24px;align-items:end}}h1{{font-size:38px;line-height:1;margin:0;color:var(--spruce)}}h2{{font-size:20px;margin:42px 0 12px}}.stamp{{font:700 12px ui-monospace,monospace;letter-spacing:.08em;color:var(--spruce);border:1px solid var(--spruce);padding:5px 8px}}.stats{{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}}.stat{{background:#fff;border:1px solid var(--line);padding:14px 18px;min-width:112px}}.stat strong{{display:block;font-size:24px;color:var(--spruce)}}table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}th,td{{text-align:left;vertical-align:top;padding:11px;border-bottom:1px solid var(--line)}}th{{background:#e9eee9;color:var(--spruce);font:700 11px ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase}}.url{{font-family:ui-monospace,monospace;overflow-wrap:anywhere;max-width:260px}}.sev{{display:inline-block;padding:2px 6px;border-radius:3px;font:700 11px ui-monospace,monospace;text-transform:uppercase}}.critical{{background:#f8dfdc;color:#802620}}.high{{background:#fff0d7;color:#855014}}.medium{{background:#e8efed;color:#235a52}}.low{{background:#eaebea;color:#4c5553}}small{{color:#5e6966}}@media print{{main{{padding:20px}}}}
    </style></head><body><main><header><div><p class='stamp'>LOCAL • REPRODUCIBLE AUDIT</p><h1>SEO inspection ledger</h1><p>{esc(crawl['start_url'])}<br>Created {esc(crawl['created_at'])} · Completed {esc(crawl.get('completed_at', ''))}</p></div><p class='stamp'>OWNERSHIP ACKNOWLEDGED</p></header><section class='stats'><div class='stat'><strong>{len(pages)}</strong>pages recorded</div><div class='stat'><strong>{len(issues)}</strong>issues recorded</div>{''.join(f"<div class='stat'><strong>{count}</strong>{severity}</div>" for severity, count in severity_counts.items())}</section><h2>Prioritized findings</h2><table><thead><tr><th>Severity</th><th>Finding</th><th>Affected URL</th><th>Evidence</th><th>Remediation</th></tr></thead><tbody>{issue_rows}</tbody></table><h2>Page inventory</h2><table><thead><tr><th>URL</th><th>Status</th><th>Title</th><th>Canonical</th><th>Robots</th></tr></thead><tbody>{page_rows}</tbody></table><p><small>Generated locally by Local SEO Spider. This report contains crawl evidence captured under the operator’s explicit authorization acknowledgement.</small></p></main></body></html>""", encoding="utf-8")
    return destination
