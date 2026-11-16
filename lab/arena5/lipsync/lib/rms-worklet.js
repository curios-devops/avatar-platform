// Method A's audio-thread half: RMS of the incoming audio, posted every ~512 samples with the context time it
// belongs to. The main thread only reads the latest number, so A's analysis runs off the main thread.
class RmsMeter extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sum = 0;
    this.count = 0;
  }
  process(inputs, outputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) this.sum += ch[i] * ch[i];
      this.count += ch.length;
    }
    if (this.count >= 512) {
      this.port.postMessage({ rms: Math.sqrt(this.sum / this.count), t: currentTime });
      this.sum = 0;
      this.count = 0;
    }
    if (outputs[0] && outputs[0][0]) outputs[0][0].fill(0);
    return true;
  }
}
registerProcessor('rms-meter', RmsMeter);
