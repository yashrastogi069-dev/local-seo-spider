from app.documents import extract_document_text


def minimal_text_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length 57 >>\nstream\nBT /F1 12 Tf 72 720 Td (Local PDF policy evidence) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    return bytes(pdf)


def test_extract_text_like_document() -> None:
    text, error = extract_document_text("text/plain", b"A local policy and support guide.")
    assert text == "A local policy and support guide."
    assert error == ""


def test_extract_pdf_text_layer() -> None:
    text, error = extract_document_text("application/pdf", minimal_text_pdf())
    assert "Local PDF policy evidence" in text
    assert error == ""


def test_unsupported_binary_is_explicit() -> None:
    text, error = extract_document_text("application/octet-stream", b"binary")
    assert text == ""
    assert "No text extractor configured" in error


def test_extract_json_semantics_nested_and_nulls() -> None:
    import json
    data = {
        "total": 100,
        "indicator": "NY.GDP.MKTP.CD",
        "description": None,
        "items": [
            {"id": 1, "name": "Item 1", "active": True, "deleted_at": None},
            {"id": 2, "name": "Item 2", "active": False, "deleted_at": "2026-01-01"},
        ],
        "metadata": {
            "version": "1.0",
            "environment": "production",
            "deprecated": False,
        },
    }
    payload = json.dumps(data).encode("utf-8")
    text, error = extract_document_text("application/json", payload)
    assert error == ""
    assert "field = total, value = 100" in text
    assert "NY.GDP.MKTP.CD" in text
    assert "items[0]: id = 1 | name = Item 1 | active = True" in text
    assert "items[1]: id = 2 | name = Item 2 | active = False" in text
    assert "metadata.version = 1.0" in text
    assert "metadata.environment = production" in text
