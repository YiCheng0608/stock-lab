# The backend image (#333): api and scheduler share it. It holds what the worker, the
# `claude -p` steps (news-llm, candidate_notes), gh and the verify screenshots
# (tools/ops/screenshot.cjs, #339) need. Build from the repo root:
#
#   docker build -f backend/Dockerfile -t stock-lab-backend .
#
# No command of its own: compose (#335) starts the api and the scheduler. Versions are
# pinned here and in backend/validation-requirements.lock.txt; node follows CI (22).
ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim

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
USER app
# PID 1 reaps orphans: a killed job's worker is re-parented to it, and without a reaper it
# stays a zombie whose PID still looks alive (schedule_runs._pid_alive, the run row).
ENTRYPOINT ["/usr/bin/tini", "--"]
