# Pronunciation Checker — Manual Test Checklist
**Feature:** Mic button on flashcard screen  
**Version:** V2.3  
**Tester:** ___________________  
**Device:** ___________________  
**OS / Browser:** ___________________  
**Date:** ___________________  

---

## Before You Start

- [ ] App is loaded and content is visible on home screen
- [ ] You are in a **quiet room** for baseline tests
- [ ] You have a second noisy environment available (or can play background noise from another device) for noise tests
- [ ] Mic permission has **not** been granted yet for fresh permission test (or clear site permissions in browser settings)

---

## 1. Visual — Mic Button Layout

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 1.1 | Open any topic → select a stack → reach flashcard screen | Mic 🎤 button appears **between** 🔄 and ✓ in the bottom row | | |
| 1.2 | Mic button at rest | Button is **white** (idle state) | | |
| 1.3 | Waveform bars visible above mic button | 8 small grey bars visible at rest | | |
| 1.4 | Advance to next card via swipe or ✓ | Mic resets to **white** on new card | | |
| 1.5 | Navigate back to stacks and re-enter a stack | Mic is **white** on first card | | |

---

## 2. Microphone Permission

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 2.1 | Tap mic for the first time | Browser shows **microphone permission prompt** | | |
| 2.2 | Deny microphone permission | Button returns to white, toast shows "Microphone not available" | | |
| 2.3 | Grant microphone permission and tap mic again | Recording starts normally | | |

---

## 3. Recording State

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 3.1 | Tap mic (permission granted) | Button turns **amber/yellow** immediately | | |
| 3.2 | While recording — observe waveform | Bars **animate** up and down in response to your voice | | |
| 3.3 | While recording — tap mic again to stop early | Button turns **blue** (processing) | | |
| 3.4 | Hold recording for 6+ seconds without tapping | Recording **auto-stops** at 6 seconds, button turns blue | | |
| 3.5 | Speak clearly for ~2 seconds then stop | Button turns blue then a result color within ~1 second | | |

---

## 4. Result Colors

Run each test by saying the word on the current flashcard. Use words from different topics.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 4.1 | Say the word **clearly and correctly** | Button turns **green** | | |
| 4.2 | Say a **similar but wrong** word (e.g. say "narangi" for apple) | Button turns **amber or red** | | |
| 4.3 | Say something **completely unrelated** in English | Button turns **red** | | |
| 4.4 | Say nothing / whisper inaudibly | Button returns to **white** (idle) — no result shown | | |
| 4.5 | Test with a **numbers topic** word (e.g. પંદર / pandar) | Result color appears correctly — numbers routed via verbatim mode | | |

---

## 5. Green State Behaviour

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 5.1 | After green result — observe button | Button **stays green** — does not auto-advance | | |
| 5.2 | After green — tap mic again | Button returns to **white** (idle), ready to record again | | |
| 5.3 | After green — swipe card right (✓ / got it) | Card advances normally, mic on new card is **white** | | |
| 5.4 | After green — tap 🔄 (again) | Card goes to review pile, mic on next card is **white** | | |

---

## 6. Amber / Red State Behaviour

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 6.1 | After amber/red result — observe button | Button **stays amber/red** | | |
| 6.2 | After amber/red — tap mic again | Button returns to **white**, child can retry | | |
| 6.3 | After amber/red — tap the flashcard (plays word audio) | Word audio plays, mic stays amber/red | | |
| 6.4 | After amber/red — swipe to advance | Card advances, mic on next card is **white** | | |

---

## 7. Noise Detection

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 7.1 | In a quiet room — tap mic and say the word clearly | No noise warning shown | | |
| 7.2 | Play loud background noise (music/TV) — tap mic without speaking | **Amber noise warning strip** appears below card: "🔇 Too noisy — find a quieter spot and try again" | | |
| 7.3 | After noise warning — tap mic again in quiet environment | Warning disappears, recording starts normally | | |
| 7.4 | Noise warning appears — swipe card to advance | Warning disappears on new card | | |

---

## 8. Audio Overlap Prevention

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 8.1 | Tap the flashcard to play word audio → immediately tap mic | Word audio **stops**, recording starts | | |
| 8.2 | Tap mic → while processing (blue) → tap flashcard | Nothing happens / audio does **not** start during processing | | |
| 8.3 | Result shown (green/amber/red) → tap flashcard | Word audio plays normally | | |

---

## 9. iOS Safari Specific

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 9.1 | Open app fresh on iOS Safari — tap a topic card first | Audio context unlocks correctly (no silent failure) | | |
| 9.2 | Tap mic on iOS Safari | Recording starts, amber state shows | | |
| 9.3 | Result appears on iOS Safari | Color shows correctly | | |
| 9.4 | Waveform animates on iOS Safari during recording | Bars move in response to voice | | |

---

## 10. Edge Cases

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 10.1 | Navigate away mid-recording (tap back button) | Recording stops cleanly, no mic stream left open | | |
| 10.2 | Rapidly tap mic multiple times | Only one recording session starts, no crashes | | |
| 10.3 | Test on a word with a long `tr` value (e.g. strawberry / સ્ટ્રોબેરી) | Scoring works, result color appears | | |
| 10.4 | Test on a short word (e.g. એક / ek) | Scoring works, result color appears | | |
| 10.5 | No internet connection — tap mic and speak | Button returns to **white** silently (ASR fails gracefully, no crash, no error shown to child) | | |

---

## Known Limitations (Do Not File as Bugs)

- **Mama (મમ્મી)**: ASR returns "mummy" — both are correct pronunciations. Result may show amber even for a correct attempt.
- **Apple (સફરજન)**: Sarvam occasionally interprets this word semantically. Result may be inconsistent.
- **Very short words (એક)**: TTS-generated audio triggers a 422 from ASR. Real child speech is longer and works correctly.
- **SNR threshold**: May need tuning based on real-world environments. Current threshold is empirical.

---

## Summary

| Category | Total Tests | Passed | Failed | Notes |
|---|---|---|---|---|
| Visual | 5 | | | |
| Permission | 3 | | | |
| Recording | 5 | | | |
| Result Colors | 5 | | | |
| Green State | 4 | | | |
| Amber/Red State | 4 | | | |
| Noise Detection | 4 | | | |
| Audio Overlap | 3 | | | |
| iOS Safari | 4 | | | |
| Edge Cases | 5 | | | |
| **Total** | **42** | | | |

---

## Sign-off

- [ ] All P0 tests passing (sections 1, 3, 4, 5, 6)
- [ ] iOS Safari tested
- [ ] No console errors during normal use
- [ ] Ready to commit

**Tester sign-off:** ___________________  
**Date:** ___________________
