#!/usr/bin/env bash
set -euo pipefail

export CMAKE_CONFIGURE_ARGS="${CMAKE_CONFIGURE_ARGS:-} -DENABLE_SMD=ON"

$PYTHON -m pip install . -vv --no-deps --no-build-isolation
site_dir=$($PYTHON - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)
libsolvent_path=$(ls "${site_dir}"/pyscf/lib/libsolvent.* 2>/dev/null | head -n 1 || true)
if [ -z "${libsolvent_path}" ]; then
  echo "ERROR: libsolvent was not built; SMD support is incomplete." >&2
  exit 1
fi
