# Security

OTAM keeps account hashes, sessions, node configuration, signing keys and live
SQLite catalogs private and node-local. Never attach these files or setup tokens
to a public issue. Hardware reports may expose filenames, device serials and
private network addresses; redact them before sharing. Local hardware evidence
is deliberately excluded from Git and release packages.

There is no default password. First enrollment requires a private local token;
normal use requires authentication, roles and CSRF checks. Start on loopback and
use SSH/VPN or an explicitly configured trusted HTTPS deployment. Do not expose
the default HTTP listener directly to the public Internet.

For a suspected vulnerability, use this repository's GitHub private vulnerability
reporting feature when available. If unavailable, open a minimal issue requesting
a private contact route without including exploit details, credentials or user
archive contents. Do not publish a real user's sensitive data as a reproduction.

Updates must be tested on copies and installed only when no tape operation is
active. Keep backups and unresolved safety journals. Hardware validation for one
model does not imply that another model is safe. See the documented limitations.
