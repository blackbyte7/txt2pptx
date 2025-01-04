FROM python:3.10-slim

# Set environment variables to prevent interactive prompts during apt-get install
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    unoconv \
    poppler-utils \
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
    # OPENAI_API_KEY="key"
    # ANTHROPIC_API_KEY="key"

CMD ["python", "run.py"]
