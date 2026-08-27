ARG HAVRE_API_IMAGE
ARG POSTGRES_CLIENT_IMAGE
FROM ${HAVRE_API_IMAGE} AS havre_api
FROM ${POSTGRES_CLIENT_IMAGE}

ARG HAVRE_SOURCE_REVISION
ARG HAVRE_SOURCE_SNAPSHOT
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HAVRE_SOURCE_REVISION=${HAVRE_SOURCE_REVISION} \
    HAVRE_SOURCE_SNAPSHOT=${HAVRE_SOURCE_SNAPSHOT}

RUN useradd --create-home --uid 10001 havre
COPY --from=havre_api /usr/local /usr/local
COPY --from=havre_api /app/pyproject.toml /app/README.md /app/
COPY --from=havre_api /app/companion /app/companion
COPY --from=havre_api /app/db/migrations /app/db/migrations
COPY --from=havre_api /app/identity /app/identity
COPY --from=havre_api /app/mlsys /app/mlsys
COPY --from=havre_api /app/services /app/services
COPY --from=havre_api /app/deploy /app/deploy
COPY --from=havre_api /app/scripts/build_stage10_image_context.py /app/scripts/build_stage10_image_context.py
COPY --from=havre_api /app/scripts/verify_stage10_deployment_config.py /app/scripts/verify_stage10_deployment_config.py
COPY --from=havre_api /app/.havre-build-context-manifest.json /app/.havre-build-context-manifest.json
WORKDIR /app

RUN python -m services.api.image_context \
    && pg_dump --version \
    && pg_restore --version
USER 10001:10001
ENTRYPOINT ["python", "-m", "services.api.cli"]
