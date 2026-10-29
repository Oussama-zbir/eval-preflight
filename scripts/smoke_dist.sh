#!/usr/bin/env bash
# Install the built wheel into a fresh virtualenv, outside this checkout, and run
# the README quickstart against it: what `pip install eval-preflight` gives a user.
#
#     uv build && scripts/smoke_dist.sh dist [EXPECTED_VERSION]
#
# EXPECTED_VERSION (the publish workflow passes the tag without its "v") must equal
# the wheel's version. Requires uv.
set -euo pipefail

dist=$(cd "${1:?usage: smoke_dist.sh DIST_DIR [EXPECTED_VERSION]}" && pwd)
expected=${2:-}
fixtures=$(cd "$(dirname "$0")/../tests/fixtures/pydantic_evals" && pwd)

wheels=("$dist"/eval_preflight-*.whl)
if [[ ${#wheels[@]} -ne 1 || ! -f ${wheels[0]} ]]; then
  echo "expected exactly one eval_preflight wheel in $dist" >&2
  exit 1
fi
version=$(basename "${wheels[0]}" | cut -d- -f2)
if [[ -n $expected && $version != "$expected" ]]; then
  echo "wheel version $version does not match the expected $expected" >&2
  exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
uv venv --quiet --no-project "$work/venv"
VIRTUAL_ENV="$work/venv" uv pip install --quiet "${wheels[0]}"
cp "$fixtures/clean_run.json" "$fixtures/name_shift.json" "$work/"
cd "$work"
bin="$work/venv/bin"

reported=$("$bin/eval-preflight" --version)
if [[ $reported != "eval-preflight $version" ]]; then
  echo "--version printed '$reported', expected 'eval-preflight $version'" >&2
  exit 1
fi

# CLI: a clean run passes (exit 0), the name-shift run fails (exit 1).
"$bin/eval-preflight" check clean_run.json --quiet
set +e
"$bin/eval-preflight" check name_shift.json --quiet
code=$?
set -e
if [[ $code -ne 1 ]]; then
  echo "name_shift.json exited $code, expected 1" >&2
  exit 1
fi

# Python API, isolated from this checkout (-I), with only the runtime dependencies.
"$bin/python" -I - <<'EOF'
from eval_preflight import IntegrityError, check, load

assert check(load("clean_run.json")).verdict == "PASS"
result = check(load("name_shift.json"))
assert result.verdict == "FAIL", result.verdict
try:
    result.raise_if_failed()
except IntegrityError:
    pass
else:
    raise AssertionError("raise_if_failed() did not raise on a FAIL verdict")
EOF

echo "smoke test passed: eval-preflight $version"
