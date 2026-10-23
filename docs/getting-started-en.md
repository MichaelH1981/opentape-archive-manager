# Getting started

OTAM is a local Linux tape archive manager with a web interface, durable worker,
persistent local staging, SHA-256 verification and an optional independent
catalog node. It stores self-describing, uncompressed PAX TAR archives. MIT license.

## Debian 13

Download `opentape-archive-manager_0.8.6_all.deb` and `SHA256SUMS` from the same
GitHub release. Compare the package's SHA-256, then install:

```sh
sudo apt update
sudo apt install ./opentape-archive-manager_0.8.6_all.deb
sudo cat /var/lib/otam/state/first-start.token
```

Open `http://127.0.0.1:8765`. For a remote server, use an SSH tunnel:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@server
```

Create your administrator account using the private local enrollment token and
a new password entered twice (at least 12 characters). There is no default
password. The one-use token prevents an arbitrary first visitor from claiming
your server. Enrollment closes permanently after success. Existing accounts are
preserved on upgrade. Do not paste enrollment tokens into issues or URLs.

The package uses Debian's Python/FastAPI/Uvicorn/HTTPX packages, without a hidden
pip download. Configuration is `/etc/otam/node.json`; private runtime data is
`/var/lib/otam`. Services are `otam-web` and `otam-worker`, running as `otam`.
The web service initially listens on loopback only. Existing manual `/opt/otam`
installations require an explicit migration; the package refuses to replace them.

## First archive

1. Grant the service user read access to sources. An NFS client IP allowlist
   does not override file ownership and permissions.
2. Configure an appropriate, mounted **local** staging filesystem and restore
   destination, plus the required systemd writable paths. Never use NFS for
   staging or the live SQLite databases. VM/container root overlays are not a
   qualified physical archive staging volume.
3. Start with simulator mode to learn the workflow without touching tape.
4. For hardware, install the Linux tools and explicitly configure udev, the
   worker's device access, supported drive profile, staging qualification and
   separate physical-operation gates. These are not enabled by installation.
5. Register an existing OTAM tape read-only, or explicitly initialize a new tape.
   Initialization makes previous contents unusable; it is not a full secure erase.
6. Create a source plan, review exclusions and select enough target media. With
   sufficient local space, binding media hashes files while producing local TARs
   in a single source pass, followed by an independent complete local inspection.
7. Review the committed plan and explicitly start archiving. Batch mode writes
   all TARs for a medium, then verifies them in a complete sequential readback.
8. Only **VERIFIED** means the complete physical TAR and its file hashes passed.
   At a media change, insert the requested cartridge and confirm the next step.

Progress counts refer to the displayed phase/current TAR, not a guaranteed ETA
for the entire operation. The initial directory inventory has an unknown total.
Use the file catalog to search, then restore into a fresh target. Existing files
are never silently replaced. A selective restore does not reverify skipped data.

Never remove pending/tail safety journals to force a write after a crash. Keep
failed reports and staged files, inspect the cause, and use explicit recovery.
Back up catalog, control, configuration and keys. Stop updates during active tape
work; no timed process killing. Package removal retains private runtime data.

## Scope

Regular file contents are supported. ACLs, xattrs, links, empty directories and
complete system backup are not included. Hardware validation is specific to the
documented IBM LTO-4 profile, not a general qualification of every drive.
Simulator success is not physical media qualification or a performance guarantee.

Further documentation (German): [Debian installation](debian-installation.md),
[User guide](user-guide.md), [configuration](web-configuration.md),
[recovery without OTAM](recovery-without-otam.md) and
[production readiness and limits](production-readiness.md).
