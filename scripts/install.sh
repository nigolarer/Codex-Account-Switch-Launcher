#!/bin/zsh
cat <<'EOF'
The resident LaunchAgent mode is deprecated in v0.17.0.
Use the standalone native Dock App instead:

  ./scripts/install-app.sh

For development you can still run:

  ./scripts/run.sh
EOF
exit 0
