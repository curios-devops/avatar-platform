// Scripted measurement for chrome-devtools evaluate_script (sourcePath): open ?char=<id>&mouths=drawn[,sprites]; at
// desktop size it saves stills (neutral, aa, O, FF), listening and a 2 s sheet per mouth; under 500 px only the sheet.
async () => {
  const P = window.__puppet, w = (ms) => new Promise(r => setTimeout(r, ms));
  const id = new URLSearchParams(location.search).get('char'), mouths = (new URLSearchParams(location.search).get('mouths') || 'drawn').split(',');
  const tag = innerWidth < 500 ? '_390' : '';
  const out = {};
  for (const m of mouths) {
    await P.load(id, m); await w(400);
    if (!tag) {
      for (const v of ['sil', 'aa', 'O', 'FF']) { P.freeze(v, { still: true }); await w(200); await P.capture(`${m}_still_${v}`); }
      P.freeze(null); await w(2500); await P.capture(`${m}_listening`);
    }
    const r = await P.sheet({ name: 'sheet' + tag, from: 0.2, dur: 2, n: 12, cols: 6 });
    out[m] = { fps: r.fpsMedian, fpsP5: r.fpsP5, ms: r.msMean, msP95: r.msP95, lag: r.lagMs, r: r.r, canvas: r.canvas.join('x'), css: r.css, grabs: r.grabs };
  }
  return out;
}
