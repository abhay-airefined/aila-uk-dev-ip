from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class Message(BaseModel):
    role: str = Field(..., description="Role of the message sender (user/assistant)")
    content: str = Field(..., description="Content of the message")
    timestamp: Optional[datetime] = Field(default=None, description="Message timestamp")

class ChatRequest(BaseModel):
    message: str = Field(..., description="User chat message")
    lat: Optional[str] = Field(default=None, description="User's latitude for location-based queries")
    long: Optional[str] = Field(default=None, description="User's longitude for location-based queries")
    session_id: Optional[str] = Field(default=None, description="Unique session identifier for conversation history")

class ChatResponse(BaseModel):
    message: str = Field(..., description="Assistant response message")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Source documents used for the response")
    session_id: str = Field(..., description="Session identifier for the conversation")
    history: List[Message] = Field(default_factory=list, description="Updated conversation history")

class StreamChatResponse(BaseModel):
    chunk: str = Field(..., description="A chunk of the streaming response")
    is_final: bool = Field(default=False, description="Whether this is the final chunk")
    session_id: Optional[str] = Field(default=None, description="Session identifier for the conversation")
    
class IngestRequest(BaseModel):
    type: str = Field(..., description="Type of document to ingest: 'decision' or 'appeal'")
    page_start: int = Field(..., description="Page number of the document to ingest")
    page_end: int = Field(..., description="Page number of the document to ingest")
    page_size: int = Field(..., description="Page size of the document to ingest")
    sleep_seconds: int = Field(..., description="Sleep seconds between pages")
    jurisdiction_code: Optional[str] = Field(default=None, description="Jurisdiction code of the document to ingest")