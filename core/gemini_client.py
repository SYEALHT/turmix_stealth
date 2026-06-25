"""
gemini_client.py — Two-pass code generation engine.

ARCHITECTURE (v4 — Two-Pass):
  Pass 1 (Plan):     Gemini returns a small JSON manifest listing the files
                     to generate + metadata. Zero code = zero encoding issues.
  Pass 2 (Generate): For each file in the manifest, Gemini generates the
                     content as plain text (no JSON wrapping). Safe for any
                     language, any size, any special characters.
  Result:            Full multi-file apps (Flask, Next.js, Docker, docs, etc.)
                     with zero JSON encoding crashes.
"""

import time
import json
import re
from google import genai
from google.genai import types
from config import config

# ── System Prompts ─────────────────────────────────────────────────────────────

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
1. Support any tech stack the user requests: Flask, FastAPI, Node/Express, pure HTML/JS, etc.
2. Include Dockerfile always for every project.
3. Include README.md, TECHNICAL_DOCS.md, and HOW_TO_RUN.md always.
4. repo_name: lowercase, hyphens only, no spaces.
5. Be realistic about the file list — include all files the app actually needs.
6. Do NOT include any code in this response. Only the manifest.
"""

FILE_PROMPT_TEMPLATE = """You are an expert {tech} developer.

Generate the COMPLETE content for this file: {file_path}
Description: {file_description}

This file is part of: {app_description}
Tech stack: {tech_stack}

Rules:
- Output ONLY the file content. No explanations, no markdown fences, no preamble.
- Make it complete and production-ready. No placeholders, no TODO comments.
- Include proper error handling, comments where helpful, and follow best practices.
- For HTML templates, make them visually stunning: modern design, Google Fonts via CDN, dark/light theme with gradient accents, smooth animations, mobile-responsive.
- For Python/backend files, use proper logging, environment variables for secrets.
- For Dockerfiles, use multi-stage builds and best security practices where appropriate.
"""


# Fallback order when a model hits rate limits / quota.
# GeminiClient walks this list automatically, left to right.
GEMINI_FALLBACK_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-pro-preview-03-25",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemma-3-27b-it",
    "gemma-3-12b-it",
]


class GeminiClient:
    _override_model: str | None = None  # Set by /model Discord command at runtime

    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model_name = "gemini-2.5-flash"

    @property
    def active_model(self) -> str:
        """Return the currently active model — respects runtime override from /model command."""
        return GeminiClient._override_model or self.model_name

    def _next_fallback(self, current_model: str) -> str | None:
        """Return the next model in the fallback chain after current_model, or None if exhausted."""
        try:
            idx = GEMINI_FALLBACK_CHAIN.index(current_model)
            if idx + 1 < len(GEMINI_FALLBACK_CHAIN):
                return GEMINI_FALLBACK_CHAIN[idx + 1]
        except ValueError:
            pass
        return None

    def _call(self, prompt: str, system: str, json_mode: bool = False, max_tokens: int = 8192) -> str:
        """Call Gemini with retry + automatic cross-model fallback on rate limits."""
        cfg_kwargs = dict(
            system_instruction=system,
            temperature=0.4,
            max_output_tokens=max_tokens,
        )
        if json_mode:
            cfg_kwargs["response_mime_type"] = "application/json"

        model = self.active_model
        last_err = None

        while model:
            for attempt in range(3):
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(**cfg_kwargs),
                    )
                    # Persist any model switch globally so next file also uses it
                    if model != (GeminiClient._override_model or self.model_name):
                        GeminiClient._override_model = model
                    return response.text.strip(), response
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_rate_limit = (
                        "quota" in err_str
                        or "resource" in err_str
                        or "429" in err_str
                        or "rate" in err_str
                    )
                    if is_rate_limit:
                        if attempt < 2:
                            wait = 15 * (2 ** attempt)
                            print(f"[Gemini] ⏳ Rate limit on `{model}` (attempt {attempt+1}/3). Waiting {wait}s...")
                            time.sleep(wait)
                        else:
                            # Try next model in chain
                            next_model = self._next_fallback(model)
                            if next_model:
                                print(f"[Gemini] ⚠️  Rate limit exhausted on `{model}` — switching to `{next_model}`")
                                model = next_model
                                break  # break inner loop, continue outer while
                            else:
                                print(f"[Gemini] ❌ All fallback models exhausted.")
                                raise last_err  # type: ignore
                    else:
                        raise
            else:
                # Inner loop finished without raising — means success was returned above
                break

        raise last_err  # type: ignore

    def generate_app(self, user_prompt: str) -> dict:
        """
        Two-pass generation:
          Pass 1: Get a JSON manifest (file list + metadata).
          Pass 2: Generate each file's content as plain text.
        Returns a dict compatible with the AppGenerator pipeline.
        """
        # ── Pass 1: Plan ──────────────────────────────────────────────────────
        print(f"[Gemini] 📋 Pass 1: Planning app structure...")
        plan_text, plan_response = self._call(
            prompt=f"Plan this application: {user_prompt}",
            system=PLAN_PROMPT,
            json_mode=True,
            max_tokens=4096,  # Plan is small
        )

        # Strip fences just in case
        plan_text = re.sub(r"^```(?:json)?\s*", "", plan_text, flags=re.MULTILINE)
        plan_text = re.sub(r"\s*```$", "", plan_text, flags=re.MULTILINE).strip()

        try:
            plan = json.loads(plan_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"❌ Failed to parse plan from Gemini: {e}\nRaw: {plan_text[:500]}")

        if not isinstance(plan, dict) or "files" not in plan:
            raise ValueError(f"❌ Gemini returned an unexpected plan format: {plan_text[:300]}")

        repo_name = plan.get("repo_name", "my-web-app")
        description = plan.get("description", user_prompt[:100])
        tech_stack = plan.get("tech_stack", ["HTML", "CSS", "JavaScript"])
        how_to_run = plan.get("how_to_run", "See HOW_TO_RUN.md")
        file_manifest = plan.get("files", [])

        print(f"[Gemini] ✅ Plan ready: {len(file_manifest)} files for '{repo_name}'")
        print(f"[Gemini]    Tech stack: {', '.join(tech_stack)}")

        # ── Pass 2: Generate each file ────────────────────────────────────────
        tech_str = ", ".join(tech_stack)
        generated_files = []

        # Primary tech for the FILE_PROMPT_TEMPLATE
        primary_tech = tech_stack[0] if tech_stack else "web"

        for i, file_entry in enumerate(file_manifest):
            file_path = file_entry.get("path", f"file_{i}.txt")
            file_desc = file_entry.get("description", f"File {i}")

            print(f"[Gemini] 📝 Generating ({i+1}/{len(file_manifest)}): {file_path}")

            file_prompt = FILE_PROMPT_TEMPLATE.format(
                tech=primary_tech,
                file_path=file_path,
                file_description=file_desc,
                app_description=f"{repo_name}: {description}",
                tech_stack=tech_str,
            )

            # Bigger token budget for source files, smaller for docs
            is_doc = file_path.endswith(".md") or file_path.endswith(".txt")
            max_tok = 4096 if is_doc else 16000

            try:
                content, _ = self._call(
                    prompt=file_prompt,
                    system=f"You are an expert {primary_tech} developer. Output ONLY raw file content, no markdown fences.",
                    json_mode=False,
                    max_tokens=max_tok,
                )
                generated_files.append({"path": file_path, "content": content})
                print(f"[Gemini]    ✅ {file_path} ({len(content)} chars)")
            except Exception as e:
                print(f"[Gemini]    ⚠️ Failed to generate {file_path}: {e}")
                generated_files.append({
                    "path": file_path,
                    "content": f"# Error generating this file\n# {e}\n"
                })

        # ── Inject token count from the plan call ─────────────────────────────
        tokens_used = None
        if hasattr(plan_response, "usage_metadata") and plan_response.usage_metadata:
            tokens_used = plan_response.usage_metadata.candidates_token_count
            print(f"[Gemini] 📊 Plan tokens: {tokens_used}")

        print(f"[Gemini] 🎉 Done! Generated {len(generated_files)} files for '{repo_name}'")

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
