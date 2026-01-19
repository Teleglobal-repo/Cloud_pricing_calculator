FROM python:3.11-slim

WORKDIR /app

# Copy dependency file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required folders
RUN mkdir -p uploads sample_templates templates static Assets

EXPOSE 8050

CMD ["gunicorn", "-b", "0.0.0.0:8050", "app:server"]
