FROM python:3.11-slim

WORKDIR /app

# Install git for branch detection and build-essential for Chroma/Numpy
RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

# Install dependencies (cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create persistence directory
RUN mkdir -p /app/cortex_db

# Run the MCP server
ENTRYPOINT ["python", "server.py"]
