FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    GRADIO_SERVER_NAME="0.0.0.0" \
    GRADIO_SERVER_PORT="7860"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    libreoffice-common \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

ENV LOG_LEVEL=INFO \
    OPENAI_MODEL="gpt-4-turbo" \
    ANTHROPIC_MODEL="claude-3-5-sonnet-20240620" \
    LLM_TEMPERATURE="0.1" \
    LLM_MAX_TOKENS="4096" \
    DOCS_PATH="data/python-pptx-documentation.pdf"

CMD ["python", "run.py"]