"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application-wide settings sourced from .env / environment."""

    # Ollama (OpenAI-compatible local LLM)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    # Embedding (local path under models/ or HuggingFace model name)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    MODELS_DIR: Path = Path(__file__).resolve().parent.parent / "models"

    # Neo4j
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

    # Repo indexing
    REPO_ROOT: Path = Path(os.getenv("REPO_ROOT", ".")).resolve()
    INDEX_EXTENSIONS: list[str] = os.getenv(
        "INDEX_EXTENSIONS", ".py,.cpp,.h,.hpp,.cs,.f90,.f95,.f03,.f08,.for,.fpp,.f,.kt,.kts,.ps1,.psm1,.psd1,.ts,.tsx,.js,.jsx"
    ).split(",")
    SKIP_DIRS: set[str] = set(
        os.getenv(
            "SKIP_DIRS",
            ".git,node_modules,__pycache__,.venv,bin,obj,Debug,Release,build,dist",
        ).split(",")
    )
    ACTIVE_PROJECT: str = os.getenv("ACTIVE_PROJECT", "_full_")

    # Paths
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    GRAPH_CACHE_PATH: Path = Path(
        os.getenv("GRAPH_CACHE_PATH", str(PROJECT_ROOT / "data" / "code_graph.pkl"))
    )


settings = Settings()
