// Live mode: plays PCM that is still arriving, like a streaming TTS response.
// main -> worklet: {type:'push', samples: Float32Array} | {type:'end'} | {type:'reset'}
// worklet -> main: {type:'pos', played, t, buffered, playing, underruns} every 2 render quanta, {type:'done'}
// Playback starts once `prebufferMs` is queued; an empty queue before 'end' is an underrun (silence, clock stops).
class PcmQueue extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = options.processorOptions || {};
    this.prebuffer = Math.round(((o.prebufferMs ?? 150) / 1000) * sampleRate);
    this.reset();
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d.type === 'push') { this.chunks.push(d.samples); this.queued += d.samples.length; }
      else if (d.type === 'end') this.ended = true;
      else if (d.type === 'reset') this.reset();
    };
  }
  reset() {
    this.chunks = []; this.off = 0; this.queued = 0; this.played = 0;
    this.started = false; this.ended = false; this.done = false; this.underruns = 0; this.starved = false; this.n = 0;
  }
  process(_, outputs) {
    const out = outputs[0][0];
    out.fill(0);
    if (!this.started && (this.queued >= this.prebuffer || (this.ended && this.queued > 0))) this.started = true;
    let playing = false;
    if (this.started) {
      let i = 0;
      while (i < out.length && this.chunks.length) {
        const c = this.chunks[0], take = Math.min(out.length - i, c.length - this.off);
        out.set(c.subarray(this.off, this.off + take), i);
        i += take; this.off += take; this.queued -= take; this.played += take;
        if (this.off >= c.length) { this.chunks.shift(); this.off = 0; }
      }
      playing = i > 0;
      if (i < out.length && !this.ended) { if (!this.starved) this.underruns++; this.starved = true; } else this.starved = false;
      if (this.ended && !this.chunks.length && !this.done) { this.done = true; this.port.postMessage({ type: 'done', played: this.played }); }
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    if (++this.n % 2 === 0) {
      this.port.postMessage({ type: 'pos', played: this.played, t: currentTime + out.length / sampleRate,
        buffered: this.queued, playing, underruns: this.underruns });
    }
    return true;
  }
}
registerProcessor('pcm-queue', PcmQueue);
