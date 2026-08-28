FROM python:3.11-slim

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create directories
RUN mkdir -p uploads/avatars uploads/certs uploads/files .freebuff

EXPOSE 5000

# Run schema + seed on first boot, then start the app
CMD python setup_sqlite.py && python seed_demo_sqlite.py && waitress-serve --host=0.0.0.0 --port=5000 --threads=8 app:app
