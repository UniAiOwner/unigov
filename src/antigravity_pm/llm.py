import os
import json
import re
import urllib.request
from pathlib import Path
from typing import Type, TypeVar, Optional
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
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> T:
    active_provider = (provider or os.environ.get("ANTIGRAVITY_PROVIDER", "gemini")).lower().strip()
    if active_provider == "ollama":
        return _call_ollama(prompt, schema, complexity, model=model)
    return _call_gemini(conn, command_name, prompt, schema, complexity, model=model)


def _get_gemini_api_key() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    secrets_path = Path.home() / ".agents" / "secrets" / "gemini_api_key.env"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line and not line.startswith("#"):
                return line.strip().strip('"').strip("'")
    return ""


def _call_gemini(
    conn,
    command_name: str,
    prompt: str,
    schema: Type[T],
    complexity: str,
    model: Optional[str] = None,
) -> T:
    api_key = _get_gemini_api_key()
    if not api_key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY missing. Set it or export ANTIGRAVITY_PROVIDER=ollama.")
        raise typer.Exit(1)

    default_model = "gemini-3.5-flash-lite" if complexity == "pro" else "gemini-3.1-flash-lite"
    model_name = model or os.environ.get("GEMINI_MODEL") or default_model
    client = genai.Client(api_key=api_key)
    with console.status(f"[cyan]UniGov: Generating {command_name} using {model_name}...[/cyan]", spinner="dots"):
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


def _call_ollama(
    prompt: str,
    schema: Type[T],
    complexity: str,
    model: Optional[str] = None,
) -> T:
    base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    default_model = "qwen2.5-coder:14b" if complexity == "pro" else "qwen2.5-coder:7b"
    model_name = model or os.environ.get("OLLAMA_MODEL") or default_model

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
    with console.status(f"[magenta]Offline Mode: Querying local Ollama model [bold]{model_name}[/bold]...[/magenta]", spinner="dots"):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                cleaned = _clean_json_str(data["message"]["content"])
                return schema.model_validate_json(cleaned)
        except Exception as exc:
            console.print(f"[bold red]Ollama Error:[/bold red] Could not reach {base_url} ({exc}).")
            raise typer.Exit(1)
