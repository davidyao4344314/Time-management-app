# Study Planning App Backend

Initial FastAPI backend foundation for the study planning app.

## Install dependencies

1. Open a terminal.
2. Change into the backend folder:

```bash
cd "/Users/david/Downloads/activities planner app/backend"
```

3. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the backend

From the backend folder, run:

```bash
uvicorn app.main:app --reload
```

The API will start at:

```text
http://127.0.0.1:8000
```

## Test the health endpoint

Open this URL in a browser:

```text
http://127.0.0.1:8000/health
```

Or test with `curl`:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```
