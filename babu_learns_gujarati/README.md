# 🐒 Babu Learns Gujarati

> A conversation-first Gujarati language learning app for Indian-American kids aged 3–10.  
> Built by Rujuta Gandhi · WhIndian Creations · 2026

**[Try it live →](https://rujutagandhi.github.io/gujarati_app/)**

---

## Overview

Babu Learns Gujarati teaches diaspora children Gujarati vocabulary through picture flashcards, voice audio, and emoji-based quizzes. The core design constraint: **zero reading ability required**. Everything is driven by pictures, Babu's voice, and swipe gestures.

For V1, the app is a single HTML file deployed on GitHub Pages — no backend, no build step, no cold starts.

Inspired by my own story: I want my toddlers to learn Gujarati in a fun and interactive way. There are no Gujarati school nearby, and grandparent exposure is not enough. 

---

## What I Built (V1)

### Features
- **45 vocabulary cards** across 3 topics: Fruits, Colors, Family
- **3 stacks per topic** (5 cards each), progressively unlocked
- **Swipe right = Got it · Swipe left = Again** — no buttons, gesture-native UX
- **ElevenLabs TTS** with a custom voice — Babu speaks every word aloud
- **Picture-only quiz**: Babu says a word, child taps the matching emoji from a 2×2 grid
- **Two-strike wrong answer logic**: encourage on first miss, reveal answer on second
- **Babu animates**: jumps on correct answers, flips on wrong ones
- **Stars = words learned** (1 star per word; no duplicate stars on replay)
- **Gujarati script toggle** — parent-facing, persists across sessions via localStorage
- **Reward screen** with confetti; Gujarati praise shown first, English below
- **Flag cards** for bad translations
- Graceful fallback to Web Speech API if ElevenLabs is unavailable

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML / CSS / JS — single file, no build step |
| Hosting | GitHub Pages (always-on, zero cold start) |
| TTS | ElevenLabs `eleven_multilingual_v2` with custom voice |
| TTS Fallback | Web Speech API (en-US) |
| Quiz | Local JS — same-stack distractors only, no API needed |
| Storage | localStorage (stars, completed stacks, flags, script toggle) |
| Content | 45 cards inline in JS — instant load, no network fetch |

---

## Lessons Learned

### Product Decisions

**Conversation-first, not literacy-first.** Removing flip cards and on-screen words was the right call — the card is just a picture, Babu says everything. This cut cognitive load dramatically for pre-readers.

**Swipe beats buttons for kids.** The Got it / Again button row felt like schoolwork. Swipe right / left is instinctive for children who grew up with touchscreens.

**Quiz distractors must come from the same stack.** Pulling from all topics put fruits next to colors, which confused the picture-choice format. Same-stack distractors make the quiz feel fair and learnable.

**Praise should be heard, not read.** Text praise at the bottom added noise without value for a non-reader. Babu speaking the praise aloud is more impactful and keeps the screen clean.

**Stars = words, not quality score.** Originally 1–3 stars for quiz performance. Changed to 1 star per word learned (5 words = 5 stars) — concrete and genuinely rewarding to a child.

**No duplicate stars.** Once a stack is complete, replaying it should not inflate the star count. A simple `alreadyDone` flag in localStorage solved this cleanly.

**Stack icon should reflect content.** Using `stack.cards[0].emoji` as the stack icon (🍎 for Everyday Fruits, 🥥 for Tropical) is more informative than a generic placeholder.

### Technical Decisions

**ElevenLabs over Sarvam for V1.** ElevenLabs has no native Gujarati voice, but `eleven_multilingual_v2` handles romanized Gujarati (Safarjan, Kelun, Keri) reasonably well with a custom voice. Sarvam is the right long-term upgrade (true Gujarati phonemes), but ElevenLabs gets V1 to market faster.

**API key exposure is acceptable at demo scale.** A static HTML file cannot read `.env` files — the key must be in the JS. Mitigated by setting a monthly character cap in the ElevenLabs dashboard. Pre-generating all 45 MP3s is the V2 fix: no key ships to the browser at all.

**`async/await` for audio.** The ElevenLabs call is async — the browser waits for the network response before playing. The fallback to Web Speech API ensures the app works even without a valid key.

**Single-file architecture.** The entire app is one HTML file. No bundler, no npm, no server. GitHub Pages deployment is a single `git push`, and there's zero infrastructure to maintain for V1.

**localStorage for all state.** No auth, no database in V1. Progress, stars, flags, and the script toggle all persist in the browser. Sufficient for a single-device child app.

### Design Decisions

**Jungle home screen** (dark green gradient + floating monkey) creates an immersive, branded feel that differentiates from generic language apps.

**Baloo 2 font** for display text — it has Indian design DNA and renders Indic character sets naturally.

**Brown skin tone emojis** (🧒🏽, 👩🏽, 👦🏽) throughout the Family topic — representation matters for diaspora children.

**Gujarati praise first on reward screen** — Gujarati comes before English to reinforce that it is the primary language, not a novelty.

**Locked stacks show only 🔒** — no text explanation needed. Young children understand visual locks.

---

## Roadmap

| Version | Focus | Key Features |
|---|---|---|
| **V1 ✅** | MVP — Static web | 45 cards, ElevenLabs TTS, picture quiz, swipe, GitHub Pages |
| **V2** | Pronunciation + Expansion | Sarvam STT feedback, 3 new topics, streaks, pre-generated MP3s |
| **V2.5** | iOS App Store | Capacitor wrapper, App Store submission |
| **V3** | Backend + Auth | Supabase, parent dashboard, cross-device sync |
| **V3.5** | Monetization | In-app purchases, story mode, merchandise |

### V2 Detail
- Pronunciation feedback: child says the word, Sarvam STT scores it
- 3 new vocabulary topics (Animals, Body Parts, Food)
- Streak counter for daily practice motivation
- Audition Indic Parler-TTS (ai4bharat) as open-source alternative to ElevenLabs
- Pre-generate all audio as static MP3s — no API key in the browser

### V2.5 — iOS
- Capacitor wrapper to package the web app as a native iOS app
- Key risk: validate Web Audio API inside Capacitor WebView on iOS Safari before committing
- Target: Apple App Store submission

### V3 — Backend
- Supabase for user accounts and cross-device progress sync
- Parent dashboard: view child progress, flagged cards, starred words
- Babu's Wisdom Corner: Gujarati proverbs with audio and cultural context
- Community flag review: crowdsourced translation quality control
- Android support

---

## Running Locally

No build step needed. Just open `index.html` in a browser.

---

## Part of

[Rujuta Gandhi's AI Product Portfolio](https://rujutagandhi.github.io) · [LinkedIn](https://linkedin.com/in/gandhirujuta)
