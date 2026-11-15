import os
import json
import re
import urllib.request
from typing import Type, TypeVar
import typer
from pydantic import BaseModel
from rich.console import Console
from google import genai
from google.genai import types

from .telemetry import log_gemini_usage

console = Console()
T = TypeVar("T", bound=BaseModel)


def _clean_json_str(raw: str) -> str:
    """Strips markdown code fences (e.g. ```json ... ```) and leading/trailing whitespace."""
    text = (raw or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def generate_structured(
    conn,
    command_name: str,
    prompt: str,
    schema: Type[T],
    complexity: str = "fast",
) -> T:
    provider = os.environ.get("ANTIGRAVITY_PROVIDER", "gemini").lower().strip()
    if provider == "ollama":
        return _call_ollama(prompt, schema, complexity)
    return _call_gemini(conn, command_name, prompt, schema, complexity)


def _call_gemini(conn, command_name: str, prompt: str, schema: Type[T], complexity: str) -> T:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY missing. Set it or export ANTIGRAVITY_PROVIDER=ollama.")
        raise typer.Exit(1)

    model_name = "gemini-2.5-pro" if complexity == "pro" else "gemini-2.5-flash"
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1,
        ),
    )
    log_gemini_usage(conn, command_name, model_name, resp)
    cleaned = _clean_json_str(resp.text)
    return schema.model_validate_json(cleaned)


def _call_ollama(prompt: str, schema: Type[T], complexity: str) -> T:
    base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    default_model = "qwen2.5-coder:14b" if complexity == "pro" else "qwen2.5-coder:7b"
    model_name = os.environ.get("OLLAMA_MODEL", default_model)

    console.print(f"[magenta]Offline Mode:[/magenta] Running local Ollama model [bold]{model_name}[/bold]...")
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "format": schema.model_json_schema(),
        "stream": False,
        "options": {"temperature": 0.1},
    }

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            cleaned = _clean_json_str(data["message"]["content"])
            return schema.model_validate_json(cleaned)
    except Exception as exc:
        console.print(f"[bold red]Ollama Error:[/bold red] Could not reach {base_url} ({exc}).")
        raise typer.Exit(1)
