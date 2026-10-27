import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.memory.search")

_chroma_client = None
_collection = None
_enabled = False


def init_semantic_search(enabled: bool = False, db_path: str = "chroma_db"):
    global _chroma_client, _collection, _enabled
    _enabled = enabled
    if not enabled:
        logger.info("Busqueda semantica deshabilitada")
        return

    try:
        import chromadb
        from chromadb.config import Settings

        chroma_dir = Path(__file__).parent.parent / db_path
        chroma_dir.mkdir(exist_ok=True)

        _chroma_client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _chroma_client.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB inicializado en %s", chroma_dir)
    except ImportError:
        logger.warning("chromadb no instalado. Instala con: pip install chromadb")
        _enabled = False
    except Exception as e:
        logger.error("Error inicializando ChromaDB: %s", e)
        _enabled = False


def is_enabled() -> bool:
    return _enabled and _collection is not None


def store_memory(text: str, source: str = "conversation", metadata: dict = None):
    if not is_enabled():
        return

    try:
        meta = {"source": source}
        if metadata:
            meta.update(metadata)

        _collection.add(
            documents=[text],
            metadatas=[meta],
            ids=[f"mem_{_collection.count() + 1}"],
        )
        logger.debug("Memoria almacenada: %s...", text[:50])
    except Exception as e:
        logger.error("Error almacenando memoria: %s", e)


def search_memory(query: str, top_k: int = 3) -> list[dict]:
    if not is_enabled():
        return []

    try:
        results = _collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        memories = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0
                memories.append({
                    "text": doc,
                    "source": meta.get("source", "unknown"),
                    "relevance": 1 - distance,
                })
        return memories
    except Exception as e:
        logger.error("Error buscando memoria: %s", e)
        return []


def clear_memories():
    if not is_enabled():
        return
    global _collection
    try:
        _chroma_client.delete_collection("jarvis_memory")
        _collection = _chroma_client.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Memorias semanticas borradas")
    except Exception as e:
        logger.error("Error borrando memorias: %s", e)
