"""{{project_name}} — FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="{{project_name}}",
    description="{{description}}",
    version="0.0.1",
)


@app.get("/health")
def health():
    return {"status": "ok"}
