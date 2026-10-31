"""Admin CLI: load files from backend/data/ into the SHARED store that every user
can query. (Users upload their own private documents through the web UI.)

Run from the project root:
    python -m backend.rag.upload_docs
    python -m backend.rag.upload_docs --chunk-size 400 --overlap 50 --replace
"""
import argparse
import os
import time

from ..config import BACKEND_DIR, settings
from ..schemas import ChunkingParams, UploadOptions
from .gemini import client
from .ingest import build_upload_config


def get_or_create_shared_store():
    for s in client.file_search_stores.list():
        if s.display_name == settings.shared_store_display_name:
            return s
    print(f"Creating shared store '{settings.shared_store_display_name}'")
    config = {"display_name": settings.shared_store_display_name}
    if settings.embedding_model:
        config["embedding_model"] = settings.embedding_model
    return client.file_search_stores.create(config=config)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default=str(BACKEND_DIR / "data"))
    p.add_argument("--chunk-size", type=int, default=250, help="max_tokens_per_chunk")
    p.add_argument("--overlap", type=int, default=40, help="max_overlap_tokens")
    p.add_argument("--replace", action="store_true", help="re-upload files that already exist in the store")
    args = p.parse_args()

    if not settings.shared_store_display_name:
        raise SystemExit("SHARED_STORE_NAME is empty; nothing to upload to.")
    chunking = ChunkingParams(max_tokens_per_chunk=args.chunk_size, max_overlap_tokens=args.overlap)
    store = get_or_create_shared_store()
    existing = {d.display_name: d.name for d in client.file_search_stores.documents.list(parent=store.name)}

    files = sorted(
        os.path.join(root, f)
        for root, _, names in os.walk(args.dir)
        for f in names
        if os.path.splitext(f)[1].lower() in settings.allowed_extensions
    )
    if not files:
        raise SystemExit(f"No supported documents found in {args.dir}")

    for path in files:
        name = os.path.basename(path)
        if name in existing:
            if not args.replace:
                print(f"skip  {name} (already in store; use --replace to re-upload)")
                continue
            client.file_search_stores.documents.delete(name=existing[name], config={"force": True})
        print(f"upload {name} (chunk={chunking.max_tokens_per_chunk}, overlap={chunking.max_overlap_tokens})")
        op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store.name,
            file=path,
            config=build_upload_config(UploadOptions(chunking=chunking), name, None),
        )
        while not op.done:
            time.sleep(2)
            op = client.operations.get(op)
        print(f"  -> {'FAILED: ' + str(op.error) if op.error else 'indexed'}")


if __name__ == "__main__":
    main()
