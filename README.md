# RAMA Web Portal

Static HTML pages and a small Python/MySQL backend for SLA inquiries and the
role-based NOC dashboard.

## Requirements

- Python 3.5 or newer
- MySQL 8
- MySQL database `rama_sla`

Install the Python dependency:

```powershell
py -3 -m pip install -r python\requirements.txt
```

Create or update the MySQL schema:

```powershell
mysql --host=127.0.0.1 --port=3306 --user=root < database\rama_sla_schema.sql
```

Set `RAMA_DB_HOST`, `RAMA_DB_PORT`, `RAMA_DB_USER`, `RAMA_DB_PASSWORD`, and
`RAMA_DB_NAME` for your MySQL installation before starting the API. On first
startup, create the initial manager and worker accounts using the interactive
prompts, or provide `RAMA_MANAGER_USERNAME`, `RAMA_MANAGER_PASSWORD`,
`RAMA_WORKER_USERNAME`, and `RAMA_WORKER_PASSWORD` through environment
variables.

Start the backend from the project root:

```powershell
py -3 python\sla_form_backend.py
```

Open the site at <http://127.0.0.1:8001/> or the NOC dashboard at
<http://127.0.0.1:8001/noc-dashboard.html>.

Workers can view records. Managers can view, add, update status, and delete
inquiries.

## GitHub Pages

The public GitHub Pages site serves the static HTML pages only. GitHub Pages
does not run the Python API or connect to MySQL, so inquiry submission and NOC
dashboard data require the backend to be hosted separately and configured with
a private database. Do not put database files, credentials, or password hashes
in the public repository.

## Local-only files

The populated local database, Python cache files, environment files, and
VS Code database connection settings are intentionally excluded from Git.
Apply the SQL schema to create the database structure; do not commit database
records, account credentials, or password hashes.
