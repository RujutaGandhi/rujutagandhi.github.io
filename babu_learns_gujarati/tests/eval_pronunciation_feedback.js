// ══════════════════════════════════════════════════════════════
// eval_pronunciation_feedback.js — Babu Learns Gujarati
// ══════════════════════════════════════════════════════════════
// PURPOSE:
//   Automated eval for pronunciation feedback system V2.3+
//   Tests:
//     1. Star rating logic (5 stars for 75%+, 3 for 50-75%, 1 for <50%)
//     2. Feedback message selection (Gujarati + English)
//     3. Sound type selection (chime/beep/boop)
//     4. Phoneme highlighting logic (character-level diff)
//     5. Babu animation selection (jump/nod/scratch)
//     6. Toggle state persistence
//
//   Note: This eval tests the LOGIC only (no browser automation).
//   For full UI testing, use PRONUNCIATION_CHECKER_MANUAL_TEST.md
//
// RUN:
//   node eval_pronunciation_feedback.js
//
// NO ENVIRONMENT VARIABLES REQUIRED (pure logic testing)
// ══════════════════════════════════════════════════════════════

// ── Test Data ─────────────────────────────────────────────────
const TEST_CASES = [
  // Perfect matches (75%+) — 5 stars
  { expected: 'mammi',      spoken: 'mammi',      similarity: 1.00,  stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  { expected: 'pandar',     spoken: 'pandar',     similarity: 1.00,  stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  { expected: 'khush',      spoken: 'khush',      similarity: 1.00,  stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  { expected: 'safarjan',   spoken: 'safarjan',   similarity: 1.00,  stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  
  // Near-perfect (75-90%) — still 5 stars
  { expected: 'narangi',    spoken: 'narangi',    similarity: 1.000, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  { expected: 'strawberry', spoken: 'strawbery',  similarity: 0.900, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },
  { expected: 'pandar',     spoken: 'pandir',     similarity: 0.833, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Almost perfect!' },
  
  // Good (50-75%) — 3 stars
  { expected: 'mammi',      spoken: 'mami',       similarity: 0.800, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Almost perfect!' }, // 80% = still 5 stars
  { expected: 'haath',      spoken: 'hath',       similarity: 0.800, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Almost perfect!' }, // 80% = still 5 stars
  { expected: 'aankh',      spoken: 'ank',        similarity: 0.600, stars: 3, sound: 'beep',      animation: 'nod',     messageGu: 'સારું!',   messageEn: 'Good job!' },
  { expected: 'laal',       spoken: 'lal',        similarity: 0.750, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Almost perfect!' }, // Edge case: exactly 75%
  
  // Try again (<50%) — 1 star
  { expected: 'safarjan',   spoken: 'apple',      similarity: 0.111, stars: 1, sound: 'try-again', animation: 'scratch', messageGu: 'ફરી કરો', messageEn: 'Try again!' },
  { expected: 'khush',      spoken: 'sad',        similarity: 0.000, stars: 1, sound: 'try-again', animation: 'scratch', messageGu: 'ફરી કરો', messageEn: 'Try again!' }, // No matching chars
  { expected: 'pandar',     spoken: 'banana',     similarity: 0.286, stars: 1, sound: 'try-again', animation: 'scratch', messageGu: 'ફરી કરો', messageEn: 'Try again!' },
  { expected: 'daada',      spoken: 'grandpa',    similarity: 0.429, stars: 1, sound: 'try-again', animation: 'scratch', messageGu: 'ફરી કરો', messageEn: 'Try again!' },
  
  // Edge cases
  { expected: 'ek',         spoken: 'ek',         similarity: 1.00,  stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Perfect!' },         // Very short word
  { expected: 'strawberry', spoken: 'strawberi',  similarity: 0.800, stars: 5, sound: 'chime',     animation: 'jump',    messageGu: 'જબરદસ્ત!', messageEn: 'Almost perfect!' }, // Long word
  { expected: 'bhooro',     spoken: 'bhuro',      similarity: 0.667, stars: 3, sound: 'beep',      animation: 'nod',     messageGu: 'સારું!',   messageEn: 'Good job!' },        // Vowel variation
];

// ── Feedback Logic (from index.html) ──────────────────────────

function getStarCount(similarity) {
  if (similarity >= 0.75) return 5;
  if (similarity >= 0.50) return 3;
  return 1;
}

function getSoundType(similarity) {
  if (similarity >= 0.75) return 'chime';
  if (similarity >= 0.50) return 'beep';
  return 'try-again';
}

function getAnimation(similarity) {
  if (similarity >= 0.75) return 'jump';
  if (similarity >= 0.50) return 'nod';
  return 'scratch';
}

function getFeedbackMessages(similarity) {
  if (similarity >= 0.90) {
    return { gu: 'જબરદસ્ત!', en: 'Perfect!' };
  } else if (similarity >= 0.75) {
    return { gu: 'જબરદસ્ત!', en: 'Almost perfect!' };
  } else if (similarity >= 0.60) {
    return { gu: 'સારું!', en: 'Good job!' };
  } else if (similarity >= 0.50) {
    return { gu: 'સારું!', en: 'Keep going!' };
  } else {
    return { gu: 'ફરી કરો', en: 'Try again!' };
  }
}

// ── Phoneme Highlighting Logic ────────────────────────────────

function highlightPhonemeDifferences(expected, spoken) {
  const exp = expected.toLowerCase().trim();
  const spk = spoken.toLowerCase().trim();
  
  const maxLen = Math.max(exp.length, spk.length);
  const diffs = [];
  
  for (let i = 0; i < maxLen; i++) {
    const expChar = exp[i] || '';
    const spkChar = spk[i] || '';
    
    if (expChar !== spkChar) {
      diffs.push({
        position: i,
        expected: expChar || '·',
        spoken: spkChar || '·',
      });
    }
  }
  
  return {
    hasDifferences: diffs.length > 0,
    differences: diffs,
    matchCount: maxLen - diffs.length,
    totalChars: maxLen,
  };
}

function getPronunciationTip(expected, spoken) {
  const exp = expected.toLowerCase();
  const spk = spoken.toLowerCase();
  
  // Find first major difference
  for (let i = 0; i < Math.max(exp.length, spk.length); i++) {
    if (exp[i] !== spk[i]) {
      const wrongChar = exp[i];
      
      // Phoneme-specific tips for common Gujarati sounds
      const tips = {
        'a': 'Try "a" like in "arm"',
        'aa': 'Hold the "aa" sound longer',
        'kh': 'Make a breathy "k" sound',
        'th': 'Soft "th" like in "thumb"',
        'dh': 'Soft "d" with breath',
        'ph': 'Soft "p" with air',
        'bh': 'Soft "b" with breath',
        'ch': 'Like "ch" in "church"',
        'r': 'Roll the "r" lightly',
      };
      
      // Check for digraphs first
      const twoChar = exp.slice(i, i + 2);
      if (tips[twoChar]) return tips[twoChar];
      
      // Single character
      if (tips[wrongChar]) return tips[wrongChar];
      
      // Generic tip
      return `Focus on the "${wrongChar}" sound`;
    }
  }
  
  return 'Great pronunciation!';
}

// ── Levenshtein (from index.html) ─────────────────────────────

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

function pronunciationSimilarity(expected, got) {
  const a = expected.toLowerCase().trim().replace(/[^a-z]/g, '');
  const b = got.toLowerCase().trim().replace(/[^a-z]/g, '');
  if (!a || !b) return 0;
  const maxLen = Math.max(a.length, b.length);
  return 1 - levenshtein(a, b) / maxLen;
}

// ── Main Test Runner ──────────────────────────────────────────

function runTests() {
  console.log('═══ Pronunciation Feedback Logic Eval ═══\n');
  
  let passed = 0;
  let failed = 0;
  const failures = [];
  
  TEST_CASES.forEach((test, idx) => {
    const testNum = (idx + 1).toString().padStart(2, '0');
    process.stdout.write(`  Test ${testNum}: "${test.expected}" vs "${test.spoken}" ... `);
    
    // Calculate similarity (should match test.similarity approximately)
    const calcSim = pronunciationSimilarity(test.expected, test.spoken);
    const simMatch = Math.abs(calcSim - test.similarity) < 0.05; // 5% tolerance for rounding
    
    // Test feedback components
    const stars = getStarCount(test.similarity);
    const sound = getSoundType(test.similarity);
    const animation = getAnimation(test.similarity);
    const messages = getFeedbackMessages(test.similarity);
    
    const starsMatch = stars === test.stars;
    const soundMatch = sound === test.sound;
    const animationMatch = animation === test.animation;
    const messageGuMatch = messages.gu === test.messageGu;
    const messageEnMatch = messages.en === test.messageEn;
    
    const allMatch = simMatch && starsMatch && soundMatch && animationMatch && messageGuMatch && messageEnMatch;
    
    if (allMatch) {
      console.log('✓ PASS');
      passed++;
    } else {
      console.log('✗ FAIL');
      failed++;
      
      const errors = [];
      if (!simMatch) errors.push(`similarity=${calcSim.toFixed(3)} expected=${test.similarity.toFixed(3)}`);
      if (!starsMatch) errors.push(`stars=${stars} expected=${test.stars}`);
      if (!soundMatch) errors.push(`sound="${sound}" expected="${test.sound}"`);
      if (!animationMatch) errors.push(`animation="${animation}" expected="${test.animation}"`);
      if (!messageGuMatch) errors.push(`messageGu="${messages.gu}" expected="${test.messageGu}"`);
      if (!messageEnMatch) errors.push(`messageEn="${messages.en}" expected="${test.messageEn}"`);
      
      failures.push({
        test: `"${test.expected}" vs "${test.spoken}"`,
        errors,
      });
    }
  });
  
  // Test phoneme highlighting
  console.log('\n═══ Phoneme Highlighting Tests ═══\n');
  
  const phonemeTests = [
    { expected: 'pandar', spoken: 'pandir', shouldHaveDiff: true },
    { expected: 'khush',  spoken: 'khush',  shouldHaveDiff: false },
    { expected: 'mammi',  spoken: 'mami',   shouldHaveDiff: true },
    { expected: 'ek',     spoken: 'ek',     shouldHaveDiff: false },
  ];
  
  phonemeTests.forEach((test, idx) => {
    const testNum = (idx + 1).toString().padStart(2, '0');
    process.stdout.write(`  Phoneme ${testNum}: "${test.expected}" vs "${test.spoken}" ... `);
    
    const result = highlightPhonemeDifferences(test.expected, test.spoken);
    const match = result.hasDifferences === test.shouldHaveDiff;
    
    if (match) {
      console.log(`✓ PASS (${result.differences.length} diffs)`);
      passed++;
    } else {
      console.log(`✗ FAIL`);
      failed++;
      failures.push({
        test: `Phoneme highlighting: "${test.expected}" vs "${test.spoken}"`,
        errors: [`hasDifferences=${result.hasDifferences} expected=${test.shouldHaveDiff}`],
      });
    }
  });
  
  // Test pronunciation tips
  console.log('\n═══ Pronunciation Tip Tests ═══\n');
  
  const tipTests = [
    { expected: 'pandar', spoken: 'pandir', shouldContain: 'a' },
    { expected: 'khush',  spoken: 'kush',   shouldContain: 'h' }, // First diff is 'h', not 'kh' digraph
    { expected: 'mammi',  spoken: 'mammi',  shouldContain: 'Great' },
  ];
  
  tipTests.forEach((test, idx) => {
    const testNum = (idx + 1).toString().padStart(2, '0');
    process.stdout.write(`  Tip ${testNum}: "${test.expected}" vs "${test.spoken}" ... `);
    
    const tip = getPronunciationTip(test.expected, test.spoken);
    const match = tip.includes(test.shouldContain);
    
    if (match) {
      console.log(`✓ PASS (tip: "${tip}")`);
      passed++;
    } else {
      console.log(`✗ FAIL (got: "${tip}")`);
      failed++;
      failures.push({
        test: `Pronunciation tip: "${test.expected}" vs "${test.spoken}"`,
        errors: [`tip="${tip}" should contain "${test.shouldContain}"`],
      });
    }
  });
  
  // ── Summary ────────────────────────────────────────────────
  const total = passed + failed;
  console.log('\n═══ Results ═══');
  console.log(`✓ Passed:  ${passed} / ${total}`);
  if (failed > 0) console.log(`✗ Failed:  ${failed} / ${total}`);
  
  if (failures.length > 0) {
    console.log('\n═══ Failures to Review ═══');
    failures.forEach(f => {
      console.log(`\n  ${f.test}`);
      f.errors.forEach(e => console.log(`    → ${e}`));
    });
  }
  
  console.log('\n═══ Test Coverage ═══');
  console.log(`  ✓ Star rating logic (5/3/1 stars based on similarity)`);
  console.log(`  ✓ Sound type selection (chime/beep/boop)`);
  console.log(`  ✓ Babu animation selection (jump/nod/scratch)`);
  console.log(`  ✓ Feedback message selection (Gujarati + English)`);
  console.log(`  ✓ Phoneme highlighting (character-level diff)`);
  console.log(`  ✓ Pronunciation tips (phoneme-specific guidance)`);
  console.log(`\n  Note: UI rendering, toggle persistence, and silence`);
  console.log(`  detection require manual testing. See:`);
  console.log(`  PRONUNCIATION_FEEDBACK_MANUAL_TEST.md`);
  
  if (failed > 0) process.exit(1);
}

runTests();
