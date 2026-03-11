"""
github_models_client.py — AI code generation using GitHub Models API.

GitHub Models gives you FREE access (via GitHub Student Pack / GitHub token) to:
  - openai/gpt-4o              — Best quality, smartest code
  - openai/gpt-4o-mini         — Fast & cheap, great for most apps (DEFAULT)
  - meta/llama-3.1-405b-instruct — Meta's largest open model
  - meta/llama-3.3-70b-instruct  — Very capable, fast
  - anthropic/claude-3.5-sonnet  — Anthropic's best model
  - mistral-ai/mistral-large     — Mistral's flagship model
  - microsoft/phi-4              — Small but very capable

API is OpenAI-compatible, uses your existing GITHUB_TOKEN — no new keys!
Endpoint: https://models.inference.ai.azure.com

ARCHITECTURE (Two-Pass):
  Pass 1 (Plan):     LLM returns a JSON manifest of files to create.
  Pass 2 (Generate): For each file, LLM generates raw plain-text content.
"""

import time
import json
import re
from pathlib import Path
from openai import OpenAI
from config import config

# ── Load Coding Standards ──────────────────────────────────────────────────────
_STANDARDS_FILE = Path(__file__).parent / "CODING_STANDARDS.md"
CODING_STANDARDS = ""
if _STANDARDS_FILE.exists():
    CODING_STANDARDS = _STANDARDS_FILE.read_text(encoding="utf-8")

# ── System Prompts (same as groq_client) ──────────────────────────────────────

PLAN_PROMPT = """You are an expert software architect specializing in full-stack web and SaaS applications.

Your job is to receive a plain-English app description and return a JSON PLAN — a list of files to generate.

OUTPUT FORMAT (strict JSON object, no markdown):
{
  "repo_name": "kebab-case-app-name",
  "description": "One-line description of the app",
  "tech_stack": ["Python", "Flask", "HTML", "CSS", "JavaScript"],
  "files": [
    {"path": "app.py", "description": "Main Flask application with all routes"},
    {"path": "templates/index.html", "description": "Main HTML page with inline CSS and JS"},
    {"path": "requirements.txt", "description": "Python dependencies"},
    {"path": "Dockerfile", "description": "Docker container config"},
    {"path": ".gitignore", "description": "Git ignore rules"},
    {"path": "README.md", "description": "Project overview and setup guide"},
    {"path": "TECHNICAL_DOCS.md", "description": "API, architecture, and code documentation"},
    {"path": "HOW_TO_RUN.md", "description": "Step-by-step instructions to run locally and with Docker"}
  ],
  "how_to_run": "Brief steps: clone repo, install deps, run app"
}

RULES:
1. Support any tech stack: Flask, FastAPI, Node/Express, pure HTML/JS, React, etc.
2. Always include Dockerfile.
3. Always include README.md, TECHNICAL_DOCS.md, HOW_TO_RUN.md.
4. repo_name: lowercase, hyphens only.
5. Do NOT include any code in this response. Only the manifest.
"""

FILE_PROMPT_TEMPLATE = """You are an expert {tech} developer. You MUST follow the coding standards below EXACTLY.

=== CODING STANDARDS (MANDATORY) ===
{coding_standards}
=== END CODING STANDARDS ===

Generate the COMPLETE content for this file: {file_path}
Description: {file_description}

This file is part of: {app_description}
Tech stack: {tech_stack}

CRITICAL RULES:
- Output ONLY the raw file content. No explanations, no markdown fences, no preamble.
- NEVER use placeholders like TODO, pass, ..., or "implement later"
- EVERY file must be COMPLETE and WORKING — no truncation
- For HTML: use Google Fonts CDN, modern dark/light theme, gradient accents, smooth animations, mobile-responsive.
- For Python/backend: proper logging, environment variables for secrets.
- For Dockerfiles: best security practices, non-root user.
"""

# ── GitHub Models available via the inference API ─────────────────────────────
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Fallback order when a model hits rate limits
GITHUB_MODELS_FALLBACK_CHAIN = [
    "gpt-4o-mini",
    "gpt-4o",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-405b-instruct",
    "mistral-ai/mistral-large",
    "microsoft/phi-4",
]


class GitHubModelsClient:
    _override_model: str | None = None  # Set by /model Discord command at runtime

    def __init__(self):
        self.client = OpenAI(
            base_url=GITHUB_MODELS_ENDPOINT,
            api_key=config.GITHUB_TOKEN,  # Uses your existing GitHub token!
        )
        self.model_name = "gpt-4o-mini"  # Default: fast + high quality

    @property
    def active_model(self) -> str:
        return GitHubModelsClient._override_model or self.model_name

    def _next_fallback(self, current_model: str) -> str | None:
        """Return the next model in the fallback chain after current_model, or None."""
        try:
            idx = GITHUB_MODELS_FALLBACK_CHAIN.index(current_model)
            if idx + 1 < len(GITHUB_MODELS_FALLBACK_CHAIN):
                return GITHUB_MODELS_FALLBACK_CHAIN[idx + 1]
        except ValueError:
            pass
        return None

    def _call(self, prompt: str, system: str, json_mode: bool = False, max_tokens: int = 8192) -> tuple[str, object]:
        """Call GitHub Models API with retry + automatic cross-model fallback on rate limits."""
        last_err = None
        model = self.active_model

        while model:
            for attempt in range(3):
                try:
                    kwargs = dict(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.4,
                        max_tokens=max_tokens,
                    )
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    print(f"[GHModels] 🤖 Calling `{model}` (attempt {attempt+1})...")
                    response = self.client.chat.completions.create(**kwargs)

                    # Persist any model switch globally so next file also uses it
                    if model != (GitHubModelsClient._override_model or self.model_name):
                        GitHubModelsClient._override_model = model

                    return response.choices[0].message.content.strip(), response

                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_rate_limit = "rate" in err_str or "429" in err_str or "quota" in err_str or "limit" in err_str

                    if is_rate_limit:
                        if attempt < 2:
                            wait = 15 * (2 ** attempt)
                            print(f"[GHModels] ⏳ Rate limit on `{model}` (attempt {attempt+1}/3). Waiting {wait}s...")
                            time.sleep(wait)
                        else:
                            next_model = self._next_fallback(model)
                            if next_model:
                                print(f"[GHModels] ⚠️  Rate limit exhausted on `{model}` — switching to `{next_model}`")
                                model = next_model
                                break  # break inner loop, continue outer while
                            else:
                                print(f"[GHModels] ❌ All fallback models exhausted.")
                                raise last_err  # type: ignore
                    else:
                        print(f"[GHModels] ❌ Non-rate-limit error on `{model}`: {e}")
                        raise
            else:
                break

        raise last_err  # type: ignore

    def generate_app(self, user_prompt: str) -> dict:
        """
        Two-pass generation:
          Pass 1: Get a JSON manifest (file list + metadata).
          Pass 2: Generate each file's content as raw plain text.
        """
        # ── Pass 1: Plan ──────────────────────────────────────────────────────
        print(f"[GHModels] 📋 Pass 1: Planning app structure with `{self.active_model}`...")
        plan_text, plan_response = self._call(
            prompt=f"Plan this application: {user_prompt}",
            system=PLAN_PROMPT,
            json_mode=True,
            max_tokens=2048,
        )

        # Strip fences just in case
        plan_text = re.sub(r"^```(?:json)?\s*", "", plan_text, flags=re.MULTILINE)
        plan_text = re.sub(r"\s*```$", "", plan_text, flags=re.MULTILINE).strip()

        try:
            plan = json.loads(plan_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"❌ Failed to parse plan from GitHub Models: {e}\nRaw: {plan_text[:500]}")

        if not isinstance(plan, dict) or "files" not in plan:
            raise ValueError(f"❌ GitHub Models returned an unexpected plan format: {plan_text[:300]}")

        repo_name = plan.get("repo_name", "my-app")
        description = plan.get("description", user_prompt[:100])
        tech_stack = plan.get("tech_stack", ["HTML", "CSS", "JavaScript"])
        how_to_run = plan.get("how_to_run", "See HOW_TO_RUN.md")
        file_manifest = plan.get("files", [])
        tech_str = ", ".join(tech_stack)
        primary_tech = tech_stack[0] if tech_stack else "web"

        print(f"[GHModels] ✅ Plan: {len(file_manifest)} files for '{repo_name}' ({tech_str})")

        # ── Pass 2: Generate each file ────────────────────────────────────────
        generated_files = []

        for i, file_entry in enumerate(file_manifest):
            file_path = file_entry.get("path", f"file_{i}.txt")
            file_desc = file_entry.get("description", f"File {i}")

            print(f"[GHModels] 📝 ({i+1}/{len(file_manifest)}): Generating {file_path}...")

            file_prompt = FILE_PROMPT_TEMPLATE.format(
                tech=primary_tech,
                file_path=file_path,
                file_description=file_desc,
                app_description=f"{repo_name}: {description}",
                tech_stack=tech_str,
                coding_standards=CODING_STANDARDS[:8000] if CODING_STANDARDS else "No standards loaded",
            )

            is_doc = file_path.endswith(".md") or file_path.endswith(".txt")
            max_tok = 2048 if is_doc else 8192

            try:
                content, _ = self._call(
                    prompt=file_prompt,
                    system=f"You are an expert {primary_tech} developer. Output ONLY raw file content with no markdown fences.",
                    json_mode=False,
                    max_tokens=max_tok,
                )
                # Strip any accidental markdown fences
                content = re.sub(r"^```[\w]*\n?", "", content, flags=re.MULTILINE)
                content = re.sub(r"\n?```$", "", content, flags=re.MULTILINE).strip()

                generated_files.append({"path": file_path, "content": content})
                print(f"[GHModels]    ✅ {file_path} ({len(content)} chars)")

            except Exception as e:
                print(f"[GHModels]    ⚠️ Failed to generate {file_path}: {e}")
                generated_files.append({
                    "path": file_path,
                    "content": f"# Error generating this file\n# {e}\n",
                })

        # Token usage stats
        tokens_used = None
        if hasattr(plan_response, "usage") and plan_response.usage:
            tokens_used = plan_response.usage.completion_tokens
            total = plan_response.usage.total_tokens
            print(f"[GHModels] 📊 Plan tokens: {tokens_used} out / {total} total")

        print(f"[GHModels] 🎉 Done! {len(generated_files)} files for '{repo_name}' using `{self.active_model}`")

        return {
            "repo_name": repo_name,
            "description": description,
            "tech_stack": tech_stack,
            "files": generated_files,
            "readme": next((f["content"] for f in generated_files if f["path"] == "README.md"), ""),
            "technical_docs": next((f["content"] for f in generated_files if f["path"] == "TECHNICAL_DOCS.md"), ""),
            "how_to_run": how_to_run,
            "tokens_used": tokens_used,
        }
