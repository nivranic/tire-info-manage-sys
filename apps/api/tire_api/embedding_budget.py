"""One UTC budget/pending gate shared by Responses and Embeddings requests."""
from datetime import timedelta

from sqlalchemy import select

from .ai_models import AICompletion, AIRequest
from .db import utcnow
from .embedding_models import EmbeddingCompletion, EmbeddingRequest

PENDING_WINDOW = timedelta(seconds=120)


def budget_usage(db):
    now = utcnow()
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(select(AIRequest.reserved_tokens, AICompletion.usage).outerjoin(
        AICompletion, AICompletion.request_id == AIRequest.id).where(AIRequest.created_at >= since)).all()
    rows += db.execute(select(EmbeddingRequest.reserved_tokens, EmbeddingCompletion.usage).outerjoin(
        EmbeddingCompletion, EmbeddingCompletion.request_id == EmbeddingRequest.id).where(
            EmbeddingRequest.created_at >= since, EmbeddingRequest.billable.is_(True))).all()
    pending_ai = db.scalar(select(AIRequest.id).outerjoin(AICompletion, AICompletion.request_id == AIRequest.id).where(
        AICompletion.request_id.is_(None), AIRequest.created_at > now - PENDING_WINDOW).limit(1))
    pending_embeddings = db.scalar(select(EmbeddingRequest.id).outerjoin(EmbeddingCompletion,
        EmbeddingCompletion.request_id == EmbeddingRequest.id).where(EmbeddingRequest.billable.is_(True),
        EmbeddingCompletion.request_id.is_(None), EmbeddingRequest.created_at > now - PENDING_WINDOW).limit(1))
    return {'day_utc': since.date().isoformat(), 'requests': len(rows),
            'accounted_tokens': sum(usage['total_tokens'] if usage else reserve for reserve, usage in rows),
            'has_pending_request': pending_ai is not None or pending_embeddings is not None,
            'accounting': 'provider_usage_when_available_otherwise_conservative_reservation'}
