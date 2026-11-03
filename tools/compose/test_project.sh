# Sourced by tools/compose/smoke.sh and deploy_smoke.sh (#340, PR #369 review): both seed their
# project's stock-data volume and end with `docker compose down --volumes`, so they run only on
# a test project, never on the production one, as close_task.sh deletes only task projects.
#
# test_project_problem NAME: why NAME is no test project, or nothing. Production is stock-lab
# and STOCK_COMPOSE_PROJECT (tools/ops/deploy.sh); a test project starts with t<n> or task-<n>
# (the task's, docs/GITHUB_WORKFLOW.md 本機檢查) or has smoke as one of its words.
test_project_problem() {
  local name="$1"
  if [ "$name" = stock-lab ] || { [ -n "${STOCK_COMPOSE_PROJECT:-}" ] && [ "$name" = "$STOCK_COMPOSE_PROJECT" ]; }; then
    printf '%s 是正式 compose project' "$name"
    return
  fi
  [[ "$name" =~ ^(t[0-9]+|task-[0-9]+)([-_][a-z0-9_-]*)?$ ]] && return
  [[ "$name" =~ ^[a-z0-9][a-z0-9_-]*$ && "$name" =~ (^|[-_])smoke([-_]|$) ]] && return
  printf '%s 不是測試用的 compose project（要以 t<n>、task-<n> 開頭，或含 smoke 一詞）' "$name"
}

# refuse_unless_test_project NAME: exit 2 before anything runs when NAME is no test project.
refuse_unless_test_project() {
  local problem
  problem="$(test_project_problem "$1")"
  [ -z "$problem" ] && return 0
  printf '%s: 拒絕：%s；這支腳本最後會 down --volumes 刪掉它的 volume\n' "$(basename "$0")" "$problem" >&2
  exit 2
}
