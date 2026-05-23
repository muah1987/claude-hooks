---
description: Universal AI inference router — run a prompt through Claude, Ollama cloud, or any available model
argument-hint: "<prompt> [--model <name>] [--task coding|thinking|general|fast]"
allowed-tools: Bash, Read, WebSearch
---

# /inference — Universal AI Inference Router

Route any inference task to the best available model. Uses a quality-first cascade for images (Recraft V3 → FLUX 1.1 Pro → FLUX.1-dev), top video models (Kling 3.0 Pro / MiniMax Hailuo-02), and Ollama cloud models for text/code/vision/reasoning.

## Variables

ARGS: the full user request, e.g. "generate image of a mosque at sunset" or "create a video of waves" or "explain this code: ..." or just a bare prompt

---

## Step 1 — Detect Task Type

| Trigger keywords | Type | Model |
|-----------------|------|-------|
| generate image / draw / create image / paint / render / visualize / illustrate / design | **image** | Recraft V3 → FLUX 1.1 Pro → FLUX.1-dev (cascade) |
| generate video / create video / animate / make a clip / text to video / video of | **video** | Kling 3.0 Pro → MiniMax Hailuo-02 (cascade) |
| look at / describe image / what is in / analyze image / screenshot at / read image / OCR | **vision** | qwen3-vl:235b-cloud (Ollama) |
| fix bug / write code / refactor / implement / function / class / unit test | **code** | qwen3-coder:480b-cloud (Ollama) |
| think through / reason / step by step / complex analysis / plan / architecture | **reasoning** | kimi-k2-thinking:cloud (Ollama) |
| translate / Arabic / Dutch / French / multilingual | **text** | glm-5:cloud (Ollama — multilingual) |
| anything else | **text** | deepseek-v3.2:cloud (Ollama) |

If ambiguous, ask the user one short clarifying question.

---

## Step 2 — Execute Inference

### IMAGE GENERATION — Python SDK Cascade (huggingface_hub InferenceClient)

**Quality ranking (HuggingFace leaderboard 2025-2026):**
- 🥇 **Recraft V3** — ELO 1172, #1 overall, best for design / illustration / logos / SVG / brand
- 🥈 **FLUX 1.1 Pro** — ELO 1143, best photorealism and general purpose
- 🥉 **FLUX.1-dev** — ELO ~1080, great quality, open weights fallback

Use the `huggingface_hub` Python SDK — returns PIL image directly, no URL parsing needed.
Try in cascade order — first success wins.

```bash
PROMPT="<the image prompt from ARGS>"
OUTFILE="/tmp/inference_$(date +%s).png"

uv run --with huggingface_hub --with Pillow python3 - << PYEOF
import os, sys
from huggingface_hub import InferenceClient

client = InferenceClient(api_key=os.environ["HF_TOKEN"])
prompt = """$PROMPT"""
outfile = "$OUTFILE"
saved = False

# ── Tier 1: Recraft V3 (best quality, #1 leaderboard) ──
print("🎨 Trying Recraft V3...")
try:
    image = client.text_to_image(prompt, model="recraft-ai/recraft-v3", provider="fal-ai")
    image.save(outfile)
    print(f"✅ Recraft V3 → {outfile}")
    saved = True
except Exception as e:
    print(f"  Recraft V3 failed: {e}")

# ── Tier 2: FLUX 1.1 Pro (ELO 1143, best photorealism) ──
if not saved:
    print("⚡ Trying FLUX 1.1 Pro...")
    try:
        image = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-pro", provider="fal-ai")
        image.save(outfile)
        print(f"✅ FLUX 1.1 Pro → {outfile}")
        saved = True
    except Exception as e:
        print(f"  FLUX 1.1 Pro failed: {e}")

# ── Tier 3: FLUX.1-dev (open weights, fast, high quality) ──
if not saved:
    print("🔄 Trying FLUX.1-dev...")
    try:
        image = client.text_to_image(
            prompt,
            model="black-forest-labs/FLUX.1-dev:fastest",
            provider="auto",
        )
        image.save(outfile)
        print(f"✅ FLUX.1-dev → {outfile}")
        saved = True
    except Exception as e:
        print(f"  FLUX.1-dev failed: {e}")

if not saved:
    print("❌ All image models failed.")
    sys.exit(1)
PYEOF
```

After running, display the image with the Read tool so the user can see it: `Read(file_path="$OUTFILE")`

**Model + provider guide:**
| Model | provider arg | Best for |
|-------|-------------|----------|
| `recraft-ai/recraft-v3` | `fal-ai` | Design, illustration, logos, brand |
| `black-forest-labs/FLUX.1-pro` | `fal-ai` | Photorealism, portraits, landscapes |
| `black-forest-labs/FLUX.1-dev:fastest` | `auto` | Fast iteration, open weights |
| `stabilityai/stable-diffusion-3.5-large` | `auto` | Alternative photorealism |

**Style note for Recraft V3**: pass `parameters={"style": "realistic_image"}` to `text_to_image()` for photorealism, or `"digital_illustration"` for art.

---

### VIDEO GENERATION — Quality Cascade

**Quality ranking 2025-2026:**
- 🥇 **Kling 3.0 Pro** — cinematic visuals, native audio gen, best motion quality
- 🥈 **MiniMax Hailuo-02** — excellent text-to-video, 768p

```bash
PROMPT="<the video prompt from ARGS>"
OUTFILE="/tmp/inference_video_$(date +%s).mp4"
VIDEO_URL=""

# ── Tier 1: Kling 3.0 Pro (best cinematic quality) ──
echo "🎬 Trying Kling 3.0 Pro (best video quality)..."
RESPONSE=$(curl -s -X POST \
  "https://router.huggingface.co/fal-ai/fal-ai/kling-video/v2.1/pro/text-to-video" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"$PROMPT\",
    \"duration\": \"5\",
    \"aspect_ratio\": \"16:9\"
  }")

VIDEO_URL=$(echo "$RESPONSE" | python3 -c "
import json,sys
d = json.load(sys.stdin)
vid = d.get('video', {})
print(vid.get('url','') if vid else d.get('url',''))
" 2>/dev/null)

# ── Tier 2: MiniMax Hailuo-02 ──
if [[ ! "$VIDEO_URL" == http* ]]; then
  echo "🔄 Falling back to MiniMax Hailuo-02..."
  RESPONSE=$(curl -s -X POST \
    "https://router.huggingface.co/fal-ai/fal-ai/minimax/video-01" \
    -H "Authorization: Bearer $HF_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"prompt\": \"$PROMPT\",
      \"duration\": 6
    }")
  VIDEO_URL=$(echo "$RESPONSE" | python3 -c "
import json,sys
d = json.load(sys.stdin)
vid = d.get('video', {})
print(vid.get('url','') if vid else d.get('url',''))
" 2>/dev/null)
fi

# ── Save result ──
if [[ "$VIDEO_URL" == http* ]]; then
  curl -s "$VIDEO_URL" -o "$OUTFILE"
  echo "✅ Video saved to $OUTFILE"
  echo "🔗 URL: $VIDEO_URL"
else
  echo "❌ All video models failed. Last response: $RESPONSE"
fi
```

> **Note:** Video generation takes 30–120 seconds. If the API returns a request ID instead of a URL, poll the status endpoint: `https://router.huggingface.co/fal-ai/fal-ai/kling-video/v2.1/pro/text-to-video/requests/{request_id}` until `status == "COMPLETED"`.

---

### TEXT GENERATION (via HF Router — novita provider, OpenAI-compatible)

```bash
PROMPT="<the user prompt>"
RESPONSE=$(curl -s -X POST \
  "https://router.huggingface.co/novita/v3/openai/chat/completions" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"meta-llama/llama-3.3-70b-instruct\",
    \"messages\": [{\"role\": \"user\", \"content\": \"$PROMPT\"}],
    \"max_tokens\": 2048,
    \"temperature\": 0.7
  }")

echo "$RESPONSE" | python3 -c "
import json,sys
d = json.load(sys.stdin)
choices = d.get('choices',[])
if choices:
    print(choices[0]['message']['content'])
else:
    print(json.dumps(d, indent=2))
"
```

---

### VISION / IMAGE UNDERSTANDING (Ollama — qwen3-vl:235b-cloud)

```bash
IMAGE_PATH="<extracted from ARGS>"
QUESTION="<the question about the image>"
BASE64=$(base64 -w 0 "$IMAGE_PATH" 2>/dev/null)
curl -s http://localhost:11434/api/chat -d "{
  \"model\": \"qwen3-vl:235b-cloud\",
  \"messages\": [{
    \"role\": \"user\",
    \"content\": \"$QUESTION\",
    \"images\": [\"$BASE64\"]
  }]
}" | python3 -c "import json,sys; [print(json.loads(l).get('message',{}).get('content',''), end='') for l in sys.stdin if l.strip()]"
```

---

### CODE GENERATION / REVIEW (Ollama — qwen3-coder:480b-cloud)

```bash
PROMPT="<the code task>"
curl -s http://localhost:11434/api/chat -d "{
  \"model\": \"qwen3-coder:480b-cloud\",
  \"messages\": [{\"role\": \"user\", \"content\": $(echo "\"$PROMPT\"")}],
  \"stream\": false
}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',{}).get('content',''))"
```

---

### REASONING / CHAIN-OF-THOUGHT (Ollama — kimi-k2-thinking:cloud)

```bash
curl -s http://localhost:11434/api/chat -d "{
  \"model\": \"kimi-k2-thinking:cloud\",
  \"messages\": [{\"role\": \"user\", \"content\": \"$PROMPT\"}],
  \"stream\": false
}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',{}).get('content',''))"
```

---

### HF ROUTER — PROVIDER REFERENCE

| Provider | URL prefix | Best for |
|----------|-----------|----------|
| fal-ai | `https://router.huggingface.co/fal-ai/` | Image & video gen (Recraft, FLUX, Kling) |
| novita | `https://router.huggingface.co/novita/v3/openai/` | Chat (OpenAI-compat, 70B+ models) |
| together-ai | `https://router.huggingface.co/together/v1/` | Large LLMs (70B+) |
| sambanova | `https://router.huggingface.co/sambanova/v1/` | Ultra-fast inference |
| fireworks-ai | `https://router.huggingface.co/fireworks-ai/inference/v1/` | Multi-modal |

---

## Step 3 — Output

- **Images**: Save to `/tmp/inference_<timestamp>.png`. Display with Read tool so user can see it. Print path + URL.
- **Videos**: Save to `/tmp/inference_video_<timestamp>.mp4`. Print path + URL. Mention duration.
- **Text**: Print directly. Offer to save for long outputs.
- **Code**: Print in fenced code block. Offer to write to file.

## Token

HF_TOKEN is available as `$HF_TOKEN` in all Bash calls (set in `~/.claude/settings.json` under `env`). Never hardcode or commit it.
