# AcxiomCRM

A Django CRM application for managing customers, leads, opportunities, follow-ups,
activities, users, and audit history. It includes a REST API, reports, and
role-based access for Admin, Manager, and SalesExecutive users.

## Requirements

- Python 3.10 or later
- Dependencies listed in `requirements.txt`

## Local setup (Windows PowerShell)

From the project directory:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Explicitly enable Django debug mode for local development.
$env:DJANGO_DEBUG = "1"

python manage.py migrate
python manage.py seed
python manage.py runserver
```

Open <http://127.0.0.1:8000/> in your browser. The SQLite database is created
as `db.sqlite3` in the project directory.

## Development test accounts

After running `python manage.py seed`, these accounts are available:

| Username | Role | Password |
| --- | --- | --- |
| `admin1` | Admin | `Test@1234` |
| `manager1` | Manager | `Test@1234` |
| `sales1` | SalesExecutive | `Test@1234` |

These are shared development credentials only. Do not use them in production or
expose them on a public deployment.

## Run tests

```powershell
$env:DJANGO_DEBUG = "1"
python manage.py test crm
```

## Production settings

`DEBUG` is off by default. Local development must explicitly set
`DJANGO_DEBUG=1`. For production, leave it unset or set it to `0`, and configure:

- `DJANGO_SECRET_KEY` with a strong, unique secret
- `DJANGO_ALLOWED_HOSTS` with a comma-separated list of the site's host names

When debug mode is off, the application requires both production variables and
enables secure cookies, HTTPS redirection, and HSTS. Serve the application over
HTTPS.
