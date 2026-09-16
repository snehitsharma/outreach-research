from fastapi import FastAPI
from fastapi.responses import FileResponse

from graph import build_graph
from routers.jobs import router as jobs_router
from apscheduler.schedulers.background import BackgroundScheduler
from followup_worker import process_due_followups
from routers.jobs import job_states, job_statuses




app = FastAPI()
app.state.graph = build_graph()
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: process_due_followups(job_states, job_statuses), "interval", minutes=5)
scheduler.start()


@app.get("/health", include_in_schema=False)
def health():
	return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("index.html", media_type="text/html")


app.include_router(jobs_router)