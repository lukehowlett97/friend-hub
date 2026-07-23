from pydantic import BaseModel


class ImageEmbeddingJobStatusCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
