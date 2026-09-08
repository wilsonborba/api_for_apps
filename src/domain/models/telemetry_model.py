from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClientErrorPayload(BaseModel):
    app_name: str = Field(min_length=2, max_length=80)
    app_version: Optional[str] = Field(default=None, max_length=50)
    environment: str = Field(min_length=2, max_length=32)
    route: Optional[str] = Field(default=None, max_length=300)
    error_title: str = Field(min_length=2, max_length=200)
    error_message: str = Field(min_length=1, max_length=4000)
    error_code: Optional[str] = Field(default=None, max_length=80)
    stack_trace: Optional[str] = Field(default=None, max_length=8000)
    request_id: Optional[str] = Field(default=None, max_length=100)
    user_agent: Optional[str] = Field(default=None, max_length=500)
    user_id: Optional[str] = Field(default=None, max_length=100)
    session_id: Optional[str] = Field(default=None, max_length=100)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    client_timestamp: Optional[str] = Field(default=None, max_length=50)
    server_timestamp: Optional[str] = Field(default=None, max_length=50)
    details: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class TelemetryDocumentModel(BaseModel):
    id: str
    app_name: str
    environment: str
    error_title: str
    error_message: str
    error_code: Optional[str] = None
    stack_trace: Optional[str] = None
    route: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    client_timestamp: Optional[str] = None
    server_timestamp: str
    details: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)
