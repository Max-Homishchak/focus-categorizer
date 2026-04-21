# Telegram Community Categorizer

Automatically profiles Telegram community members — extracts their messages, categorizes them with an LLM, and serves an interactive web report with semantic search.

---

## How it works

```
Telegram group/topic
        │
        ▼
  Extract messages          ← Telethon, authenticated via QR code in browser
        │
        ▼
  LLM categorization        ← Parallel batches, resumable, prompt-hash aware
        │
        ▼
  Build search index        ← OpenAI embeddings (text-embedding-3-small)
        │
        ▼
  Web report + search       ← FastAPI server, filterable cards, semantic chat
```

Everything happens in the browser — the only command you ever run is the one that starts the server.

---

## Prerequisites

Before you start, make sure you have:

- **Python 3.10+** — check with `python3 --version`
- **Telegram API credentials** — get them at [my.telegram.org/apps](https://my.telegram.org/apps) (free, takes 2 minutes)
- **OpenAI API key** — get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- **Telegram account** — must be a member of the group you want to analyze

---

## Step 1 — Clone the repository

```bash
git clone <repo-url>
cd telegram-categorizer
```

---

## Step 2 — Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

---

## Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

---

## Step 4 — Get Telegram API credentials

1. Go to [my.telegram.org/apps](https://my.telegram.org/apps) and log in with your phone number
2. Click **"Create application"**, fill in any app name (e.g. `categorizer`)
3. Copy the **App api_id** (a number) and **App api_hash** (a hex string)

You will enter these in the setup wizard — no need to create any files manually.

---

## Step 5 — Start the server

```bash
python -m app
```

The server starts on `http://127.0.0.1:8787`. Open it in your browser.

On the first visit the report page will be empty — no data yet.

<img width="987" height="540" alt="image" src="https://github.com/user-attachments/assets/a703f665-ba08-42da-8745-7cf94c576be0" />

---

## Step 6 — Complete the setup wizard

On the first visit, you should go the **Setup** page.

### Telegram credentials

Fill in your API ID, API hash, phone number and the channel/group to analyze.

<img width="594" height="469" alt="image" src="https://github.com/user-attachments/assets/a8423c88-df91-499f-82ca-49792b6bb4ae" />


### OpenAI credentials

Enter your API key and choose models for categorization and reranking.

<img width="602" height="391" alt="image" src="https://github.com/user-attachments/assets/e949914e-330e-4d8c-80e7-3a9e39f42c8f" />


### Advanced settings (optional)

Expand **Show advanced options** to tune extraction limits, batch sizes, parallel workers and search thresholds.

<img width="632" height="754" alt="image" src="https://github.com/user-attachments/assets/1c1689e4-9224-4a7e-855b-01aaa2cf898f" />


Click **Save Settings**. You will be redirected to the main report page.

> 💡 Secrets (API hash, API key) are ONLY stored locally in `data/settings.json`, which is gitignored. They are never sent/saved anywhere except the respective Telegram/OpenAI APIs.

---

## Step 7 — Run categorization

Click the **Run categorization** button in the top-right corner of the report page.

A confirmation dialog will appear — click **Run**.

<img width="1284" height="689" alt="image" src="https://github.com/user-attachments/assets/1b783ed8-3f25-45c5-b300-00cf36ad06aa" />


### First run: Telegram authentication

Because this is the first run, the app needs to authenticate with Telegram.

**Scan the QR code** — open Telegram on your phone → Settings → Devices → Link Desktop Device → scan the code.

<img width="429" height="384" alt="image" src="https://github.com/user-attachments/assets/70506ad2-ce98-46d0-9ad1-3a453260222f" />


**If you have 2FA enabled** — the modal switches to a password field automatically.

<img width="371" height="217" alt="image" src="https://github.com/user-attachments/assets/19908754-7db1-4f7d-b374-cda0b2c1fe2c" />


The session is saved to `tg_session.session`. Subsequent runs skip authentication entirely.

### What happens during a run

```
1. Extract messages from Telegram  (progress bar: pulsing)
2. Categorize users in parallel batches  (progress bar: X / total)
3. Build semantic search index  (progress bar: pulsing)
4. Write static exports  (report.html, .csv, .json)
```

The header shows a live progress bar and phase label. You can also watch the terminal for detailed batch-by-batch logs.

<img width="945" height="196" alt="image" src="https://github.com/user-attachments/assets/217f4234-7a72-4fb8-b711-0bc074858943" />


The page reloads automatically when the run completes.

> 💡 If the run is interrupted, just click **Run** again — it resumes from where it stopped. Only users with new messages or no categorization are re-processed.

---

## Step 8 — Explore the report

Once the run finishes, the report shows the full categorized community.

<img width="983" height="539" alt="image" src="https://github.com/user-attachments/assets/ea3a4e28-ba40-4fc7-a50b-a4806bcc391d" />

The report includes:

- **Stats bar** — total users, messages, categories, worth-checking count
- **Category distribution** chart
- **Filterable user cards** with expandable profiles (summary, tags, metadata, messages)
- **Filters**: text search, category, tag, Worth Checking toggle

---

## Step 9 — Use semantic search

Click the **🔍** button in the bottom-right corner to open the search panel.

Type a natural-language query, for example:

- `Agentic AI engineers with production experience`
- `Traders with verified income`
- `Python developers in Kyiv`

The report filters to matching users instantly.

<img width="980" height="542" alt="image" src="https://github.com/user-attachments/assets/533085fc-cc46-418d-b8a5-097dec70b283" />

The search runs a two-stage pipeline:
1. **Cosine similarity** retrieval — fast top-N candidates from the embedding index
2. **LLM reranker** — precise scoring with confidence score and rationale per candidate

Click **↺ Clear search filter** inside the panel to return to the full list.

---

## Customizing categories and the prompt

Click **Edit Prompt** in the report header to open the prompt editor.

<img width="987" height="533" alt="image" src="https://github.com/user-attachments/assets/0fc2cd4c-fb72-4eba-a288-a952b2b5e0de" />

- **Categories table** — add, edit, or delete categories and their descriptions
- **Assignment rules** — rules the LLM follows when deciding between categories
- **System prompt** (advanced) — the full prompt template

When you save a changed prompt, the app detects the hash change and asks for confirmation before re-categorizing all users. This is intentional — changing the prompt invalidates existing categorizations.

---

## Advanced settings reference

Open **Settings → Show advanced options** to configure:

### Extraction

| Field | Default | Description |
|---|---|---|
| Max messages to fetch | `1000` | Total messages pulled from Telegram per run |
| Min messages per user | `1` | Skip users with fewer messages (filters out one-liners) |
| Telegram topic ID | `8` | Forum thread to scrape — `0` = all topics |

### Categorization

| Field | Default | Description |
|---|---|---|
| Users per LLM call | `5` | How many users are sent together in one LLM call |
| Messages per user in prompt | `10` | Max messages per user included in the categorization prompt |
| LLM retry attempts | `3` | Retries on API failure (exponential backoff) |
| Parallel batch workers | `5` | Concurrent LLM calls in flight |

### Search

| Field | Default | Description |
|---|---|---|
| Top-k candidates | `25` | Candidates retrieved by cosine similarity and passed to reranker |
| Search confidence threshold | `0.6` | Minimum confidence score to include a result (0.0–1.0) |

---

## Re-running and incremental updates

| Scenario | What to do |
|---|---|
| New members joined since last run | Click **Run** — only new/updated users are processed |
| Want to re-categorize everyone | Edit and save the prompt, confirm the re-run |
| Start completely fresh | Delete `data/` folder and run again |

---

## Data and privacy

All data is stored locally under `data/`:

```
data/
├── settings.json        ← credentials (gitignored)
├── users.json           ← extracted user records
├── messages.json        ← extracted messages
├── categorizations/     ← one JSON shard per user
├── embeddings.npz       ← search index vectors
├── meta.json            ← prompt hash, schema version
└── exports/             ← report.html, .csv, .json
```

No database, no cloud storage. Everything is plain JSON files you can read and edit by hand.

---

## Troubleshooting

**Server won't start**
```bash
source venv/bin/activate
python -m app
```

**QR code not appearing / authentication failing**
- Check that your Telegram API ID and hash are correct in Settings
- Make sure your phone has internet access to scan the QR

**Categorization is slow**
- Reduce **Parallel batch workers** if you're hitting OpenAI rate limits
- Switch to `gpt-4o-mini` for the categorization model (faster, cheaper, slightly lower quality)

**Search returns no results**
- Lower the **Search confidence threshold** (try `0.4`)
- Re-run categorization if the search index is stale (the app will log a warning)

**Want to force a fresh categorization**
```bash
rm -rf data/categorizations/ data/embeddings.npz data/meta.json
# Then click Run in the browser
```

---

## Project structure

```
telegram-categorizer/
├── app/
│   ├── categorize/      ← LLM categorization (worker, service, prompt, schema)
│   ├── extract/         ← Telegram extraction + auth manager
│   ├── report/          ← Jinja2 templates + static export
│   ├── search/          ← Embedder, vector index, LLM reranker
│   ├── server/          ← FastAPI app + routes
│   ├── storage/         ← FileStore (flat-file persistence)
│   ├── config.py        ← Config loader (settings.json → env → defaults)
│   └── __main__.py      ← Server entrypoint
├── config/
│   ├── categories.json  ← Category definitions and assignment rules
│   └── prompts/         ← System prompt and few-shot example
├── data/                ← Runtime state (gitignored)
├── images/              ← Screenshots used in this README
├── requirements.txt
└── README.md
```
