#!/usr/bin/env bash
set -euo pipefail

# ===============================
# RadKit multi-host deploy script
# - Adds ubuntu0, ubuntu1, ubuntu2 as RadKit devices
# - ubuntu1 and ubuntu2 are added using ubuntu0 as a jump host
# - Reads radkit-devices.json and replaces placeholder jumphostUuid values:
#     "x" -> ubuntu0_uuid, "y" -> ubuntu1_uuid, "z" -> ubuntu2_uuid
# - Bulk-imports the resolved devices JSON
# ===============================

LOGFILE="radkit-automation-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1

# --------- USER EDITABLE DEFAULTS (override via env or prompt) ---------
: "${UBUNTU0_NAME:=ubuntu0}"
: "${UBUNTU1_NAME:=ubuntu1}"
: "${UBUNTU2_NAME:=ubuntu2}"

# Hosts or IPs for the Ubuntu jump hosts (these are the *Docker hosts*, not containers)
: "${UBUNTU0_HOST:=192.0.2.10}"
: "${UBUNTU1_HOST:=192.0.2.11}"
: "${UBUNTU2_HOST:=192.0.2.12}"

# SSH creds used by RadKit to reach the jump hosts
: "${JH_SSH_USER:=clab}"
: "${JH_SSH_PASS:=clab@123}"
: "${JH_SSH_PORT:=22}"

# Incoming devices JSON file (with placeholders x, y, z for jumphostUuid)
: "${DEVICES_JSON:=radkit-devices.json}"
# Output JSON file after replacement
: "${RESOLVED_JSON:=radkit-devices.resolved.json}"

# ----------------------------------------------------------------------

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: Required command '$1' not found in PATH." >&2
    exit 1
  }
}

# Ensure required tools exist
need_cmd jq
need_cmd radkit-control

echo "=== RadKit Multi-Host Deployment ==="
echo "Log: $LOGFILE"
echo

# Prompt for PROD:xxxx value if not set via env
if [[ -z "${PROD_VALUE:-}" ]]; then
  read -rp "Enter RadKit PROD value (PROD:xxxx-xxxx-xxxx): " PROD_VALUE
fi
if [[ -z "$PROD_VALUE" ]]; then
  echo "ERROR: PROD value is required."; exit 1
fi

# ----- Helpers ----------------------------------------------------------

# Return UUID for a device by name (empty if not found)
get_uuid_by_name() {
  local name="$1"
  radkit-control device list --json \
    | jq -r --arg n "$name" '.[] | select(.name==$n) | .uuid' \
    | awk 'NF' || true
}

# Create (or upsert) a Linux jump host device.
# For ubuntu0, we DON'T set --jumphost-uuid.
# For ubuntu1/2, we add --jumphost-uuid <UBUNTU0_UUID> so they chain behind ubuntu0.
create_or_update_jumphost() {
  local name="$1" host="$2" via_uuid="${3:-}"

  # If it exists, skip creation
  local uuid
  uuid="$(get_uuid_by_name "$name" || true)"
  if [[ -n "$uuid" ]]; then
    echo "Device '$name' already exists with uuid: $uuid"
    echo "$uuid"
    return 0
  fi

  echo "Creating device '$name' (host=$host) ..."

  # Base args common to all three ubuntu* jump hosts
  local base_args=(
    --name "$name"
    --host "$host"
    --device-type LINUX
    --enabled true
    --terminal.port "$JH_SSH_PORT"
    --terminal.connection-method SSH
    --terminal.username "$JH_SSH_USER"
    --terminal.password "$JH_SSH_PASS"
  )

  if [[ -n "$via_uuid" ]]; then
    # Chain via ubuntu0
    echo "Using --jumphost-uuid $via_uuid for '$name'"
    radkit-control device create "${base_args[@]}" --jumphost-uuid "$via_uuid" >/tmp/radkit-create-"$name".json
  else
    radkit-control device create "${base_args[@]}" >/tmp/radkit-create-"$name".json
  fi

  # Try to read UUID from the create response; otherwise fetch by name
  uuid="$(jq -r '.uuid // empty' </tmp/radkit-create-"$name".json || true)"
  if [[ -z "$uuid" ]]; then
    uuid="$(get_uuid_by_name "$name" || true)"
  fi

  if [[ -z "$uuid" ]]; then
    echo "ERROR: Failed to create or resolve UUID for device '$name'." >&2
    exit 1
  fi

  echo "Created '$name' with uuid: $uuid"
  echo "$uuid"
}

# ----------------------------------------------------------------------
echo "Logging in to RadKit using supplied PROD token ..."
radkit-control account login --prod "$PROD_VALUE"
echo "Login complete."
echo

echo "Ensuring ubuntu0/1/2 jump hosts exist (ubuntu1/2 chained via ubuntu0)..."

UBUNTU0_UUID="$(get_uuid_by_name "$UBUNTU0_NAME" || true)"
if [[ -z "$UBUNTU0_UUID" ]]; then
  UBUNTU0_UUID="$(create_or_update_jumphost "$UBUNTU0_NAME" "$UBUNTU0_HOST")"
fi
echo "ubuntu0 uuid: $UBUNTU0_UUID"

UBUNTU1_UUID="$(get_uuid_by_name "$UBUNTU1_NAME" || true)"
if [[ -z "$UBUNTU1_UUID" ]]; then
  UBUNTU1_UUID="$(create_or_update_jumphost "$UBUNTU1_NAME" "$UBUNTU1_HOST" "$UBUNTU0_UUID")"
fi
echo "ubuntu1 uuid: $UBUNTU1_UUID"

UBUNTU2_UUID="$(get_uuid_by_name "$UBUNTU2_NAME" || true)"
if [[ -z "$UBUNTU2_UUID" ]]; then
  UBUNTU2_UUID="$(create_or_update_jumphost "$UBUNTU2_NAME" "$UBUNTU2_HOST" "$UBUNTU0_UUID")"
fi
echo "ubuntu2 uuid: $UBUNTU2_UUID"

echo
echo "Writing UUIDs to .radkit-uuids.env for reuse ..."
cat > .radkit-uuids.env <<EOF
UBUNTU0_UUID="$UBUNTU0_UUID"
UBUNTU1_UUID="$UBUNTU1_UUID"
UBUNTU2_UUID="$UBUNTU2_UUID"
EOF
echo "Saved: .radkit-uuids.env"
echo

# --------- Resolve device JSON placeholders (x/y/z) --------------------
if [[ ! -f "$DEVICES_JSON" ]]; then
  echo "ERROR: Devices JSON '$DEVICES_JSON' not found." >&2
  exit 1
fi

echo "Resolving jumphostUuid placeholders in $DEVICES_JSON -> $RESOLVED_JSON ..."

jq \
  --arg u0 "$UBUNTU0_UUID" \
  --arg u1 "$UBUNTU1_UUID" \
  --arg u2 "$UBUNTU2_UUID" \
  'map(
      if .jumphostUuid == "x" then .jumphostUuid = $u0
      elif .jumphostUuid == "y" then .jumphostUuid = $u1
      elif .jumphostUuid == "z" then .jumphostUuid = $u2
      else . end
    )' "$DEVICES_JSON" > "$RESOLVED_JSON"

echo "Resolved JSON written to $RESOLVED_JSON"
echo

# --------- Bulk import the resolved devices ----------------------------
echo "Running bulk import with $RESOLVED_JSON ..."
radkit-control device bulk-create --json-input "$RESOLVED_JSON"
echo "Bulk import complete."

echo "==========================================="
echo " Done. Logs saved at: $LOGFILE"
echo " UUIDs: $(pwd)/.radkit-uuids.env"
echo " Resolved devices: $(pwd)/$RESOLVED_JSON"
echo "==========================================="
