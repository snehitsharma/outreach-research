from fastapi import FastAPI

from graph import build_graph
from routers.jobs import router as jobs_router


app = FastAPI()
app.state.graph = build_graph()


@app.get("/health", include_in_schema=False)
def health():
	return {"status": "ok"}


app.include_router(jobs_router)