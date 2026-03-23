# Pronunciation Feedback System — Manual Test Checklist
**Feature:** Auto-stop silence detection + Star-based feedback with Babu reactions  
**Version:** V2.3+  
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
- [ ] Clear localStorage if testing from a fresh state: `localStorage.clear()` in browser console

---

## 1. Home Screen — Toggle Visibility

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 1.1 | Load home screen fresh | Two toggle rows visible: "Show Gujarati script" and "Show detailed feedback" | | |
| 1.2 | Check default toggle states | Both toggles are **OFF** by default (unchecked) | | |
| 1.3 | Toggle "Show Gujarati script" ON | Toggle moves to right, turns green | | |
| 1.4 | Toggle "Show detailed feedback" ON | Toggle moves to right, turns green | | |
| 1.5 | Refresh page after toggling both ON | Both toggles remain **ON** (state persisted in localStorage) | | |
| 1.6 | Toggle both OFF and refresh | Both toggles remain **OFF** | | |

---

## 2. Silence Detection — Auto-Stop Behavior

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 2.1 | Tap mic and say word clearly, then stop speaking | After ~1.5 seconds of silence, mic button **auto-turns blue** (processing) | | |
| 2.2 | Tap mic, say first half of word, pause 2 seconds, finish word | Mic stops **after pause** (not ideal, but expected with 1.5s threshold) | | |
| 2.3 | Tap mic, speak continuously for 4 seconds without pausing | Recording continues (no premature stop) | | |
| 2.4 | Tap mic, speak for 7+ seconds continuously | Recording **hard-stops at 6 seconds**, processes immediately | | |
| 2.5 | Tap mic in completely silent room, don't speak | After 6 seconds, mic stops and returns to **white** (no feedback shown, SNR check fails) | | |
| 2.6 | Tap mic, whisper very quietly (below volume threshold) | After 1.5-6 seconds, mic stops and shows **noise warning** or returns to idle | | |

---

## 3. Feedback Display — Base Elements (Always Shown)

Run these tests with "Show detailed feedback" **OFF**. Say words clearly to test each feedback tier.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 3.1 | Say word **perfectly** (e.g. "mammi" for મમ્મી) | Feedback appears: Babu **jumps**, ⭐⭐⭐⭐⭐ (5 stars), "જબરદસ્ત! Perfect!", **chime** plays | | |
| 3.2 | Say word with minor error (e.g. "pandir" for "pandar") | Feedback: Babu **jumps**, ⭐⭐⭐⭐⭐ (5 stars), "જબરદસ્ત! Almost perfect!", **chime** plays | | |
| 3.3 | Say word with moderate error (e.g. "hath" for "haath") | Feedback: Babu **nods**, ⭐⭐⭐☆☆ (3 stars), "સારું! Good job!", **beep** plays | | |
| 3.4 | Say completely wrong word (e.g. "apple" for "safarjan") | Feedback: Babu **scratches head**, ⭐☆☆☆☆ (1 star), "ફરી કરો Try again!", **boop** plays | | |
| 3.5 | Observe feedback persistence | Feedback **stays visible** until user taps mic again | | |
| 3.6 | After feedback shown, tap mic again | Feedback **clears**, mic resets to white (idle), ready to record again | | |

---

## 4. Babu Animations

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 4.1 | Get 5-star feedback (perfect/almost perfect) | Babu emoji **jumps** (moves up, rotates, comes back down) | | |
| 4.2 | Animation completes | After ~0.5s, Babu returns to **idle state** (not stuck mid-animation) | | |
| 4.3 | Get 3-star feedback (good) | Babu emoji **nods** (gentle bob up and down) | | |
| 4.4 | Get 1-star feedback (try again) | Babu emoji **scratches head** (tilts side to side, thinking motion) | | |
| 4.5 | Rapidly trigger multiple feedbacks | Only one animation plays at a time (no stacking/glitching) | | |

---

## 5. Sound Feedback

Test with device volume **UP** (not muted). Use headphones if testing in public.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 5.1 | Get 5-star feedback | **Two ascending tones** play (chime: C5 → E5, sounds cheerful) | | |
| 5.2 | Get 3-star feedback | **Single neutral beep** plays (A4 note, ~0.18s duration) | | |
| 5.3 | Get 1-star feedback | **Gentle boop** plays (G3 note, low tone but not harsh) | | |
| 5.4 | Test with device muted | No sound plays, but feedback UI still appears correctly | | |
| 5.5 | Rapidly trigger feedbacks | Each sound plays fully (no cutoff/overlap issues) | | |

---

## 6. Phoneme Feedback Toggle — OFF State

Ensure "Show detailed feedback" toggle is **OFF**.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 6.1 | Get any feedback (1/3/5 stars) | Phoneme comparison section is **NOT visible** | | |
| 6.2 | Check feedback elements present | Only see: Babu animation, stars, Gujarati message, English message | | |
| 6.3 | Verify no "Expected:" or "You said:" text | Phoneme details completely hidden | | |

---

## 7. Phoneme Feedback Toggle — ON State

Turn "Show detailed feedback" toggle **ON**. Return to flashcard screen.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 7.1 | Say word with minor error (e.g. "pandir" for "pandar") | Phoneme section appears below feedback with:<br>• Expected: pan**d**a**r**<br>• You said: pan**d**i**r**<br>• Differences highlighted in red<br>• Tip: "Focus on the 'a' sound" | | |
| 7.2 | Say word perfectly | Phoneme section still appears:<br>• Expected: mammi<br>• You said: mammi<br>• All characters in green (matched)<br>• Tip: "Great pronunciation!" | | |
| 7.3 | Say completely wrong word | Phoneme section shows major differences, many red characters | | |
| 7.4 | Test with short word (e.g. "ek") | Phoneme highlighting works correctly (no overflow/truncation) | | |
| 7.5 | Test with long word (e.g. "strawberry") | Phoneme section wraps/scrolls correctly, readable | | |
| 7.6 | Turn toggle OFF mid-session | Return to flashcard, get feedback → phoneme section **disappears** | | |
| 7.7 | Turn toggle back ON | Get feedback → phoneme section **reappears** | | |

---

## 8. Phoneme Tip Accuracy

With "Show detailed feedback" ON, test specific phoneme patterns.

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 8.1 | Say "kush" for "khush" (missing 'h') | Tip mentions "kh" sound: "Make a breathy 'k' sound" | | |
| 8.2 | Say "pandir" for "pandar" ('i' vs 'a') | Tip mentions "a" sound: "Try 'a' like in 'arm'" | | |
| 8.3 | Say "mami" for "mammi" (missing 'm') | Tip gives character-specific guidance or generic "Focus on..." | | |
| 8.4 | Say word perfectly | Tip shows: "Great pronunciation!" | | |

---

## 9. Feedback Persistence and Dismissal

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 9.1 | Get feedback, wait 10 seconds without touching screen | Feedback **stays visible** (no auto-dismiss) | | |
| 9.2 | Get feedback, tap mic button | Feedback **clears immediately**, mic resets to idle | | |
| 9.3 | Get feedback, swipe card right (✓ got it) | Card advances, feedback from previous card **does not carry over** | | |
| 9.4 | Get feedback, tap flashcard to play audio | Word audio plays, feedback **stays visible** | | |
| 9.5 | Get feedback, tap back button | Navigate to stacks screen, no console errors | | |

---

## 10. Integration with Existing Features

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 10.1 | Pronunciation check on "numbers" topic word | Feedback works correctly (numbers routed via verbatim ASR) | | |
| 10.2 | Test with Gujarati script toggle ON | Gujarati script appears on card, feedback system still works | | |
| 10.3 | Flag a card, then test pronunciation | Feedback works, flag state persists | | |
| 10.4 | Complete stack with multiple pronunciation checks | Quiz launches normally, no state corruption | | |
| 10.5 | Earn stars from quiz → check home screen | Star counter updates correctly (pronunciation checks don't award stars) | | |

---

## 11. Edge Cases — Silence Detection

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 11.1 | Tap mic, cough loudly, then stay silent | Silence timer resets after cough, then auto-stops after 1.5s | | |
| 11.2 | Tap mic in noisy environment (TV/music playing) | May not auto-stop due to ambient noise keeping volume above threshold (expected) | | |
| 11.3 | Tap mic, say half a word, sneeze, finish word | Mic stops during/after sneeze (noise breaks silence detection) | | |
| 11.4 | Tap mic, speak very softly but continuously | Should NOT auto-stop if volume stays above threshold | | |
| 11.5 | Tap mic on slow device/browser | Silence detection still works (no race conditions with processing) | | |

---

## 12. Cross-Browser / Device Testing

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 12.1 | iOS Safari — silence detection | Auto-stop works correctly | | |
| 12.2 | iOS Safari — sounds play | Chime/beep/boop audible (Web Audio API supported) | | |
| 12.3 | iOS Safari — Babu animations | Jump/nod/scratch animations render smoothly | | |
| 12.4 | iOS Safari — phoneme highlighting | Character diffs display correctly (no font issues) | | |
| 12.5 | Chrome Android — all features | Silence detection, sounds, animations, phoneme feedback work | | |
| 12.6 | Firefox desktop — all features | All features work (Web Audio API supported) | | |

---

## 13. Performance

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 13.1 | Trigger 10 pronunciation checks in a row | No memory leaks, page responsive | | |
| 13.2 | Check browser console during usage | No errors related to AudioContext, silence detection, or feedback rendering | | |
| 13.3 | Test on low-end device (old phone/tablet) | Feedback renders within 1-2 seconds of ASR response | | |
| 13.4 | Toggle phoneme feedback ON/OFF rapidly | No UI glitches, toggle responds smoothly | | |

---

## 14. Accessibility

| # | Test | Expected | Pass / Fail | Notes |
|---|---|---|---|---|
| 14.1 | Phoneme text readability | Character diffs are clearly visible (sufficient color contrast) | | |
| 14.2 | Feedback messages in Gujarati script | Gujarati text renders correctly (no missing glyphs) | | |
| 14.3 | Star rating clarity | 5 stars vs 3 stars vs 1 star easily distinguishable | | |
| 14.4 | Sound-only mode (visual feedback off) | If user looks away, sounds alone clearly indicate success tier | | |

---

## Summary

| Category | Total Tests | Passed | Failed | Notes |
|---|---|---|---|---|
| Home Screen Toggles | 6 | | | |
| Silence Detection | 6 | | | |
| Feedback Display | 6 | | | |
| Babu Animations | 5 | | | |
| Sound Feedback | 5 | | | |
| Phoneme Toggle OFF | 3 | | | |
| Phoneme Toggle ON | 7 | | | |
| Phoneme Tip Accuracy | 4 | | | |
| Feedback Persistence | 5 | | | |
| Integration | 5 | | | |
| Silence Edge Cases | 5 | | | |
| Cross-Browser | 6 | | | |
| Performance | 4 | | | |
| Accessibility | 4 | | | |
| **Total** | **71** | | | |

---

## Known Limitations (Do Not File as Bugs)

- **Silence detection with pauses**: If a child pauses mid-word for >1.5s, recording may stop prematurely. This is a tradeoff for natural auto-stop UX. Consider increasing `SILENCE_DURATION` to 2000ms if this is common.
- **Very quiet speakers**: Children speaking very softly may trigger silence detection even while speaking. Consider lowering `SILENCE_THRESHOLD` from 30 to 20 if this occurs.
- **Background noise**: Continuous ambient noise (TV, music) may prevent auto-stop. This is expected; users should be guided to quiet environments.
- **Phoneme tips for uncommon patterns**: Tips default to generic "Focus on..." for rare phoneme combinations not in the lookup table.

---

## Calibration Notes

If silence detection is too aggressive or too lenient, adjust these constants in `index.html`:

```javascript
const SILENCE_THRESHOLD = 30;   // Volume level (0-255): lower = more sensitive
const SILENCE_DURATION = 1500;  // Milliseconds of silence before auto-stop
const MAX_RECORDING_TIME = 6000; // Hard stop (keep at 6s for API limits)
```

Test after any changes to ensure balance between auto-stop convenience and avoiding false triggers.

---

## Sign-off

- [ ] All P0 tests passing (sections 2, 3, 4, 5)
- [ ] Phoneme toggle functionality verified (sections 6, 7)
- [ ] Silence detection tested across quiet/noisy environments
- [ ] iOS Safari tested
- [ ] No console errors during normal use
- [ ] Ready to commit

**Tester sign-off:** ___________________  
**Date:** ___________________
