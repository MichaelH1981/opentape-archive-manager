#!/usr/bin/env bash
# READ-ONLY tape acceptance with GNU/Linux tools and a standalone Python helper.
# Stop the idle OTAM worker first; use its user, state directory and TMPDIR.
set -euo pipefail
umask 077
export LC_ALL=C

if [[ $# != 9 ]]; then
  printf 'Usage: %s STATE TMPDIR NST_DEVICE SG_DEVICE DRIVE_SERIAL MAM_SERIAL MEDIA_UUID NEW_OUTPUT RECOVER_PY\n' "$0" >&2
  exit 2
fi
state=$1
test_tmp=$2
tapedev=$3
sgdev=$4
drive_serial=$5
medium_serial=$6
media_id=$7
output=$8
recover_py=$9
[[ "$tapedev" =~ ^/dev/nst[0-9]+$ && "$sgdev" =~ ^/dev/sg[0-9]+$ ]]
[[ "$state" = /* && "$test_tmp" = /* && "$output" = /* && "$recover_py" = /* ]]
[[ -d "$state/drive-locks" && -d "$test_tmp" && -f "$recover_py" && ! -e "$output" ]]
[[ "$output" != /dev/* && "$output" != /proc/* && "$output" != /sys/* ]]
[[ ! -L "$state/worker.lock" ]]
exec 9>"$state/worker.lock"
flock -n 9
io_lock="$test_tmp/otam-io-$(id -u).lock"
[[ ! -L "$io_lock" ]]
exec 8>"$io_lock"
flock -n 8

tape_name=${tapedev##*/}
sg_name=${sgdev##*/}
device_sysfs=$(readlink -f "/sys/class/scsi_tape/$tape_name/device")
[[ "$device_sysfs" = "$(readlink -f "/sys/class/scsi_generic/$sg_name/device")" ]]
drive_id=$(printf '%s|%s' "$device_sysfs" "$drive_serial" | sha256sum | cut -c1-32)
[[ ! -L "$state/drive-locks/$drive_id.lock" ]]
exec 7>"$state/drive-locks/$drive_id.lock"
flock -n 7

inquiry=$(sg_inq --page=0x80 --export "$sgdev")
grep -Fx -- "SCSI_IDENT_SERIAL=$drive_serial" <<< "$inquiry"
mam=$(sg_read_attr --first=0x401 "$sgdev")
actual_medium=$(sed -n 's/^  Medium serial number: *//p' <<< "$mam" | sed 's/[[:space:]]*$//')
[[ "$actual_medium" = "$medium_serial" ]]
options=$(<"/sys/class/scsi_tape/$tape_name/options")
(( (options & ~0x107) == 0 ))

mkdir -m 700 -- "$output"
trap 'result=$?; if (( result != 0 )); then jq -n --argjson status "$result" --arg medium "$medium_serial" '\''{state:"FAILED",exit_status:$status,medium_serial:$medium,scope:"read-only GNU/Linux tape recovery"}'\'' > "$output/report.json"; fi' EXIT
printf '%s\n' "$inquiry" > "$output/inquiry.txt"
printf '%s\n' "$mam" > "$output/mam.txt"

mt -f "$tapedev" setblk 0
read_file() {
  local position=$1
  local destination=$2
  mt -f "$tapedev" rewind
  if (( position > 0 )); then mt -f "$tapedev" fsf "$position"; fi
  local observed
  observed=$(mt -f "$tapedev" status)
  printf '%s\n' "$observed" > "$output/position-$position.txt"
  grep -F -- "File number=$position, block number=0," <<< "$observed"
  # No fullblock/sync/noerror: preserve every variable record unchanged and stop
  # at the first physical EOF. Output must be a new ordinary file.
  dd if="$tapedev" of="$destination" bs=1M conv=excl status=progress
}

read_file 0 "$output/00000000.tar"
tar -xOf "$output/00000000.tar" media.json | jq -e --arg id "$media_id" --arg serial "$medium_serial" \
  '.format == "otam-pax-v1" and .media_id == $id and .medium_serial == $serial'
read_file 1 "$output/00000001.tar"
read_file 2 "$output/00000002.tar"
tar -tf "$output/00000001.tar" > "$output/tar-members.txt"
result=$(python3 -I "$recover_py" "$output/00000001.tar" "$output/00000002.tar" "$output/restored")
(cd "$output" && sha256sum 00000000.tar 00000001.tar 00000002.tar > SHA256SUMS)
archive_hash=$(sha256sum "$output/00000001.tar" | cut -d' ' -f1)
jq -n --arg drive "$drive_serial" --arg medium "$medium_serial" --arg media "$media_id" \
  --arg hash "$archive_hash" --argjson result "$result" \
  '{state:"VERIFIED",scope:"read-only GNU/Linux device recovery without OTAM imports",drive_serial:$drive,medium_serial:$medium,media_id:$media,archive_sha256:$hash,result:$result}' \
  > "$output/report.json"
printf '%s\n' "$result"
