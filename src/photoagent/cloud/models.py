"""Data models for cloud vision analysis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CloudAnalysisResult:
    """Result of a single cloud-based image analysis."""

    image_path: str
    category: str
    subcategory: str
    subject: str
    mood: str
    tags: list[str]
    quality_note: str | None
    model: str
    input_tokens: int
    output_tokens: int
    thumb_byte_size: int
    analyzed_at: str  # ISO timestamp
