"""Oryveta MVP API. GitHub identity OAuth is separate from future GitHub App permissions."""

from __future__ import annotations

import json
import secrets
import time
import shutil
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oryveta_engine.benchmarks import CHALLENGES
from oryveta_engine.scaffold import BLUEPRINTS, generate_files, write_scaffold
from oryveta_engine.repositories import (InvalidRepository, create_archive,
    fetch_public_github_repo, snapshot_zip, parse_github_url)

from .auth import SESSION_MAX_AGE, csrf_for_session, current_user, hash_token, new_session, require_csrf
from .config import Settings
from .database import Database

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class ProjectInput(BaseModel):
    name: str = Field(min_length=2, max_length=90)
    brief: str = Field(min_length=10, max_length=2500)
    blueprint: str


class ImportInput(BaseModel):
    url: str = Field(min_length=23, max_length=260)


class ArenaInput(BaseModel):
    challenge: str
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    settings.validate()
    app = FastAPI(title="Oryveta API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db = Database(settings.database_path)
    app.state.settings = settings

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https://avatars.githubusercontent.com data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith(("/api/", "/auth/"))
            else "public, max-age=120"
        )
        return response

    @app.get("/api/health")
    def health():
        with app.state.db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "component": "api", "version": "0.1.0"}

    @app.get("/api/config")
    def public_config():
        return {"github_auth_enabled": settings.github_enabled,
                "local_demo_enabled": settings.demo_enabled,
                "navigation": ["Start New", "Evolve"],
                "name": "Oryveta", "version": "0.1.0"}

    @app.get("/auth/github")
    def github_login():
        if not settings.github_enabled:
            raise HTTPException(503, "GitHub OAuth is not configured")
        state = secrets.token_urlsafe(32)
        with app.state.db.connect() as conn:
            conn.execute("INSERT INTO oauth_states(state_hash,expires_at) VALUES(?,?)",
                         (hash_token(state), time.time() + 600))
        query = urlencode({"client_id": settings.github_client_id, "state": state,
                           "redirect_uri": f"{settings.base_url}/auth/github/callback", "scope": "read:user"})
        response = RedirectResponse(f"https://github.com/login/oauth/authorize?{query}", status_code=302)
        # Bind the OAuth response to the browser that initiated sign-in.
        # SameSite=Lax permits this cookie on GitHub's top-level GET redirect.
        response.set_cookie("oryveta_oauth_state", hash_token(state), httponly=True,
                            secure=settings.cookie_secure, samesite="lax", max_age=600)
        return response

    @app.get("/auth/github/callback")
    async def github_callback(code: str, state: str, request: Request):
        browser_state = request.cookies.get("oryveta_oauth_state", "")
        if not browser_state or not secrets.compare_digest(browser_state, hash_token(state)):
            raise HTTPException(403, "OAuth state does not match this browser")
        with app.state.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT expires_at FROM oauth_states WHERE state_hash=?",
                               (hash_token(state),)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state_hash=?", (hash_token(state),))
            conn.commit()
        if not row or row["expires_at"] <= time.time():
            raise HTTPException(403, "Invalid OAuth state")
        async with httpx.AsyncClient(timeout=12) as client:
            exchanged = await client.post(
                "https://github.com/login/oauth/access_token",
                data={"client_id": settings.github_client_id,
                      "client_secret": settings.github_client_secret,
                      "code": code, "redirect_uri": f"{settings.base_url}/auth/github/callback"},
                headers={"Accept": "application/json"},
            )
            exchanged.raise_for_status()
            access_token = exchanged.json().get("access_token")
            if not access_token:
                raise HTTPException(401, "GitHub authorization was rejected")
            profile = await client.get("https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}",
                         "Accept": "application/vnd.github+json", "User-Agent": "oryveta/0.1"})
            profile.raise_for_status()
            user = profile.json()
        if not user.get("id") or not user.get("login"):
            raise HTTPException(401, "GitHub profile missing required information")
        github_id = str(user["id"])
        with app.state.db.connect() as conn:
            found = conn.execute("SELECT id FROM users WHERE github_id=?", (github_id,)).fetchone()
            user_id = found["id"] if found else app.state.db.new_id()
            conn.execute("""INSERT INTO users(id,github_id,login,display_name,avatar_url,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(github_id) DO UPDATE SET
                login=excluded.login,display_name=excluded.display_name,avatar_url=excluded.avatar_url""",
                (user_id, github_id, user["login"], user.get("name") or user["login"],
                 user.get("avatar_url") or "", time.time()))
        session = new_session(app.state.db, user_id)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("oryveta_oauth_state")
        response.set_cookie("oryveta_session", session, httponly=True,
                            secure=settings.cookie_secure, samesite="lax", max_age=SESSION_MAX_AGE)
        return response

    @app.post("/auth/local-demo")
    def demo_login(request: Request):
        if not settings.demo_enabled or request.client is None or request.client.host not in {
            "127.0.0.1", "::1", "testclient"
        }:
            raise HTTPException(404, "Local demo is disabled")
        user_id = "local-demo-user"
        with app.state.db.connect() as conn:
            conn.execute("""INSERT OR IGNORE INTO users
                (id,github_id,login,display_name,avatar_url,created_at)
                VALUES(?,NULL,?,?,?,?)""",
                (user_id, "demo", "Local Demo", "", time.time()))
        session = new_session(app.state.db, user_id)
        response = Response(status_code=204)
        response.set_cookie("oryveta_session", session, httponly=True,
                            secure=settings.cookie_secure, samesite="lax", max_age=SESSION_MAX_AGE)
        return response

    @app.post("/auth/logout")
    def logout(request: Request, user=Depends(current_user), _=Depends(require_csrf)):
        with app.state.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?",
                         (hash_token(request.cookies.get("oryveta_session", "")),))
        response = Response(status_code=204)
        response.delete_cookie("oryveta_session")
        return response

    @app.get("/api/me")
    def me(request: Request, user=Depends(current_user)):
        return {**user, "csrf_token": csrf_for_session(request.cookies["oryveta_session"])}

    @app.get("/api/overview")
    def overview(user=Depends(current_user)):
        db = app.state.db
        with db.connect() as conn:
            project_count = conn.execute("SELECT COUNT(*) c FROM projects WHERE user_id=?", (user["id"],)).fetchone()["c"]
            job_count = conn.execute("SELECT COUNT(*) c FROM jobs WHERE user_id=?", (user["id"],)).fetchone()["c"]
            completed = conn.execute("SELECT COUNT(*) c FROM jobs WHERE user_id=? AND kind='benchmark' AND status='succeeded'", (user["id"],)).fetchone()["c"]
            active = conn.execute("SELECT COUNT(*) c FROM jobs WHERE user_id=? AND status IN ('queued','running')", (user["id"],)).fetchone()["c"]
        return {"projects": project_count, "jobs": job_count, "experiments": job_count,
                "verified_runs": completed, "active_jobs": active}

    @app.get("/api/projects")
    def list_projects(user=Depends(current_user)):
        with app.state.db.connect() as conn:
            rows = conn.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC",
                                (user["id"],)).fetchall()
        return [dict(row) for row in rows]

    def project_dir(user_id: str, project_id: str) -> Path:
        return Path(settings.workspace_root).resolve() / user_id / project_id

    def owned_project(project_id: str, user: dict) -> dict:
        with app.state.db.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?",
                               (project_id, user["id"])).fetchone()
        if row is None:
            raise HTTPException(404, "Project not found")
        return dict(row)

    def create_analysis_job(user_id: str, project_id: str) -> str:
        job_id = app.state.db.new_id()
        now = time.time()
        with app.state.db.connect() as conn:
            conn.execute("""INSERT INTO jobs(id,user_id,project_id,kind,status,created_at,updated_at)
                VALUES(?,?,?,'analyze','queued',?,?)""", (job_id, user_id, project_id, now, now))
        app.state.db.add_event(user_id, "analysis_queued", "Repository analysis queued", job_id)
        return job_id

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectInput, user=Depends(current_user), _=Depends(require_csrf)):
        if data.blueprint not in BLUEPRINTS:
            raise HTTPException(422, "Unsupported project template")
        files = generate_files(data.name, data.brief, data.blueprint)
        project_id = app.state.db.new_id()
        root = project_dir(user["id"], project_id)
        root.parent.mkdir(parents=True, exist_ok=True)
        write_scaffold(root, files)
        try:
            with app.state.db.connect() as conn:
                conn.execute("""INSERT INTO projects(id,user_id,name,brief,blueprint,status,origin,created_at)
                    VALUES(?,?,?,?,?,'scaffolded','new',?)""",
                    (project_id, user["id"], data.name, data.brief, data.blueprint, time.time()))
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        app.state.db.add_event(user["id"], "project_created", f"Starter repository created: {data.name}")
        return {"id": project_id, "name": data.name, "blueprint": data.blueprint,
                "origin": "new", "status": "scaffolded", "files": sorted(files),
                "note": "Runnable starter, not an implementation of all requested features."}

    @app.post("/api/projects/import/github", status_code=201)
    def import_github(data: ImportInput, user=Depends(current_user), _=Depends(require_csrf)):
        try:
            owner, repo = parse_github_url(data.url)
            _, archive = fetch_public_github_repo(data.url)
        except InvalidRepository as err:
            raise HTTPException(422, str(err)) from err
        except httpx.HTTPError as err:
            raise HTTPException(502, "Could not retrieve GitHub repository") from err
        return import_snapshot(archive, repo, user, f"https://github.com/{owner}/{repo}")

    def import_snapshot(archive: bytes, name: str, user: dict, source_url: str | None = None) -> dict:
        project_id = app.state.db.new_id()
        root = project_dir(user["id"], project_id)
        root.parent.mkdir(parents=True, exist_ok=True)
        try:
            count = snapshot_zip(root, archive)
            with app.state.db.connect() as conn:
                conn.execute("""INSERT INTO projects(id,user_id,name,brief,blueprint,status,origin,source_url,created_at)
                    VALUES(?,?,?,'Imported repository','imported','analyzing','import',?,?)""",
                    (project_id, user["id"], name[:90], source_url, time.time()))
            job_id = create_analysis_job(user["id"], project_id)
        except InvalidRepository as err:
            shutil.rmtree(root, ignore_errors=True)
            raise HTTPException(422, str(err)) from err
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return {"id": project_id, "name": name, "origin": "import", "status": "analyzing",
                "file_count": count, "analysis_job_id": job_id}

    @app.post("/api/projects/import/zip", status_code=201)
    async def import_zip(request: Request, user=Depends(current_user), _=Depends(require_csrf)):
        if request.headers.get("content-type", "").split(";")[0] != "application/zip":
            raise HTTPException(415, "Upload a ZIP with Content-Type: application/zip")
        if len(request.headers.get("x-project-name", "Imported project")) > 90:
            raise HTTPException(422, "Project name too long")
        size = 0
        chunks: list[bytes] = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 12 * 1024 * 1024:
                raise HTTPException(413, "ZIP exceeds the 12 MB import limit")
            chunks.append(chunk)
        archive = b"".join(chunks)
        name = request.headers.get("x-project-name", "Imported project")
        return import_snapshot(archive, name, user)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, user=Depends(current_user)):
        result = owned_project(project_id, user)
        root = project_dir(user["id"], project_id)
        if root.is_dir():
            result["files"] = sorted(p.relative_to(root).as_posix()
                                     for p in root.rglob("*") if p.is_file())[:2000]
        with app.state.db.connect() as conn:
            analysis = conn.execute("""SELECT result_json,created_at FROM project_analyses
                WHERE project_id=? ORDER BY created_at DESC LIMIT 1""", (project_id,)).fetchone()
        result["analysis"] = json.loads(analysis["result_json"]) if analysis else None
        return result

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: str, user=Depends(current_user)):
        owned_project(project_id, user)
        root = project_dir(user["id"], project_id)
        if not root.is_dir():
            raise HTTPException(404, "Project source files are not available")
        try:
            archive = create_archive(root)
        except InvalidRepository as err:
            raise HTTPException(413, str(err)) from err
        return Response(content=archive, media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=oryveta-project.zip"})

    @app.post("/api/projects/{project_id}/analyze", status_code=202)
    def queue_analysis(project_id: str, user=Depends(current_user), _=Depends(require_csrf)):
        owned_project(project_id, user)
        if not project_dir(user["id"], project_id).is_dir():
            raise HTTPException(404, "Source snapshot missing")
        job_id = create_analysis_job(user["id"], project_id)
        return {"id": job_id, "status": "queued"}

    @app.get("/api/internal/evaluations/challenges")
    def challenges(user=Depends(current_user)):
        return list(CHALLENGES.values())

    @app.get("/api/internal/evaluations/runs")
    def list_runs(user=Depends(current_user)):
        with app.state.db.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE user_id=? AND kind='benchmark' ORDER BY created_at DESC LIMIT 80",
                                (user["id"],)).fetchall()
        return [{**dict(row), "result": json.loads(row["result_json"]) if row["result_json"] else None} for row in rows]

    @app.post("/api/internal/evaluations/runs", status_code=202)
    def start_run(data: ArenaInput, request: Request, user=Depends(current_user), _=Depends(require_csrf)):
        if data.challenge not in CHALLENGES:
            raise HTTPException(422, "Unsupported benchmark")
        idem = request.headers.get("idempotency-key", "")
        if len(idem) > 128:
            raise HTTPException(422, "Idempotency key too long")
        db = app.state.db
        with db.connect() as conn:
            # Serialize the check-and-insert to make concurrent retries safe.
            conn.execute("BEGIN IMMEDIATE")
            if idem:
                existing = conn.execute("""SELECT id,status,challenge,seed,kind FROM jobs
                    WHERE user_id=? AND idempotency_key=?""", (user["id"], idem)).fetchone()
                if existing:
                    conn.commit()
                    if (existing["kind"], existing["challenge"], existing["seed"]) != (
                        "benchmark", data.challenge, data.seed
                    ):
                        raise HTTPException(409, "Idempotency key was used for another request")
                    return {"id": existing["id"], "status": existing["status"], "replayed": True}
            job_id = db.new_id()
            now = time.time()
            conn.execute("""INSERT INTO jobs
                (id,user_id,kind,challenge,seed,status,idempotency_key,created_at,updated_at)
                VALUES(?,?,'benchmark',?,?,'queued',?,?,?)""",
                (job_id, user["id"], data.challenge, data.seed, idem or None, now, now))
            conn.commit()
        db.add_event(user["id"], "benchmark_queued", f"Queued {data.challenge} benchmark", job_id)
        return {"id": job_id, "status": "queued", "replayed": False}

    @app.get("/api/activity")
    def activity(user=Depends(current_user)):
        with app.state.db.connect() as conn:
            rows = conn.execute("SELECT * FROM events WHERE user_id=? ORDER BY created_at DESC LIMIT 60",
                                (user["id"],)).fetchall()
        return [dict(row) for row in rows]

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
