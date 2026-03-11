"""
bot.py — Discord bot interface for AppBuilder.

Usage:
  In your Discord server, use the slash command:
    /build description: make me a todo app with React and Node.js

The bot will:
  1. Call Gemini to generate the full-stack app
  2. Push it to a private GitHub repo
  3. Reply with the repo URL + how-to-run instructions

SETUP:
  1. Go to https://discord.com/developers/applications
  2. Select your app → Bot → Copy Token
  3. Paste token into .env as DISCORD_BOT_TOKEN=...
  4. Invite bot with scopes: bot + applications.commands
     Permissions: Send Messages, Use Slash Commands, Embed Links
"""

import sys
import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

# Fix path so imports work when running from discord_bot/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from core.pipeline import run_pipeline


# ── Bot setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True  # CRITICAL: Required for !sync command to work
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


@bot.event
async def on_ready():
    print(f"[Discord] ✅ Logged in as {bot.user} (ID: {bot.user.id})", flush=True)
    print("[Discord] ⚙️ Syncing slash commands (global)...", flush=True)
    try:
        synced = await tree.sync()
        print(f"[Discord] 🚀 Synced {len(synced)} slash commands globally.", flush=True)
    except Exception as e:
        print(f"[Discord] ❌ Sync failed: {e}", flush=True)
    print("[Discord] Bot is ready! If commands don't show up, try typing !sync in your server.", flush=True)


@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Admin command to force a sync to the current server (much faster than global)."""
    print(f"[Discord] ⚙️ Manual sync triggered by {ctx.author}", flush=True)
    await ctx.send("⚙️ Syncing commands to this server...")
    try:
        # Sync to the current guild for instant results
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ Synced {len(synced)} commands to this server! Try /build now.")
        print(f"[Discord] ✅ Guild sync complete.", flush=True)
    except Exception as e:
        print(f"[Discord] ❌ Manual sync failed: {e}", flush=True)
        await ctx.send(f"❌ Sync failed: {e}")


# ── /build command ────────────────────────────────────────────────────────────

@tree.command(
    name="build",
    description="Describe an app in plain English and I'll build + push it to GitHub!"
)
@app_commands.describe(description="Plain-English description of the app you want built")
async def build_command(interaction: discord.Interaction, description: str):
    """
    Main slash command: /build description:<NLP prompt>
    """
    # Acknowledge immediately (generation takes time)
    await interaction.response.defer(thinking=True)
    
    # Build a nice "working on it" embed
    working_embed = discord.Embed(
        title="🔨 Turmux Vibe — Building your app...",
        description=(
            f"**Prompt:** {description[:300]}\n\n"
            f"⏳ **Step 1/2:** Planning your app architecture with `{_active_model}`...\n"
            "Then generating each file one by one.\n\n"
            "⏱️ This takes **2–3 minutes** for complex apps. Hang tight!"
        ),
        color=0x4285F4,
    )
    working_embed.set_footer(text=f"Powered by {_active_model} + GitHub")
    
    await interaction.followup.send(embed=working_embed)

    # Run the pipeline in a thread (blocking call)
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, run_pipeline, description
        )

        # Success embed
        tech = ", ".join(result.get("tech_stack", []) or ["Auto-detected"])
        how_to_run = result.get("how_to_run", "See HOW_TO_RUN.md in the repo.")
        # Trim how_to_run to fit Discord's 4096-char description limit
        if len(how_to_run) > 1000:
            how_to_run = how_to_run[:997] + "..."

        live_url = result.get("live_url")
        embed_title = "✅ App Generated, Deployed & Live! 🌐" if live_url else "✅ App Generated & Pushed to GitHub!"
        success_embed = discord.Embed(
            title=embed_title,
            color=0x00C851,
        )
        success_embed.add_field(
            name="📦 Repository",
            value=f"[{result['repo_name']}]({result['repo_url']}) *(private)*",
            inline=False,
        )
        if live_url:
            success_embed.add_field(
                name="🌐 Live URL",
                value=f"[{live_url}]({live_url})",
                inline=False,
            )
        success_embed.add_field(
            name="📝 Description",
            value=result.get("description", description[:200]),
            inline=False,
        )
        success_embed.add_field(
            name="🛠 Tech Stack",
            value=tech,
            inline=False,
        )
        success_embed.add_field(
            name="📁 Files Generated",
            value=f"{result['file_count']} files",
            inline=True,
        )
        
        tokens_used = result.get("tokens_used")
        if tokens_used:
            success_embed.add_field(
                name="📊 Tokens Used",
                value=f"{tokens_used:,} / 65,536",
                inline=True,
            )
            
        success_embed.add_field(
            name="🔒 Visibility",
            value="Private",
            inline=True,
        )
        success_embed.add_field(
            name="▶️ How to Run",
            value=f"```\n{how_to_run}\n```",
            inline=False,
        )
        success_embed.set_footer(text="🤖 Turmux Vibe | Gemini + GitHub")

        await interaction.followup.send(embed=success_embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Build Failed",
            description=f"```\n{str(e)[:1500]}\n```",
            color=0xFF4444,
        )
        error_embed.set_footer(text="Check your .env keys and try again")
        await interaction.followup.send(embed=error_embed)
        raise


# ── /status command ───────────────────────────────────────────────────────────

@tree.command(name="status", description="Check if the Turmux Vibe bot is online and all keys are configured")
async def status_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🟢 Turmux Vibe — Status", color=0x00C851)
    
    # GitHub token powers both repo creation AND GitHub Models AI
    gh_models_status = "✅ Set (powers GitHub Models AI!)" if config.GITHUB_TOKEN else "❌ Missing"
    embed.add_field(name="🐙 GitHub Token", value=gh_models_status, inline=False)
    embed.add_field(name="👤 GitHub User", value=f"`{config.GITHUB_USERNAME}`" if config.GITHUB_USERNAME else "❌ Not set", inline=True)
    embed.add_field(name="🤖 Gemini API Key", value="✅ Set" if config.GEMINI_API_KEY else "⚠️ Not set (Gemini models unavailable)", inline=True)
    embed.add_field(name="🚀 Vercel Token", value="✅ Set" if config.VERCEL_TOKEN else "⚠️ Not set (auto-deploy disabled)", inline=False)
    embed.add_field(name="🧠 Active Model", value=f"`{_active_model}`", inline=True)
    
    # Determine backend
    if _active_model in GEMINI_MODELS:
        backend = "Gemini"
    elif _active_model in GROQ_MODELS:
        backend = "Groq"
    else:
        backend = "GitHub Models (Student Pack)"
    embed.add_field(name="⚡ AI Backend", value=backend, inline=True)
    embed.set_footer(text="Use /build to generate your app! | /model to switch AI model")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /cmd command ──────────────────────────────────────────────────────────────

@tree.command(name="cmd", description="Show all available bot commands")
async def cmd_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Turmux Vibe — Available Commands",
        description="Here are all the commands you can use:",
        color=0x4285F4,
    )
    
    embed.add_field(
        name="🔨 /build",
        value="Generate a full app from plain English\n`/build description: make me a todo app with Flask`",
        inline=False,
    )
    embed.add_field(
        name="🔧 /update",
        value="Update an existing GitHub repo with AI\n`/update repo: my-app changes: add dark mode`",
        inline=False,
    )
    embed.add_field(
        name="🧠 /model",
        value="Switch between AI models (GPT-4o, Gemini, Llama, etc.)",
        inline=False,
    )
    embed.add_field(
        name="🟢 /status",
        value="Check bot status and configured API keys",
        inline=True,
    )
    embed.add_field(
        name="🔑 /keys",
        value="Live-validate all your API keys",
        inline=True,
    )
    embed.add_field(
        name="📊 /apiinfo",
        value="Check API details, quotas, and rate limits",
        inline=True,
    )
    embed.add_field(
        name="📋 /cmd",
        value="Show this help message",
        inline=True,
    )
    
    embed.set_footer(text="Turmux Vibe | AI-powered app generation")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Shared model state ────────────────────────────────────────────────────────
# Models the user can choose from. Stored as a module-level variable so /build picks it up.

# ── GitHub Models (via GitHub Student Pack — uses GITHUB_TOKEN, no extra key needed!) ──
GITHUB_MODELS = {
    "gpt-4o-mini":                      "⭐ GPT-4o Mini — Fast, smart, DEFAULT (GitHub Models)",
    "gpt-4o":                           "GPT-4o — OpenAI's best, most capable (GitHub Models)",
    "meta/llama-3.1-405b-instruct":     "Llama 3.1 405B — Meta's monster model (GitHub Models)",
    "meta/llama-3.3-70b-instruct":      "Llama 3.3 70B — Fast & very capable (GitHub Models)",
    "anthropic/claude-3.5-sonnet":      "Claude 3.5 Sonnet — Anthropic's best (GitHub Models)",
    "mistral-ai/mistral-large":         "Mistral Large — Great for complex reasoning (GitHub Models)",
    "microsoft/phi-4":                  "Phi-4 — Microsoft's compact powerhouse (GitHub Models)",
}

# Groq models
GROQ_MODELS = {
    "llama-3.3-70b-versatile": "LLaMA 3.3 70B via Groq — Fast inference",
    "llama-3.1-8b-instant":    "LLaMA 3.1 8B Instant via Groq — Fastest, simple apps",
    "mixtral-8x7b-32768":      "Mixtral 8x7B via Groq — Huge 32k context",
    "gemma2-9b-it":            "Gemma 2 9B via Groq — Google's model, balanced",
}

# Gemini models
GEMINI_MODELS = {
    "gemini-2.5-flash":              "Gemini 2.5 Flash — Google's latest, best reasoning",
    "gemini-2.5-pro-preview-03-25": "Gemini 2.5 Pro — Most capable, complex apps",
    "gemini-2.0-flash":              "Gemini 2.0 Flash — Fast & capable, great balance",
    "gemini-2.0-flash-lite":         "Gemini 2.0 Flash Lite — Lightweight & fastest Google model",
    "gemini-1.5-pro":                "Gemini 1.5 Pro — Long context (1M tokens)",
    "gemini-1.5-flash":              "Gemini 1.5 Flash — Efficient Google model",
    "gemma-3-27b-it":                "Gemma 3 27B — Google's open model, best Gemma quality",
    "gemma-3-12b-it":                "Gemma 3 12B — Google's open model, fast & balanced",
}

AVAILABLE_MODELS = {**GITHUB_MODELS, **GEMINI_MODELS, **GROQ_MODELS}
_active_model: str = "gpt-4o-mini"  # Default: GitHub Models GPT-4o-mini


# ── /model command ─────────────────────────────────────────────────────────────

class ModelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=model_id,
                description=desc[:100],
                default=(model_id == _active_model)
            )
            for model_id, desc in AVAILABLE_MODELS.items()
        ]
        super().__init__(placeholder="Choose a Gemini model...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        global _active_model
        _active_model = self.values[0]

        from core.gemini_client import GeminiClient
        from core.groq_client import GroqClient
        from core.github_models_client import GitHubModelsClient

        if _active_model in GEMINI_MODELS:
            GeminiClient._override_model = _active_model
            GroqClient._override_model = None
            GitHubModelsClient._override_model = None
            backend = "Gemini"
        elif _active_model in GROQ_MODELS:
            GroqClient._override_model = _active_model
            GeminiClient._override_model = None
            GitHubModelsClient._override_model = None
            backend = "Groq"
        else:
            # GitHub Models (GPT-4o, Claude, Llama, etc.)
            GitHubModelsClient._override_model = _active_model
            GeminiClient._override_model = None
            GroqClient._override_model = None
            backend = "GitHub Models (Student Pack)"

        await interaction.response.send_message(
            f"✅ Active model switched to `{_active_model}`\n**Backend:** {backend}\nAll future `/build` commands will use this model.",
            ephemeral=True
        )


class ModelView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(ModelSelect())


@tree.command(name="model", description="Switch the Gemini AI model used for code generation")
async def model_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🧠 Select Gemini Model",
        description=f"Currently active: `{_active_model}`\nPick a model below to use for all future `/build` commands.",
        color=0x4285F4,
    )
    for model_id, desc in AVAILABLE_MODELS.items():
        embed.add_field(name=model_id, value=desc, inline=False)
    await interaction.response.send_message(embed=embed, view=ModelView(), ephemeral=True)


# ── /apiinfo command ───────────────────────────────────────────────────────────

@tree.command(name="apiinfo", description="Check Gemini API details, active model, and rate limit info")
async def apiinfo_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)

    import requests as req

    embed = discord.Embed(title="📊 API Info & Quota", color=0x4285F4)
    embed.add_field(name="🧠 Active Model", value=f"`{_active_model}`", inline=False)

    # Check Groq API
    try:
        import requests as req
        r = req.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            timeout=10,
        )
        if r.status_code == 200:
            models_data = r.json().get("data", [])
            model_names = [m["id"] for m in models_data if "llama" in m["id"] or "mistral" in m["id"] or "mixtral" in m["id"] or "gemma" in m["id"]]
            embed.add_field(
                name="✅ Groq API",
                value=f"Connected • {len(models_data)} models available",
                inline=True,
            )
            embed.add_field(
                name="🔥 Available Models",
                value="\n".join(f"• `{m}`" for m in model_names[:8]) or "None found",
                inline=False,
            )
        else:
            embed.add_field(name="❌ Groq API", value=f"Error {r.status_code}: {r.text[:100]}", inline=True)
    except Exception as e:
        embed.add_field(name="❌ Groq API", value=f"Connection failed: {e}", inline=True)

    # Check Vercel account info
    if config.VERCEL_TOKEN:
        try:
            rv = req.get(
                "https://api.vercel.com/v2/user",
                headers={"Authorization": f"Bearer {config.VERCEL_TOKEN}"},
                timeout=10,
            )
            if rv.status_code == 200:
                user_data = rv.json().get("user", {})
                username = user_data.get("username") or user_data.get("email", "Unknown")
                embed.add_field(name="🚀 Vercel", value=f"✅ Connected as `{username}`", inline=True)
            else:
                embed.add_field(name="🚀 Vercel", value=f"❌ Error {rv.status_code}", inline=True)
        except Exception as e:
            embed.add_field(name="🚀 Vercel", value=f"❌ {e}", inline=True)
    else:
        embed.add_field(name="🚀 Vercel", value="⚠️ Token not set", inline=True)

    embed.add_field(
        name="📋 Groq Rate Limits (Free Tier)",
        value=(
            "• **llama-3.3-70b-versatile**: 30 RPM / 14,400 RPD / 131k tokens/min\n"
            "• **llama-3.1-8b-instant**: 30 RPM / 14,400 RPD / 131k tokens/min\n"
            "• **mixtral-8x7b-32768**: 30 RPM / 14,400 RPD / 5k tokens/min\n"
            "• **gemma2-9b-it**: 30 RPM / 14,400 RPD / 15k tokens/min\n"
            "• RPM = Requests/min, RPD = Requests/day"
        ),
        inline=False,
    )
    embed.set_footer(text="Use /model to switch models | /keys to validate all keys")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── /keys command ──────────────────────────────────────────────────────────────

@tree.command(name="keys", description="Live-validate all your API keys (Gemini, GitHub, Vercel)")
async def keys_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)

    import requests as req

    embed = discord.Embed(title="🔑 API Keys — Live Check", color=0x4285F4)

    # ── Check Groq ──
    try:
        rg2 = req.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            timeout=10,
        )
        if rg2.status_code == 200:
            count = len(rg2.json().get("data", []))
            embed.add_field(name="⚡ Groq API", value=f"✅ Valid — {count} models accessible", inline=False)
        else:
            embed.add_field(name="⚡ Groq API", value=f"❌ Invalid ({rg2.status_code})", inline=False)
    except Exception as e:
        embed.add_field(name="⚡ Groq API", value=f"❌ Error: {e}", inline=False)

    # ── Check GitHub ──
    try:
        rg = req.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {config.GITHUB_TOKEN}"},
            timeout=10,
        )
        if rg.status_code == 200:
            gh_user = rg.json()
            scopes = rg.headers.get("X-OAuth-Scopes", "unknown")
            embed.add_field(
                name="🐙 GitHub Token",
                value=f"✅ Valid — Logged in as `{gh_user['login']}`\nScopes: `{scopes}`",
                inline=False,
            )
        else:
            embed.add_field(name="🐙 GitHub Token", value=f"❌ Invalid ({rg.status_code})", inline=False)
    except Exception as e:
        embed.add_field(name="🐙 GitHub Token", value=f"❌ Error: {e}", inline=False)

    # ── Check Vercel ──
    if config.VERCEL_TOKEN:
        try:
            rv = req.get(
                "https://api.vercel.com/v2/user",
                headers={"Authorization": f"Bearer {config.VERCEL_TOKEN}"},
                timeout=10,
            )
            if rv.status_code == 200:
                user_data = rv.json().get("user", {})
                username = user_data.get("username") or user_data.get("email", "Connected")
                embed.add_field(name="🚀 Vercel Token", value=f"✅ Valid — Account: `{username}`", inline=False)
            else:
                embed.add_field(name="🚀 Vercel Token", value=f"❌ Invalid ({rv.status_code}): {rv.text[:100]}", inline=False)
        except Exception as e:
            embed.add_field(name="🚀 Vercel Token", value=f"❌ Error: {e}", inline=False)
    else:
        embed.add_field(name="🚀 Vercel Token", value="⚠️ Not set in .env — auto-deploy disabled", inline=False)

    embed.set_footer(text="All checks done! | Use /apiinfo for rate limit details")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── /update command ────────────────────────────────────────────────────────────

@tree.command(
    name="update",
    description="Update an existing repo with AI — paste a GitHub URL or just the repo name"
)
@app_commands.describe(
    repo="GitHub URL (https://github.com/you/repo) OR just the repo name (e.g. 'todo-app')",
    changes="Plain-English description of the changes you want (e.g. 'add dark mode to the frontend')"
)
async def update_command(interaction: discord.Interaction, repo: str, changes: str):
    """Update an existing GitHub repo via AI."""
    await interaction.response.defer(thinking=True)

    working_embed = discord.Embed(
        title="🔧 Turmux Vibe — Updating your repo...",
        description=(
            f"**Repo:** `{repo}`\n"
            f"**Changes:** {changes[:300]}\n\n"
            "⏳ **Step 1/3:** Fetching your repo files...\n"
            "⏳ **Step 2/3:** AI is planning which files to change...\n"
            "⏳ **Step 3/3:** Generating & pushing updated files...\n\n"
            "⏱️ This takes **1–2 minutes** depending on how many files change."
        ),
        color=0xF4A800,
    )
    working_embed.set_footer(text=f"Updating {repo}... Hang tight!")
    await interaction.followup.send(embed=working_embed)

    try:
        from core.repo_updater import RepoUpdater
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: RepoUpdater().run(repo, changes)
        )

        # Build the changed files list
        modified = [f["path"] for f in result["files_changed"] if f["action"] == "modify"]
        created  = [f["path"] for f in result["files_changed"] if f["action"] == "create"]
        deleted  = result.get("files_deleted", [])

        changes_text = ""
        if modified:
            changes_text += "**✏️ Modified:**\n" + "\n".join(f"• `{p}`" for p in modified) + "\n"
        if created:
            changes_text += "**➕ Created:**\n" + "\n".join(f"• `{p}`" for p in created) + "\n"
        if deleted:
            changes_text += "**🗑️ Deleted:**\n" + "\n".join(f"• `{p}`" for p in deleted) + "\n"

        if not changes_text:
            changes_text = "No files were changed (AI determined no updates needed)."

        success_embed = discord.Embed(
            title="✅ Repo Updated!",
            color=0x00C851,
        )
        success_embed.add_field(
            name="📦 Repository",
            value=f"[{repo}]({result['repo_url']}) *(private)*",
            inline=False,
        )
        success_embed.add_field(
            name="📝 Changes Made",
            value=result["summary"],
            inline=False,
        )
        success_embed.add_field(
            name="📁 Files",
            value=changes_text[:1024] or "None",
            inline=False,
        )
        success_embed.set_footer(text="🤖 Turmux Vibe | Use /update again to keep improving!")

        await interaction.followup.send(embed=success_embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Update Failed",
            description=f"```\n{str(e)[:1500]}\n```",
            color=0xFF4444,
        )
        error_embed.set_footer(text="Make sure the repo name is correct and try again")
        await interaction.followup.send(embed=error_embed)
        raise


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    token = config.DISCORD_BOT_TOKEN
    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("\n❌ ERROR: DISCORD_BOT_TOKEN is not set in .env!", flush=True)
        print("   Go to: https://discord.com/developers/applications", flush=True)
        print("   → Your App → Bot → Reset Token → Copy it", flush=True)
        print("   → Paste it in appbuilder/.env as DISCORD_BOT_TOKEN=...", flush=True)
        sys.exit(1)
    
    print("[Discord] Starting Turmux Vibe bot...", flush=True)
    bot.run(token)
