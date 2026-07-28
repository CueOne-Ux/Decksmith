"""Executable entry point for Decksmith's bundled Demucs engine."""

import importlib.metadata
import os
import platform
import sys
from pathlib import Path


if len(sys.argv) == 2 and sys.argv[1] == "--decksmith-capability":
    print(f"{importlib.metadata.version('demucs')}\t{platform.python_version()}")
    raise SystemExit(0)

model_directory = Path(os.environ.get("DECKSMITH_MODEL_DIR", ""))
if model_directory.is_dir():
    import huggingface_hub

    def bundled_model_file(_repo_id: str, filename: str, *args, **kwargs) -> str:
        path = model_directory / Path(filename).name
        if not path.is_file():
            raise FileNotFoundError(f"Bundled Demucs model file is missing: {path.name}")
        return str(path)

    huggingface_hub.hf_hub_download = bundled_model_file

from demucs.separate import main


if __name__ == "__main__":
    main()
