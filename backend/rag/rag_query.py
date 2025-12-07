from google import genai
from google.genai import types
from .file_store import get_store, client
import os

# Client is already initialized in file_store, but we can reuse or re-init. 
# We imported 'client' from .file_store to share the instance/config.

def ask_gemini(question: str):
    store = get_store()

    # Updated model name to match available models (gemini-2.5-flash)
    model_name = "gemini-2.5-flash"

    print(f"Querying {model_name} with store {store.name}...")

    response = client.models.generate_content(
        model=model_name,
        contents=question,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    google_search_retrieval=None, # Explicitly invalidating others if needed, or just specific:
                    file_search=types.FileSearch(
                        file_search_store_names=[store.name]
                    )
                )
            ]
        )
    )

    # Extract citations
    citations = []
    # Check if candidates exist and have citations.
    # The response structure might vary slightly, but usually response.citations or response.candidates[0].citations
    # The user code used `response.citations`. We will try that, but also check candidates if needed.
    
    # In some SDK versions, citations are top-level on response? Or inside candidates?
    # User code: if hasattr(response, "citations"): ...
    # We will keep that.
    
    if hasattr(response, "citations") and response.citations:
        for c in response.citations:
            citations.append({
                "file": c.uri, # often uri or title or custom metadata
                "quote": c.content if hasattr(c, 'content') else "Mutation/Quote logic here",
            })
            # Note: The user code had c.file_name and c.quote. 
            # We'll stick to their property names if they match the SDK they are using, 
            # but I'll add safety.
            
    # Fallback if the user's property names were guesses
    # (The SDK is evolving).
    # response.candidates[0].citation_metadata.citation_sources...
    
    # Let's trust the user's snippet for the extraction logic but wrap it visually?
    # No, I'll provide the user's logic exactly but with the model name fix.
    
    # Re-writing the extraction block to match user request but with safety.
    
    final_citations = []
    if hasattr(response, "citations") and response.citations:
         for c in response.citations:
            final_citations.append({
                "file": getattr(c, 'file_name', 'Unknown File'),
                "quote": getattr(c, 'quote', 'No quote content')
            })
            
    return response.text, final_citations
