FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHON=/opt/venv/bin/python
WORKDIR /app

RUN python -m venv /opt/venv

COPY requirements.txt requirements-dev.txt ./
RUN /opt/venv/bin/python -m pip install --no-cache-dir --timeout 60 -r requirements-dev.txt

COPY pyproject.toml Makefile ./
COPY make/ make/
COPY src/ src/
COPY tests/ tests/

RUN /opt/venv/bin/python -m pip install --no-cache-dir --timeout 60 -e . \
    && /opt/venv/bin/python -m pip check

CMD ["make", "quality"]