"""Fixed local PDF text extraction, executed by the bounded parser supervisor."""
import hashlib
from importlib.metadata import version
from io import BytesIO
import logging

SOURCE_ID = 'workspace-pdf-text'
PARSER_VERSION = 'workspace-pdf-text@1'
MAX_PAGES = 2000
MAX_PAGE_CHARACTERS = 100_000
MAX_TEXT_CHARACTERS = 1_000_000
ERROR_CODES = frozenset({'document_pdf_invalid', 'document_pdf_too_many_pages', 'document_pdf_text_too_large'})


class DocumentPDFError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def extractor_version():
    return 'pdf-page-text@1+pypdf@' + version('pypdf')


def parse_document_pdf(data, document_id):
    from pypdf import PdfReader
    # Third-party parser diagnostics can contain original source values. The
    # supervisor publishes fixed errors and byte counts through its receipt.
    logger = logging.getLogger('pypdf')
    prior_level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        if not isinstance(data, bytes) or not data.startswith(b'%PDF-'):
            raise DocumentPDFError('document_pdf_invalid')
        reader = PdfReader(BytesIO(data))
        result = {'document_id': document_id, 'extractor_version': extractor_version(),
                  'status': 'encrypted', 'page_count': None, 'characters': 0, 'pages': []}
        if reader.is_encrypted:
            return result
        count = len(reader.pages)
        if count < 1:
            raise DocumentPDFError('document_pdf_invalid')
        if count > MAX_PAGES:
            raise DocumentPDFError('document_pdf_too_many_pages')
        for number, page in enumerate(reader.pages, 1):
            text = ' '.join((page.extract_text() or '').split())
            encoded = text.encode('utf-8', errors='strict')
            result['characters'] += len(text)
            if len(text) > MAX_PAGE_CHARACTERS or result['characters'] > MAX_TEXT_CHARACTERS:
                raise DocumentPDFError('document_pdf_text_too_large')
            result['pages'].append({'page': number, 'text': text,
                'text_hash': hashlib.sha256(encoded).hexdigest(),
                'status': 'text' if text else 'no_extractable_text'})
        text_pages = sum(page['status'] == 'text' for page in result['pages'])
        result.update(page_count=count, status='text_available' if text_pages == count
                      else 'partial_text' if text_pages else 'no_extractable_text')
        return result
    except DocumentPDFError:
        raise
    except Exception:
        raise DocumentPDFError('document_pdf_invalid') from None
    finally:
        logger.setLevel(prior_level)
