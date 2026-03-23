// ══════════════════════════════════════════════════════════════
// eval_asr_proxy.js — Babu Learns Gujarati
// ══════════════════════════════════════════════════════════════
// PURPOSE:
//   Closed-loop eval for asr-proxy.
//   For each test word:
//     1. Call tts-proxy to generate audio (same as production)
//     2. Feed that audio into asr-proxy
//     3. Compare returned transcript against expected `tr` value
//     4. Report pass/fail and flag any mismatches
//
//   If TTS and ASR are internally consistent, the romanized
//   transcript should match the `tr` column exactly (or close
//   enough for syllable-level comparison).
//
// RUN:
//   export SUPABASE_URL="https://iulwgadxcojjmbggvfrj.supabase.co"
//   node eval_asr_proxy.js
//
// ENVIRONMENT VARIABLES REQUIRED:
//   SUPABASE_URL — Supabase project URL
// ══════════════════════════════════════════════════════════════

const fs   = require('fs');
const path = require('path');

const SUPABASE_URL  = process.env.SUPABASE_URL;
const TTS_ENDPOINT  = `${SUPABASE_URL}/functions/v1/tts-proxy`;
const ASR_ENDPOINT  = `${SUPABASE_URL}/functions/v1/asr-proxy`;

if (!SUPABASE_URL) {
  console.error('Missing SUPABASE_URL environment variable.');
  process.exit(1);
}

// ── Test words ────────────────────────────────────────────────
// Sampled across topics and difficulty levels.
// `tr` is the expected romanized output from ASR.
// Mix of short (એક), medium (હાથી), and longer (સ્ટ્રોબેરી) words.
const TEST_WORDS = [
  // family
  { gu: 'મમ્મી',      tr: 'mammi',      en: 'Mama',       topic: 'family'    },
  { gu: 'દાદા',       tr: 'daada',      en: 'Dada',       topic: 'family'    },
  // bodyparts
  { gu: 'હાથ',        tr: 'haath',      en: 'Hand',       topic: 'bodyparts' },
  { gu: 'આંખ',        tr: 'aankh',      en: 'Eye',        topic: 'bodyparts' },
  // emotions
  { gu: 'ખુશ',        tr: 'khush',      en: 'Happy',      topic: 'emotions'  },
  { gu: 'ઉદાસ',       tr: 'udaas',      en: 'Sad',        topic: 'emotions'  },
  // fruits
  { gu: 'સફરજન',      tr: 'safarjan',   en: 'Apple',      topic: 'fruits'    },
  { gu: 'નારંગી',     tr: 'narangi',    en: 'Orange',     topic: 'fruits'    },
  { gu: 'સ્ટ્રોબેરી', tr: 'strawberry', en: 'Strawberry', topic: 'fruits'    },
  // colors
  { gu: 'લાલ',        tr: 'laal',       en: 'Red',        topic: 'colors'    },
  { gu: 'ભૂરો',       tr: 'bhooro',     en: 'Blue',       topic: 'colors'    },
  // numbers — routed to verbatim mode in asr-proxy
  { gu: 'એક',         tr: 'ek',         en: 'One',        topic: 'numbers'   },
  { gu: 'પાંચ',       tr: 'paanch',     en: 'Five',       topic: 'numbers'   },
  { gu: 'દસ',         tr: 'das',        en: 'Ten',        topic: 'numbers'   },
  { gu: 'પંદર',       tr: 'pandar',     en: 'Fifteen',    topic: 'numbers'   },
];

// ── Helpers ───────────────────────────────────────────────────

// Normalise both strings the same way before comparing:
// lowercase, collapse whitespace, strip punctuation.
function normalise(str) {
  return str.toLowerCase().trim().replace(/[^a-z0-9\s]/g, '').replace(/\s+/g, ' ');
}

// Levenshtein edit distance — counts minimum single-character edits
// (insert, delete, substitute) to turn string a into string b.
function levenshtein(a, b) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) =>
    Array.from({ length: b.length + 1 }, (_, j) => i === 0 ? j : j === 0 ? i : 0)
  );
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1]
        : 1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
  return dp[a.length][b.length];
}

// Character-level similarity: 1 - (edit distance / max length).
// Much better than token matching for single Gujarati words —
// laal vs lal = 75% rather than 0%, giving meaningful amber feedback.
function similarity(expected, got) {
  const a = normalise(expected);
  const b = normalise(got);
  const maxLen = Math.max(a.length, b.length);
  if (maxLen === 0) return 1;
  return 1 - levenshtein(a, b) / maxLen;
}

// ── Step 1: TTS → audio buffer ────────────────────────────────
async function generateAudio(word) {
  const fetch = (await import('node-fetch')).default;

  const res = await fetch(TTS_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: word.gu }),
  });

  if (!res.ok) {
    throw new Error(`TTS failed for "${word.gu}": ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  if (!data.audios || !data.audios[0]) {
    throw new Error(`TTS returned no audio for "${word.gu}"`);
  }

  return Buffer.from(data.audios[0], 'base64');
}

// ── Step 2: audio buffer → ASR transcript ─────────────────────
async function transcribe(audioBuffer, word) {
  const fetch    = (await import('node-fetch')).default;
  const FormData = (await import('form-data')).default;

  const form = new FormData();
  // Send as mp3 — matches what tts-proxy returns
  form.append('audio', audioBuffer, {
    filename:    'recording.mp3',
    contentType: 'audio/mpeg',
  });
  // Pass topic so asr-proxy can route numbers to verbatim mode
  form.append('topic', word.topic);

  const res = await fetch(ASR_ENDPOINT, {
    method:  'POST',
    headers: form.getHeaders(),
    body:    form,
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`ASR failed for "${word.gu}": ${res.status} ${errText}`);
  }

  const data = await res.json();
  if (data.error) {
    throw new Error(`ASR error for "${word.gu}": ${data.error}`);
  }
  return data.transcript;
}

// ── Main ──────────────────────────────────────────────────────
async function main() {
  console.log('═══ asr-proxy Closed-Loop Eval ═══');
  console.log(`TTS endpoint: ${TTS_ENDPOINT}`);
  console.log(`ASR endpoint: ${ASR_ENDPOINT}`);
  console.log(`Testing ${TEST_WORDS.length} words...\n`);

  const results = [];

  for (const word of TEST_WORDS) {
    process.stdout.write(`  ${word.en.padEnd(14)} (${word.gu}) ... `);

    try {
      // Step 1: generate reference audio via TTS
      const audioBuffer = await generateAudio(word);

      // Step 2: feed audio into ASR
      const transcript = await transcribe(audioBuffer, word);

      // Step 3: compare
      const sim    = similarity(word.tr, transcript);
      const passed = sim >= 0.8; // 80% character similarity (Levenshtein) = pass

      const status = passed ? '✓ PASS' : '✗ FAIL';
      console.log(`${status}  expected="${word.tr}"  got="${transcript}"  similarity=${(sim * 100).toFixed(0)}%`);

      results.push({ word, transcript, sim, passed, error: null });

    } catch (err) {
      console.log(`✗ ERROR  ${err.message}`);
      results.push({ word, transcript: null, sim: 0, passed: false, error: err.message });
    }

    // Small delay to avoid rate limiting
    await new Promise(r => setTimeout(r, 500));
  }

  // ── Summary ────────────────────────────────────────────────
  const passed  = results.filter(r => r.passed).length;
  const failed  = results.filter(r => !r.passed && !r.error).length;
  const errored = results.filter(r => r.error).length;

  console.log('\n═══ Results ═══');
  console.log(`✓ Passed:  ${passed} / ${TEST_WORDS.length}`);
  if (failed  > 0) console.log(`✗ Failed:  ${failed}`);
  if (errored > 0) console.log(`⚠ Errored: ${errored}`);

  // ── Flag mismatches for review ─────────────────────────────
  const mismatches = results.filter(r => !r.passed);
  if (mismatches.length > 0) {
    console.log('\n═══ Mismatches to review ═══');
    mismatches.forEach(r => {
      if (r.error) {
        console.log(`  ${r.word.en}: ERROR — ${r.error}`);
      } else {
        console.log(`  ${r.word.en}: expected="${r.word.tr}"  got="${r.transcript}"  sim=${(r.sim * 100).toFixed(0)}%`);
        console.log(`    → Consider updating tr column to "${r.transcript}" if ASR output is more accurate`);
      }
    });
  }

  // ── Write results to file for record ──────────────────────
  const outPath = path.join(__dirname, 'eval_results.json');
  fs.writeFileSync(outPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    passed, failed, errored,
    results: results.map(r => ({
      en:         r.word.en,
      gu:         r.word.gu,
      expected:   r.word.tr,
      got:        r.transcript,
      similarity: r.sim,
      passed:     r.passed,
      error:      r.error,
    }))
  }, null, 2));
  console.log(`\nFull results written to eval_results.json`);

  if (passed < TEST_WORDS.length) process.exit(1);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
