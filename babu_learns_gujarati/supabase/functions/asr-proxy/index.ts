// ══════════════════════════════════════════════════════════════
// asr-proxy — Babu Learns Gujarati
// ══════════════════════════════════════════════════════════════
// PURPOSE:
//   Receives a child's recorded audio blob from the frontend,
//   returns a romanized transcript for phoneme comparison.
//
// TOPIC-BASED ROUTING:
//   The frontend passes a "topic" field in the form data.
//   numbers topic → verbatim ASR + Sarvam Transliterate (2 calls)
//   all other topics → translit ASR (1 call)
//
//   Why different modes?
//   - translit normalises numbers to numerals before romanizing,
//     so "પંદર" (fifteen) becomes "15" instead of "pandar".
//   - verbatim preserves spoken words as Gujarati script ("પંદર"),
//     then Transliterate API converts to Roman ("pandar").
//   - All non-number topics work correctly with translit in 1 call.
//
// REQUEST:
//   POST multipart/form-data
//   Fields: "audio" — audio blob (webm/opus from MediaRecorder)
//           "topic" — flashcard topic e.g. "numbers", "fruits"
//
// RESPONSE:
//   { transcript: string }   — romanized e.g. "pandar"
//   { error: string }        — on failure
//
// ENVIRONMENT VARIABLES REQUIRED (set in Supabase dashboard):
//   SARVAM_API_KEY — Sarvam API subscription key
// ══════════════════════════════════════════════════════════════

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const SARVAM_ASR_URL           = "https://api.sarvam.ai/speech-to-text";
const SARVAM_TRANSLITERATE_URL = "https://api.sarvam.ai/transliterate";
const CORS_HEADERS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

serve(async (req: Request) => {
  // ── CORS preflight ───────────────────────────────────────────
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed" }),
      { status: 405, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  // ── Read API key ─────────────────────────────────────────────
  const apiKey = Deno.env.get("SARVAM_API_KEY");
  if (!apiKey) {
    console.error("SARVAM_API_KEY not set");
    return new Response(
      JSON.stringify({ error: "Server configuration error" }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  // ── Parse incoming form data ─────────────────────────────────
  let audioBlob: Blob;
  let topic: string;
  try {
    const formData = await req.formData();
    const audioField = formData.get("audio");

    if (!audioField || !(audioField instanceof File)) {
      return new Response(
        JSON.stringify({ error: "Missing audio field in form data" }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }
    audioBlob = audioField;
    topic = (formData.get("topic") as string ?? "").toLowerCase().trim();
  } catch (err) {
    console.error("Failed to parse form data:", err);
    return new Response(
      JSON.stringify({ error: "Invalid request body" }),
      { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  // ── Validate audio size (Supabase Edge Function limit: 2MB) ──
  const MAX_BYTES = 2 * 1024 * 1024;
  if (audioBlob.size > MAX_BYTES) {
    return new Response(
      JSON.stringify({ error: "Audio too large — keep recordings under 6 seconds" }),
      { status: 413, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  // ── Route by topic ───────────────────────────────────────────
  const isNumbers = topic === "numbers";
  console.log(`Topic: "${topic}" → mode: ${isNumbers ? "verbatim + transliterate" : "translit"}`);

  try {
    if (isNumbers) {
      // ── NUMBERS PATH: verbatim ASR → Transliterate API ────────
      // verbatim returns Gujarati script without number normalisation
      // e.g. child says "પંદર" → ASR returns "પંદર" (not "15")
      // Transliterate then converts "પંદર" → "pandar"

      const sarvamForm = new FormData();
      sarvamForm.append("file", audioBlob, "recording.webm");
      sarvamForm.append("model", "saaras:v3");
      sarvamForm.append("language_code", "gu-IN");
      sarvamForm.append("mode", "verbatim");

      const asrRes = await fetch(SARVAM_ASR_URL, {
        method: "POST",
        headers: { "api-subscription-key": apiKey },
        body: sarvamForm,
      });

      if (!asrRes.ok) {
        const errText = await asrRes.text();
        console.error(`ASR (verbatim) error ${asrRes.status}:`, errText);
        return new Response(
          JSON.stringify({ error: "Speech recognition failed — please try again" }),
          { status: 502, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      const asrData = await asrRes.json();
      const gujaratiScript: string = (asrData.transcript ?? "").trim();
      console.log(`ASR verbatim: "${gujaratiScript}"`);

      if (!gujaratiScript) {
        return new Response(
          JSON.stringify({ error: "No speech detected — try again" }),
          { status: 422, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      // Transliterate Gujarati script → Roman
      const translitRes = await fetch(SARVAM_TRANSLITERATE_URL, {
        method: "POST",
        headers: {
          "api-subscription-key": apiKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          input:                gujaratiScript,
          source_language_code: "gu-IN",
          target_language_code: "en-IN",
        }),
      });

      if (!translitRes.ok) {
        const errText = await translitRes.text();
        console.error(`Transliterate error ${translitRes.status}:`, errText);
        return new Response(
          JSON.stringify({ error: "Transliteration failed — please try again" }),
          { status: 502, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      const translitData = await translitRes.json();
      const transcript: string = (translitData.transliterated_text ?? "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z\s]/g, "");

      console.log(`Transliterated: "${transcript}"`);

      if (!transcript) {
        return new Response(
          JSON.stringify({ error: "Could not romanize speech — try again" }),
          { status: 422, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      return new Response(
        JSON.stringify({ transcript }),
        { status: 200, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );

    } else {
      // ── ALL OTHER TOPICS: translit ASR (single call) ──────────
      // translit returns romanized output directly
      // e.g. child says "ખુશ" → transcript: "khush"

      const sarvamForm = new FormData();
      sarvamForm.append("file", audioBlob, "recording.webm");
      sarvamForm.append("model", "saaras:v3");
      sarvamForm.append("language_code", "gu-IN");
      sarvamForm.append("mode", "translit");

      const asrRes = await fetch(SARVAM_ASR_URL, {
        method: "POST",
        headers: { "api-subscription-key": apiKey },
        body: sarvamForm,
      });

      if (!asrRes.ok) {
        const errText = await asrRes.text();
        console.error(`ASR (translit) error ${asrRes.status}:`, errText);
        return new Response(
          JSON.stringify({ error: "Speech recognition failed — please try again" }),
          { status: 502, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      const asrData = await asrRes.json();
      const transcript: string = (asrData.transcript ?? "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z\s]/g, "");

      console.log(`ASR translit: "${transcript}"`);

      if (!transcript) {
        return new Response(
          JSON.stringify({ error: "No speech detected — try again" }),
          { status: 422, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }

      return new Response(
        JSON.stringify({ transcript }),
        { status: 200, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }

  } catch (err) {
    console.error("Unexpected error in asr-proxy:", err);
    return new Response(
      JSON.stringify({ error: "Unexpected error — please try again" }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }
});
