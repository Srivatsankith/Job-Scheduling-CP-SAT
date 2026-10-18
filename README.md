# DynamiQ

Manufacturing scheduling dashboard using React, FastAPI, OR-Tools CP-SAT, and MongoDB.

## Deploy with Docker Compose

The production Compose setup serves the dashboard through Nginx and keeps the API private on the Compose network. MongoDB is hosted in Atlas; no local MongoDB installation is needed on the deployment host.

1. Install Docker Engine with the Docker Compose plugin on the deployment host.
2. Create `backend/.env` from `backend/.env.example`. Set `MONGODB_URI` to the Atlas driver connection string and `MONGODB_DATABASE` to `dynamiq`.
3. Create the repository-root `.env` from `.env.example` and set a unique `BASIC_AUTH_USER` and long `BASIC_AUTH_PASSWORD`.
4. Add the deployment host's outbound IP address to the Atlas project's IP access list, and create a database user with access to this database.
5. Build and start the services from the repository root:

   ```sh
   docker compose up --build -d
   ```

6. Verify locally at `http://127.0.0.1:8080`. Nginx prompts for the shared dashboard credentials and protects both the UI and API. Check API and database health at `http://127.0.0.1:8080/api/health`.

The API creates its MongoDB collections and indexes at startup. The `resources`, `tasks`, `archived_tasks`, and `schedule_state` collections hold dashboard state. No SQL setup script is used. The web port binds to loopback so it is not exposed directly; configure a TLS reverse proxy on the host to forward to `127.0.0.1:8080` before making the site public. Basic Auth credentials must travel over HTTPS.

## Local development

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) for local run instructions. Run backend tests with `python -m unittest discover -s tests -v` from `backend`; run frontend tests with `npm test` from `frontend`.

## Deployment security

The Compose deployment uses one shared Basic Auth account; it does not provide per-user accounts or roles. Protect the site with HTTPS and do not expose the backend port directly. Do not commit either `.env` file; they contain deployment credentials.
