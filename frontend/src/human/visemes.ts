// Oculus 15 visemes (what the A0 orchestrator emits, backend/app/orchestrator/contract.py) to ARKit
// facial actions, which Anny exports as morph targets. Weights tuned by eye on the Anny face.
export type Weights = Record<string, number>;

export const VISEME_TO_ARKIT: Record<string, Weights> = {
  sil: {},
  PP: { mouthPressLeft: 0.5, mouthPressRight: 0.5, mouthRollLower: 0.35, mouthRollUpper: 0.3, mouthClose: 0.15 },
  FF: { mouthRollLower: 0.6, mouthUpperUpLeft: 0.25, mouthUpperUpRight: 0.25, jawOpen: 0.08 },
  TH: { jawOpen: 0.16, tongueOut: 0.35, mouthStretchLeft: 0.1, mouthStretchRight: 0.1 },
  DD: { jawOpen: 0.2, mouthStretchLeft: 0.15, mouthStretchRight: 0.15, mouthUpperUpLeft: 0.1, mouthUpperUpRight: 0.1 },
  kk: { jawOpen: 0.24, mouthStretchLeft: 0.22, mouthStretchRight: 0.22 },
  CH: { jawOpen: 0.15, mouthFunnel: 0.5, mouthShrugUpper: 0.25, mouthUpperUpLeft: 0.15, mouthUpperUpRight: 0.15 },
  SS: { jawOpen: 0.07, mouthStretchLeft: 0.35, mouthStretchRight: 0.35, mouthSmileLeft: 0.12, mouthSmileRight: 0.12 },
  nn: { jawOpen: 0.14, mouthClose: 0.1, mouthStretchLeft: 0.1, mouthStretchRight: 0.1 },
  RR: { jawOpen: 0.15, mouthFunnel: 0.35, mouthPucker: 0.25 },
  aa: { jawOpen: 0.55, mouthLowerDownLeft: 0.25, mouthLowerDownRight: 0.25, mouthUpperUpLeft: 0.16, mouthUpperUpRight: 0.16 },
  // E / ih lift the upper lip a little: in open vowels the upper incisors show, which is most of what reads as "speech"
  E: { jawOpen: 0.32, mouthStretchLeft: 0.32, mouthStretchRight: 0.32, mouthLowerDownLeft: 0.15, mouthLowerDownRight: 0.15, mouthUpperUpLeft: 0.14, mouthUpperUpRight: 0.14 },
  ih: { jawOpen: 0.22, mouthSmileLeft: 0.22, mouthSmileRight: 0.22, mouthStretchLeft: 0.12, mouthStretchRight: 0.12, mouthUpperUpLeft: 0.1, mouthUpperUpRight: 0.1 },
  oh: { jawOpen: 0.42, mouthFunnel: 0.55, mouthLowerDownLeft: 0.1, mouthLowerDownRight: 0.1 },
  ou: { jawOpen: 0.2, mouthPucker: 0.75, mouthFunnel: 0.25 },
};

export const EXPRESSIONS: Record<string, Weights> = {
  neutral: {},
  smile: { mouthSmileLeft: 0.6, mouthSmileRight: 0.6, cheekSquintLeft: 0.35, cheekSquintRight: 0.35, eyeSquintLeft: 0.2, eyeSquintRight: 0.2 },
  happy: { mouthSmileLeft: 0.9, mouthSmileRight: 0.9, cheekSquintLeft: 0.6, cheekSquintRight: 0.6, jawOpen: 0.15, mouthLowerDownLeft: 0.3, mouthLowerDownRight: 0.3 },
  surprised: { browInnerUp: 0.8, browOuterUpLeft: 0.7, browOuterUpRight: 0.7, eyeWideLeft: 0.6, eyeWideRight: 0.6, jawOpen: 0.3, mouthFunnel: 0.2 },
  sad: { browInnerUp: 0.6, mouthFrownLeft: 0.6, mouthFrownRight: 0.6, mouthShrugLower: 0.3, eyeSquintLeft: 0.1, eyeSquintRight: 0.1 },
  angry: { browDownLeft: 0.8, browDownRight: 0.8, noseSneerLeft: 0.4, noseSneerRight: 0.4, mouthPressLeft: 0.4, mouthPressRight: 0.4, eyeSquintLeft: 0.3, eyeSquintRight: 0.3 },
  thinking: { browInnerUp: 0.25, browDownLeft: 0.3, mouthPressLeft: 0.3, mouthLeft: 0.25, eyeLookUpLeft: 0.3, eyeLookUpRight: 0.3 },
};
