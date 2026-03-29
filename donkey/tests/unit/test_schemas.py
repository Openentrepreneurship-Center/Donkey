"""Pydantic 스키마 검증."""

import pytest
from pydantic import ValidationError

from app.schemas.response import AIResultBody, ConsultationSummary, ConversationItem


def test_consultation_summary_defaults():
    cs = ConsultationSummary()
    assert cs.doctorNotes == []
    assert cs.conversationContent == []


def test_conversation_item():
    item = ConversationItem(role="원장님", index=0, content="안녕하세요")
    assert item.role == "원장님"


def test_ai_result_body_requires_fields():
    with pytest.raises(ValidationError):
        AIResultBody()  # type: ignore[call-arg]
