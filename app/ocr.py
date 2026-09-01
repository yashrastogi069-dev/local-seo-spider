"""Optional local OCR helpers; failures remain explicit page-level evidence."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _tesseract_text(image: Path, timeout: int = 30) -> tuple[str, str]:
    binary = shutil.which("tesseract")
    if not binary:
        return "", "OCR unavailable: install Tesseract and ensure it is on PATH."
    try:
        completed = subprocess.run([binary, str(image), "stdout", "--psm", "6", "tsv"], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"OCR failed: {type(exc).__name__}."
    if completed.returncode != 0:
        return "", f"OCR failed with exit code {completed.returncode}."
    rows = completed.stdout.splitlines()
    words: list[str] = []
    confidences: list[float] = []
    for row in rows[1:]:
        columns = row.split("\t")
        if len(columns) >= 12 and columns[10] not in {"", "-1"}:
            try:
                confidence = float(columns[10])
                if confidence >= 0:
                    confidences.append(confidence)
            except ValueError:
                pass
            if columns[11].strip():
                words.append(columns[11].strip())
    text = " ".join(words)
    quality = f" OCR confidence {sum(confidences) / len(confidences):.1f}%" if confidences else " OCR confidence unavailable"
    return text, "OCR-derived text; verify against the source image." + quality + "."


def ocr_image(payload: bytes, suffix: str = ".bin", max_bytes: int = 10_000_000) -> tuple[str, str]:
    if not payload or len(payload) > max_bytes:
        return "", "OCR skipped: image is empty or exceeds the configured byte limit."
    with tempfile.TemporaryDirectory(prefix="local-seo-ocr-") as directory:
        image = Path(directory) / f"source{suffix if suffix.startswith('.') else '.' + suffix}"
        image.write_bytes(payload)
        return _tesseract_text(image)


def ocr_pdf(payload: bytes, max_pages: int = 8, max_bytes: int = 25_000_000) -> tuple[str, str]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return "", "OCR unavailable: pdftoppm is not installed."
    if not payload or len(payload) > max_bytes:
        return "", "OCR skipped: PDF is empty or exceeds the configured byte limit."
    with tempfile.TemporaryDirectory(prefix="local-seo-pdf-ocr-") as directory:
        root = Path(directory) / "page"
        source = Path(directory) / "source.pdf"
        source.write_bytes(payload)
        try:
            result = subprocess.run([pdftoppm, "-f", "1", "-l", str(max_pages), "-png", "-r", "150", str(source), str(root)], capture_output=True, text=True, timeout=90, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", f"PDF OCR rendering failed: {type(exc).__name__}."
        if result.returncode != 0:
            return "", f"PDF OCR rendering failed with exit code {result.returncode}."
        pages: list[str] = []
        note = ""
        for image in sorted(Path(directory).glob("page-*.png"))[:max_pages]:
            text, note = _tesseract_text(image)
            if text:
                pages.append(text)
        if pages:
            return "\n".join(pages), "OCR-derived text from image-only PDF; verify against the source document."
        return "", note or "OCR produced no text."
