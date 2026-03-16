# 🐒 Babu Learns Gujarati

> A conversation-first Gujarati language learning app for Indian-American kids aged 3–10.  
> Built by Rujuta Gandhi · WhIndian Creations · 2026

**[Try it live →](https://rujutagandhi.github.io/babu_learns_gujarati/)**

---

## Overview

Babu Learns Gujarati teaches diaspora children Gujarati vocabulary through picture flashcards, voice audio, and emoji-based quizzes. The core design constraint: **zero reading ability required**. Everything is driven by pictures, Babu's voice, and swipe gestures.

Inspired by my own story: I want my toddlers to learn Gujarati in a fun and interactive way. There are no Gujarati schools nearby, and grandparent exposure is not enough.

---

## What's New in V2.2

### Audio — Pre-generated MP3s via GitHub Actions CI/CD

All 95 Gujarati word audio files are now pre-generated as static MP3s and served directly from GitHub Pages. This matches the architecture used by Duolingo, Rosetta Stone, and Pimsleur — no major language app makes live TTS API calls during a learning session.

**Three-tier audio fallback:**
1. **Tier 1 — Static MP3** (`audio/{topic}_{stack}_{card}.mp3`) — plays in under 100ms, zero API cost
2. **Tier 2 — Sarvam Edge Function** — live TTS call if the MP3 file is missing
3. **Tier 3 — Web Speech API** — browser fallback if both above fail

**GitHub Actions workflow** (`generate_audio.yml`) automatically generates MP3s when `flashcards_manifest.json` changes. The manifest tracks which cards have audio and what Gujarati script they contain — only new or changed cards trigger regeneration. See `AUDIO_GENERATION.md` for the full workflow documentation.

### Audio UX Improvements

- Word plays immediately when a flashcard loads — no button press needed
- Tapping the flashcard repeats the word
- Speaker button removed from the card screen — tap the card to replay
- Audio context unlocked on first user gesture for reliable autoplay on iOS and mobile browsers

### Card Screen UI

- Removed the 🔊 Hear Babu and 🐢 Slow buttons
- Replaced with two round action buttons: 🔄 (review again) and ✓ (got it)
- Tapping the card itself replays the word

### Quiz Flow Fixes

- **Congrats timing** — praise audio plays immediately on correct answer; Next button appears after praise finishes
- **New word timing** — navigating to the next question plays the new word after the screen loads, not before
- **Wrong answer audio** — Babu says "Try karo!" then pauses, then repeats the word (sequential, not simultaneous)
- **Review loop before quiz** — cards marked "again" are replayed before the quiz starts
- **Play Again** — now restarts the quiz instead of going back to the flashcard screen

### Background Color

Card, quiz, and reward screens consistently use the jungle green gradient. Topic color gradients apply to the stacks screen only. This matches Duolingo and Rosetta Stone — consistent environment keeps the child focused on content.

---

## What's New in V2.1

### TTS — Switched from ElevenLabs to Sarvam Bulbul v3
Sarvam receives native Gujarati script (e.g. "સફરજન") and produces authentic Gujarati pronunciation. ElevenLabs was receiving romanized text (e.g. "Safarjan") and producing an anglicized accent.

### Backend — Supabase Edge Functions (no keys in the browser)
Two Supabase Edge Functions act as backend proxies:
- **`get-cards`** — fetches all flashcard content using an internal service role key
- **`tts-proxy`** — forwards TTS requests to Sarvam using an internal API key

No credentials are exposed in the browser.

### Content — Supabase database replaces hardcoded JS
All 95 flashcards live in a Supabase `flashcards` table with Row Level Security enabled. New words can be added through the Supabase dashboard without touching code.

### New Topics
- **Numbers** — 1 through 20, 4 stacks of 5 cards
- **Body Parts** — 15 kid-appropriate words across 3 stacks
- **Emotions** — 15 words across 3 stacks

---

## What I Built (V1)

- **45 vocabulary cards** across 3 topics: Fruits, Colors, Family
- **3 stacks per topic** (5 cards each), progressively unlocked
- **Swipe right = Got it · Swipe left = Again** — gesture-native UX
- **ElevenLabs TTS** with a custom voice
- **Picture-only quiz**: Babu says a word, child taps the matching emoji from a 2×2 grid
- **Two-strike wrong answer logic**: encourage on first miss, reveal answer on second
- **Babu animates**: jumps on correct, flips on wrong
- **Stars = words learned** (1 per word; no duplicates on replay)
- **Gujarati script toggle** — persists via localStorage
- **Reward screen** with confetti; Gujarati praise first, English below
- **Flag cards** for bad translations

---

## Tech Stack

| Layer | V1 | V2.1 | V2.2 |
|---|---|---|---|
| Frontend | Vanilla HTML / CSS / JS | Same | Same |
| Hosting | GitHub Pages | Same | Same |
| TTS | ElevenLabs | Sarvam Bulbul v3 | Pre-generated MP3s |
| TTS input | Romanized text | Gujarati script | Gujarati script |
| TTS fallback | Web Speech (en-US) | Web Speech (gu-IN) | Edge Function → Web Speech |
| Backend | None — keys in HTML | Supabase Edge Functions | Same |
| Content | 45 cards hardcoded | 95 cards in Supabase | Same |
| Audio delivery | Live API calls | Live API calls | Static MP3s + fallback |
| CI/CD | None | None | GitHub Actions |

---

## Lessons Learned

### Product Decisions

**Conversation-first, not literacy-first.** The card is just a picture — Babu says everything. Reduced cognitive load dramatically for pre-readers.

**Tap the card to repeat.** Removing the speaker button and making the card tappable is more intuitive — the picture is the thing you're learning, so tapping it to hear it again is a natural gesture.

**Review before quiz, not after.** Cards marked "again" should be seen again before the quiz. A child who struggled shouldn't be quizzed without a second chance.

**Congrats should finish before Next appears.** The original timing had praise playing simultaneously with the next word. Sequential audio makes both meaningful.

**Wrong answer audio needs a pause.** "Try karo! Apple." as one string is confusing. "Try karo!" → pause → "Apple" is how a patient teacher speaks.

**Pre-generate audio, don't stream it.** Live TTS calls add 500–1500ms per word. Pre-generating 95 MP3s means audio plays in under 100ms. This is what every major language app does.

**Consistent background = consistent focus.** Changing background per topic created visual noise. Jungle green throughout is the brand.

**Send native script to TTS.** ElevenLabs received "Safarjan" and guessed. Sarvam receives "સફરજન" and knows exactly how to say it.

### Technical Decisions

**GitHub Actions for audio generation.** The workflow only runs when `flashcards_manifest.json` changes — not on every code push. Only new or changed cards are processed. This mirrors how content pipelines work at production language apps.

**Three-tier audio fallback.** The app degrades gracefully if any layer fails. Forgetting to update the manifest doesn't break the app — it falls back to live API calls with latency.

**Concurrency control in GitHub Actions.** `concurrency: group: generate-audio` prevents two workflow runs from overlapping and causing git push conflicts.

**Retry logic for Sarvam API.** Short Gujarati words occasionally return empty audio. The script retries up to 3 times with increasing delays before marking a file as failed.

**`speakText` returns a Promise.** Resolves when audio ends across all three tiers. Enables `.then()` chaining for sequential audio without setTimeout guesswork.

**Audio context unlock on first gesture.** A silent audio clip played on the first topic card tap unlocks the audio context for the entire session.

---

## Roadmap

| Version | Focus | Key Features |
|---|---|---|
| **V1** | MVP — Static web | 45 cards, ElevenLabs TTS, picture quiz, swipe, GitHub Pages |
| **V2.1** | Backend + Sarvam TTS | Sarvam Bulbul v3, Supabase Edge Functions, 95 cards, 3 new topics |
| **V2.2 ✅** | Performance + UX | Pre-generated MP3s, GitHub Actions CI/CD, quiz flow fixes, audio unlock |
| **V2.3** | Pronunciation Feedback | Sarvam STT — child speaks word, app responds |
| **V2.5** | iOS App Store | Capacitor wrapper, App Store submission |
| **V3** | Auth + Parent Dashboard | Supabase user accounts, cross-device sync, parent dashboard |
| **V3.5** | Monetization | In-app purchases, story mode, merchandise |

---

## Running Locally

No build step needed. Open `index.html` in a browser. The app fetches cards from Supabase and plays pre-generated MP3s from `/audio/`. To regenerate audio files locally, see `AUDIO_GENERATION.md`.

---

## Part of

[Rujuta Gandhi's AI Product Portfolio](https://rujutagandhi.github.io) · [LinkedIn](https://linkedin.com/in/gandhirujuta)
