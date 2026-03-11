# 🎯 Turmix Vibe — AI Code Generation Standards

> **This document is injected into all AI prompts to ensure high-quality, working code.**

---

## ⚠️ CRITICAL RULES — DO NOT BREAK

### 1. **Complete, Working Code Only**
- **NO placeholders** like `// TODO: implement this`, `pass`, `...`, or `/* your code here */`
- **NO truncated files** — every file must be complete from start to end
- **NO pseudo-code** — only real, runnable code
- **NO ellipsis** (`...`) to indicate "rest of code" — write ALL the code

### 2. **File Consistency**
- All imports MUST reference files that actually exist in the project
- All function calls MUST reference functions that are actually defined
- All routes/endpoints MUST match between frontend and backend
- Database models MUST match between schema definitions and usage

### 3. **Error Handling**
- Wrap all async operations in try/catch (JS) or try/except (Python)
- Validate ALL user inputs before processing
- Return meaningful error messages, not generic "Error occurred"
- Handle edge cases: empty arrays, null values, network failures

---

## 📁 File Structure Requirements

### Backend (Python/Flask/FastAPI)
```
app.py              # Main entry point, ALL routes defined here
requirements.txt    # ALL dependencies with versions
Dockerfile          # Multi-stage build, non-root user
.env.example        # Document ALL environment variables
```

### Frontend (HTML/CSS/JS)
```
index.html          # Complete with DOCTYPE, head, body
styles.css          # Or inline in <style> if single file
script.js           # Or inline in <script> if single file
```

### Full-Stack
```
backend/
  app.py
  requirements.txt
frontend/
  index.html
  styles.css
docker-compose.yml  # Link frontend and backend
```

---

## 🔧 Language-Specific Standards

### Python
```python
# ✅ CORRECT
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route("/api/items", methods=["GET"])
def get_items():
    try:
        items = db.query(Item).all()
        return jsonify([item.to_dict() for item in items])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
```

```python
# ❌ WRONG — Never do this
def get_items():
    # TODO: implement database query
    pass
```

### JavaScript
```javascript
// ✅ CORRECT
async function fetchItems() {
    try {
        const response = await fetch('/api/items');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('Failed to fetch items:', error);
        showErrorToast('Could not load items. Please try again.');
        return [];
    }
}
```

```javascript
// ❌ WRONG — Never do this
async function fetchItems() {
    const response = await fetch('/api/items');
    return response.json(); // No error handling!
}
```

### HTML/CSS
```html
<!-- ✅ CORRECT -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My App</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; }
        /* Complete styles... */
    </style>
</head>
<body>
    <!-- Complete content... -->
    <script>
        // Complete JavaScript...
    </script>
</body>
</html>
```

---

## 🎨 UI/UX Standards

### Visual Design
- Use **modern, clean design** with proper spacing
- Include **dark/light mode** support where appropriate
- Use **gradient accents** for buttons and highlights
- Ensure **mobile responsiveness** (min-width: 320px)
- Add **smooth animations** (transitions: 0.2s ease)

### Fonts & Colors
```css
/* Recommended Google Fonts */
font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
font-family: 'JetBrains Mono', 'Fira Code', monospace; /* for code */

/* Recommended color palette */
--bg-light: #ffffff;
--bg-dark: #0d1117;
--accent: #3b82f6;
--success: #22c55e;
--error: #ef4444;
```

---

## 🐳 Docker Standards

```dockerfile
# ✅ CORRECT — Multi-stage, secure
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
```

---

## 📝 Documentation Standards

### README.md Must Include:
1. **Project title and description**
2. **Tech stack badges**
3. **Quick start instructions**
4. **Environment variables documentation**
5. **API endpoints (if applicable)**

### HOW_TO_RUN.md Must Include:
1. **Prerequisites** (Python version, Node version, etc.)
2. **Installation steps** (copy-paste ready)
3. **Running locally** (with exact commands)
4. **Running with Docker** (with exact commands)
5. **Common issues and solutions**

---

## 🚫 Forbidden Patterns

| ❌ Never Do This | ✅ Do This Instead |
|-----------------|-------------------|
| `# TODO: ...` | Implement the feature |
| `pass` in functions | Write actual implementation |
| `...` to indicate more code | Write complete code |
| `/* implement later */` | Implement now |
| Hardcoded API keys | Use `os.getenv("KEY")` |
| `print()` for logging | Use `logging` module |
| Catching all exceptions silently | Log and re-raise or handle properly |

---

## ✅ Quality Checklist

Before outputting any file, verify:

- [ ] File is complete (no truncation, no placeholders)
- [ ] All imports reference existing modules/files
- [ ] All function calls reference defined functions
- [ ] Error handling is comprehensive
- [ ] Code follows language best practices
- [ ] UI is responsive and visually polished
- [ ] Docker config is secure and optimized
- [ ] Documentation is actionable (copy-paste ready)
