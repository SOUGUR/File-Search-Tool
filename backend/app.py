from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.rag.rag_query import ask_gemini
import os

app = FastAPI()

# Add CORS so frontend can talk to backend (still useful for local dev if split)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
# Assumes frontend is at ../frontend relative to this file
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")

# Mount the frontend directory to serve static assets (css, js, etc.)
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))

class Query(BaseModel):
    question: str

@app.post("/chat")
def chat(data: Query):
    try:
        answer, citations = ask_gemini(data.question)
        return {
            "answer": answer,
            "citations": citations
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
