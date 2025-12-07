from .file_store import get_store, client
import os
import time

def upload_document(path):
    store = get_store()
    print(f"Uploading {path} to store {store.name}...")

    try:
        # Start upload
        op = client.file_search_stores.upload_to_file_search_store(
            file=path,
            file_search_store_name=store.name,
            config={
                "chunking_config": {
                    "white_space_config": {
                        "max_tokens_per_chunk": 250,
                        "max_overlap_tokens": 40
                    }
                }
            }
        )

        # IMPORTANT FIX:
        operation_name = op  

        print(f"Operation started: {operation_name}")

        # Poll the operation until done
        while True:
            updated_op = client.operations.get(operation_name)
            if updated_op.done:
                print(f"Upload completed successfully for {path}")
                break

            print("Waiting for upload to complete...")
            time.sleep(2)

    except Exception as e:
        print(f"Error uploading {path}: {e}")


if __name__ == "__main__":
    # Root folder: backend/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")

    if not os.path.exists(data_dir):
        print(f"Data directory not found: {data_dir}")
        exit(1)

    print(f"Scanning {data_dir} for documents...")

    valid_extensions = {".txt", ".pdf", ".md", ".csv", ".html"}

    files_found = False

    for root, dirs, files in os.walk(data_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()

            if ext in valid_extensions:
                files_found = True
                file_path = os.path.join(root, file)
                print(f"Found file: {file}")
                upload_document(file_path)

    if not files_found:
        print("No valid documents found in backend/data/")
