# How to Run the Gemini RAG Chatbot

Follow these steps to get your chatbot up and running.

## 1. Prerequisites

- **Python**: Ensure you have Python installed (version 3.9 or higher). [Download Python](https://www.python.org/downloads/)
- **API Key**: You need a Google Gemini API key. Get it from [Google AI Studio](https://aistudio.google.com/).

## 2. Backend Setup

1.  **Navigate to the backend directory**:
    Open your terminal or command prompt and run:
    ```bash
    cd backend
    ```

2.  **Install Dependencies**:
    Install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure API Key**:
    - Open the `.env` file located in the `backend/` folder.
    - Replace `your_api_key_here` with your actual API key.
    - Example:
      ```
      GEMINI_API_KEY=AIzaSyD...
      ```

## 3. Upload Data (RAG Setup)

Before the bot can answer questions about your documents, you need to upload them.

1.  **Add your files**:
    - The project comes with a sample file: `backend/data/your_docs_here.txt`.
    - You can add more `.txt` or `.pdf` files to the `backend/data/` folder.

2.  **Run the upload script**:
    Make sure you are still in the `backend/` directory:
    ```bash
    python -m rag.upload_docs
    ```
    - Check the terminal output. It should say "File uploaded to Gemini" and confirm it was added.

## 4. Run the Server

Start the FastAPI backend server:

```bash
uvicorn app:app --reload
```
You should see output indicating the server is running at `http://127.0.0.1:8000`.

## 5. Launch the Frontend

1.  Open a new terminal window (keep the backend running).
2.  Navigate to the `frontend` directory:
    ```bash
    cd frontend
    ```
3.  **Open in Browser**:
    - You can simply double-click the `index.html` file in your file explorer.
    - OR, if you use VS Code, right-click `index.html` and select "Open with Live Server" (if installed).
    - OR, just drag and drop `index.html` into your Chrome/Edge browser.

## 6. Test It

1.  Type a question in the chat box, for example:
    > "What is this project about?"
    or
    > "How does the RAG process work?"
2.  The bot should reply using information from the `your_docs_here.txt` file you uploaded.
