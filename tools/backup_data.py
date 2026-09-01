"""Create a safe local backup without copying secrets or live SQLite journals."""
from __future__ import annotations
import argparse
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def backup(project: Path, output: Path) -> Path:
    data = project / "data"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile_dir(output.parent) as staging:
        if (data / "local_seo_spider.sqlite3").exists():
            destination = staging / "data" / "local_seo_spider.sqlite3"
            destination.parent.mkdir(parents=True)
            source_conn = sqlite3.connect(data / "local_seo_spider.sqlite3")
            dest_conn = sqlite3.connect(destination)
            with dest_conn:
                source_conn.backup(dest_conn)
            dest_conn.close(); source_conn.close()
        for name in ("README.md", "local-seo-spider.env.example", "extraction-profile.example.json"):
            source = project / name
            if source.exists(): shutil.copy2(source, staging / name)
        exports = data / "exports"
        if exports.exists():
            for source in exports.rglob("*"):
                if source.is_file() and source.suffix not in {".db-wal", ".db-shm"}:
                    destination = staging / "data" / "exports" / source.relative_to(exports)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in staging.rglob("*"):
                if item.is_file(): archive.write(item, item.relative_to(staging))
    return output


class tempfile_dir:
    def __init__(self, parent: Path): self.parent = parent; self.path: Path | None = None
    def __enter__(self) -> Path:
        import tempfile
        self.path = Path(tempfile.mkdtemp(prefix="local-seo-backup-", dir=self.parent)); return self.path
    def __exit__(self, *_: object) -> None:
        if self.path: shutil.rmtree(self.path, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup local SEO Spider data without .env or environment files.")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    target = args.output or args.project / "backups" / f"local-seo-spider-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.zip"
    print(backup(args.project.resolve(), target.resolve()))
