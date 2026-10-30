# The backend image (#333): api and scheduler share it. It holds what the worker, the
# `claude -p` steps (news-llm, candidate_notes), gh and the verify screenshots
# (tools/ops/screenshot.cjs, #339) need. Build from the repo root:
#
#   docker build -f backend/Dockerfile -t stock-lab-backend .
#
# No command of its own: compose (docker-compose.yml, #335) starts the api and the scheduler
# through backend/docker/entrypoint.sh. Versions are pinned here (base images by tag and
# digest, gh, Claude Code) and in backend/validation-requirements.lock.txt, which also lists
# the Linux-only uvloop.
ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ARG NODE_IMAGE=node:22.23.4-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE}

ARG GH_VERSION=2.102.0
ARG CLAUDE_CODE_VERSION=2.1.312
ARG APP_UID=1000

ENV TZ=Asia/Taipei \
    LANG=C.UTF-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend \
    STOCK_DATA_DIR=/data \
    SCREENSHOT_BROWSER=/usr/bin/chromium

# tzdata for TZ; git for the job's checks and the tests; chromium and a CJK font for
# screenshot.cjs (without the font Chinese text renders as boxes, #243); tini as PID 1.
# apt packages are not pinned: Debian drops superseded versions from the mirror, so a
# pinned version stops building; the base digest fixes the release (bookworm) and the
# CI docker job builds from scratch and prints the chromium version it got.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git tzdata tini chromium fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global --no-fund --no-audit "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz" \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && mv "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${arch}"

COPY backend/requirements.txt backend/validation-requirements.lock.txt /tmp/requirements/
RUN pip install --no-cache-dir -r /tmp/requirements/requirements.txt \
        -c /tmp/requirements/validation-requirements.lock.txt \
    && rm -rf /tmp/requirements
# The CI repository job's tools (ruff; PyYAML for checks.py and tools/ci's unittest), for the
# local checks run in the container (docs/GITHUB_WORKFLOW.md 本機檢查, #339). The same pins as
# that job installs: tools/ci/test_checks.py holds the two equal.
RUN pip install --no-cache-dir ruff==0.14.14 PyYAML==6.0.3
RUN pip uninstall -y httpx

# A non-root user. ~/.claude.json marks the CLI's first-run onboarding done, so
# `claude -p` does not stop at it; the login itself comes from the environment (#337).
# The data directory and the repo checkout (bind mounted by compose) may belong to
# another uid, hence safe.directory for git.
RUN useradd --create-home --uid "${APP_UID}" --shell /bin/bash app \
    && printf '{"hasCompletedOnboarding": true}\n' > /home/app/.claude.json \
    && chown app:app /home/app/.claude.json \
    && mkdir -p /data /app \
    && chown app:app /data /app \
    && git config --system --add safe.directory '*'

WORKDIR /app
COPY --chown=app:app . /app
# compose's entrypoint (#335): executable whatever mode the build context gave it (a Windows
# checkout has no execute bit).
RUN chmod 0755 /app/backend/docker/entrypoint.sh
# What schedule_runs records of the code a run used (#336); the context has no .git:
#   docker build --build-arg STOCK_IMAGE_TAG=<tag> --build-arg STOCK_GIT_HEAD="$(git rev-parse HEAD)" ...
ARG STOCK_IMAGE_TAG=""
ARG STOCK_GIT_HEAD=""
ENV STOCK_IMAGE_TAG=${STOCK_IMAGE_TAG} \
    STOCK_GIT_HEAD=${STOCK_GIT_HEAD}
USER app
# PID 1 reaps orphans: a killed job's worker is re-parented to it, and without a reaper it
# stays a zombie whose PID still looks alive (schedule_runs._pid_alive, the run row).
ENTRYPOINT ["/usr/bin/tini", "--"]
