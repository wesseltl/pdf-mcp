# Smart Lab Index Controlled-Production Deployment

This runbook targets one on-premises Linux host, one approved read-only filesystem scope, and a
small trusted operator group. It does not claim regulatory validation, Windows/AD ACL enforcement,
or tenant isolation.

The hash-verified dependency lock supplied with `0.6.0` targets CPython 3.12 on Linux x86_64 with
glibc 2.34 or newer. Build and validate a separate lock and artifact before using another production
platform. The normal package remains compatible with Python 3.10 and newer for non-production use.

## Release gates

Do not connect confidential laboratory data until all of these are true:

- The source scope and service account have been approved by the data owner and security team.
- The service account has read access to the approved source and no source write access.
- The state and backup volumes use host-level encryption and are excluded from the source tree.
- Operators connect only on the host or through an encrypted SSH tunnel. Port `8876` is not exposed
  on a public or internal LAN interface.
- The executable or wheel checksum is verified. Windows/macOS artifacts are publisher-signed when
  signing credentials are configured. An unsigned artifact requires an organization-approved,
  reproducible local build and independent checksum verification.
- A backup has been created, verified, restored to a separate path, and opened successfully.
- Representative, non-sensitive lab fixtures pass extraction and conflict-review acceptance tests.
- Retention, incident response, patching, and restore ownership are assigned locally.

## Hash-verified offline installation

On a connected staging host with the same Python/OS target, create the runtime wheelhouse from the
release lock. Transfer the wheelhouse, application wheel, lock, and separately published application
checksum through the organization's approved media path.

```bash
python3.12 -m pip download --require-hashes \
  --dest wheelhouse \
  -r requirements/smart-lab-production-linux-x86_64-py312.lock
sha256sum --ignore-missing -c python-distributions-SHA256SUMS
```

On the production host, verify the application checksum again and install without contacting an
index. The service account does not need package-install permissions.

```bash
cd /approved-media
sha256sum --ignore-missing -c python-distributions-SHA256SUMS
sudo python3.12 -m venv /opt/smart-lab-index/venv
sudo /opt/smart-lab-index/venv/bin/pip install --no-index \
  --find-links /approved-media/wheelhouse --require-hashes \
  -r /approved-media/smart-lab-production-linux-x86_64-py312.lock
sudo /opt/smart-lab-index/venv/bin/pip install --no-index --no-deps \
  /approved-media/pdf_agent_mcp-0.6.0-py3-none-any.whl
/opt/smart-lab-index/venv/bin/pip check
```

## Service account and paths

Example paths used by the supplied systemd units:

```bash
sudo useradd --system --home /var/lib/smart-lab-index --shell /usr/sbin/nologin smart-lab-index
sudo install -d -o smart-lab-index -g smart-lab-index -m 0700 /var/lib/smart-lab-index
sudo install -d -o root -g smart-lab-index -m 0750 /etc/smart-lab-index
sudo install -d -o root -g root -m 0755 /opt/smart-lab-index
```

Install the application in `/opt/smart-lab-index/venv`, then create the operator key as the service
account. The command prints the one-time browser password and stores the same value in a `0600` file.

```bash
sudo -u smart-lab-index /opt/smart-lab-index/venv/bin/smart-lab-index init-operator \
  --output /var/lib/smart-lab-index/operator.token
sudo install -o smart-lab-index -g smart-lab-index -m 0600 \
  /var/lib/smart-lab-index/operator.token /etc/smart-lab-index/operator.token
sudo rm /var/lib/smart-lab-index/operator.token
```

Copy and edit the environment and unit templates. If the source is not `/srv/lab-data`, also change
the unit's `ConditionPathIsDirectory` and `ReadOnlyPaths` paths. Keep the source outside
`/var/lib/smart-lab-index`. The service receives the operator key through systemd's read-only
credential mount rather than opening the configuration copy directly.

```bash
sudo install -o root -g smart-lab-index -m 0640 \
  deploy/systemd/smart-lab-index.env.example /etc/smart-lab-index/smart-lab-index.env
sudo install -o root -g root -m 0644 deploy/systemd/smart-lab-index*.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/smart-lab-index-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smart-lab-index.service smart-lab-index-backup.timer
```

The app performs one incremental run at startup and every configured interval. One malformed parser
input is handled in a disposable child process with CPU, memory, wall-clock, file-write, network, and
serialized-output controls. The parent continues with the remaining files.

## Health and access

The service listens only on `127.0.0.1`. Liveness and readiness reveal no indexed content:

```bash
curl --fail http://127.0.0.1:8876/healthz
curl --fail http://127.0.0.1:8876/readyz
/opt/smart-lab-index/venv/bin/smart-lab-index health \
  --database /var/lib/smart-lab-index/index.db
```

From an operator PC, use an SSH tunnel and open `http://127.0.0.1:8876/`. Enter username `operator`
and the generated access key when the browser prompts.

```bash
ssh -N -L 8876:127.0.0.1:8876 SSH_USER@SERVER_IP
```

## Backup and restore drill

Backups are consistent SQLite snapshots with an owner-only JSON manifest and SHA-256. They are still
plaintext and must be stored on an encrypted, access-controlled volume. Keep each backup beside its
`BACKUP_NAME.db.manifest.json`; restore fails closed when that manifest is absent, linked, malformed,
or inconsistent with the database.

```bash
sudo -u smart-lab-index /opt/smart-lab-index/venv/bin/smart-lab-index backup \
  --database /var/lib/smart-lab-index/index.db
/opt/smart-lab-index/venv/bin/smart-lab-index verify-backup \
  /var/lib/smart-lab-index/backups/index-YYYYMMDDTHHMMSSZ.db
```

Restore is offline and fails while the running app owns the database. `--replace` first creates and
verifies a pre-restore safety backup.

```bash
sudo systemctl stop smart-lab-index.service
sudo -u smart-lab-index /opt/smart-lab-index/venv/bin/smart-lab-index restore \
  /secure-backups/index-YYYYMMDDTHHMMSSZ.db \
  --database /var/lib/smart-lab-index/index.db --replace
sudo systemctl start smart-lab-index.service
curl --fail http://127.0.0.1:8876/readyz
```

The supplied timer creates daily backups but deliberately does not delete them. Configure monitored
capacity and an approved retention policy, copy both files to a separate encrypted failure domain,
and schedule periodic restore drills. A local backup on the same disk is not disaster recovery.

## Remaining deployment responsibilities

The organization must validate extraction against its actual templates, decide which sources are
authoritative, define issue-review procedures, and verify source/result access rules. The current
filesystem connector records POSIX mode ownership but does not enforce Windows/AD/SharePoint ACLs.
Use a dedicated source scope whose entire indexed result set may be seen by every configured operator.
Monitor service health, backup failures, disk capacity, and the system journal; re-run dependency and
fixture validation before every upgrade.
