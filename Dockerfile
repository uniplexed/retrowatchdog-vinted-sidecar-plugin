# Self-contained: the build context is this directory.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

# Dependencies before source, so editing the mapping does not reinstall the
# package (and does not re-hit PyPI) on every rebuild.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Unprivileged, because this is the process that talks to the internet and
# parses what comes back. It needs to write nothing: no database, no volume,
# no cache directory.
RUN useradd --system --uid 10001 --no-create-home sidecar
USER sidecar

# Documentation only. The compose service publishes NO host port: the sidecar
# is reachable from the app over the compose network and from nowhere else.
EXPOSE 8000

CMD ["python", "-m", "app.server"]
