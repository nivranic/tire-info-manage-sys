"""One UTC budget/pending gate shared by Responses and Embeddings requests."""
from datetime import datetime, timedelta

from sqlalchemy import select

from .ai_models import AIRequest, AICompletion
from .db import utcnow
from .embedding_models import EmbeddingRequest, EmbeddingCompletion

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


def budget_history(db, days: int):
    """按 UTC 日聚合的 AI/嵌入用量历史（只读；含今天共 days 天，空日补零）。"""
    now = utcnow()
    since_day = now.date() - timedelta(days=days - 1)
    since = datetime(since_day.year, since_day.month, since_day.day)
    rows = db.execute(select(AIRequest.created_at, AIRequest.reserved_tokens, AICompletion.usage).outerjoin(
        AICompletion, AICompletion.request_id == AIRequest.id).where(AIRequest.created_at >= since)).all()
    rows += db.execute(select(EmbeddingRequest.created_at, EmbeddingRequest.reserved_tokens, EmbeddingCompletion.usage).outerjoin(
        EmbeddingCompletion, EmbeddingCompletion.request_id == EmbeddingRequest.id).where(
            EmbeddingRequest.created_at >= since, EmbeddingRequest.billable.is_(True))).all()
    by_day: dict = {}
    for created_at, reserve, usage in rows:
        day = by_day.setdefault(created_at.date(), [0, 0])
        day[0] += 1
        day[1] += usage['total_tokens'] if usage else reserve
    return {'since_date': since_day.isoformat(), 'until_date': (since_day + timedelta(days=days - 1)).isoformat(),
            'days': [{'date': (since_day + timedelta(days=offset)).isoformat(),
                      'requests': by_day.get(since_day + timedelta(days=offset), [0, 0])[0],
                      'accounted_tokens': by_day.get(since_day + timedelta(days=offset), [0, 0])[1]}
                     for offset in range(days)],
            'accounting': 'provider_usage_when_available_otherwise_conservative_reservation'}
