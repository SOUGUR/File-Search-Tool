# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Add PYTHONPATH so Python can import backend.*
ENV PYTHONPATH=/app

# Install system dependencies if needed (none strictly for these python packages, but good practice)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the backend requirements file
COPY backend/requirements.txt ./backend/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the rest of the application code
COPY backend ./backend
COPY frontend ./frontend

# Expose port 8000 for FastAPI
EXPOSE 8000

# Define environment variable
# ENV NAME World

# Run app.py when the container launches
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
