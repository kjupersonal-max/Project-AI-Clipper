from __future__ import annotations

import os
import sys
from importlib import reload
from pathlib import Path


def test_env_file_points_to_backend_root():
    from app.core.config import BACKEND_ROOT, ENV_FILE

    assert ENV_FILE == BACKEND_ROOT / ".env"
    assert ENV_FILE.is_file()


def test_settings_load_backend_env_regardless_of_cwd(tmp_path, monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    env_file = backend_root / ".env"
    if not env_file.is_file():
        return

    original_cwd = Path.cwd()
    foreign_cwd = tmp_path / "foreign"
    foreign_cwd.mkdir()

    config_module_name = "app.core.config"
    sys.modules.pop(config_module_name, None)

    try:
        os.chdir(foreign_cwd)
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        import app.core.config as config_module

        reload(config_module)
        settings = config_module.settings

        assert settings.analysis_provider == "openai"
        assert bool(settings.analysis_api_key.strip())
    finally:
        os.chdir(original_cwd)
        sys.modules.pop(config_module_name, None)
        import app.core.config as config_module  # noqa: F401
