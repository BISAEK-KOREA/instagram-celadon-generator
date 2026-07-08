# -*- coding: utf-8 -*-
"""사우디 여성 대상 '한국문화×한류' 1분 릴스 생성기 (v3 — 다국어: 아랍어/영어).
- 언어: 환경변수 LANG_CODE = "ar"(기본) 또는 "en"
- 음성: edge-tts (ar → ar-SA-ZariyahNeural / en → en-US-AriaNeural)
- 소재: Pexels 무료(상업이용OK). 장면별 영상 클립 우선, 없으면 사진, 그래도 없으면 청자빛 배경.
  * 이미 받아둔 소재 파일이 있으면 재다운로드 없이 재활용 → 언어별 영상이 동일한 화면을 씀
- 자막: 아랍어는 raqm-대응 RTL 렌더링, 영어는 일반 LTR 렌더링 (투명 오버레이 합성)

Pexels 키는 저장소에 넣지 않고 외부 파일에서 읽는다: C:\\Users\\leeka\\.pexels_key.txt
"""
import os, sys, subprocess, asyncio, re
from io import BytesIO
import requests
import edge_tts

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)
import generate_post as gp
from PIL import Image, ImageDraw

FFMPEG = r"C:\Users\leeka\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
OUT = os.path.join(PROJECT, "video_out")
os.makedirs(OUT, exist_ok=True)

PEXELS_KEY = open(r"C:\Users\leeka\.pexels_key.txt", encoding="utf-8").read().strip()
PX = {"Authorization": PEXELS_KEY}
UA = {"User-Agent": "bisaek-video/3.0"}

LANG = os.environ.get("LANG_CODE", "ar")
VOICES = {"ar": "ar-SA-ZariyahNeural", "en": "en-US-AriaNeural", "ko": "ko-KR-SunHiNeural"}
VOICE = VOICES[LANG]
W, H = 1080, 1920
FPS = 30
BRAND = "@bisaek.kr"

SCENES = [
    {"id": "01", "media": "video", "q": "glowing skin face beauty",
     "narr": {"ar": "بشرة تلمع كالزجاج… هل تعلمين أنّ سرّها عمره مئات السنين؟",
              "en": "Skin that glows like glass… did you know its secret is centuries old?",
              "ko": "유리처럼 빛나는 피부. 그 비밀이 수백 년 전부터 시작됐다는 걸 아세요?"},
     "sub": {"ar": "بشرة الزجاج… سرٌّ عمره قرون", "en": "Glass skin — a secret centuries old",
             "ko": "글래스 스킨 — 수백 년 된 비밀"}},
    {"id": "02", "media": "video", "q": "korea palace traditional",
     "narr": {"ar": "«بشرة الزجاج» ليست صيحة جديدة، بل إرثٌ من نساء عصر جوسون في كوريا القديمة.",
              "en": "'Glass skin' is not a new trend — it's a legacy from the women of Korea's Joseon era.",
              "ko": "'글래스 스킨'은 새로운 유행이 아니에요. 조선시대 여성들이 물려준 유산이죠."},
     "sub": {"ar": "ليست صيحة… بل إرثٌ من عصر جوسون", "en": "Not a trend — a Joseon-era legacy",
             "ko": "유행이 아니라 조선의 유산"}},
    {"id": "03", "media": "video", "q": "woman skincare routine",
     "narr": {"ar": "بالنسبة للمرأة الكورية، العناية بالبشرة طقسٌ يومي من عدة مراحل: تنظيف مزدوج، تونر، إيسنس، سيروم، ثم ترطيب. تمنحه وقتًا وحبًّا كل صباح ومساء.",
              "en": "For Korean women, skincare is not one step but a daily ritual of many stages: double cleansing, toner, essence, serum, then moisturizing — given time and love every morning and night.",
              "ko": "한국 여성에게 스킨케어는 한 단계가 아니라 여러 단계의 매일 의식이에요. 이중 세안, 토너, 에센스, 세럼, 그리고 보습까지. 아침저녁으로 시간과 정성을 들이죠."},
     "sub": {"ar": "العناية = طقسٌ يومي من عدة مراحل", "en": "Skincare — a daily multi-step ritual",
             "ko": "스킨케어 — 매일의 여러 단계 의식"}},
    {"id": "04", "media": "video", "q": "honey dripping",
     "narr": {"ar": "وفي قلب هذه العناية مكوّناتٌ تقليدية: ماء الأرز للإشراق، والجينسنغ للحيوية، والعسل والشيح للترطيب والتهدئة.",
              "en": "At the heart of this care are traditional ingredients: rice water for radiance, ginseng for vitality, and honey and mugwort for hydration and soothing.",
              "ko": "그 중심엔 전통 재료가 있어요. 환하게 하는 쌀뜨물, 생기를 주는 인삼, 그리고 보습과 진정의 꿀과 쑥이죠."},
     "sub": {"ar": "ماء الأرز · الجينسنغ · العسل والشيح", "en": "Rice water · Ginseng · Honey & mugwort",
             "ko": "쌀뜨물 · 인삼 · 꿀과 쑥"}},
    {"id": "05", "media": "photo", "q": "beige silk fabric",
     "narr": {"ar": "وهذه المكوّنات تعيش اليوم في أشهر منتجات «هانبانغ» الكورية.",
              "en": "And these ingredients live on today in Korea's most popular 'hanbang' products.",
              "ko": "이 재료들은 오늘날 인기 있는 한방 화장품에 그대로 살아 있어요."},
     "sub": {"ar": "أشهر منتجات هانبانغ اليوم", "en": "Today's popular hanbang products",
             "ko": "오늘날 인기 한방 제품"},
     "products": {
         "ar": ["سولهواسو · يونجو إيسنس — إشراق ونضارة — ‏٢٨٤ ﷼‏",
                "هانيول · تونر الشيح — تهدئة وترطيب — ‏٧٣ ﷼‏",
                "هوو · بيتشوب إيسنس — فخامة وشدّ — ‏٤٢٢ ﷼‏"],
         "en": ["Sulwhasoo First Care Serum — glow — ~284 SAR",
                "Hanyul Artemisia Toner — soothing — ~73 SAR",
                "Whoo Bichup Essence — firming — ~422 SAR"],
         "ko": ["설화수 윤조에센스 — 광채 — 약 10.5만원",
                "한율 어린쑥 토너 — 진정 — 약 2.7만원",
                "더후 비첩 자생 에센스 — 탄력 — 약 15.6만원"]}},
    {"id": "06", "media": "video", "q": "korea seoul lantern night",
     "narr": {"ar": "جمالٌ نابعٌ من الطبيعة والتقاليد. تابِعينا لمزيدٍ من أسرار الجمال والثقافة الكورية.",
              "en": "Beauty born from nature and tradition. Follow us for more secrets of Korean beauty and culture.",
              "ko": "자연과 전통에서 피어난 아름다움. 한국의 미와 문화 이야기를 더 보려면 팔로우하세요."},
     "sub": {"ar": "تابِعينا — جمال وثقافة كوريا", "en": "Follow us — Korean beauty & culture",
             "ko": "팔로우하세요 — 한국의 미와 문화"}},
]


def _slug(q):
    return re.sub(r"[^a-z0-9]+", "_", q.lower())[:14]


def fetch_video(query):
    path = os.path.join(OUT, f"src_{_slug(query)}.mp4")
    if os.path.exists(path) and os.path.getsize(path) > 40000:
        print(f"    영상 재활용: {query}")
        return path
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers=PX,
                         params={"query": query, "orientation": "portrait",
                                 "per_page": 10, "size": "medium"}, timeout=25)
        r.raise_for_status()
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("link")]
            files.sort(key=lambda f: (f.get("height") or 0))
            choice = next((f for f in files if (f.get("height") or 0) >= 1200), files[-1] if files else None)
            if not choice:
                continue
            try:
                data = requests.get(choice["link"], headers=UA, timeout=60).content
                if len(data) > 40000:
                    open(path, "wb").write(data)
                    print(f"    영상 OK: {query} ({choice.get('width')}x{choice.get('height')})")
                    return path
            except Exception:
                continue
    except Exception as e:
        print(f"    영상 검색 실패({query}): {e}")
    return None


def fetch_photo(query):
    try:
        r = requests.get("https://api.pexels.com/v1/search", headers=PX,
                         params={"query": query, "orientation": "portrait",
                                 "per_page": 10, "size": "large"}, timeout=25)
        r.raise_for_status()
        for ph in r.json().get("photos", []):
            src = ph.get("src", {})
            url = src.get("large2x") or src.get("large") or src.get("portrait") or src.get("original")
            if not url:
                continue
            try:
                data = requests.get(url, headers=UA, timeout=30).content
                img = Image.open(BytesIO(data)).convert("RGB")
                if img.width >= 600 and img.height >= 600:
                    print(f"    사진 OK: {query} ({img.width}x{img.height})")
                    return img
            except Exception:
                continue
    except Exception as e:
        print(f"    사진 검색 실패({query}): {e}")
    return None


def cover_fit(img, size):
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    nw, nh = img.size
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def get_media(scene):
    bgpath = os.path.join(OUT, f"bg_{scene['id']}.png")
    if scene.get("media") == "video":
        vp = fetch_video(scene["q"]) if scene.get("q") else None
        if vp:
            return "video", vp
    if os.path.exists(bgpath):
        print(f"    사진 재활용: 장면 {scene['id']}")
        return "photo", bgpath
    img = fetch_photo(scene["q"]) if scene.get("q") else None
    if img is None:
        img = gp.create_celadon_background((W, H), seed=int(scene["id"]) * 7 + 3).convert("RGB")
        print(f"    (장면 {scene['id']}: 청자빛 배경 대체)")
    cover_fit(img, (W, H)).save(bgpath, "PNG")
    return "photo", bgpath


def make_overlay(scene):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rtl = (LANG == "ar")
    akw = gp._arabic_draw_kwargs() if rtl else {}
    font_path = gp.FONT_AR_PATH if rtl else gp.FONT_KO_PATH
    wrap = gp.wrap_arabic if rtl else gp.wrap_korean

    start = int(H * 0.50)
    for y in range(start, H):
        d.line([(0, y), (W, y)], fill=(8, 18, 14, int(200 * (y - start) / (H - start))))
    for y in range(0, int(H * 0.18)):
        d.line([(0, y), (W, y)], fill=(8, 18, 14, int(120 * (1 - y / (H * 0.18)))))

    bf = gp.load_variable_font(gp.FONT_KO_PATH, 34, "Regular")
    d.text((W - 44 - d.textlength(BRAND, font=bf), 44), BRAND, font=bf, fill=(255, 255, 255, 220))

    sub = scene["sub"][LANG]
    if scene.get("products"):
        tfont = gp.load_variable_font(font_path, 58, "Bold")
        gp.draw_centered_multiline(d, wrap(d, sub, tfont, int(W * 0.86)), tfont, W / 2,
                                   int(H * 0.20), fill=(240, 244, 238), line_gap=14,
                                   stroke_width=3, stroke_fill=(10, 25, 18), extra_draw_kwargs=akw)
        cfont = gp.load_variable_font(font_path, 42, "Bold")
        y = int(H * 0.38)
        for p in scene["products"][LANG]:
            d.rounded_rectangle([int(W * 0.07), y, int(W * 0.93), y + 150], radius=28, fill=(18, 30, 25, 205))
            gp.draw_centered_multiline(d, wrap(d, p, cfont, int(W * 0.82)), cfont, W / 2, y + 30,
                                       fill=(255, 255, 255), line_gap=8, stroke_width=2,
                                       stroke_fill=(10, 25, 18), extra_draw_kwargs=akw)
            y += 180
    else:
        sfont = gp.load_variable_font(font_path, 66 if rtl else 60, "Bold")
        gp.draw_centered_multiline(d, wrap(d, sub, sfont, int(W * 0.86)), sfont, W / 2,
                                   int(H * 0.66), fill=(255, 255, 255), line_gap=18,
                                   stroke_width=3, stroke_fill=(10, 25, 18), extra_draw_kwargs=akw)

    p = os.path.join(OUT, f"ov_{LANG}_{scene['id']}.png")
    ov.save(p, "PNG")
    return p


async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE).save(path)


def make_audio(scene):
    p = os.path.join(OUT, f"audio_{LANG}_{scene['id']}.mp3")
    asyncio.run(_tts(scene["narr"][LANG], p))
    return p


def duration(path):
    return float(subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path]).strip())


def compose(scene, kind, media, overlay, audio):
    dur = duration(audio) + 0.7
    out = os.path.join(OUT, f"scene_{LANG}_{scene['id']}.mp4")
    fades = f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur-0.4:.2f}:d=0.4"
    base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
            + (f",fps={FPS}" if kind == "video" else "") + "[bg];"
            f"[bg][1:v]overlay=0:0,{fades},format=yuv420p[v]")
    pre = ["-stream_loop", "-1", "-i", media] if kind == "video" else ["-loop", "1", "-i", media]
    cmd = [FFMPEG, "-y"] + pre + ["-i", overlay, "-i", audio,
           "-filter_complex", base, "-map", "[v]", "-map", "2:a",
           "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out, dur


def build_one(lang):
    global LANG, VOICE
    LANG, VOICE = lang, VOICES[lang]
    print(f"=== 언어: {LANG} / 음성: {VOICE} ===")
    clips, total = [], 0.0
    for sc in SCENES:
        print(f"장면 {sc['id']} 처리 중…")
        kind, media = get_media(sc)
        clip, dur = compose(sc, kind, media, make_overlay(sc), make_audio(sc))
        clips.append(clip); total += dur
        print(f"    -> {kind}, {dur:.1f}초")
    listfile = os.path.join(OUT, f"concat_{LANG}.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{c.replace(os.sep, '/')}'\n")
    final = os.path.join(OUT, f"glass_skin_reel_{LANG}.mp4")
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", final],
                   check=True, capture_output=True)
    print(f"완성: {final} (약 {total:.0f}초)\n")
    return final


def main():
    # 기본값: 아랍어(기본) + 한국어 + 영어 세 버전 모두 생성.
    # 특정 언어만 만들려면 환경변수 LANG_CODES="ar" 또는 "ar,en" 처럼 지정.
    env = os.environ.get("LANG_CODES", "").strip()
    langs = [l.strip() for l in env.split(",") if l.strip()] or ["ar", "ko", "en"]
    for lg in langs:
        build_one(lg)
    print("모든 언어 완료:", ", ".join(langs))


if __name__ == "__main__":
    main()
