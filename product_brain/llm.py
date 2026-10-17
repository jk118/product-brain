"""Minimal async client for an OpenAI-compatible chat endpoint (Crusoe Managed Inference).

Stdlib only. In mock mode no request is sent; prompts are still built so token
counts stay comparable between teams.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass
class Settings:
    base_url: str
    api_key: str
    agent_model: str
    curator_model: str
    concurrency: int = 8
    max_tokens: int = 1024
    timeout: float = 90.0
    thinking: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = lambda k, default="": os.environ.get(k) or default  # blank values in .env fall back too
        agent = env("AGENT_MODEL", "nvidia/Nemotron-3.5-Lightning-30B-A3B")
        return cls(
            base_url=env("CRUSOE_BASE_URL", "https://api.inference.crusoecloud.com/v1"),
            api_key=env("CRUSOE_API_KEY"),
            agent_model=agent,
            curator_model=env("CURATOR_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"),
            concurrency=int(env("LLM_CONCURRENCY", "4")),
            max_tokens=int(env("LLM_MAX_TOKENS", "1024")),
            thinking=env("LLM_THINKING", "false").lower() in ("1", "true", "yes"),
        )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def parse_json(text: str):
    """Pull the first JSON object out of a model reply (tolerates <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


class LLM:
    def __init__(self, settings: Settings, model: str, mock: bool = False):
        self.settings, self.model, self.mock = settings, model, mock
        self._sem = asyncio.Semaphore(settings.concurrency)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def chat(self, system: str, user: str, max_tokens: int | None = None,
                   temperature: float = 0.1) -> tuple[str, int]:
        """Returns (reply text, total tokens used). Mock mode returns ("", estimated prompt tokens)."""
        self.calls += 1
        if self.mock:
            n = estimate_tokens(system) + estimate_tokens(user)
            self.prompt_tokens += n
            return "", n
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens or self.settings.max_tokens,
            "temperature": temperature,
            # Nemotron reasons by default and can spend the whole budget before answering
            "chat_template_kwargs": {"enable_thinking": self.settings.thinking},
        }
        async with self._sem:
            data = await asyncio.to_thread(self._post, body)
        usage = data.get("usage") or {}
        p = usage.get("prompt_tokens") or estimate_tokens(system + user)
        c = usage.get("completion_tokens") or 0
        self.prompt_tokens += p
        self.completion_tokens += c
        return data["choices"][0]["message"].get("content") or "", p + c

    def _post(self, body: dict) -> dict:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"})
        tries = 8  # without a payment method Crusoe allows only 30 requests/min per model
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=self.settings.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                    raise RuntimeError(f"LLM HTTP {e.code}: {e.read()[:300]!r}") from e
            except (urllib.error.URLError, TimeoutError):
                if attempt == tries - 1:
                    raise
            time.sleep(min(60, 2 ** attempt) + random.uniform(0, 1))
        raise RuntimeError("unreachable")
