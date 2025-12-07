from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

STORE_NAME = "my-rag-store"

def get_store():
    # List existing stores
    # Note: list() returns a pager, need to iterate to access .file_search_stores usually, 
    # but the SDK might simplify this. Safe approach is to iterate.
    
    # According to recent SDK versions, client.file_search_stores.list() returns an object where we can iterate.
    # We'll try to find the store by display_name.
    
    # In some versions of the SDK, list() returns a generator or an iterable response.
    # We will iterate through it.
    
    try:
        stores = client.file_search_stores.list()
        # Handle if stores is a pager or list directly
        # The provided code used stores.file_search_stores which implies the response object has that attribute.
        # We will keep the user's logic but wrap it safely.
        
        existing_stores = []
        if hasattr(stores, 'file_search_stores'):
             existing_stores = stores.file_search_stores
        else:
             existing_stores = stores # Assuming it's iterable
             
        for s in existing_stores:
             if s.display_name == STORE_NAME:
                 return s
                 
    except Exception as e:
        print(f"Error listing stores: {e}")

    print(f"Creating new store: {STORE_NAME}")
    return client.file_search_stores.create(
        config={"display_name": STORE_NAME}
    )
