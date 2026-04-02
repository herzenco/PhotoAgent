"""Data models for PhotoAgent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ImageRecord:
    """Mirrors the images table in the catalog database."""

    id: Optional[int] = None
    file_path: str = ""
    filename: str = ""
    extension: str = ""
    file_size: Optional[int] = None
    file_md5: Optional[str] = None
    perceptual_hash: Optional[str] = None
    date_taken: Optional[datetime] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    city: Optional[str] = None
    country: Optional[str] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    lens: Optional[str] = None
    iso: Optional[int] = None
    aperture: Optional[float] = None
    shutter_speed: Optional[str] = None
    flash_used: Optional[bool] = None
    orientation: Optional[int] = None
    file_created: Optional[datetime] = None
    file_modified: Optional[datetime] = None
    ai_caption: Optional[str] = None
    ai_tags: Optional[str] = None
    ai_scene_type: Optional[str] = None
    ai_quality_score: Optional[float] = None
    is_screenshot: bool = False
    is_duplicate_of: Optional[int] = None
    face_count: int = 0
    organization_status: str = "pending"
    scanned_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None


@dataclass
class FaceRecord:
    """A detected face and its embedding."""

    image_id: int = 0
    embedding: bytes = b""
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_w: Optional[float] = None
    bbox_h: Optional[float] = None
    cluster_id: Optional[int] = None
    cluster_label: Optional[str] = None


@dataclass
class ScanResult:
    """Summary of a filesystem scan operation."""

    total_found: int = 0
    new_images: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0


@dataclass
class AnalysisResult:
    """Summary of an image analysis batch."""

    total_processed: int = 0
    newly_analyzed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0


@dataclass
class ExecutionResult:
    """Summary of a file execution or undo operation."""

    total_planned: int = 0
    successful: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    conflicts_resolved: int = 0
    duration: float = 0.0
