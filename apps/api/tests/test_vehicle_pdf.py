"""Pure rejection gates; the real S2 positive is an explicit offline probe.

No PDF corpus, app/database import, SHA monkeypatch, or network is used here.
The separately recorded real-byte probe exercises the identical public parser.
"""
import pytest

from tire_api.adapters.xiaomi_first_generation_pdf import ReviewedPDFError, parse_reviewed_pdf


VEHICLE_ID = "xiaomi-su7-first-generation"


@pytest.mark.parametrize("raw", [None, "PDF text", bytearray(b"%PDF-1.7"), memoryview(b"%PDF-1.7"), 17, True])
def test_reviewed_pdf_rejects_non_bytes(raw):
    with pytest.raises(ReviewedPDFError, match="^parser_input_invalid$"):
        parse_reviewed_pdf(raw, VEHICLE_ID)


@pytest.mark.parametrize("vehicle_id", [None, 17, "", "xiaomi-su7-current", "xiaomi-su7-first-generation "])
def test_reviewed_pdf_rejects_unverified_vehicle_identity(vehicle_id):
    with pytest.raises(ReviewedPDFError, match="^vehicle_generation_not_verified$"):
        parse_reviewed_pdf(b"%PDF-1.7", vehicle_id)


def test_reviewed_pdf_rejects_empty_bytes():
    with pytest.raises(ReviewedPDFError, match="^parser_input_invalid$"):
        parse_reviewed_pdf(b"", VEHICLE_ID)


@pytest.mark.parametrize("raw", [b"PDF-1.7", b"%pdf-1.7", b" \n%PDF-1.7", b"{\"data\": []}"])
def test_reviewed_pdf_rejects_non_pdf_bytes(raw):
    with pytest.raises(ReviewedPDFError, match="^vehicle_pdf_invalid$"):
        parse_reviewed_pdf(raw, VEHICLE_ID)


def test_reviewed_pdf_rejects_over_budget_before_hash_acceptance():
    with pytest.raises(ReviewedPDFError, match="^parser_input_too_large$"):
        parse_reviewed_pdf(b"%PDF-" + b"x" * (8 * 1024 * 1024 - 4), VEHICLE_ID)


def test_reviewed_pdf_rejects_signature_only_synthetic_input():
    with pytest.raises(ReviewedPDFError, match="^vehicle_pdf_revision_unreviewed$"):
        parse_reviewed_pdf(b"%PDF-1.7\nsynthetic", VEHICLE_ID)


def test_reviewed_pdf_rejects_matching_size_with_unknown_hash():
    with pytest.raises(ReviewedPDFError, match="^vehicle_pdf_revision_unreviewed$"):
        parse_reviewed_pdf(b"%PDF-" + b"x" * (3240150 - 5), VEHICLE_ID)


def test_reviewed_pdf_does_not_claim_source_url_or_mime_validation():
    with pytest.raises(TypeError):
        parse_reviewed_pdf(b"%PDF-1.7", VEHICLE_ID, url="https://invalid.example/file.pdf", content_type="application/pdf")
