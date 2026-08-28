FROM python:3.11-slim

# System deps for PyMySQL SSL
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create uploads directory
RUN mkdir -p uploads/avatars uploads/certs uploads/files

EXPOSE 8000

# Production server: waitress (threaded, production-ready WSGI)
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "--threads=8", "app:app"]
