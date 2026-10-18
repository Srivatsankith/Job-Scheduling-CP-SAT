# DynamiQ dashboard

The React dashboard uses the FastAPI backend for tasks, archived tasks, resources, schedules, and solver requests. MongoDB persistence is configured by the backend; the browser keeps only transient UI state.

## Local development

Install Node.js, install the backend requirements, and configure `backend/.env` using `backend/.env.example`. Start MongoDB or configure a MongoDB Atlas URI, then start the API from `backend`:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

From this directory, run:

```powershell
npm ci
npm run dev
```

Vite proxies `/api` requests to the local backend.

## Production

Use the repository-level `docker-compose.yml` to build the production React/Nginx image and FastAPI image. The Nginx container serves the static dashboard and proxies `/api` to the backend.
