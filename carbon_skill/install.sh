#!/usr/bin/env bash
# Install the `carbon` skill for Claude Code (and other harnesses that read
# ~/.claude/skills). Linux and macOS. Needs uv: https://docs.astral.sh/uv/
#
#   bash carbon_skill/install.sh              install or update
#   bash carbon_skill/install.sh --uninstall  remove it again
#
# Never uses sudo. Safe to run again: an existing install made by this script
# is updated in place and keeps its past runs.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/carbon"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST="$CLAUDE_DIR/skills/carbon"
BIN_DIR="$HOME/.local/bin"
FORCE=no
CHECK_FAILED=no
LOCATION_ARGS=""
CHECK=yes
UNINSTALL=no
MARKER=".installed-by-carbon-skill"
WRAPPER_TAG="# carbon-skill wrapper"

usage() {
  cat <<USAGE
Usage: bash install.sh [options]

  --dest DIR      install the skill here (default: $DEST)
  --bin-dir DIR   put the carbon_start/carbon_end/carbon_report commands here
                  (default: $BIN_DIR)
  --force         replace an existing carbon skill that this script did not
                  install (it is moved to a backup first, never deleted)
  --no-check      skip the 15-second test measurement at the end
  --uninstall     remove the skill and its commands
  -h, --help      show this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; LOCATION_ARGS="$LOCATION_ARGS --dest \"$2\""; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; LOCATION_ARGS="$LOCATION_ARGS --bin-dir \"$2\""; shift 2 ;;
    --force) FORCE=yes; shift ;;
    --no-check) CHECK=no; shift ;;
    --uninstall) UNINSTALL=yes; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say()  { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #
if [ "$UNINSTALL" = yes ]; then
  for cmd in carbon_start carbon_end carbon_report; do
    if [ -f "$BIN_DIR/$cmd" ] && grep -q "$WRAPPER_TAG" "$BIN_DIR/$cmd"; then
      rm -f "$BIN_DIR/$cmd" && say "Removed $BIN_DIR/$cmd"
    fi
  done
  if [ -f "$DEST/$MARKER" ]; then
    for p in "$DEST"/runs/*/monitor.pid; do
      [ -f "$p" ] && kill -TERM "$(cat "$p")" 2>/dev/null || true
    done
    rm -rf "$DEST" && say "Removed $DEST"
  elif [ -e "$DEST" ]; then
    warn "$DEST was not installed by this script; left it alone."
  else
    say "Nothing installed at $DEST"
  fi
  exit 0
fi

# --------------------------------------------------------------------------- #
# prerequisites
# --------------------------------------------------------------------------- #
case "$(uname -s)" in
  Linux|Darwin) ;;
  MINGW*|MSYS*|CYGWIN*)
    die "Native Windows is not supported. Install WSL (https://learn.microsoft.com/windows/wsl/install), and run Claude Code and this script inside it." ;;
  *) die "Unsupported OS: $(uname -s). The carbon skill supports Linux and macOS." ;;
esac

[ -f "$SRC/SKILL.md" ] || die "Cannot find the skill sources at $SRC. Run this script from inside the cloned repository."

if ! command -v uv >/dev/null 2>&1; then
  die "uv is required but not on PATH. Install it with
    curl -LsSf https://astral.sh/uv/install.sh | sh
then open a new terminal and run this script again.
(More options: https://docs.astral.sh/uv/getting-started/installation/)"
fi

for tool in ps awk sed grep; do
  command -v "$tool" >/dev/null 2>&1 || die "'$tool' is required but not found."
done

case "$DEST" in
  "$SRC"|"$SRC"/*) die "--dest must not be the source folder itself." ;;
esac

say "Installing the carbon skill"
say "  from: $SRC"
say "  to:   $DEST"

# --------------------------------------------------------------------------- #
# an existing install
# --------------------------------------------------------------------------- #
if [ -e "$DEST" ] && [ ! -f "$DEST/$MARKER" ]; then
  if [ "$FORCE" != yes ]; then
    die "$DEST already exists and was not installed by this script.
Re-run with --force to replace it. It will be moved to a backup first,
including its runs/; nothing is deleted."
  fi
  # The backup must live outside skills/, or it would load as a second skill.
  BACKUP="$CLAUDE_DIR/carbon-skill-backup-$(date +%Y%m%d-%H%M%S)"
  say "Moving the existing skill to $BACKUP"
  mv "$DEST" "$BACKUP"
fi

# --------------------------------------------------------------------------- #
# copy the skill
# --------------------------------------------------------------------------- #
mkdir -p "$DEST"
rm -rf "$DEST/scripts"
cp -R "$SRC/scripts" "$DEST/scripts"
for f in SKILL.md pyproject.toml uv.lock .python-version; do
  cp "$SRC/$f" "$DEST/$f"
done
find "$DEST/scripts" -name __pycache__ -type d -prune -exec rm -rf {} +
chmod +x "$DEST"/scripts/*.sh
mkdir -p "$DEST/runs"
touch "$DEST/$MARKER"

# --------------------------------------------------------------------------- #
# python environment
# --------------------------------------------------------------------------- #
say "Creating the skill's Python environment with uv (codecarbon, ecologits)"
# --frozen: exactly the versions in uv.lock. uv downloads Python 3.12 itself if
# this machine has no suitable one. VIRTUAL_ENV is cleared so an activated
# environment elsewhere is not used by mistake.
( cd "$DEST" && env -u VIRTUAL_ENV uv sync --frozen --no-dev --project "$DEST" --quiet ) \
  || die "uv sync failed (see above)."

# The codecarbon CLI's `monitor` command blocks until Ctrl+C, which hangs an
# agent's tool call. Keep the real CLI as codecarbon-real (the skill's scripts
# call that), and put a shim that refuses to run in its place.
VBIN="$DEST/.venv/bin"
[ -x "$VBIN/codecarbon" ] || [ -x "$VBIN/codecarbon-real" ] || die "uv sync did not install the codecarbon CLI."
if [ -f "$VBIN/codecarbon" ] && ! grep -q 'REFUSED: do not run the codecarbon CLI' "$VBIN/codecarbon" 2>/dev/null; then
  mv -f "$VBIN/codecarbon" "$VBIN/codecarbon-real"
fi
cat > "$VBIN/codecarbon" <<'SHIM'
#!/usr/bin/env bash
cat >&2 <<'MSG'
REFUSED: do not run the codecarbon CLI directly.

  `codecarbon monitor` blocks until Ctrl+C. Running it here hangs your tool call
  and leaves an unowned monitor with no run directory and no auto-stop.

Use the carbon skill's commands instead (they return immediately):

    carbon_start  [label]
    carbon_end    [label]
    carbon_report [label]
MSG
exit 1
SHIM
chmod +x "$VBIN/codecarbon"

# --------------------------------------------------------------------------- #
# commands on PATH
# --------------------------------------------------------------------------- #
mkdir -p "$BIN_DIR"
for cmd in carbon_start carbon_end carbon_report; do
  target="$BIN_DIR/$cmd"
  if [ -e "$target" ] && ! grep -q "$WRAPPER_TAG" "$target" 2>/dev/null \
     && ! grep -q "carbon/scripts/$cmd.sh" "$target" 2>/dev/null; then
    warn "$target exists and is not a carbon skill command; left it alone."
    continue
  fi
  cat > "$target" <<WRAP
#!/usr/bin/env bash
$WRAPPER_TAG
exec bash "$DEST/scripts/$cmd.sh" "\$@"
WRAP
  chmod +x "$target"
done
say "Commands: $BIN_DIR/{carbon_start,carbon_end,carbon_report}"
ON_PATH=yes
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) ON_PATH=no
     warn "$BIN_DIR is not on your PATH. The skill still works: the agent calls
  the scripts by their full path. To type the commands yourself, add this line
  to your shell profile (~/.bashrc, ~/.zshrc, or ~/.config/fish/config.fish):
      export PATH=\"$BIN_DIR:\$PATH\"        (fish: fish_add_path $BIN_DIR)" ;;
esac

# --------------------------------------------------------------------------- #
# test measurement
# --------------------------------------------------------------------------- #
if [ "$CHECK" = yes ]; then
  say "Test measurement (about 20 seconds)..."
  LAST_BEFORE="$(cat "$DEST/runs/.last" 2>/dev/null || true)"
  CHECK_LABEL="install-check"
  if bash "$DEST/scripts/carbon_start.sh" "$CHECK_LABEL"; then
    sleep 12
    bash "$DEST/scripts/carbon_end.sh" "$CHECK_LABEL" || warn "carbon_end reported a problem (see above)."
    if [ -s "$DEST/runs/$CHECK_LABEL/emissions.csv" ]; then
      say "Test measurement OK: codecarbon measured and saved its results."
    else
      warn "codecarbon ran but did not save emissions.csv. Last lines of its log:"
      tail -n 15 "$DEST/runs/$CHECK_LABEL/monitor.log" >&2 || true
      CHECK_FAILED=yes
    fi
  else
    CHECK_FAILED=yes
    warn "The test measurement did not start. See the message above, and
  $DEST/runs/$CHECK_LABEL/monitor.log"
  fi
  rm -rf "${DEST:?}/runs/$CHECK_LABEL"
  if [ -n "$LAST_BEFORE" ]; then printf '%s\n' "$LAST_BEFORE" > "$DEST/runs/.last"; else rm -f "$DEST/runs/.last"; fi
fi

if [ "$CHECK_FAILED" = yes ]; then
  cat >&2 <<FAIL

The skill is installed, but the test measurement failed (see above), so
carbon_start will not work yet on this machine. Fix the problem and run this
script again; it is safe to re-run.
FAIL
  exit 1
fi

cat <<DONE

Installed. Next:
  1. In Claude Code, run /carbon or ask "start carbon tracking". If the skill
     is not listed yet, restart Claude Code (skills load at session start).
  2. Commands:  carbon_start [label]   carbon_end [label]   carbon_report [label]
DONE
if [ "$ON_PATH" = no ]; then
  echo "     (until $BIN_DIR is on PATH: bash $DEST/scripts/carbon_start.sh, ...)"
fi
cat <<DONE
  3. Electricity grid: detected from your IP address at each carbon_start
     (see the Grid: line above). To fix it yourself, set CARBON_COUNTRY to an
     ISO-3 code (NLD, DEU, GBR, USA, ...) before carbon_start.

Uninstall:  bash $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh --uninstall$LOCATION_ARGS
DONE
