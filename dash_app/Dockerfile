FROM python:3.13-slim

# Allows the web application to receive requests through AWS Lambda.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 \
    /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    AWS_LWA_PORT=8080 \
    AWS_LWA_ENABLE_COMPRESSION=true

# Install dependencies before copying the application.
COPY dash_app/requirements.txt ./requirements.txt

RUN python -m pip install --no-cache-dir -r requirements.txt

# Includes the Python modules and assets/style.css.
COPY dash_app/ ./dash_app/

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "60", "--worker-tmp-dir", "/tmp", "--access-logfile", "-", "--error-logfile", "-", "dash_app.app:server"]