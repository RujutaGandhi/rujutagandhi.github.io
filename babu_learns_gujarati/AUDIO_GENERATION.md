# Audio Generation — Babu Learns Gujarati

## Why audio is pre-generated

All Gujarati word audio is pre-generated as static MP3 files rather than
calling the Sarvam TTS API at runtime. This matches the approach used by
Duolingo, Rosetta Stone, and Pimsleur — no major language app makes live
TTS calls during a learning session.

Benefits:
- Audio plays in under 100ms — effectively instant
- Zero Sarvam API calls during user sessions
- Works offline once files are cached by the browser
- Dramatically lower API costs as user base grows

---

## How it works

A GitHub Actions workflow automatically generates MP3 files whenever
flashcard content changes in Supabase.

### Trigger
The workflow runs when `flashcards_manifest.json` is pushed to `main`.
This file must be updated manually whenever you add or edit content in
Supabase (see below).

### What the workflow does
1. Fetches all rows from the Supabase `flashcards` table
2. Compares against `flashcards_manifest.json` to find new or changed cards
3. Calls the `tts-proxy` Edge Function for each changed card
4. Saves MP3 files to `babu_learns_gujarati/audio/`
5. Updates `flashcards_manifest.json`
6. Commits and pushes all changes back to the repo automatically

---

## File naming convention
```
audio/{topic}_{stack_index}_{card_index}.mp3
```

Examples:
- `audio/fruits_0_0.mp3` — Fruits, Stack 1, Card 1 (Apple/સફરજન)
- `audio/numbers_2_3.mp3` — Numbers, Stack 3, Card 4 (Fourteen/ચૌદ)
- `audio/emotions_1_0.mp3` — Emotions, Stack 2, Card 1 (Laughing/હસું)

Indexes are zero-based and match the `stack_index` and `card_index`
columns in the Supabase `flashcards` table exactly.

---

## ⚠️ When to update — critical workflow

### Adding new words to Supabase
1. Insert new rows into the `flashcards` table in Supabase dashboard
2. Open `flashcards_manifest.json` locally — add a placeholder entry:
```json
   "topic_stackindex_cardindex": "pending"
```
3. Commit and push `flashcards_manifest.json` to `main`
4. GitHub Actions detects the change and runs automatically
5. New MP3 files are generated and committed back to the repo

### Editing an existing word's Gujarati script
1. Update the `gu` column in the Supabase `flashcards` table
2. Delete the corresponding entry from `flashcards_manifest.json` locally
3. Commit and push `flashcards_manifest.json` to `main`
4. GitHub Actions regenerates only that word's MP3

### If you forget to update the manifest
The app falls back gracefully — it tries the static MP3 first, then
calls the Sarvam Edge Function live if the file doesn't exist. The
user experience degrades slightly (latency returns) but the app
never breaks.

---

## Forcing a full regeneration

To regenerate all 95+ MP3 files from scratch:
1. Delete the contents of `flashcards_manifest.json` — replace with `{}`
2. Commit and push
3. GitHub Actions regenerates every file

Use this if you change the Sarvam voice or model settings in `tts-proxy`.

---

## Running the script locally

If you need to generate audio on your machine without GitHub Actions:
```bash
# From the babu_learns_gujarati/ directory
export SUPABASE_URL="https://iulwgadxcojjmbggvfrj.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-role-key"
export TTS_ENDPOINT="https://iulwgadxcojjmbggvfrj.supabase.co/functions/v1/tts-proxy"
node generate_audio.js
```

Then commit and push the generated MP3 files and updated manifest.

---

## V2.3 planned improvement

Move to GitHub Actions triggering automatically when Supabase content
changes, eliminating the manual manifest update step entirely.

---

## Secrets required

The GitHub Actions workflow reads these from GitHub repository secrets:
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_KEY` — Supabase service role key (not the anon key)

The `tts-proxy` endpoint URL is hardcoded in the workflow — it is not
a secret.

---

## Audio privacy

Audio files are currently public via GitHub Pages. Restricting access
to authenticated users is planned for V3 when a backend with
authentication is introduced.