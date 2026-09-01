from pathlib import Path

from tools.backup_data import backup
from tools import benchmark_executors


def test_backup_includes_exports_but_excludes_environment(tmp_path: Path) -> None:
    (tmp_path / "data" / "exports").mkdir(parents=True)
    import sqlite3
    connection = sqlite3.connect(tmp_path / "data" / "local_seo_spider.sqlite3")
    connection.execute("CREATE TABLE marker (value TEXT)")
    connection.commit()
    connection.close()
    (tmp_path / "data" / "exports" / "report.html").write_text("report", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    output = tmp_path / "backup.zip"
    backup(tmp_path, output)
    import zipfile
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "data/exports/report.html" in names
    assert ".env" not in names


def test_benchmark_writes_report_and_validates_scope(tmp_path: Path, monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, settings): pass
        def run(self, request, progress): return ([object()], [object(), object()], "loaded")
    monkeypatch.setattr(benchmark_executors, "CrawlEngine", FakeEngine)
    output = tmp_path / "benchmark.json"
    benchmark_executors.run(["https://owned.example/", "https://owned.example/about"], ["serial", "thread"], output)
    import json
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [row["executor_mode"] for row in payload["benchmark"]] == ["serial", "thread"]
    assert payload["benchmark"][0]["pages"] == 1
