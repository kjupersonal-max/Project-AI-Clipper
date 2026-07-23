from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.services.discovery_transcription import benchmark_discovery_transcription
from app.services.transcription import reset_whisper_model_cache
from app.services.transcription_config import mark_cuda_unavailable, reset_cuda_availability_cache


def main() -> None:
    project_id = sys.argv[1] if len(sys.argv) > 1 else "6dbfd514-90f0-4241-bf18-51c6de001ff2"
    configure_logging("WARNING")
    mark_cuda_unavailable("cpu benchmark")
    reset_cuda_availability_cache()
    reset_whisper_model_cache()
    settings.whisper_device = "cpu"

    shutil.rmtree(Path("transcripts") / project_id, ignore_errors=True)
    started = time.perf_counter()
    report = benchmark_discovery_transcription(project_id, language="en", use_cache=False)
    elapsed = time.perf_counter() - started
    payload = report.to_dict()
    payload["measured_total_seconds"] = round(elapsed, 3)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
