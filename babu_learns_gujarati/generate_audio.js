// ══════════════════════════════════════════════════════════════
// generate_audio.js — Babu Learns Gujarati
// ══════════════════════════════════════════════════════════════
// PURPOSE:
//   Fetches all flashcards from Supabase, compares against the
//   local manifest, and generates MP3 files for any new or
//   changed cards. Runs automatically via GitHub Actions.
//
// WHEN TO RUN MANUALLY:
//   1. Update flashcards_manifest.json with any content change
//   2. Run: node generate_audio.js (from babu_learns_gujarati/)
//   3. Commit and push the new MP3 files and updated manifest
//
// NAMING CONVENTION:
//   audio/{topic}_{stack_index}_{card_index}.mp3
//   e.g. audio/fruits_0_0.mp3 = Fruits, Stack 1, Card 1 (Apple)
//
// ENVIRONMENT VARIABLES REQUIRED:
//   SUPABASE_URL        — Supabase project URL
//   SUPABASE_SERVICE_KEY — Supabase service role key
//   TTS_ENDPOINT        — tts-proxy Edge Function URL
// ══════════════════════════════════════════════════════════════

const fs   = require('fs');
const path = require('path');

const SUPABASE_URL        = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;
const TTS_ENDPOINT        = process.env.TTS_ENDPOINT;
const AUDIO_DIR           = path.join(__dirname, 'audio');
const MANIFEST_PATH       = path.join(__dirname, 'flashcards_manifest.json');

// ── Validate environment ──────────────────────────────────────
if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY || !TTS_ENDPOINT) {
  console.error('Missing required environment variables.');
  console.error('Required: SUPABASE_URL, SUPABASE_SERVICE_KEY, TTS_ENDPOINT');
  process.exit(1);
}

// ── Ensure audio directory exists ─────────────────────────────
if (!fs.existsSync(AUDIO_DIR)) {
  fs.mkdirSync(AUDIO_DIR, { recursive: true });
  console.log('Created audio/ directory');
}

// ── Load existing manifest ────────────────────────────────────
let manifest = {};
if (fs.existsSync(MANIFEST_PATH)) {
  manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));
  console.log(`Loaded manifest with ${Object.keys(manifest).length} existing entries`);
} else {
  console.log('No manifest found — will generate all audio files');
}

// ── Fetch all flashcards from Supabase ────────────────────────
async function fetchCards() {
  const fetch = (await import('node-fetch')).default;
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/flashcards?select=*&order=stack_index.asc,card_index.asc`,
    {
      headers: {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': `Bearer ${SUPABASE_SERVICE_KEY}`
      }
    }
  );
  if (!res.ok) {
    throw new Error(`Supabase fetch failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

// ── Generate MP3 for a single card ───────────────────────────
async function generateMP3(card) {
  const fetch = (await import('node-fetch')).default;
  const filename = `${card.topic}_${card.stack_index}_${card.card_index}.mp3`;
  const filepath = path.join(AUDIO_DIR, filename);

  console.log(`Generating: ${filename} (${card.gu})`);

  const res = await fetch(TTS_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: card.gu })
  });

  if (!res.ok) {
    throw new Error(`TTS request failed for ${card.gu}: ${res.status} ${await res.text()}`);
  }

const data = await res.json();

    // Retry up to 3 times if no audio returned
    if (!data.audios || !data.audios[0]) {
      let retryData = data;
      for (let attempt = 1; attempt <= 3; attempt++) {
        console.log(`  Retrying ${card.gu} (attempt ${attempt}/3)...`);
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        const retryRes = await fetch(TTS_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: card.gu })
        });
        retryData = await retryRes.json();
        if (retryData.audios && retryData.audios[0]) break;
      }
      if (!retryData.audios || !retryData.audios[0]) {
        throw new Error(`No audio returned for ${card.gu} after 3 retries`);
      }
      const buffer = Buffer.from(retryData.audios[0], 'base64');
      fs.writeFileSync(filepath, buffer);
      console.log(`  ✓ Saved ${filename} on retry (${buffer.length} bytes)`);
      return filename;
    }

  // Decode base64 and save as MP3
  const buffer = Buffer.from(data.audios[0], 'base64');
  fs.writeFileSync(filepath, buffer);
  console.log(`  ✓ Saved ${filename} (${buffer.length} bytes)`);

  return filename;
}

// ── Main ──────────────────────────────────────────────────────
async function main() {
  console.log('═══ Babu Audio Generator ═══');

  // Fetch all cards
  console.log('\nFetching flashcards from Supabase...');
  const cards = await fetchCards();
  console.log(`Found ${cards.length} cards`);

  // Find cards that need audio generated
  const toGenerate = cards.filter(card => {
    const key = `${card.topic}_${card.stack_index}_${card.card_index}`;
    const existing = manifest[key];
    // Generate if: no manifest entry, or Gujarati script has changed
    return !existing || existing.gu !== card.gu;
  });

  console.log(`\n${toGenerate.length} cards need audio generation`);

  if (toGenerate.length === 0) {
    console.log('Nothing to generate — all audio is up to date.');
    return;
  }

  // Generate audio for each card that needs it
  let successCount = 0;
  let errorCount   = 0;

  for (const card of toGenerate) {
    try {
      await generateMP3(card);
      // Update manifest
      const key = `${card.topic}_${card.stack_index}_${card.card_index}`;
      manifest[key] = { gu: card.gu, en: card.en, generated: new Date().toISOString() };
      successCount++;
      // Small delay between API calls to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, 300));
    } catch (err) {
      console.error(`  ✗ Failed: ${err.message}`);
      errorCount++;
    }
  }

  // Save updated manifest
  fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2));
  console.log(`\nManifest updated with ${Object.keys(manifest).length} total entries`);

  // Summary
  console.log('\n═══ Summary ═══');
  console.log(`✓ Generated: ${successCount} files`);
  if (errorCount > 0) {
    console.log(`✗ Failed:    ${errorCount} files`);
    process.exit(1); // Fail the GitHub Action if any errors
  }
  console.log('Done.');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});