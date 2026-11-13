"""The gesture layer of the FlashHead call: pre-made half-body clips of the being play under the live face, one clip per
moment of the call, and FlashHead's generated face is pasted onto the clip's head frame by frame. Only cv2, numpy and
mediapipe, so the compositing can be tuned on a laptop from dumped FlashHead frames (fh_dump.py, compose_offline.py).

Round 3 anchoring (v3), after round 2 still showed a slight double contour on fast clip motion:
  * more anchors, frame by frame: eye corners, nose bridge and tip, and mouth corners on both sides (the clip and
    FlashHead), fitted by weighted least squares. A similarity from the eyes alone left the mouth and chin off whenever
    the two heads pitched differently; a light affine term lets eyes AND mouth land on the clip's.
  * no lag: round 2 smoothed the clip track over 7 frames and FlashHead's track with an exponential average, so on a
    quick nod the face trailed the head. Now the clip track is smoothed over 3 frames with zero phase (offline) and
    FlashHead's with a One Euro filter (steady when still, no lag when it moves).
  * soft edges: the face's alpha fades with the distance to its outline (transparent towards the borders), and the
    alpha and the colour match are smoothed over time in the canvas, so one frame's seam never differs from the next.
"""
import time

import cv2
import numpy as np

FPS = 25
CANVAS_W, CANVAS_H = 720, 1280
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)

OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150,
        136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
# registration anchors and weights: eye corners (most reliable), nose bridge to tip, mouth corners
ANCHORS = [33, 133, 362, 263, 168, 6, 197, 4, 1, 61, 291]
WEIGHTS = np.array([3, 3, 3, 3, 2, 2, 1.5, 1.5, 1.5, 1.5, 1.5], np.float32)


def face_mesh(static=False):
    import mediapipe as mp
    return mp.solutions.face_mesh.FaceMesh(static_image_mode=static, max_num_faces=1, refine_landmarks=False,
                                           min_detection_confidence=0.3, min_tracking_confidence=0.3)


def landmarks(det, bgr):
    r = det.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    if not r.multi_face_landmarks:
        return None
    H, W = bgr.shape[:2]
    return np.array([(l.x * W, l.y * H) for l in r.multi_face_landmarks[0].landmark], np.float32)


def eye_track(pts):
    """(eye midpoint x, y, eye distance, eye-line angle) from the four eye corners."""
    a, b = (pts[33] + pts[133]) / 2, (pts[362] + pts[263]) / 2
    return np.array([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, float(np.hypot(*(b - a))), np.arctan2(b[1] - a[1], b[0] - a[0])], np.float32)


def sim(t):
    return t[2] * np.array([[np.cos(t[3]), -np.sin(t[3])], [np.sin(t[3]), np.cos(t[3])]], np.float32)


def fit(src, dst, w, affine=0.5):
    """2x3 transform src -> dst: weighted similarity (Umeyama) plus `affine` of the way to the weighted full affine."""
    w = w / w.sum()
    ms, md = (src * w[:, None]).sum(0), (dst * w[:, None]).sum(0)
    s, d = src - ms, dst - md
    C = (d * w[:, None]).T @ s
    U, S, Vt = np.linalg.svd(C)
    R = U @ np.diag([1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
    scale = S.sum() / (w * (s ** 2).sum(1)).sum()
    Ms = scale * R
    X = np.hstack([s, np.ones((len(s), 1), np.float32)]) * np.sqrt(w)[:, None]
    A = np.linalg.lstsq(X, d * np.sqrt(w)[:, None], rcond=None)[0][:2].T
    M = Ms + affine * (A - Ms)
    return np.hstack([M, (md - M @ ms)[:, None]]).astype(np.float32)


class OneEuro:
    """One Euro filter (Casiez et al. 2012) on an array: little smoothing when it moves fast, a lot when it is still."""

    def __init__(self, min_cutoff=1.2, beta=0.05, d_cutoff=1.0):
        self.mc, self.beta, self.dc, self.x, self.dx = min_cutoff, beta, d_cutoff, None, None

    @staticmethod
    def _a(cutoff):
        tau = 1 / (2 * np.pi * cutoff); return 1 / (1 + tau * FPS)

    def __call__(self, x):
        if self.x is None:
            self.x, self.dx = x.copy(), np.zeros_like(x); return x
        dx = (x - self.x) * FPS
        self.dx = self.dx + self._a(self.dc) * (dx - self.dx)
        cutoff = self.mc + self.beta * np.abs(self.dx)
        self.x = self.x + self._a(cutoff) * (x - self.x)
        return self.x.copy()


def soft_mask(pts, t, shape, fade=0.22):
    """FlashHead's face outline, cut above the brows, with alpha rising from 0 at the outline to 1 at `fade` x the eye
    distance inside it: transparent towards the borders, solid on eyes, nose, mouth and chin."""
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [pts[OVAL].astype(np.int32)], 1)
    d, ang = t[2], t[3]
    n = np.array([np.sin(ang), -np.cos(ang)], np.float32)
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    up = (xs - t[0]) * n[0] + (ys - t[1]) * n[1]
    m[up > 0.7 * d] = 0
    dist = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    a = np.clip(dist / (fade * d), 0, 1)
    a = a * a * (3 - 2 * a)  # smoothstep
    k = int(d * 0.15) | 1
    return cv2.GaussianBlur(a, (k, k), 0)


def mirror(size, k):
    turn, r = divmod(k, size)
    return r if turn % 2 == 0 else size - r - 1


def segment_for(text, need=2):
    """Which body clip goes with this sentence: lists and strong statements -> emphasis, the rest -> explaining."""
    import re
    hits = len(re.findall(r"\b(primero|segundo|tercero|uno|dos|tres|ojo|importante|clave|lo mejor|incre[ií]ble|s[ií] o s[ií]|"
                          r"first|second|third|important|key|amazing)\b", text, re.I)) + max(0, text.count("!") - 1)
    return "emphasis" if hits >= need else "explain"


MIN_CLIP_S = 2.0
CHARS_PER_S = 14.5  # the voice's pace (Spanish, speed 1.03): turns a sentence's length into its spoken time


def plan_for(text, first_turn=False):
    """A clip per sentence of the answer: [(frame where it starts, clip)]. The first sentence of the call's first turn
    is the greeting; then emphasis for lists and strong statements, explaining for the rest. A sentence too short to
    show a gesture keeps the previous clip: every clip plays at least MIN_CLIP_S, so the body never flickers."""
    import re
    plan, t = [], 0.0
    for k, sent in enumerate(x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x):
        clip = "greet" if first_turn and k == 0 else segment_for(sent, need=1)  # one list word or "ojo" per sentence
        if not plan or (clip != plan[-1][1] and t * FPS - plan[-1][0] >= MIN_CLIP_S * FPS):
            plan.append((int(t * FPS), clip))
        t += len(sent) / CHARS_PER_S
    return plan


def fit_canvas(bgr):
    h, w = bgr.shape[:2]
    tw = min(w, int(h * 9 / 16))
    crop = bgr[:, (w - tw) // 2:(w - tw) // 2 + tw]
    crop = cv2.resize(crop, (CANVAS_W, int(h * CANVAS_W / tw)), interpolation=cv2.INTER_AREA)
    out = np.full((CANVAS_H, CANVAS_W, 3), 250, np.uint8)
    out[:min(CANVAS_H, crop.shape[0])] = crop[:CANVAS_H]
    return out


class BodyClips:
    """Clips per moment (listen, think, greet, explain, emphasis). 'listen' while the being is silent (after `hold`
    silent frames), the turn's clip while it talks, a cross-fade at every switch; each clip restarts from its first
    frame and all start from the portrait's pose. version 'v3' = the anchoring above, 'v2' = round 2 (for comparison)."""

    def __init__(self, clips, version="v3", fade=6, hold=15):
        self.v, self.fade_n, self.hold = version, fade, hold
        self.clips = {}
        for name, path in clips.items():
            det = face_mesh()
            cap, frames = cv2.VideoCapture(path), []
            src_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
            while True:
                ok, f = cap.read()
                if not ok:
                    break
                frames.append(fit_canvas(f))
            idx = np.round(np.arange(0, len(frames), src_fps / FPS)).astype(int)
            frames = [frames[min(i, len(frames) - 1)] for i in idx]
            pts, missed = [], 0
            for f in frames:
                p = landmarks(det, f)
                if p is None:
                    missed += 1; p = pts[-1] if pts else None
                pts.append(p)
            first = next(p for p in pts if p is not None)
            P = np.stack([first if p is None else p for p in pts])  # frames x 468 x 2
            sm = 3 if version == "v3" else 7
            k = np.ones(sm, np.float32) / sm
            P = np.apply_along_axis(lambda s: np.convolve(np.pad(s, sm // 2, mode="edge"), k, mode="valid"), 0, P)
            self.clips[name] = (frames, P.astype(np.float32))
            log(f"body clip {name}: {len(frames)} frames ({len(frames) / FPS:.1f}s), face missed in {missed}")
        self.det_fh = face_mesh()
        self.state = "listen" if "listen" in self.clips else next(iter(self.clips))
        self.turn = "explain" if "explain" in self.clips else self.state
        self.n, self.fade, self.prev, self.silent = 0, 0, None, 0
        self.euro, self.fh_pts, self.alpha, self.gain = OneEuro(), None, None, None
        self.residual = []  # per frame: mean anchor error after registration (px, canvas)
        self.halo = []      # per frame: share of the pasted face that falls outside the clip's own face

    def _switch(self, state):
        if state != self.state and state in self.clips:
            log(f"body {self.state} -> {state}")
            self.state, self.n, self.fade = state, 0, self.fade_n

    def set_turn(self, state):
        if state in self.clips:
            self.turn = state
            if self.state != "listen" and self.n < FPS:
                self._switch(state)

    def set_plan(self, text, first_turn=False):
        """Round 3: the answer's text gives a clip per sentence, switched as the being reaches that sentence."""
        self.plan = [(f, c) for f, c in plan_for(text, first_turn) if c in self.clips]
        self.talked = 0
        if self.plan:
            self.turn = self.plan[0][1]
            if self.state not in ("listen", "think"):
                self._switch(self.turn)

    def thinking(self):
        """The person finished speaking and the answer is on its way: the 'think' clip fills the wait."""
        if "think" in self.clips and self.state == "listen":
            self._switch("think")

    def __call__(self, face_rgb, n, talking=None):
        if talking:
            self.silent = 0
            if self.state in ("listen", "think"):
                self._switch(self.turn)
            self.talked = getattr(self, "talked", 0) + 1
            for f, c in getattr(self, "plan", []):  # the clip of the sentence being spoken now
                if f <= self.talked:
                    self.turn = c
            if self.turn != self.state:
                self._switch(self.turn)
        elif talking is not None:
            self.silent += 1
            if self.silent >= self.hold and self.state != "think":
                self._switch("listen" if "listen" in self.clips else self.state)
            if self.state == "think" and self.silent > 6 * FPS:  # the answer never came: back to listening
                self._switch("listen")
        frames, P = self.clips[self.state]
        i = mirror(len(frames), self.n); self.n += 1
        out = frames[i].copy()
        if face_rgb is not None:
            out = (self._paste_v3 if self.v == "v3" else self._paste_v2)(out, face_rgb, P[i])
        if self.fade > 0 and self.prev is not None:
            a = self.fade / (self.fade_n + 1)
            out = cv2.addWeighted(self.prev, a, out, 1 - a, 0); self.fade -= 1
        self.prev = out
        return out

    # ------------------------------------------------------------------ round 3
    def _paste_v3(self, out, face_rgb, pc):
        face = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2BGR)
        p = landmarks(self.det_fh, face)
        if p is not None:
            self.fh_pts = self.euro(p)
        if self.fh_pts is None:
            return out
        pf = self.fh_pts
        M = fit(pf[ANCHORS], pc[ANCHORS], WEIGHTS)
        mapped = pf[ANCHORS] @ M[:, :2].T + M[:, 2]
        self.residual.append(float(np.average(np.linalg.norm(mapped - pc[ANCHORS], axis=1), weights=WEIGHTS)))
        tf = eye_track(pf)
        h2 = (face.shape[0] // 2, face.shape[1] // 2)
        tf2 = tf.copy(); tf2[:3] *= 0.5
        mask = cv2.resize(soft_mask(pf * 0.5, tf2, h2), (face.shape[1], face.shape[0]), interpolation=cv2.INTER_LINEAR)
        a = cv2.warpAffine(mask, M, (CANVAS_W, CANVAS_H), flags=cv2.INTER_LINEAR, borderValue=0)
        # temporal smoothing of the seam only (the pixels are not smoothed, so nothing trails)
        self.alpha = a if self.alpha is None or self.alpha.shape != a.shape else 0.55 * a + 0.45 * self.alpha
        # ...and only where the clip has its own face too: FlashHead skin never lands on the clip's background or hair
        a = self.alpha * self._clip_mask(pc)
        if self.halo is not None:
            self.halo.append(float((self.alpha * (1 - self._clip_hard)).sum() / max(1.0, self.alpha.sum())))
        ys, xs = np.nonzero(a > 0.003)
        if len(xs) == 0:
            return out
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        M2 = M.copy(); M2[:, 2] -= (x0, y0)
        f = cv2.warpAffine(face, M2, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        aa = a[y0:y1, x0:x1][..., None]
        roi = out[y0:y1, x0:x1].astype(np.float32)
        m = aa[..., 0] > 0.6
        if m.sum() > 50:  # colour match to the clip's light, smoothed over time so it never flickers
            mu_f, mu_r = f[m].mean(0), roi[m].mean(0)
            sd_f, sd_r = f[m].std(0) + 1e-3, roi[m].std(0) + 1e-3
            g = np.concatenate([np.clip(sd_r / sd_f, 0.85, 1.15), np.clip(mu_r - mu_f, -20, 20)])
            self.gain = g if self.gain is None else 0.8 * self.gain + 0.2 * g
            f = (f - mu_f) * self.gain[:3] + mu_f + self.gain[3:]
        out[y0:y1, x0:x1] = np.clip(f * aa + roi * (1 - aa), 0, 255).astype(np.uint8)
        return out

    def _clip_mask(self, pc):
        """The clip's own face outline in this frame (cut above the brows), soft towards its border."""
        t = eye_track(pc)
        x0, y0 = np.maximum(pc[OVAL].min(0).astype(int) - 4, 0); x1, y1 = pc[OVAL].max(0).astype(int) + 4
        m = np.zeros((CANVAS_H, CANVAS_W), np.uint8)
        sub = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(sub, [(pc[OVAL] - (x0, y0)).astype(np.int32)], 1)
        nrm = np.array([np.sin(t[3]), -np.cos(t[3])], np.float32)
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        sub[((xs - t[0]) * nrm[0] + (ys - t[1]) * nrm[1]) > 0.8 * t[2]] = 0
        m[y0:y1, x0:x1] = sub
        self._clip_hard = m.astype(np.float32)
        dist = cv2.distanceTransform(sub, cv2.DIST_L2, 3)
        a = np.clip(dist / (0.12 * t[2]), 0, 1)
        out = np.zeros((CANVAS_H, CANVAS_W), np.float32); out[y0:y1, x0:x1] = a * a * (3 - 2 * a)
        return out

    # ------------------------------------------------------------------ round 2 (kept for the comparison)
    def _paste_v2(self, out, face_rgb, pc):
        face = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2BGR)
        p = landmarks(self.det_fh, face)
        if p is not None:
            tf = eye_track(p)
            if self.fh_pts is not None:
                tf[3] = self._tf[3] + np.arctan2(np.sin(tf[3] - self._tf[3]), np.cos(tf[3] - self._tf[3]))
                tf = 0.6 * tf + 0.4 * self._tf; p = 0.6 * p + 0.4 * self.fh_pts
            self._tf, self.fh_pts = tf, p
        if self.fh_pts is None:
            return out
        tf, pf, tc = self._tf, self.fh_pts, eye_track(pc)
        Mf = sim(tc) @ np.linalg.inv(sim(tf)); bf = tc[:2] - Mf @ tf[:2]
        M = np.hstack([Mf, bf[:, None]]).astype(np.float32)
        mapped = pf[ANCHORS] @ M[:, :2].T + M[:, 2]
        self.residual.append(float(np.average(np.linalg.norm(mapped - pc[ANCHORS], axis=1), weights=WEIGHTS)))
        m = np.zeros(face.shape[:2], np.float32)
        cv2.fillPoly(m, [pf[OVAL].astype(np.int32)], 1.0)
        d, ang = tf[2], tf[3]
        nrm = np.array([np.sin(ang), -np.cos(ang)], np.float32)
        ys, xs = np.mgrid[0:face.shape[0], 0:face.shape[1]].astype(np.float32)
        m *= np.clip((0.75 * d - ((xs - tf[0]) * nrm[0] + (ys - tf[1]) * nrm[1])) / (0.25 * d), 0, 1)
        m = cv2.erode(m, np.ones((max(3, int(d * 0.12)),) * 2, np.uint8))
        m = cv2.GaussianBlur(m, (int(d * 0.35) | 1,) * 2, d * 0.12)
        a = cv2.warpAffine(m, M, (CANVAS_W, CANVAS_H), flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
        self._clip_mask(pc); self.halo.append(float((a[..., 0] * (1 - self._clip_hard)).sum() / max(1.0, a.sum())))
        f = cv2.warpAffine(face, M, (CANVAS_W, CANVAS_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        r = out.astype(np.float32); mm = a[..., 0] > 0.5
        if mm.sum() > 50:
            mu_f, mu_r = f[mm].mean(0), r[mm].mean(0)
            sd_f, sd_r = f[mm].std(0) + 1e-3, r[mm].std(0) + 1e-3
            f = (f - mu_f) * np.clip(sd_r / sd_f, 0.85, 1.15) + mu_f + np.clip(mu_r - mu_f, -20, 20)
        return np.clip(f * a + r * (1 - a), 0, 255).astype(np.uint8)
