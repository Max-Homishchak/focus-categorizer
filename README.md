# Telegram FOCUS Categorizer

## Summary

Automates profiling of FOCUS community members. Extracts messages from a group/topic, sends them to an LLM (OpenAI) for categorization, and generates a filterable HTML report, CSV, and JSON with structured profiles (category, tags, metadata, worth-checking flag).

---

## Prerequisites

- **Python 3.10+**
- **Telegram API credentials** — get them at [my.telegram.org/apps](https://my.telegram.org/apps)
- **OpenAI API key** — get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- **Telegram account** — you must be a member of the group you want to analyze

---

## Configuration

All settings are configured via a `.env` file in the project root. Copy `.env.example` to `.env` and fill in the values.

### Required

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` | Your Telegram API ID (integer) |
| `TELEGRAM_API_HASH` | Your Telegram API hash |
| `TELEGRAM_PHONE` | Phone number linked to your Telegram account |
| `CHANNEL_USERNAME` | Group/channel username (without `@`) or numeric ID (e.g. `-1001234567890`) |
| `OPENAI_API_KEY` | Your OpenAI API key |

### Extraction

| Variable | Default | Description |
|---|---|---|
| `MAX_MESSAGES` | `1000` | Maximum number of messages to pull from Telegram |
| `MIN_MESSAGES_PER_USER` | `1` | Skip users with fewer messages than this |
| `TOPIC_ID` | `0` | Forum topic ID to scrape (0 = all topics) |

### LLM

| Variable | Default | Description |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model to use for categorization |
| `USERS_PER_BATCH` | `5` | Number of users sent per LLM API call |
| `MAX_MESSAGES_PER_USER` | `10` | Max messages per user included in the LLM prompt |
| `MAX_RETRIES` | `3` | Retry attempts on API failure (exponential backoff) |

### Categories & Rules

Categories and their assignment rules are defined in a single JSON file:

| Variable | Default | Description |
|---|---|---|
| `CATEGORIES_FILE` | `./config/categories.json` | Path to the categories + rules config file |

The file has two sections:

- **`categories`** — array of `{"name": "...", "description": "..."}` objects. The name is the exact label assigned by the LLM and shown in the report. The description tells the LLM what fits this category.
- **`assignment_rules`** — array of strings, each a rule the LLM follows when deciding between categories (e.g. disambiguation, strictness, evidence requirements).

A `config/categories.example.json` is provided as a starting point. Copy it to `categories.json` and adjust for your use case:

```bash
cp config/categories.example.json config/categories.json
```

### Prompts

| Variable | Default | Description |
|---|---|---|
| `PROMPT_FILE` | `./prompts/system_prompt.txt` | Path to the system prompt template (must contain `{categories}` and `{category_rules}` placeholders) |
| `FEW_SHOT_FILE` | `./prompts/few_shot_example.txt` | Path to the few-shot example file (optional — leave empty to skip) |

Edit the prompt files directly to customize how the LLM processes users. No code changes needed.

### Filtering (post-categorization)

These filters are applied when generating reports. They do not affect LLM processing — you can change them and re-run without re-categorizing.

| Variable | Default | Description |
|---|---|---|
| `FILTER_INCLUDE_CATEGORIES` | *(empty)* | Comma-separated categories to include (empty = all) |
| `FILTER_EXCLUDE_CATEGORIES` | *(empty)* | Comma-separated categories to exclude |
| `FILTER_SKIP_USER_IDS` | *(empty)* | Comma-separated user IDs to skip entirely |
| `FILTER_REQUIRE_TAGS` | *(empty)* | Comma-separated tags — only show users matching at least one |
| `FILTER_ONLY_WORTH_CHECKING` | `false` | Set to `true` to only show users flagged as worth checking |

### Output

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_DIR` | `./output` | Directory where reports are saved |

---

## Setup & Usage

### 1. Clone and enter the project

```bash
cd telegram-categorizer
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your Telegram API credentials, OpenAI API key, and the channel/group you want to analyze.

### 5. Run the agent

```bash
python main.py
```

### 6. Authenticate with Telegram (first run only)

On the first run, a QR code will appear in the terminal. Scan it with your Telegram app:

**Telegram > Settings > Devices > Link Desktop Device > scan the QR code**

If you have **two-factor authentication** enabled, you'll be prompted to enter your Telegram cloud password after scanning the QR code.

The session is cached in `tg_session.session` — subsequent runs skip this step.

### 7. Wait for processing

The agent will:
- Extract messages from the configured channel/topic
- Send users to the LLM in batches (progress is logged)
- Save a checkpoint after each batch — if the process crashes, re-running resumes from where it stopped

### 8. View results

```bash
open output/report.html
```

Three files are generated in the output directory:

| File | Description |
|---|---|
| `report.html` | Interactive report with search, category/tag filters, and expandable user cards |
| `categorized_users.csv` | Spreadsheet-friendly export with all fields |
| `categorized_users.json` | Full structured data including messages |

### Re-running

- **Resume after crash**: Just run `python main.py` again — the checkpoint picks up where it left off.
- **Fresh re-categorization**: Delete the checkpoint first, then run:
  ```bash
  rm output/_checkpoint.json
  python main.py
  ```
- **Change filters only** (no LLM re-processing): Edit filter variables in `.env`, then run `python main.py`. If all users are already checkpointed, only the report is regenerated.
