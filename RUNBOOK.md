# Runbook

Everyday operation of MobilityFlow AI on a development machine. For what
the product is and how it is built, see `README.md`.

---

## Starting work

```powershell
cd C:\Users\Jafari\Desktop\MobilityFlow_AI5
docker compose up -d
```

Wait until every line says `Healthy` or `Started`, then open:

```
http://localhost
```

**Only that address.** Ports 8501 and 8000 are deliberately not published:
the session cookie can only be set on the one origin where both Streamlit
and the API answer, and reaching the app anywhere else means reaching it
without a session. See `deploy/nginx.conf`.

| What | Where |
|---|---|
| The application | http://localhost |
| API docs | http://localhost/api/docs |
| API health | http://localhost/api/health |
| MinIO console | http://localhost:9001 |

Stopping for the day is optional - containers can be left running:

```powershell
docker compose down
```

---

## After pulling changes

Code lives in the image, not on a mount, so new code needs a rebuild:

```powershell
docker compose build streamlit api celery_worker celery_beat
docker compose up -d
docker compose exec -T api python -m scripts.migrate
```

`docker compose up -d` on its own restarts containers with the **old**
code. If a change seems to have no effect, this is almost always why.

The migration step is safe to run every time - it is idempotent. Skipping
it when a migration is pending does not corrupt anything either: the app
refuses to start and prints the command. That refusal is the check in
`db/schema_check.py` doing its job.

---

## Running the tests

```powershell
python -m pytest -q
```

Needs PostgreSQL reachable on the host - the compose stack publishes it
on `127.0.0.1:5433`, so `docker compose up -d` first. The suite uses its
own database (`mobilityflow_test`) and never touches application data;
see the top of `conftest.py`.

Useful subsets:

```powershell
python -m pytest tests/test_browser_session.py tests/test_session_cookie_endpoint.py -v
python -m pytest -q -k session
```

---

## Sessions and login

The session lives in an HttpOnly cookie (`mf_session`), never in the URL.
Two settings govern it, both optional in `.env`:

| Setting | Default | What it does |
|---|---|---|
| `MOBILITYFLOW_SESSION_IDLE_MINUTES` | 30 | Ends a session nobody has used |
| `MOBILITYFLOW_BROWSER_SESSION_HOURS` | 12 | Caps one login however active |

To test the idle timeout without waiting half an hour, put
`MOBILITYFLOW_SESSION_IDLE_MINUTES=2` in `.env`, run
`docker compose up -d streamlit`, and confirm both halves:

- log in, wait three minutes, refresh → back at the login form;
- log in, click something every minute, refresh → still signed in.

Then **delete the line** rather than commenting it out, and
`docker compose up -d streamlit` again.

A misspelt `MOBILITYFLOW_*` name is refused at startup with the setting
it was probably meant to be - see `bootstrap/config_check.py`. Silently
ignoring one is how an idle timeout came to be configured in a `.env`
file and applied nowhere.

---

## When something breaks

Streamlit deliberately shows users no tracebacks (`showErrorDetails =
"none"` in `.streamlit/config.toml` - a customer once saw table and
column names in an error). So the detail is in the logs:

```powershell
docker compose logs --tail 100 streamlit
docker compose logs --tail 100 api
```

Read from the last `Traceback` down. The final line is the error.

### `password authentication failed for user "mobilityflow"`

`POSTGRES_PASSWORD` was changed in `.env`, but a PostgreSQL password
lives in the data volume and is read from that variable **only when the
volume is first created**. The clients now use the new password and the
server still has the old one.

```powershell
docker compose exec postgres psql -U mobilityflow -d mobilityflow
```

At the `psql` prompt, with the value from `.env`:

```sql
ALTER USER mobilityflow WITH PASSWORD 'the_new_password';
\q
```

```powershell
docker compose restart streamlit api celery_worker celery_beat
```

### Login works, but a refresh returns to the login form

The cookie is not being set. Check, in order:

1. the address is `http://localhost`, not `http://localhost:8501`;
2. `docker compose exec -T api python -m scripts.migrate` has been run;
3. `docker compose exec -T api python -m scripts.verify_session_cookie`
   passes every line.

### A change had no visible effect

The image was not rebuilt. See *After pulling changes*.

---

## Secrets

`.env` is never committed (`.gitignore`, plus a CI check that refuses
it). Neither are `backup_*.sql` dumps - they contain real case data and
password hashes.

When sharing terminal output, filter it:

```powershell
docker compose exec -T streamlit printenv | findstr MOBILITYFLOW
```

A bare `printenv` prints `JWT_SECRET_KEY` and `ENCRYPTION_KEY`. Anyone
holding the first can forge a token for any user and any role without
knowing a password.

Rotating them:

| Secret | Effect of changing it |
|---|---|
| `JWT_SECRET_KEY` | Access tokens invalid; everyone logs in again. Cheap. |
| `POSTGRES_PASSWORD` | Also needs `ALTER USER` above. |
| `MINIO_ROOT_PASSWORD` | Change `S3_SECRET_ACCESS_KEY` to the same value. |
| `ENCRYPTION_KEY` | OCR text of already-processed documents becomes unreadable. The files themselves are unaffected; re-process to restore. |

---

## Committing

```powershell
git checkout -b feature/what-this-is
git add -A
git status
git commit
git push -u origin feature/what-this-is
```

The push prints a link that opens the pull request. CI runs on the PR;
merge when it is green.

If git reports `Unable to create '.git/index.lock': File exists` and no
git process is running:

```powershell
del .git\index.lock
```

If git reports a large number of modified files that contain no changes,
line endings have drifted. `.gitattributes` settles this permanently;
applying it to an existing clone takes one command:

```powershell
git add --renormalize .
git commit -m "Normalise line endings"
```
