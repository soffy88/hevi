"""Procedural 2D puppets rendered with PIL (CPU only)."""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'


def _grad(W, H, top, bot):
    t = np.linspace(0, 1, H)[:, None, None]
    a = np.array(top)[None, None, :] * (1 - t) + np.array(bot)[None, None, :] * t
    return Image.fromarray(np.repeat(a, W, 1).astype(np.uint8))


# ---------------- presenter (talking head / spokesperson) ----------------
class Presenter:
    """Illustrated presenter; mouth driven by audio RMS, eyes blink, head sways."""

    def __init__(self, W, H, bg=((18, 28, 52), (40, 70, 110)), suit=(30, 40, 60), skin=(238, 200, 170),
                 hair=(40, 28, 22), tie=(200, 60, 50), seed=3, studio=True):
        self.W, self.H = W, H
        self.bgimg = _grad(W, H, *bg)
        if studio:
            d = ImageDraw.Draw(self.bgimg)
            for i in range(7):
                x = int(W * (0.08 + i * 0.14))
                d.rectangle([x, int(H * 0.15), x + int(W * 0.08), int(H * 0.62)], fill=(60, 95, 140))
            d.rectangle([0, int(H * 0.78), W, H], fill=(22, 30, 48))
            self.bgimg = self.bgimg.filter(ImageFilter.GaussianBlur(6))
        self.suit, self.skin, self.hair, self.tie = suit, skin, hair, tie
        rng = np.random.default_rng(seed)
        self.blinks = set()
        t = 40
        while t < 100000:
            for k in range(4):
                self.blinks.add(t + k)
            t += int(rng.integers(60, 130))

    def frame(self, i, mouth, fps=24, cx=None, scale=1.0):
        W, H = self.W, self.H
        img = self.bgimg.copy()
        d = ImageDraw.Draw(img)
        s = H / 720 * scale
        cx = (W // 2 if cx is None else cx) + int(6 * s * math.sin(i / fps * 0.9))
        cy = int(H * 0.40 + 3 * s * math.sin(i / fps * 1.7))
        tilt = 2.0 * math.sin(i / fps * 0.6)
        # torso
        d.rounded_rectangle([cx - 230 * s, cy + 150 * s, cx + 230 * s, H + 40 * s], 90 * s, fill=self.suit)
        d.polygon([(cx - 60 * s, cy + 150 * s), (cx, cy + 260 * s), (cx + 60 * s, cy + 150 * s)], fill=(235, 235, 240))
        d.polygon([(cx - 18 * s, cy + 165 * s), (cx + 18 * s, cy + 165 * s), (cx + 12 * s, cy + 300 * s),
                   (cx, cy + 320 * s), (cx - 12 * s, cy + 300 * s)], fill=self.tie)
        d.rectangle([cx - 40 * s, cy + 90 * s, cx + 40 * s, cy + 160 * s], fill=tuple(int(c * .9) for c in self.skin))
        # head on its own layer so it can tilt
        hw, hh = int(360 * s), int(420 * s)
        head = Image.new('RGBA', (hw, hh), (0, 0, 0, 0))
        h = ImageDraw.Draw(head)
        ox, oy = hw // 2, hh // 2
        h.ellipse([ox - 125 * s, oy - 150 * s, ox + 125 * s, oy + 160 * s], fill=self.skin)
        h.ellipse([ox - 140 * s, oy - 175 * s, ox + 140 * s, oy - 20 * s], fill=self.hair)
        h.rectangle([ox - 140 * s, oy - 100 * s, ox - 112 * s, oy + 20 * s], fill=self.hair)
        h.rectangle([ox + 112 * s, oy - 100 * s, ox + 140 * s, oy + 20 * s], fill=self.hair)
        h.ellipse([ox - 132 * s, oy - 10 * s, ox - 108 * s, oy + 45 * s], fill=self.skin)
        h.ellipse([ox + 108 * s, oy - 10 * s, ox + 132 * s, oy + 45 * s], fill=self.skin)
        blink = i in self.blinks
        for ex in (-50, 50):
            if blink:
                h.line([ox + (ex - 20) * s, oy + 5 * s, ox + (ex + 20) * s, oy + 5 * s], fill=(40, 30, 30), width=max(2, int(5 * s)))
            else:
                h.ellipse([ox + (ex - 20) * s, oy - 10 * s, ox + (ex + 20) * s, oy + 18 * s], fill='white')
                h.ellipse([ox + (ex - 9) * s, oy - 5 * s, ox + (ex + 9) * s, oy + 13 * s], fill=(50, 35, 30))
            h.line([ox + (ex - 25) * s, oy - 32 * s - 4 * s * mouth, ox + (ex + 25) * s, oy - 36 * s - 4 * s * mouth],
                   fill=self.hair, width=max(3, int(7 * s)))
        h.line([ox, oy + 15 * s, ox - 8 * s, oy + 55 * s, ox + 6 * s, oy + 58 * s], fill=(200, 150, 125), width=max(2, int(4 * s)))
        m = max(0.0, min(1.0, mouth))
        mw, mh = 46 * s * (1 - 0.25 * m), 6 * s + 44 * s * m
        my = oy + 95 * s
        h.ellipse([ox - mw, my - mh / 2, ox + mw, my + mh / 2], fill=(120, 40, 45), outline=(90, 30, 35), width=max(2, int(3 * s)))
        if m > 0.3:
            h.rectangle([ox - mw * 0.7, my - mh / 2 + 1, ox + mw * 0.7, my - mh / 2 + 9 * s], fill='white')
        head = head.rotate(tilt, resample=Image.BICUBIC, center=(ox, oy + 100 * s))
        img.paste(head, (int(cx - ox), int(cy - oy)), head)
        # slow handheld-style camera drift (push-in/out + lateral), so the shot is never locked-off
        z = 1.0 + 0.06 * (0.5 - 0.5 * math.cos(i / fps * 0.35))
        dx = 0.015 * W * math.sin(i / fps * 0.21)
        cw, ch = W / z, H / z
        x0 = (W - cw) / 2 + dx * (z - 1) / 0.06
        img = img.crop((int(x0), int((H - ch) / 2), int(x0 + cw), int((H + ch) / 2))).resize((W, H), Image.BILINEAR)
        return img


def mouth_series(env: np.ndarray) -> np.ndarray:
    """Smooth RMS into a 0..1 mouth-open series with quantised visemes (5 levels)."""
    e = np.convolve(env, np.ones(2) / 2, 'same')
    e = np.clip((e - 0.08) / 0.8, 0, 1)
    return np.round(e * 4) / 4


# ---------------- caveman character animation ----------------
def _limb(d, p, a, l, w, col):
    q = (p[0] + l * math.sin(a), p[1] + l * math.cos(a))
    d.line([p, q], fill=col, width=w)
    d.ellipse([q[0] - w / 2, q[1] - w / 2, q[0] + w / 2, q[1] + w / 2], fill=col)
    return q


def caveman_scene(W=1280, H=720, fps=24, seconds=12.0):
    """Yields frames: walk into cave mouth, crouch and pick up a stone, light & raise torch, turn to camera."""
    sky = _grad(W, H, (250, 180, 120), (120, 80, 70))
    bg = sky.copy()
    d = ImageDraw.Draw(bg)
    d.ellipse([W * 0.62, H * 0.08, W * 0.72, H * 0.08 + W * 0.1], fill=(255, 225, 160))
    d.polygon([(0, H * 0.55), (W * 0.2, H * 0.42), (W * 0.45, H * 0.52), (W * 0.7, H * 0.38), (W, H * 0.5), (W, H), (0, H)], fill=(110, 85, 70))
    rock = [(W * 0.55, H), (W * 0.58, H * 0.25), (W * 0.75, H * 0.12), (W, H * 0.15), (W, H)]
    d.polygon(rock, fill=(85, 70, 62))
    d.chord([W * 0.66, H * 0.32, W * 0.96, H * 1.15], 180, 360, fill=(25, 18, 16))
    d.rectangle([W * 0.66, H * 0.735, W * 0.96, H], fill=(25, 18, 16))
    d.rectangle([0, H * 0.82, W, H], fill=(92, 72, 58))
    for k in range(40):
        x = (k * 97) % W; y = H * 0.84 + (k * 37) % int(H * 0.15)
        d.ellipse([x, y, x + 10 + k % 7, y + 6], fill=(70, 55, 45))
    bg = bg.filter(ImageFilter.GaussianBlur(1))
    skin, fur, hair = (170, 120, 85), (120, 80, 45), (45, 30, 20)
    stone_pos = (W * 0.52, H * 0.835)
    rng = np.random.default_rng(1)
    N = int(seconds * fps)
    for i in range(N):
        t = i / fps
        img = bg.copy()
        d = ImageDraw.Draw(img, 'RGBA')
        # timeline
        if t < 4.5:
            x = W * 0.12 + (W * 0.40) * (t / 4.5); phase = t * 2 * math.pi * 1.1; bend = 0; arm_up = 0
        elif t < 7:
            x = W * 0.52; phase = 0; k = min(1, (t - 4.5) / 0.8) if t < 6.2 else max(0, 1 - (t - 6.2) / 0.8); bend = k; arm_up = 0
        else:
            x = W * 0.52; phase = 0; bend = 0; arm_up = min(1, (t - 7) / 1.2)
        facing = 1
        turn = 0.0
        if t > 10:
            turn = min(1, (t - 10) / 0.8)
        sx = math.cos(turn * math.pi)  # 1 -> -1 horizontal flip (turn around)
        gy = H * 0.83
        hip = (x, gy - 150)
        lean = 0.9 * bend
        sh_ = (hip[0] + 110 * math.sin(lean) * sx, hip[1] - 110 * math.cos(lean))
        sw = math.sin(phase) * 0.5
        bob = abs(math.cos(phase)) * 6 if t < 4.5 else 0
        hip = (hip[0], hip[1] - bob); sh_ = (sh_[0], sh_[1] - bob)
        # legs
        for side, ph in ((0, sw), (1, -sw)):
            col = (150, 105, 75) if side else skin
            knee = _limb(d, hip, ph * sx + 0.25 * bend * sx, 75 - 15 * bend, 22, col)
            _limb(d, knee, ph * 0.3 * sx - 0.6 * bend * sx, 75, 20, col)
        # body (fur tunic)
        d.polygon([(hip[0] - 38, hip[1] + 25), (sh_[0] - 40, sh_[1]), (sh_[0] + 40, sh_[1]), (hip[0] + 38, hip[1] + 25)], fill=fur)
        d.line([(sh_[0] - 30, sh_[1] + 10), (hip[0] + 30, hip[1] + 10)], fill=(90, 55, 30), width=6)
        # head
        hx, hy = sh_[0] + 10 * sx * math.cos(lean), sh_[1] - 48
        d.ellipse([hx - 36, hy - 40, hx + 36, hy + 40], fill=skin)
        d.chord([hx - 40, hy - 50, hx + 40, hy + 20], 180, 360, fill=hair)
        ex = hx + 14 * sx
        if abs(sx) > 0.25:
            d.ellipse([ex - 5, hy - 6, ex + 5, hy + 4], fill=(30, 20, 15))
        d.line([(hx - 12 * sx, hy + 18), (hx + 16 * sx, hy + 16)], fill=(110, 60, 45), width=3)
        d.chord([hx - 30, hy + 10, hx + 30, hy + 48], 0, 180, fill=hair)
        # back arm
        _limb(d, sh_, -sw * sx * 0.8 + 0.3 * sx, 120, 18, (150, 105, 75))
        # front arm: reach for stone when bending, raise torch afterwards
        if bend > 0:
            a = (-sw * 0.8 + 0.4 + 0.9 * bend) * sx
        else:
            a = (math.pi - 0.35) * arm_up * sx + (1 - arm_up) * (sw * 0.8) * sx
        hand = _limb(d, sh_, a, 120, 18, skin)
        holding = t >= 6.0
        if not holding:
            d.ellipse([stone_pos[0] + 20, stone_pos[1] - 12, stone_pos[0] + 48, stone_pos[1] + 8], fill=(120, 120, 125))
        if holding and t < 7.6:
            d.ellipse([hand[0] - 13, hand[1] - 10, hand[0] + 13, hand[1] + 10], fill=(120, 120, 125))
        if t >= 7.6:  # torch with flame
            top = (hand[0] + 10 * sx, hand[1] - 70)
            d.line([(hand[0], hand[1] + 15), top], fill=(95, 60, 30), width=12)
            fl = min(1, (t - 7.6) / 0.6)
            glow = Image.new('L', (W, H), 0)
            gd = ImageDraw.Draw(glow)
            r = 260 * fl * (1 + 0.06 * math.sin(t * 17))
            gd.ellipse([top[0] - r, top[1] - r, top[0] + r, top[1] + r], fill=110)
            glow = glow.filter(ImageFilter.GaussianBlur(70))
            img = Image.composite(Image.new('RGB', (W, H), (255, 170, 70)), img, glow)
            d = ImageDraw.Draw(img, 'RGBA')
            for k in range(14):
                jx = rng.normal(0, 7); jy = rng.uniform(0, 55) * fl
                rr = (20 - k) * fl
                d.ellipse([top[0] + jx - rr, top[1] - jy - rr * 1.5, top[0] + jx + rr, top[1] - jy + rr],
                          fill=(255, 120 + k * 9, 30, 160))
        # ambient vignette darkens at the start, brightens with torch
        yield np.asarray(img.convert('RGB'))
