# Boson_ai_Hack: Viva

An AI examiner for presentation defenses, built for the Boson AI × MScAC Higgs Audio Hackathon 2026. You present your slides; a Higgs Avatar examiner listens, knows which slide you're on, interrupts when a claim doesn't hold up, keeps you to time, fact-checks you, runs Q&A (answer in English, Indonesian or Mandarin), and hands you a scorecard.

> Work in progress. See [`PLAN.md`](PLAN.md) for the design, build stages and the interface contract between the agent and the web app. Setup instructions, architecture and known limitations will be filled in before submission.

## Quick start for contributors
1. `cp .env.example .env`, then fill in the keys. Get them from your teammate privately; never commit them.
2. `python docs/fetch_vendor_docs.py`: downloads the Boson docs and the tutorial reference files into `docs/vendor/`.
3. Read `CLAUDE.md`, then the `CLAUDE.md` in the folder you're working in (`agent/`, `server/` or `web/`).
