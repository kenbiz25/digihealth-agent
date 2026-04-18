# Digi-Health AI Agent — Team Guide

**Medtronic Labs | Digital Health Intelligence Unit**
Live at: https://digihealth.mdtlabs.org

---

## What Is It?

The Digi-Health AI Agent is an automated intelligence platform that monitors digital health news across 9 priority countries every day, analyses it using AI, and produces a structured executive brief — including a downloadable PDF — ready for leadership review.

No manual research. No copy-pasting. The system runs on its own.

---

## Target Countries

| Tier | Countries | Coverage |
|------|-----------|----------|
| **Tier 1 — Priority** | Sierra Leone, Bangladesh | Deepest — 4 queries each, MoH sites, official signals, sentiment |
| **Tier 2** | Kenya, Rwanda, Ghana, India | Broad — news, official statements, LinkedIn discussions |
| **Tier 3** | Saudi Arabia, Tanzania, Bhutan | Baseline — news + policy updates |

---

## How It Works — The Pipeline

When a run is triggered, 7 AI agents work in sequence:

```
Scraper → Verifier → Enricher → Impact Classifier → Writer → PDF → Email
```

| Step | What It Does |
|------|-------------|
| **1. Scraper** | Searches the web, news sites, LinkedIn, Twitter, and Ministry of Health pages for the last 24 hours |
| **2. Verifier** | Fact-checks each article and scores it for credibility (removes low-quality results) |
| **3. Enricher** | Adds context — categories, follow-up links, which countries are mentioned |
| **4. Impact Classifier** | Rates each article: Critical / High / Medium / Low and writes an executive headline |
| **5. Writer** | Produces a one-page country snapshot for each of the 9 countries covering the last 7 days |
| **6. PDF Generator** | Compiles all snapshots into a formatted executive brief with the Medtronic Labs logo |
| **7. Email** | Sends the brief automatically on scheduled Monday runs |

---

## Accessing the Platform

Open your browser and go to: **https://digihealth.mdtlabs.org**

No login required. The dashboard loads immediately.

---

## Dashboard Walkthrough

### Sidebar (Left Panel)
The left sidebar is your control centre. It is always visible and lets you:
- See live stats (total runs, articles verified, AI provider, schedule)
- **Filter articles by country** — click any country to instantly see only that country's news
- **Filter by impact level** — Critical, High, Medium, Low
- **Filter by source** — Twitter/X, LinkedIn, Web, News
- **View the latest brief** or **Run the pipeline** directly from the sidebar

### Executive Pulse (Top of main area)
A real-time summary of the most recent run:
- **Impact distribution bar** — shows the split of Critical / High / Medium / Low articles at a glance
- **Critical Alerts** — articles that need immediate executive attention
- **High Priority** — significant developments to watch
- **Recommended Actions** — AI-generated action items from critical and high items

### Articles Tab
A full searchable and filterable list of all verified articles. Each article shows:
- Impact badge (colour-coded)
- Executive headline (AI-written)
- Source and publication date
- Countries mentioned
- Recommended action

### Pipeline Tab
Watch the AI agents run in real time. Each step lights up as it completes with a progress log below. Use this when you trigger a manual run.

### Run History Tab
A log of every run ever executed. For each completed run you can:
- **👁 View Brief** — opens the PDF directly in the browser
- **⬇ Download PDF** — saves the brief to your device

### Custom Search Tab
Search any topic across the web and get AI-extracted results instantly — without triggering a full pipeline run. Useful for ad-hoc research.

### AI Models Tab
Shows which AI models are active for each pipeline step and their current configuration.

### Request / Edit Tab
Submit plain-English requests to modify or query the latest brief — for example: *"Expand the Sierra Leone section"* or *"Summarise the telemedicine developments in India."*

---

## Running the Pipeline

### Automatic (Scheduled)
The system runs every **Monday at 07:00 EAT** automatically. No action needed.

### Manual Run
1. Use the **Country** dropdown in the top-right header to select a specific country (or leave blank for all)
2. Click **▶ Run Now**
3. Switch to the **Pipeline tab** to watch progress in real time
4. When complete, the PDF brief is available in **Run History**

### Country-Specific Run
To run a scan for one country only (faster, uses fewer tokens):
- Select the country from the sidebar or header dropdown
- Click **▶ Run Now**
- Only that country's snapshot will be produced

---

## The PDF Brief

Each brief contains:
- **Cover page** — stats summary, country index, executive overview
- **One page per country** — impact snapshot, top 5 headlines (clickable links to sources), official signals, social sentiment, recommended actions
- **Strategic Outlook** — cross-country macro trend and forward-looking call to action

Briefs are named by date and stored on the server. Every completed run has its own PDF accessible from Run History.

---

## Updating the System

When code changes are made locally:
```
1. git add . && git commit -m "description" && git push   (on local machine)
2. ssh into server → cd ~/digihealth-agent → git pull → sudo systemctl restart digihealth
```

---

## Key Contacts

| Role | Responsibility |
|------|---------------|
| Medtronic Labs team | Access the dashboard, read briefs, submit requests |
| System administrator | Server access, API key management, deployments |

---

*Digi-Health AI Agent — Medtronic Labs | Built on Anthropic Claude + Tavily Search*
