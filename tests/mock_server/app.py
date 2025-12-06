"""
Mock downstream server for end-to-end testing.
"""

import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import uvicorn


app = FastAPI(title="Mock Downstream API")


@app.get("/api/hello")
async def hello():
    """Simple hello endpoint."""
    return {"message": "hello"}


@app.post("/api/echo")
async def echo(request: Request):
    """Echo back the request body."""
    body = await request.json()
    return body


@app.get("/api/slow")
async def slow():
    """Slow endpoint for timeout testing."""
    await asyncio.sleep(2)
    return {"message": "slow response"}


@app.get("/api/error")
async def error():
    """Error endpoint."""
    raise HTTPException(status_code=500, detail="Internal error")


@app.get("/api/stream")
async def stream():
    """SSE streaming endpoint."""
    async def generate():
        for i in range(5):
            yield f"data: message {i}\n\n"
            await asyncio.sleep(0.5)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Mock OpenAI-style chat completions endpoint."""
    body = await request.json()

    if body.get("stream"):
        async def generate():
            for i in range(3):
                chunk = {
                    "id": f"chatcmpl-{i}",
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"token{i} "},
                            "finish_reason": None
                        }
                    ]
                }
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.2)
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
        )

    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! This is a mock response."
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        }
    }


@app.get("/v1/models")
async def list_models():
    """Mock OpenAI-style models endpoint."""
    return {
        "object": "list",
        "data": [
            {"id": "gpt-4", "object": "model"},
            {"id": "gpt-3.5-turbo", "object": "model"},
        ]
    }


def run_mock_server(port: int = 9999):
    """Run the mock server."""
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    run_mock_server()
