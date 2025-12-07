# Gemini RAG Chatbot

A simple RAG (Retrieval Augmented Generation) chatbot using Google Gemini and FastAPI.

## Project Structure

- `backend/`: FastAPI application and RAG logic.
- `frontend/`: Simple HTML/CSS/JS chat interface.

## Setup

### Prerequisites
- Python 3.9+
- Gemini API Key

### 1. Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

Create a `.env` file in `backend/` and add your API key:
```
GEMINI_API_KEY=your_actual_api_key
```

### 2. Upload Documents

Place your documents (PDF, TXT, etc.) in `backend/data/`.
Then run the upload script:

```bash
python -m rag.upload_docs
```

(Make sure you are in the `backend/` directory so the module import works, or set PYTHONPATH).
Better way from project root:
```bash
python backend/rag/upload_docs.py
```
*Note: You might need to adjust imports or run as module.*

Recommended way:
```bash
cd backend
python -m rag.upload_docs
```
It will allow you to select files or just upload the default one in `backend/data/your_docs_here.txt`.

### 3. Run Backend

```bash
uvicorn app:app --reload
```
The API will start at `http://localhost:8000`.

### 4. Frontend

Simply open `frontend/index.html` in your browser.

## Features
- **RAG Engine**: Uses Gemini `file_search` tool.
- **Citations**: Displays source file and quotes for transparency.
- **Clean UI**: Responsive chat interface.
