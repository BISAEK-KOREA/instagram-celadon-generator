# -*- coding: utf-8 -*-
"""릴스 생성기 v2 — '시네마틱' 업그레이드 (Shop@KBridge 홍보부터 적용).

v1(build_video.py) 대비 개선:
- 소재: 장면별 pexels_id / pexels_photo_id 로 '사람이 고른' 클립을 정확히 지정
- 배경음악: assets/music/*.mp3 (CC0) 를 내레이션 밑에 깔고, 말할 때 자동으로 볼륨 다운(사이드체인 덕킹)
- 색보정: 전 장면 동일한 따뜻한 그레이드 + 은은한 비네트 → 통일된 톤앤매너
- 전환: 장면 사이 0.5초 크로스페이드(xfade/acrossfade)
- 사진 장면: 켄번즈(천천히 줌인) 모션
- 자막: 부드러운 페이드 인/아웃 + 로즈 액센트 라인의 세련된 타이포
- 마지막에 브랜드 엔딩 카드(음악만) 자동 추가
- 목소리: edge-tts rate -5% (차분하게)

사용: PROJECT_JSON=projects/<slug>.json python build_video2.py
"""
import os, sys, subprocess, asyncio, re, json
from io import BytesIO
import requests
import edge_tts

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)
import generate_post as gp
from PIL import Image, ImageDraw, ImageFilter

FFMPEG = r"C:\Users\leeka\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
OUT = os.path.join(PROJECT, "video_out")
os.makedirs(OUT, exist_ok=True)

PEXELS_KEY = open(r"C:\Users\leeka\.pexels_key.txt", encoding="utf-8").read().strip()
PX = {"Authorization": PEXELS_KEY}
UA = {"User-Agent": "bisaek-video/4.0"}

VOICES = {"ar": "ar-SA-ZariyahNeural", "en": "en-US-AriaNeural", "ko": "ko-KR-SunHiNeural"}
LANG = "ar"
VOICE = VOICES[LANG]
W, H = 1080, 1920
BGW, BGH = 1512, 2688          # 사진은 켄번즈 여유분을 위해 1.4배로 저장
FPS = 30
BRAND = "@bisaek.kr"
ACCENT = (233, 183, 183)        # 로즈 블러시 액센트
DARK = (24, 13, 16)             # 따뜻한 다크 (그라데이션/스트로크)
XFADE = 0.5                     # 장면 전환 길이(초)
MUSIC = os.path.join(PROJECT, "assets", "music", "evening_sunset_cc0.mp3")
MUSIC_VOL = 0.20

_pj = os.environ.get("PROJECT_JSON")
if not _pj:
    print("PROJECT_JSON 환경변수로 프로젝트 파일을 지정하세요."); sys.exit(1)
_meta = json.load(open(_pj, encoding="utf-8"))
SCENES = _meta["scenes"]
TITLE = _meta.get("title", "")
PROD_NO = _meta.get("prod_no", "")
SLUG = _meta.get("slug", "reel")
COVER = _meta.get("cover")
ENDCARD = _meta.get("endcard")  # {"title","sub":{lang},"handle","small":{lang}} 없으면 생략


def _slug(q):
    return re.sub(r"[^a-z0-9]+", "_", q.lower())[:14]


# ---------------------------------------------------------------- 소재 확보
def fetch_video_by_id(vid):
    path = os.path.join(OUT, f"src_id{vid}.mp4")
    if os.path.exists(path) and os.path.getsize(path) > 40000:
        print(f"    영상 재활용: id{vid}")
        return path
    r = requests.get(f"https://api.pexels.com/videos/videos/{vid}", headers=PX, timeout=25)
    r.raise_for_status()
    files = [f for f in r.json().get("video_files", []) if f.get("link")]
    files.sort(key=lambda f: (f.get("height") or 0))
    choice = next((f for f in files if (f.get("height") or 0) >= 1600),
                  files[-1] if files else None)
    if not choice:
        raise RuntimeError(f"id{vid}: no files")
    data = requests.get(choice["link"], headers=UA, timeout=120).content
    open(path, "wb").write(data)
    print(f"    영상 OK: id{vid} ({choice.get('width')}x{choice.get('height')})")
    return path


def fetch_photo_by_id(pid):
    r = requests.get(f"https://api.pexels.com/v1/photos/{pid}", headers=PX, timeout=25)
    r.raise_for_status()
    src = r.json().get("src", {})
    url = src.get("large2x") or src.get("original")
    img = Image.open(BytesIO(requests.get(url, headers=UA, timeout=60).content)).convert("RGB")
    print(f"    사진 OK: id{pid} ({img.width}x{img.height})")
    return img


def cover_fit(img, size):
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    nw, nh = img.size
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def get_media(scene):
    bgpath = os.path.join(OUT, f"bg2_{SLUG}_{scene['id']}.png")
    if scene.get("image"):
        src = scene["image"] if os.path.isabs(scene["image"]) else os.path.join(PROJECT, scene["image"])
        if os.path.exists(src):
            cover_fit(Image.open(src).convert("RGB"), (BGW, BGH)).save(bgpath)
            return "photo", bgpath
    if scene.get("pexels_id"):
        return "video", fetch_video_by_id(scene["pexels_id"])
    if os.path.exists(bgpath):
        print(f"    사진 재활용: 장면 {scene['id']}")
        return "photo", bgpath
    if scene.get("pexels_photo_id"):
        img = fetch_photo_by_id(scene["pexels_photo_id"])
    else:
        img = gp.create_celadon_background((BGW, BGH), seed=int(scene["id"]) * 7 + 3).convert("RGB")
    cover_fit(img, (BGW, BGH)).save(bgpath, "PNG")
    return "photo", bgpath


# ---------------------------------------------------------------- 오버레이(자막)
def _grad(d, y0, y1, color, a_from, a_to):
    for y in range(int(y0), int(y1)):
        t = (y - y0) / max(1, (y1 - y0))
        d.line([(0, y), (W, y)], fill=color + (int(a_from + (a_to - a_from) * t),))


def make_overlay_brandfilm(scene):
    """삼성/LG 광고식: 화면 중앙 대형 타이포, 카드/하단자막 없음, 전면 은은한 스크림."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 55))   # 전면 얇은 스크림(글자 가독)
    d = ImageDraw.Draw(ov)
    rtl = (LANG == "ar")
    akw = gp._arabic_draw_kwargs() if rtl else {}
    font_path = gp.FONT_AR_PATH if rtl else gp.FONT_KO_PATH
    wrap = gp.wrap_arabic if rtl else gp.wrap_korean

    bf = gp.load_variable_font(gp.FONT_KO_PATH, 30, "Regular")
    d.text((W - 44 - d.textlength(BRAND, font=bf), 46), BRAND, font=bf, fill=(255, 255, 255, 170))
    if PROD_NO:
        pnf = gp.load_variable_font(gp.FONT_KO_PATH, 22, "Regular")
        d.text((44, 50), PROD_NO, font=pnf, fill=(255, 255, 255, 110))

    # 상단 작은 브랜드 아이브로우 (레터스페이스 느낌의 라틴 소형 캡션)
    ef = gp.load_variable_font(gp.FONT_KO_PATH, 30, "Regular")
    eyebrow = "S H O P @ K B R I D G E"
    d.text((W / 2 - d.textlength(eyebrow, font=ef) / 2, int(H * 0.30)), eyebrow,
           font=ef, fill=(255, 255, 255, 150))

    # 중앙 대형 카피
    sub = scene["sub"][LANG]
    sfont = gp.load_variable_font(font_path, 88 if rtl else 76, "Bold")
    lines = wrap(d, sub, sfont, int(W * 0.84))
    lh = (88 if rtl else 76) + 26
    y0 = H / 2 - (len(lines) * lh) / 2 - 20
    gp.draw_centered_multiline(d, lines, sfont, W / 2, y0, fill=(255, 255, 255),
                               line_gap=26, stroke_width=2, stroke_fill=(10, 8, 10),
                               extra_draw_kwargs=akw)
    d.line([(W / 2 - 60, y0 + len(lines) * lh + 40), (W / 2 + 60, y0 + len(lines) * lh + 40)],
           fill=ACCENT + (220,), width=3)

    p = os.path.join(OUT, f"ov2_{LANG}_{SLUG}_{scene['id']}.png")
    ov.save(p, "PNG")
    return p


def make_overlay(scene):
    if _meta.get("style") == "brandfilm":
        return make_overlay_brandfilm(scene)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rtl = (LANG == "ar")
    akw = gp._arabic_draw_kwargs() if rtl else {}
    font_path = gp.FONT_AR_PATH if rtl else gp.FONT_KO_PATH
    wrap = gp.wrap_arabic if rtl else gp.wrap_korean

    _grad(d, H * 0.60, H, DARK, 0, 175)          # 아래쪽만 은은하게
    _grad(d, 0, H * 0.12, DARK, 105, 0)

    bf = gp.load_variable_font(gp.FONT_KO_PATH, 33, "Regular")
    d.text((W - 44 - d.textlength(BRAND, font=bf), 46), BRAND, font=bf, fill=(255, 255, 255, 195))
    if PROD_NO:
        pnf = gp.load_variable_font(gp.FONT_KO_PATH, 24, "Regular")
        d.text((44, 50), PROD_NO, font=pnf, fill=(255, 255, 255, 130))

    sub = scene["sub"][LANG]
    if scene.get("products"):
        tfont = gp.load_variable_font(font_path, 58, "Bold")
        gp.draw_centered_multiline(d, wrap(d, sub, tfont, int(W * 0.86)), tfont, W / 2,
                                   int(H * 0.17), fill=(255, 252, 250), line_gap=14,
                                   stroke_width=2, stroke_fill=DARK, extra_draw_kwargs=akw)
        d.line([(W / 2 - 90, int(H * 0.17) + 96), (W / 2 + 90, int(H * 0.17) + 96)],
               fill=ACCENT + (235,), width=4)
        cfont = gp.load_variable_font(font_path, 42, "Bold")
        y = int(H * 0.335)
        for p in scene["products"][LANG]:
            d.rounded_rectangle([int(W * 0.08), y, int(W * 0.92), y + 148], radius=26,
                                fill=(28, 16, 20, 200))
            bar_x = int(W * 0.92) - 10 if rtl else int(W * 0.08)
            d.rounded_rectangle([bar_x, y + 18, bar_x + 10, y + 130], radius=5, fill=ACCENT + (235,))
            gp.draw_centered_multiline(d, wrap(d, p, cfont, int(W * 0.76)), cfont, W / 2, y + 32,
                                       fill=(255, 255, 255), line_gap=8, stroke_width=1,
                                       stroke_fill=DARK, extra_draw_kwargs=akw)
            y += 178
    else:
        yb = int(H * 0.685)
        d.line([(W / 2 - 70, yb - 34), (W / 2 + 70, yb - 34)], fill=ACCENT + (225,), width=3)
        sfont = gp.load_variable_font(font_path, 64 if rtl else 56, "Bold")
        gp.draw_centered_multiline(d, wrap(d, sub, sfont, int(W * 0.86)), sfont, W / 2,
                                   yb, fill=(255, 255, 255), line_gap=16,
                                   stroke_width=2, stroke_fill=DARK, extra_draw_kwargs=akw)

    p = os.path.join(OUT, f"ov2_{LANG}_{SLUG}_{scene['id']}.png")
    ov.save(p, "PNG")
    return p


def make_endcard_bg():
    """엔딩 카드 배경: 첫 pexels 장면 프레임을 흐리고 어둡게."""
    p = os.path.join(OUT, f"endbg_{SLUG}.png")
    if os.path.exists(p):
        return p
    src = None
    for sc in SCENES:
        if sc.get("pexels_id"):
            v = os.path.join(OUT, f"src_id{sc['pexels_id']}.mp4")
            if os.path.exists(v):
                fr = os.path.join(OUT, f"_endfr_{SLUG}.png")
                subprocess.run([FFMPEG, "-y", "-ss", "1.0", "-i", v, "-frames:v", "1", fr],
                               check=True, capture_output=True)
                src = Image.open(fr).convert("RGB")
                break
    if src is None:
        src = gp.create_celadon_background((W, H)).convert("RGB")
    im = cover_fit(src, (W, H)).filter(ImageFilter.GaussianBlur(22))
    im = Image.blend(im, Image.new("RGB", (W, H), DARK), 0.62)
    im.save(p, "PNG")
    return p


def make_endcard_overlay():
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    ec = ENDCARD
    akw = gp._arabic_draw_kwargs() if LANG == "ar" else {}
    font_path = gp.FONT_AR_PATH if LANG == "ar" else gp.FONT_KO_PATH
    wrap = gp.wrap_arabic if LANG == "ar" else gp.wrap_korean

    tf = gp.load_variable_font(gp.FONT_KO_PATH, 96, "Bold")
    t = ec.get("title", "Shop@KBridge")
    d.text((W / 2 - d.textlength(t, font=tf) / 2, int(H * 0.36)), t, font=tf, fill=(255, 255, 255, 255))
    d.line([(W / 2 - 120, int(H * 0.36) + 140), (W / 2 + 120, int(H * 0.36) + 140)],
           fill=ACCENT + (240,), width=4)
    sf = gp.load_variable_font(font_path, 46, "Bold")
    gp.draw_centered_multiline(d, wrap(d, ec["sub"][LANG], sf, int(W * 0.84)), sf, W / 2,
                               int(H * 0.36) + 190, fill=ACCENT, line_gap=10, extra_draw_kwargs=akw)
    hf = gp.load_variable_font(gp.FONT_KO_PATH, 58, "Bold")
    hd = ec.get("handle", "@shopatkbridge")
    d.text((W / 2 - d.textlength(hd, font=hf) / 2, int(H * 0.52)), hd, font=hf, fill=(255, 255, 255, 255))
    if ec.get("small"):
        mf = gp.load_variable_font(font_path, 34, "Regular")
        gp.draw_centered_multiline(d, wrap(d, ec["small"][LANG], mf, int(W * 0.84)), mf, W / 2,
                                   int(H * 0.585), fill=(255, 255, 255), line_gap=8, extra_draw_kwargs=akw)
    bf = gp.load_variable_font(gp.FONT_KO_PATH, 34, "Regular")
    d.text((W / 2 - d.textlength(BRAND, font=bf) / 2, H - 130), BRAND, font=bf, fill=(255, 255, 255, 180))
    p = os.path.join(OUT, f"ov2_{LANG}_{SLUG}_end.png")
    ov.save(p, "PNG")
    return p


# ---------------------------------------------------------------- 오디오/합성
async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE, rate="-5%").save(path)


def make_audio(scene):
    p = os.path.join(OUT, f"audio2_{LANG}_{SLUG}_{scene['id']}.mp3")
    asyncio.run(_tts(scene["narr"][LANG], p))
    return p


def duration(path):
    return float(subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path]).strip())


GRADE = ("eq=contrast=1.05:saturation=1.06:brightness=0.01,"
         "colorbalance=rs=.025:gs=.005:bs=-.02:rm=.02:bm=-.015,"
         "vignette=PI/5")


def compose(scene, kind, media, overlay, audio):
    dur = duration(audio) + 0.9
    out = os.path.join(OUT, f"sc2_{LANG}_{SLUG}_{scene['id']}.mp4")
    frames = int(dur * FPS) + 2
    if kind == "video":
        bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},setsar=1,fps={FPS},{GRADE}[bg]")
        pre = ["-stream_loop", "-1", "-i", media]
    else:
        bg = (f"[0:v]zoompan=z='min(1.0+0.00045*on,1.13)':"
              f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s={W}x{H}:fps={FPS},"
              f"setsar=1,{GRADE}[bg]")
        pre = ["-loop", "1", "-i", media]
    fc = (bg + ";"
          f"[1:v]format=rgba,fade=t=in:st=0.35:d=0.45:alpha=1,"
          f"fade=t=out:st={dur-0.85:.2f}:d=0.5:alpha=1[ovf];"
          f"[bg][ovf]overlay=0:0,format=yuv420p[v];"
          f"[2:a]adelay=400|400,apad[a]")
    cmd = [FFMPEG, "-y"] + pre + ["-loop", "1", "-t", f"{dur:.2f}", "-i", overlay, "-i", audio,
           "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-crf", "19",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out, dur


def compose_endcard():
    dur = 3.4
    bg = make_endcard_bg()
    ovp = make_endcard_overlay()
    out = os.path.join(OUT, f"sc2_{LANG}_{SLUG}_end.mp4")
    fc = (f"[0:v]scale={W}:{H},setsar=1,fps={FPS}[bg];"
          f"[1:v]format=rgba,fade=t=in:st=0.2:d=0.5:alpha=1[ovf];"
          f"[bg][ovf]overlay=0:0,format=yuv420p[v]")
    cmd = [FFMPEG, "-y", "-loop", "1", "-t", f"{dur}", "-i", bg,
           "-loop", "1", "-t", f"{dur}", "-i", ovp,
           "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=44100:cl=stereo",
           "-filter_complex", fc, "-map", "[v]", "-map", "2:a",
           "-t", f"{dur}", "-r", str(FPS), "-c:v", "libx264", "-crf", "19",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out, dur


def assemble(clips, durs):
    """크로스페이드로 이어붙이고 배경음악을 덕킹 믹스."""
    final = os.path.join(OUT, f"{SLUG}_reel_{LANG}.mp4")
    n = len(clips)
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    music_idx = n
    inputs += ["-stream_loop", "-1", "-i", MUSIC]

    fc, vprev, aprev = [], "0:v", "0:a"
    cur = durs[0]
    for i in range(1, n):
        off = cur - XFADE
        vout, aout = f"v{i}", f"a{i}"
        fc.append(f"[{vprev}][{i}:v]xfade=transition=fade:duration={XFADE}:offset={off:.3f}[{vout}]")
        fc.append(f"[{aprev}][{i}:a]acrossfade=d={XFADE}[{aout}]")
        vprev, aprev = vout, aout
        cur = off + durs[i]
    total = cur
    fc.append(f"[{music_idx}:a]volume={MUSIC_VOL},atrim=0:{total:.2f},"
              f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0,total-3.0):.2f}:d=3.0[mt]")
    fc.append(f"[{aprev}]asplit=2[voice][key]")
    fc.append(f"[mt][key]sidechaincompress=threshold=0.02:ratio=10:attack=30:release=700[duck]")
    fc.append(f"[voice][duck]amix=inputs=2:duration=first:normalize=0[aout]")
    cmd = [FFMPEG, "-y"] + inputs + ["-filter_complex", ";".join(fc),
           "-map", f"[{vprev}]", "-map", "[aout]", "-t", f"{total:.2f}",
           "-r", str(FPS), "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", final]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"완성: {final} (약 {total:.0f}초)")
    return final


def build_one(lang):
    global LANG, VOICE
    LANG, VOICE = lang, VOICES[lang]
    print(f"=== 언어: {LANG} / 음성: {VOICE} ===")
    clips, durs = [], []
    for sc in SCENES:
        print(f"장면 {sc['id']} 처리 중…")
        kind, media = get_media(sc)
        clip, dur = compose(sc, kind, media, make_overlay(sc), make_audio(sc))
        clips.append(clip); durs.append(dur)
        print(f"    -> {kind}, {dur:.1f}초")
    if ENDCARD:
        clip, dur = compose_endcard()
        clips.append(clip); durs.append(dur)
        print(f"엔딩 카드 {dur:.1f}초")
    return assemble(clips, durs)


def make_cover():
    if not COVER:
        return None
    bg = None
    if COVER.get("scene"):
        sc = next((s for s in SCENES if s["id"] == COVER["scene"]), None)
        if sc and sc.get("pexels_id"):
            v = os.path.join(OUT, f"src_id{sc['pexels_id']}.mp4")
            if os.path.exists(v):
                fr = os.path.join(OUT, f"_cvfr_{SLUG}.png")
                subprocess.run([FFMPEG, "-y", "-ss", "1.2", "-i", v, "-frames:v", "1", fr],
                               check=True, capture_output=True)
                bg = Image.open(fr).convert("RGB")
    if bg is None:
        bg = gp.create_celadon_background((W, H)).convert("RGB")
    im = cover_fit(bg, (W, H))
    im = Image.blend(im, Image.new("RGB", (W, H), (0, 0, 0)), 0.45).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    cy = H // 2
    for y in range(H):
        d.line([(0, y), (W, y)], fill=DARK + (int(150 * abs(y - cy) / cy),))
    im = Image.alpha_composite(im, ov); d = ImageDraw.Draw(im)
    akw = gp._arabic_draw_kwargs()
    tf = gp.load_variable_font(gp.FONT_AR_PATH, 52, "Bold")
    gp.draw_centered_multiline(d, gp.wrap_arabic(d, COVER["tag"], tf, int(W * 0.86)), tf, W / 2,
                               int(H * 0.34), fill=ACCENT, line_gap=8, extra_draw_kwargs=akw)
    d.line([(W / 2 - 110, int(H * 0.34) + 82), (W / 2 + 110, int(H * 0.34) + 82)],
           fill=ACCENT + (220,), width=3)
    hf = gp.load_variable_font(gp.FONT_AR_PATH, 120, "Bold")
    gp.draw_centered_multiline(d, gp.wrap_arabic(d, COVER["hook"], hf, int(W * 0.92)), hf, W / 2,
                               int(H * 0.40), fill=(255, 255, 255), line_gap=16,
                               stroke_width=5, stroke_fill=DARK, extra_draw_kwargs=akw)
    bf = gp.load_variable_font(gp.FONT_KO_PATH, 40, "Regular")
    d.text((W / 2 - d.textlength("@bisaek.kr", font=bf) / 2, H - 120), "@bisaek.kr",
           font=bf, fill=(255, 255, 255, 220))
    out = os.path.join(OUT, f"{SLUG}_cover.png"); im.convert("RGB").save(out)
    print(f"커버 생성: {out}")
    return out


def main():
    if os.environ.get("COVER_ONLY"):
        make_cover(); return
    env = os.environ.get("LANG_CODES", "").strip()
    langs = [l.strip() for l in env.split(",") if l.strip()] or ["ar", "ko", "en"]
    for lg in langs:
        build_one(lg)
    make_cover()
    print("모든 언어 완료:", ", ".join(langs))


if __name__ == "__main__":
    main()
