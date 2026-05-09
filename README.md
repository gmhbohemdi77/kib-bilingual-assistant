# KIB Bilingual Assistant

A bilingual (English / العربية) AI assistant for **Kuwait International Bank (KIB)**, built on Retrieval-Augmented Generation (RAG) over the bank's official website content.

🌐 **Live demo:** [kib-bilingual-assistant.streamlit.app](https://kib-bilingual-assistant-gnusmy9za8k4aqimserw65.streamlit.app/)

---

## What it does

Ask the assistant any question about KIB in English or Arabic, and get an answer grounded in real KIB website content — with source citations.

```
You:    What is KIB Aqari?
Bot:    KIB Aqari is a comprehensive, one-stop-shop real estate platform
        offered by Kuwait International Bank. Key features include automated
        rent collection, unpaid rent tracking, property appraisal requests,
        and QR code verification for appraisal reports.
        Sources: kib.com.kw/en/home/Real-Estate (score 0.882)
```

```
أنت:        ما هي الحسابات؟
المساعد:   يقدم بنك الكويت الدولي مجموعة كاملة من الحسابات...
            المصادر: kib.com.kw/en/home/Personal/Bank (score 0.871)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User (English or Arabic)                      │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Streamlit Web App (Streamlit Cloud)                 │
│   • Bilingual chat UI                                            │
│   • Microsoft Entra ID sign-in (dev mode toggle for demo)       │
│   • Role-based access: AI Trainer panel for admins              │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│             core.rag — Reusable RAG Module                       │
│   1. Detect language (Arabic vs English)                         │
│   2. Embed question (text-embedding-3-small, 1536-d)             │
│   3. Vector search MongoDB Atlas                                 │
│   4. Generate answer with gpt-4.1-mini, grounded in context     │
└──────────────┬──────────────────────────────┬───────────────────┘
               ▼                              ▼
        ┌─────────────┐               ┌──────────────────┐
        │ Azure OpenAI│               │ MongoDB Atlas    │
        │  (kib-openai)│              │  (kib-cluster)   │
        │              │              │  Vector index    │
        └─────────────┘               └──────────────────┘
                                              ▲
                                              │
┌─────────────────────────────────────────────┴───────────────────┐
│   GitHub Actions — Daily KIB Scraper (Phase 6.1)                │
│   • Cron: 00:00 UTC daily                                        │
│   • Scrapes KIB site, runs SHA-256 change detection,             │
│     updates only changed chunks                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

### 🌍 Bilingual support
Detects question language (English / Arabic) and uses separate embedding fields (`embedding_en`, `embedding_ar`) in MongoDB. Average retrieval score: **0.80–0.88**.

### 🔐 Role-based access
Two user types:
- **Regular Employee** — chat-only access
- **AI Trainer** — chat + admin panel for manual data refresh

Implemented via Microsoft Entra ID security groups. Currently in dev-mode toggle (Entra ID setup pending IT approval).

### ⏱ Change detection
Each scraped content chunk is hashed (SHA-256). Daily updates only re-embed *new* chunks — saves ~90% of compute on no-change days.

| Run | Pages scraped | New chunks | Unchanged | Time |
|-----|---------------|------------|-----------|------|
| First | 3 | 7 | 0 | 2 min |
| Second | 3 | 0 | 7 | 11 sec |

### 🎁 Offer/promotion monitor
Automatically flags new content from `/offers` and `/promotions` pages, plus any chunk mentioning offer keywords. Surfaces them in the AI Trainer Panel.

### 🛠 AI Trainer manual refresh
Trainers can trigger an immediate scrape + change-detection update from the web UI, without waiting for the next scheduled run.

---

## Tech stack

| Layer | Tool |
|-------|------|
| **Frontend** | Streamlit |
| **Auth** | Microsoft Entra ID (MSAL) |
| **RAG core** | Custom Python (`core.rag`) |
| **Embeddings** | Azure OpenAI `text-embedding-3-small` |
| **Chat** | Azure OpenAI `gpt-4.1-mini` |
| **Vector DB** | MongoDB Atlas (Vector Search) |
| **Scraper** | `curl_cffi` + BeautifulSoup |
| **API (Teams)** | FastAPI |
| **Daily updates** | GitHub Actions (cron) |
| **Hosting** | Streamlit Cloud (web), GitHub Actions (jobs) |

---

## Project status (Phase 5 + 6)

| # | Task | Status |
|---|------|--------|
| **5.1** | Teams via Copilot Studio | Code complete; deployment pending |
| **5.2** | Streamlit web app | ✅ **Live** |
| **5.3** | Entra ID authentication | Code complete; awaiting IT approval |
| **5.4** | Role-based access (AI Trainer / Employee) | Code complete; demoed via dev mode |
| **6.1** | Daily scraper | ✅ **Live on GitHub Actions** |
| **6.2** | Change detection (SHA-256) | ✅ Working |
| **6.3** | AI Trainer manual update portal | ✅ Working in deployed app |
| **6.4** | New offers/promotions monitor | ✅ Working |

---

## Local development

```bash
# Clone
git clone https://github.com/gmhbohemdi77/kib-bilingual-assistant
cd kib-bilingual-assistant

# Set up Python
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# Configure
# Create a .env file at the project root with your secrets:
#   MONGODB_URL, AZURE_ENDPOINT, AZURE_KEY,
#   AZURE_API_VERSION, AZURE_EMBEDDING_DEPLOYMENT, AZURE_CHAT_DEPLOYMENT

# Run the chat UI (dev mode skips Entra ID)
set KIB_DEV_AUTH=1
streamlit run streamlit_app/app.py
```

Open [localhost:8501](http://localhost:8501) and pick a sign-in role.

To run the Phase 6 update job manually:

```bash
python -m core.update
```

---

## Deployment

### Web app (Streamlit Cloud)
Pushed automatically when this repo is updated on `main`. Secrets live in the Streamlit Cloud project settings, not the repo.

### Daily scraper (GitHub Actions)
See `.github/workflows/daily_update.yml`. Runs every day at 00:00 UTC, with manual trigger available via the **Actions** tab.

---

## Project context

Built as the deployment phase of a CSC489 senior capstone project at **Gulf University for Science & Technology (GUST)**. Phases 1–4 (cloud infrastructure, RAG pipeline, website scraping, bilingual support) were completed by the project team prior to this work.

This deployment scope (Phases 5 & 6) covers:
- Public-facing web UI
- Authentication framework
- Role-based access control
- Real-time data refresh automation
- Change detection and cost optimization

---

## License

For academic use as part of CSC489 at GUST. Not licensed for commercial use without permission from the project team.
