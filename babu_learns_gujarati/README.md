# 🐒 Babu Learns Gujarati

> A conversation-first Gujarati language learning app for Indian-American kids aged 3–10.  
> Built by Rujuta Gandhi · WhIndian Creations · 2026

**[Try it live →](https://rujutagandhi.github.io/babu_learns_gujarati/)**

---

## Overview

Babu Learns Gujarati teaches diaspora children Gujarati vocabulary through picture flashcards, voice audio, and emoji-based quizzes. The core design constraint: **zero reading ability required**. Everything is driven by pictures, Babu's voice, and swipe gestures.

Inspired by my own story: I want my toddlers to learn Gujarati in a fun and interactive way. There are no Gujarati schools nearby, and grandparent exposure is not enough.

---

## What's New in V2.1

### TTS — Switched from ElevenLabs to Sarvam Bulbul v3
The app now uses Sarvam's Bulbul v3 model (`gu-IN`) for text-to-speech. Unlike ElevenLabs which was receiving romanized text (e.g. "Safarjan"), Sarvam receives native Gujarati script (e.g. "સફરજન") and produces authentic Gujarati pronunciation. This is a meaningful improvement for diaspora children learning to hear the language correctly.

### Backend — Supabase Edge Functions (no keys in the browser)
V1 exposed the ElevenLabs API key directly in the HTML. V2.1 introduces two Supabase Edge Functions as a backend proxy:
- **`get-cards`** — fetches all flashcard content from Supabase using an internal service role key
- **`tts-proxy`** — forwards TTS requests to Sarvam using an internal API key

No credentials are exposed in the browser. The app only knows two endpoint URLs.

### Content — Supabase database replaces hardcoded JS
All 95 flashcards now live in a Supabase `flashcards` table with Row Level Security enabled. The app fetches cards dynamically on load. New words can be added through the Supabase dashboard without touching code.

### New Topics — 3 additional topics added
- **Numbers** — 1 through 20, 4 stacks of 5 cards, digit characters as visuals
- **Body Parts** — 15 kid-appropriate words across 3 stacks (eyes, ears, nose, mouth, hands, feet, hair, teeth, arm, leg, brain, bone, heart, fingers, back)
- **Emotions** — 15 words across 3 stacks (happy, sad, angry, scared, tired, laughing, surprised, loving, calm, sick, embarrassed, excited, disappointed, loved, frustrated)

### UI Changes
- Topic cards now show Gujarati transliteration below the English name (e.g. "Fal" under "Fruits"); Gujarati script shown if script toggle is on
- Replaced "Hear Babu" and "Slow" buttons with three round action buttons: 🔄 (review again), 🔊 (replay word), ✓ (got it)
- Removed swipe hint arrows from the card screen — swipe gestures still work
- Card and quiz screens now use the jungle green background for visual consistency
- Fixed quiz praise timing — Next button now appears after Babu finishes speaking
- Fixed Play Again — now restarts the quiz instead of going back to flashcards
- Fixed quiz audio — now sends Gujarati script to Sarvam instead of romanized text

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

---

## Tech Stack

| Layer | V1 | V2.1 |
|---|---|---|
| Frontend | Vanilla HTML / CSS / JS — single file | Same |
| Hosting | GitHub Pages | Same |
| TTS | ElevenLabs `eleven_multilingual_v2` | Sarvam Bulbul v3 (`gu-IN`) |
| TTS input | Romanized text (e.g. "Safarjan") | Gujarati script (e.g. "સફરજન") |
| TTS fallback | Web Speech API (en-US) | Web Speech API (gu-IN) |
| Backend | None — keys in HTML | Supabase Edge Functions |
| Content | 45 cards hardcoded in JS | 95 cards in Supabase database |
| Storage | localStorage | localStorage |

---

## Lessons Learned

### Product Decisions

**Conversation-first, not literacy-first.** Removing flip cards and on-screen words was the right call — the card is just a picture, Babu says everything. This cut cognitive load dramatically for pre-readers.

**Swipe beats buttons for kids.** The Got it / Again button row felt like schoolwork. Swipe right / left is instinctive for children who grew up with touchscreens.

**Quiz distractors must come from the same stack.** Pulling from all topics put fruits next to colors, which confused the picture-choice format. Same-stack distractors make the quiz feel fair and learnable.

**Praise should be heard, not read.** Text praise at the bottom added noise without value for a non-reader. Babu speaking the praise aloud is more impactful and keeps the screen clean.

**Stars = words, not quality score.** Originally 1-3 stars for quiz performance. Changed to 1 star per word learned (5 words = 5 stars) — concrete and genuinely rewarding to a child.

**No duplicate stars.** Once a stack is complete, replaying it should not inflate the star count. A simple alreadyDone flag in localStorage solved this cleanly.

**Send native script to TTS, not romanization.** ElevenLabs was receiving "Safarjan" and guessing pronunciation. Sarvam receives "સફરજન" and knows exactly how to say it. The quality difference is significant.

**Backend proxies protect API keys without a full server.** Supabase Edge Functions are lightweight Deno functions — no cold start problem, no server to maintain, free tier sufficient for V2.1. The Sarvam key and Supabase service key never leave the server.

### Technical Decisions

**Sarvam Bulbul v3 over ElevenLabs for V2.1.** Bulbul v3 is trained on Indian languages and handles Gujarati script natively. ElevenLabs required romanized input and produced a non-Gujarati accent. The switch was the single most impactful quality improvement in V2.1.

**Supabase Edge Functions as the backend proxy.** No separate server needed — the Edge Functions live inside the existing Supabase project. Two functions handle everything: one for fetching cards, one for proxying TTS. Secrets are stored as Supabase environment variables and never exposed to the browser.

**RLS on with a public read policy.** The flashcards table has Row Level Security enabled with a single SELECT policy for all users. The anon key cannot write, delete, or access any other table. The service role key (used inside the Edge Function) has full access but never reaches the browser.

**Flashcard content in Supabase, not hardcoded JS.** Moving from 45 hardcoded cards to 95 database rows was the right call for a portfolio piece. New words can be added through the Supabase dashboard. The table schema supports all 6 topics dynamically.

**Topic card UI generated dynamically.** renderTopicCards() loops over whatever topics come back from Supabase. Adding a new topic to the database automatically creates a new card on the home screen. The only hardcoded part is TOPIC_CONFIG — the emoji and gradient for each topic key — which is a deliberate UI design decision, not content.

### Design Decisions

**Jungle green background on all screens.** Extending the dark green gradient to the card and quiz screens creates a consistent, immersive jungle feel. The light cream background on quiz screens was causing white text to be invisible — the fix also improved brand consistency.

**Round icon buttons replace labeled audio buttons.** The 🔄 🔊 ✓ button row is more intuitive for children than "Hear Babu" and "Slow" text labels. The colors reinforce meaning: orange for review, green for learned.

**Topic name translation below English label.** Showing "Fal" under "Fruits" on the home screen gives children and parents immediate cultural context. Switching to Gujarati script mode shows "ફળ" instead — consistent with the script toggle behavior throughout the app.

---

## Roadmap

| Version | Focus | Key Features |
|---|---|---|
| **V1** | MVP — Static web | 45 cards, ElevenLabs TTS, picture quiz, swipe, GitHub Pages |
| **V2.1** | Backend + Sarvam TTS | Sarvam Bulbul v3, Supabase Edge Functions, 95 cards, 3 new topics |
| **V2.2** | Caching + Performance | localStorage cache with version check, faster load times |
| **V2.3** | Pronunciation Feedback | Sarvam STT — child speaks word, app responds |
| **V2.5** | iOS App Store | Capacitor wrapper, App Store submission |
| **V3** | Auth + Parent Dashboard | Supabase user accounts, cross-device sync, parent dashboard |
| **V3.5** | Monetization | In-app purchases, story mode, merchandise |

### V2.2 — Caching
- Cache flashcard content in localStorage after first load
- Version number stored in Supabase — app checks version on load and only re-fetches if content has changed
- First load slow, every subsequent load instant

### V2.3 — Pronunciation Feedback
- Child taps microphone button and speaks the word
- Sarvam STT scores pronunciation
- Babu responds with encouragement or gentle correction

### V2.5 — iOS
- Capacitor wrapper to package the web app as a native iOS app
- Key risk: validate Web Audio API inside Capacitor WebView on iOS Safari before committing
- Target: Apple App Store submission

### V3 — Backend
- Supabase user accounts and cross-device progress sync
- Parent dashboard: view child progress, flagged cards, starred words
- Babu's Wisdom Corner: Gujarati proverbs with audio and cultural context
- Community flag review: crowdsourced translation quality control
- Move TOPIC_CONFIG (emoji, gradient) to a topics table in Supabase — nothing hardcoded
- Android support

---

## Running Locally

No build step needed. Just open index.html in a browser.

Note: the app fetches cards and audio from Supabase Edge Functions. These work from any origin in a local browser — no local server needed.

---

## Part of

[Rujuta Gandhi's AI Product Portfolio](https://rujutagandhi.github.io) · [LinkedIn](https://linkedin.com/in/gandhirujuta)
