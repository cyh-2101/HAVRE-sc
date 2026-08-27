ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 havre
WORKDIR /app

# Keep the exact third-party dependency layer independent of HAVRE source
# changes so a second immutable release reuses only already verified wheels.
COPY deploy/runtime-requirements.lock /tmp/havre-runtime-requirements.lock
RUN python -m pip install --require-hashes --only-binary=:all: --no-deps \
        -r /tmp/havre-runtime-requirements.lock

ARG HAVRE_SOURCE_REVISION
ARG HAVRE_SOURCE_SNAPSHOT
ENV HAVRE_SOURCE_REVISION=${HAVRE_SOURCE_REVISION} \
    HAVRE_SOURCE_SNAPSHOT=${HAVRE_SOURCE_SNAPSHOT}

COPY pyproject.toml README.md /app/
COPY companion /app/companion
COPY db/migrations /app/db/migrations
COPY identity /app/identity
COPY mlsys /app/mlsys
COPY services /app/services
COPY deploy /app/deploy
COPY apps/web/havre-chat.html /app/apps/web/havre-chat.html
COPY scripts/build_stage10_image_context.py /app/scripts/build_stage10_image_context.py
COPY scripts/verify_stage10_deployment_config.py /app/scripts/verify_stage10_deployment_config.py
COPY .havre-build-context-manifest.json /app/.havre-build-context-manifest.json

RUN python -m services.api.image_context

RUN python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check

USER 10001:10001
ENTRYPOINT ["python", "-m", "services.api.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
