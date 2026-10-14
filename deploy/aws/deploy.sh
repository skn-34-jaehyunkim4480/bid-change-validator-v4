#!/usr/bin/env bash
set -euo pipefail
umask 077

SHA="${1:?Usage: deploy.sh <immutable-git-sha>}"
cd /opt/bidcheck
# Keep the optional, read-only retrieval mount path available even before the
# private artifacts are provisioned. The feature flag stays false by default.
install -d -m 0700 /opt/bidcheck/ml-experimental-artifacts
RHWP_BIN=/opt/bidcheck/rhwp-pr8-20261013/rhwp
test -x "$RHWP_BIN"
printf '%s  %s\n' '435209cc31429e89f894cd4a639c7506611c6a4eea158842d2fbffe44ad057f5' "$RHWP_BIN" | sha256sum --check --status

# 골든 계정 비밀번호 파일은 무슨 일이 있어도(실패·되돌림 포함) 끝날 때 지운다.
GOLDEN_SEED_FILE=/opt/bidcheck/golden-seed.password
trap 'rm -f "$GOLDEN_SEED_FILE"' EXIT

PREVIOUS=""
if [ -s .release ]; then PREVIOUS="$(cat .release)"; fi
SERVICES=(api web caddy)
COMPOSE_FILES=(-f docker-compose.yml)
DJANGO_QA_WAS_ACTIVE=false
if [ -f .django-qa-active ]; then DJANGO_QA_WAS_ACTIVE=true; fi
if [ -f django-qa.enabled ]; then
  COMPOSE_FILES+=(-f docker-compose.django-qa.yml)
  SERVICES+=(django-qa)
fi
PROFILE_ARGS=()
if [ -f collector.enabled ]; then
  PROFILE_ARGS=(--profile collector)
  SERVICES+=(notice-poller)
fi
if [ -f processing.enabled ]; then
  PROFILE_ARGS+=(--profile processing)
  SERVICES+=(processing-worker)
fi

rollback() {
  trap - ERR
  if [ -n "$PREVIOUS" ]; then
    echo "DEPLOY_FAILED_ROLLING_BACK_IMAGE" "$PREVIOUS" >&2
    if [ "$DJANGO_QA_WAS_ACTIVE" != true ]; then
      rm -f django-qa.enabled .django-qa-active
      echo DJANGO_QA_DISABLED_ON_ROLLBACK >&2
    fi
    python3 prepare-env.py "$PREVIOUS"
    ROLLBACK_COMPOSE=(-f docker-compose.yml)
    ROLLBACK_SERVICES=(api web caddy)
    if [ "$DJANGO_QA_WAS_ACTIVE" = true ]; then
      ROLLBACK_COMPOSE+=(-f docker-compose.django-qa.yml)
      ROLLBACK_SERVICES+=(django-qa)
    fi
    if [ -f collector.enabled ]; then ROLLBACK_SERVICES+=(notice-poller); fi
    if [ -f processing.enabled ]; then ROLLBACK_SERVICES+=(processing-worker); fi
    docker compose --env-file .env "${ROLLBACK_COMPOSE[@]}" "${PROFILE_ARGS[@]}" \
      up -d --wait "${ROLLBACK_SERVICES[@]}" || true
    printf '%s\n' "$PREVIOUS" > .release
  fi
}
trap rollback ERR

python3 prepare-env.py "$SHA"
aws ecr get-login-password --region ap-northeast-2 | docker login \
  --username AWS --password-stdin 226234259348.dkr.ecr.ap-northeast-2.amazonaws.com >/dev/null

PULL_SERVICES=(api web)
if [ -f django-qa.enabled ]; then PULL_SERVICES+=(django-qa); fi
docker compose --env-file .env "${COMPOSE_FILES[@]}" pull --quiet "${PULL_SERVICES[@]}"
docker compose --env-file .env -f docker-compose.yml up --no-deps --abort-on-container-exit \
  --exit-code-from schema-check schema-check

if [ -f .release ]; then cp -p .release .previous-release; fi

if ! docker compose --env-file .env "${COMPOSE_FILES[@]}" "${PROFILE_ARGS[@]}" up -d --wait "${SERVICES[@]}" || \
   ! curl --fail --silent --show-error --max-time 20 \
       --resolve 15-165-249-43.sslip.io:443:127.0.0.1 \
       https://15-165-249-43.sslip.io/health >/dev/null; then
  rollback
  exit 1
fi

printf '%s\n' "$SHA" > .release
if [ -f django-qa.enabled ]; then touch .django-qa-active; fi
trap - ERR
echo DEPLOY_HEALTHY "$SHA"

# 골든 v0.2 시험 계정 넣기(선택). 배포 워크플로를 손으로 돌리면서 seed_golden 을 켰을 때만 이 파일이 있다.
# 배포가 건강해진 뒤에 돌리고, 실패해도 이미지를 되돌리지 않는다(배포와 무관한 일이다). 비밀번호 파일은 한 번 읽고 지운다.
if [ -f "$GOLDEN_SEED_FILE" ]; then
  if GOLDEN_SEED_PASSWORD="$(cat "$GOLDEN_SEED_FILE")" docker compose --env-file .env -f docker-compose.yml \
       run --rm --no-deps -T -e GOLDEN_SEED_PASSWORD api \
       python -m app.scripts.seed_golden_v02_accounts --bundle-dir /app/golden/qualification-v0.2 \
       --include-analysis --create-missing-notices --shared-db; then
    echo GOLDEN_SEEDED
  else
    echo GOLDEN_SEED_FAILED >&2
    exit 1
  fi
fi
