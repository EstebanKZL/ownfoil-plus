FROM python:3.14-alpine

# Install platform-specific build dependencies
ARG TARGETPLATFORM
# `apk upgrade` (not just `apk update`) pulls in any OS package patch that landed in
# Alpine's repo after this base image layer was last baked - there's typically a gap
# of days to weeks between a CVE fix reaching the package repo and the official
# python:*-alpine image being rebuilt with it, and that gap is exactly what shows up
# as "known" vulnerabilities in a registry scan of an image built from a cached base
# layer. `su-exec` replaces `sudo` below: this image only ever uses it for the one
# privilege-drop in run.sh, which is exactly what su-exec is built for - a few KB
# versus the full sudo package, with none of sudo's own (repeated, sometimes
# critical) CVE history.
RUN apk update && apk upgrade --no-cache && apk add --no-cache bash su-exec \
    && if [ "$TARGETPLATFORM" = "linux/arm/v6" ] || [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then \
        apk add --no-cache build-base gcc musl-dev jpeg-dev zlib-dev libffi-dev cairo-dev pango-dev gdk-pixbuf-dev; \
    fi

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt && rm /tmp/requirements.txt
RUN if [ "$TARGETPLATFORM" = "linux/arm/v6" ] || [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then \
        apk del build-base gcc musl-dev jpeg-dev zlib-dev libffi-dev cairo-dev pango-dev gdk-pixbuf-dev; \
    fi

RUN mkdir /app
COPY ./app /app
# Only read for the version the shop reports (discovery._app_version).
COPY ./pyproject.toml /app/pyproject.toml
COPY ./docker/run.sh /app/run.sh
RUN chmod +x /app/run.sh

RUN mkdir -p /app/data

WORKDIR /app

# Python rather than curl/wget: nothing extra to install. start-period covers the
# first start's migrations and TitleDB bootstrap on slow ARM boards.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8465/api/health', timeout=8)" || exit 1

ENTRYPOINT [ "/app/run.sh" ]

