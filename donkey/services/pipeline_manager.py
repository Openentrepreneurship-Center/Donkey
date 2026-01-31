"""Thread-safe singleton manager for pyannote pipeline."""

import threading
from typing import Optional

from openai import OpenAI
from pyannote.audio import Pipeline

from donkey.config import get_settings


class PipelineManager:
    """
    Thread-safe singleton manager for pyannote diarization pipeline.

    Ensures the heavy pipeline model is loaded only once and provides
    thread-safe access to prevent concurrent diarization issues.
    """

    _instance: Optional["PipelineManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PipelineManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._settings = get_settings()
        self._pipeline: Optional[Pipeline] = None
        self._openai_client: Optional[OpenAI] = None
        self._pipeline_lock = threading.Lock()
        self._ready = False
        self._initialized = True

    def initialize(self) -> None:
        """
        Initialize the pipeline and OpenAI client.
        Should be called at server startup.
        """
        if self._ready:
            return

        with self._pipeline_lock:
            if self._ready:
                return

            # Initialize OpenAI client
            self._openai_client = OpenAI(api_key=self._settings.openai_api_key)

            # Load pyannote pipeline
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=self._settings.hf_token,
            )

            self._ready = True

    @property
    def is_ready(self) -> bool:
        """Check if the pipeline is loaded and ready."""
        return self._ready

    @property
    def pipeline(self) -> Pipeline:
        """Get the diarization pipeline (thread-safe)."""
        if not self._ready or self._pipeline is None:
            raise RuntimeError("Pipeline not initialized. Call initialize() first.")
        return self._pipeline

    @property
    def openai_client(self) -> OpenAI:
        """Get the OpenAI client."""
        if not self._ready or self._openai_client is None:
            raise RuntimeError("OpenAI client not initialized. Call initialize() first.")
        return self._openai_client

    @property
    def diarization_lock(self) -> threading.Lock:
        """
        Get the lock for diarization operations.
        Use this to ensure only one diarization runs at a time.
        """
        return self._pipeline_lock


def get_pipeline_manager() -> PipelineManager:
    """Get the singleton PipelineManager instance."""
    return PipelineManager()
