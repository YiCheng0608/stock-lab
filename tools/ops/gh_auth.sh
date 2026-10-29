# The one test for "GitHub refused gh's credentials" (#337), sourced by watchdog.sh and
# monitor.sh (#338); not run.
#
# gh_auth_error EXIT ERR_FILE: a failed gh call was refused for its credentials: exit 4
# is "requires authentication" (no GH_TOKEN and no login;
# cli.github.com/manual/gh_help_exit-codes), and an expired or revoked GH_TOKEN gets
# "HTTP 401: Bad credentials" with exit 1. Other failures (network, rate limit) are not.
gh_auth_error() {
  [ "$1" = 4 ] || grep -qiE 'HTTP 401|Bad credentials|gh auth login' "$2" 2>/dev/null
}
