# SlowBooks Pro Server Edition — setup guide

One download, two products: the same signed Windows build that runs as a
single-user desktop app can serve your whole office. Add a second user
and the deployment *becomes* Server Edition — no separate license, no
separate download, free either way.

## What you get

- One Windows PC hosts the books; everyone else uses a **browser** —
  nothing to install on the other computers.
- **Users and roles**: admin (everything), bookkeeper (daily books, no
  admin functions), read-only (reports and lookups). **HR and payroll are
  admin functions** — pay runs, pay stubs, W-2/941 forms, direct-deposit
  accounts, portal tokens, benefits, garnishments, onboarding paperwork and
  employee records are refused to the other two roles, reads included; the
  employee list stays visible to them as a directory (names, activity,
  work state) with pay, tax elections and addresses blanked. Time entries
  and time off remain daily books.
- Every change in the audit log says **who** made it.
- The company stays **one file** — backup is copy, undo is restore.

## Quick trial (no install, stops when you close it)

Configure these settings in the data home's `.env` before starting. Use
absolute paths to a PEM certificate chain and unencrypted PEM private key:

```dotenv
SLOWBOOKS_TLS_CERTFILE=C:/ProgramData/SlowBooksPro/tls/server.pem
SLOWBOOKS_TLS_KEYFILE=C:/ProgramData/SlowBooksPro/tls/server-key.pem
SLOWBOOKS_TLS_CA_FILE=C:/ProgramData/SlowBooksPro/tls/office-ca.pem
SLOWBOOKS_TLS_HEALTH_HOST=books.office.example
```

The CA bundle is needed for a private CA; otherwise system trust is used.
Clients must trust the issuer. The certificate must cover the hostname clients
use. Set `SLOWBOOKS_TLS_HEALTH_HOST` to that name, resolving to this server
locally, so the health check does not require a loopback IP certificate.
For the Windows updater, pass the same name as `-HealthHost`; its default
is the Windows computer name. Without the launcher setting, the probe uses
the bound interface IP (loopback for `0.0.0.0`). Do not bypass certificate warnings.
Plain-HTTP LAN startup is disabled; local desktop mode is unchanged.

On the machine that will host, using the configured data home:

```powershell
cd <folder containing SlowBooksPro.exe>
.\SlowBooksPro.exe --serve-lan --data-dir C:\ProgramData\SlowBooksPro
```

A popup shows the connect URLs (also written to `connect-urls.txt` in the
data folder). Allow the Windows Firewall prompt. From any other computer
on the network, browse to `https://<host-name>:3001`.

## Permanent install (starts with Windows, no login needed)

From an **elevated** PowerShell in the folder containing the exe:

```powershell
powershell -ExecutionPolicy Bypass -File _internal\scripts\windows\serveredition-install.ps1
```

This registers a startup task as LOCAL SERVICE, permits only local-subnet
clients on Private/Domain firewall profiles, and sets the data home to
`C:\ProgramData\SlowBooksPro` (machine-wide, not one user's profile),
starts the server, and prints your team's connect URLs. If you already
have desktop-mode books in `%LOCALAPPDATA%\SlowBooksPro`, the script
copies them (company files, encryption key, uploads, backups) into the
new data home the first time — your desktop copies are left untouched.
Existing destination files are not overwritten. Reconcile any conflicts and
preserve the original encryption keys before proceeding. Configure TLS in this
data home's `.env`; the installer stops if certificate/key paths are missing.
LOCAL SERVICE needs read access to the installed application and TLS files;
it receives modify access to the data home. Protect private keys and audit
existing file permissions. Native Windows installation remains a release test gate.

Run it from an **elevated** PowerShell (right-click → Run as
Administrator) and from the installed app's folder — a wrong location
stops with a "SlowBooksPro.exe not found" message before anything is
changed.

Undo it any time:

```powershell
powershell -ExecutionPolicy Bypass -File _internal\scripts\windows\serveredition-uninstall.ps1
```

Your books survive uninstall — the script never deletes data.

## Adding your team

On a multi-user install the sign-in screen lists active usernames, so each
person selects their name and enters only their password. Names—not roles—are
visible before sign-in, so Server Edition remains appropriate only on a trusted
network.

1. Sign in as the admin → **Settings → Users**.
2. Add each person with a username, password, and role. The moment a
   second user exists, the login screen gains a username field and the
   header reads **SERVER EDITION**.
3. Roles are enforced server-side: a read-only user physically cannot
   post an entry; a bookkeeper cannot touch Settings, Users, backups, or
   migrations. The last active admin can never be locked out — the app
   refuses to demote or deactivate them.
4. Account status and credentials are checked on subsequent requests. Changing
   a role or password requires signing in again; disabled/deleted accounts are
   denied. Pre-upgrade session cookies also require a fresh login.

## Honest limits (current release)

- **Deployment validation required** — verify certificate trust, service file
  permissions, firewall scope, and backup/restore before use. These changes are
  not enterprise certification; do not expose the service to the internet.
- Comfortable for small teams (2–10 people). The database serializes
  writes; hundreds of concurrent users is not the design target.
- The update badge appears in-app as usual: opening the app asks
  dl.slowbookspro.com for the latest version, which tells that host the
  install's IP address and version. Set `SLOWBOOKS_UPDATE_CHECK=0` in the
  host's SlowBooks `.env` file and restart to turn it off. Updating means
  running the new installer on the host machine.

## Troubleshooting

- **"Nothing happened" when running the exe** — the packaged exe has no
  console; output goes to `launcher.log` in the data folder, and
  `--serve-lan` shows its URLs in a popup + `connect-urls.txt`.
- **Double-clicking the exe shows a WebView2 error** — that's the
  *desktop window* needing the WebView2 runtime (the installer sets it
  up; the portable zip doesn't). `--serve-lan` doesn't need WebView2 at
  all — browsers on client machines are all it takes.
- **Other computers can't connect** — check the firewall rule (the
  install script creates it; the quick-trial path relies on you clicking
  Allow), and confirm host and clients are on the same network.
