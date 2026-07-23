"""AI Agent Run model for tracking LLM interactions."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class AIAgentRun(Base):
    """Tracks AI agent runs for observability and debugging.
    
    Every LLM interaction (summarize, chat, etc.) creates a run record
    that captures the full context: prompt, response, validation, and results.
    """
    __tablename__ = "ai_agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Run configuration
    mode = Column(String(50), nullable=False)  # summarize, chat, etc.
    provider = Column(String(50), nullable=False)  # fake, ollama, openrouter
    model = Column(String(100), nullable=True)  # model name used
    
    # Run status
    status = Column(String(24), nullable=False, default="running")  # running, completed, failed
    
    # Input
    user_message = Column(Text, nullable=True)  # user's input message
    prompt_text = Column(Text, nullable=True)  # full prompt sent to LLM
    
    # Output
    raw_response = Column(Text, nullable=True)  # raw LLM response
    parsed_response = Column(JSON, nullable=True)  # parsed/structured response
    validation_errors = Column(JSON, nullable=True)  # any validation issues
    
    # Results
    created_memory_ids = Column(JSON, nullable=True)  # list of memory UUIDs (as strings)
    created_suggestion_ids = Column(JSON, nullable=True)  # list of suggestion UUIDs (as strings)
    tool_calls = Column(JSON, nullable=True)  # any tool calls made
    
    # Performance
    duration_ms = Column(Integer, nullable=True)  # execution time in milliseconds
    
    # Error handling
    error_message = Column(Text, nullable=True)  # error details if failed
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    completed_at = Column(DateTime, nullable=True)