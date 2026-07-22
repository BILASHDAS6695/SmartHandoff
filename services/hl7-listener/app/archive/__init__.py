"""Archive sub-package — GCS raw HL7 message archival and fallback queue.

Exports:
  GCSArchiver       — async-capable GCS uploader with retry and fallback
  FallbackQueue     — bounded in-memory deque with background flush task

Design refs:
    AIR-003  — archive every raw HL7 message before ACK
    DR-015   — raw HL7 archive retention: 7 years, HIPAA bucket
    BR-020   — no PHI in GCS metadata
"""
from app.archive.gcs_archiver import GCSArchiver
from app.archive.fallback_queue import FallbackQueue

__all__ = ["GCSArchiver", "FallbackQueue"]
