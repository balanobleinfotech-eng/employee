FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install python dependencies directly using wheels
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Ensure entrypoint script has LF line endings and is executable
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Pre-collect static files during build
RUN python manage.py collectstatic --no-input

EXPOSE 8000

CMD ["/bin/sh", "/app/entrypoint.sh"]
