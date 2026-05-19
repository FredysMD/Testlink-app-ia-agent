#!/usr/bin/env python3
"""
TestLink MCP API — punto de entrada FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent import TestLinkAgent
from config import API_HOST, API_PORT, API_TITLE, API_VERSION, LOG_LEVEL

app = FastAPI(title=API_TITLE, version=API_VERSION)
agent = TestLinkAgent()


class PromptRequest(BaseModel):
    prompt: str


@app.post("/testlink/prompt")
async def process_testlink_prompt(request: PromptRequest):
    if not agent.connect():
        raise HTTPException(status_code=500, detail="No se pudo conectar a TestLink")
    result = await agent.process_prompt(request.prompt)

    response: dict = {"message": str(result.get("message", ""))}
    if result.get("data") is not None:
        response["count"] = result.get("count", 0)
        response["data"] = result["data"]
    if not result.get("success", True):
        response["error"] = True
    return response


@app.get("/testlink/health")
async def health_check():
    return {"status": "healthy", "service": API_TITLE}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "testlink_api:app",
        host=API_HOST,
        port=API_PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,
    )
