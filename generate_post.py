"""
인스타그램용 비색(청자색) 배경 이미지 포스트 자동 생성기
- 표준 인스타그램 세로 사이즈: 1080x1350 (4:5)
- 한국어 + 아랍어(RTL, 자소 결합 reshaping) 텍스트 지원
- 단일 포스트 생성 또는 JSON 목록을 읽어 일괄(batch) 자동 생성

필요 패키지:
    pip install pillow arabic-reshaper python-bidi requests

사용 예:
    # 단일 포스트
    python generate_post.py --ko "고요함 속의 아름다움" --ar "الجمال في السكون" --tag "청자 이야기" --handle "@museum.official"

    # 일괄 생성
    python generate_post.py --batch posts.json

Instagram 자동 게시 (--upload):
    아이디/비밀번호 로그인 자동화는 이용약관 위반 및 계정 정지 위험이 있어 지원하지 않는다.
    대신 공식 "Instagram API with Instagram Login"(Business Login for Instagram)을 사용한다.
    단일 계정(자기 소유) 운영에 Meta가 권장하는 방식으로, Facebook 페이지 연결이 필요 없다. 사전 준비:
      1. 인스타그램 계정을 비즈니스/크리에이터 계정으로 전환
      2. Meta 개발자 앱에 Instagram > "API setup with Instagram login" 제품 추가,
         instagram_business_basic, instagram_business_content_publish 권한으로
         OAuth 진행 후 장기(60일) 액세스 토큰 발급
      3. output 폴더의 이미지를 공개 URL로 접근 가능한 곳(GitHub Pages 등)에
         동일 파일명으로 호스팅 (Graph API가 image_url을 직접 fetch하기 때문에 로컬 파일 불가)
      4. 환경변수 설정 후 --upload 플래그로 실행
         set IG_USER_ID=...
         set IG_ACCESS_TOKEN=...
         set PUBLIC_BASE_URL=https://example.com/celadon-posts
         python generate_post.py --ko "..." --ar "..." --upload

완전 자동(예약) 게시 — GitHub Actions에서 사용:
    .github/workflows/auto-post.yml 이 정해진 요일에 자동으로 아래 순서를 실행한다.
      1. --refresh-token: 60일 장기 토큰을 다시 60일로 갱신 (매 실행마다, 만료 방지)
      2. --next: posts.json 중 다음 순서 1개만 생성해 docs/ 에 저장하고 state.json 갱신
      3. 생성된 docs/ 이미지를 git commit + push (GitHub Pages로 공개됨)
      4. 잠시 대기 후 --publish: 방금 만든 이미지를 실제로 Instagram에 게시
    사람이 할 일은 GitHub 저장소 생성/Pages 활성화, IG_USER_ID·IG_ACCESS_TOKEN을
    저장소 Secrets에 등록하는 것뿐 — 그 이후로는 매번 자동 실행된다.
"""

import argparse
import json
import os
import random
import textwrap
import time
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_SUPPORT = True
except ImportError:
    ARABIC_SUPPORT = False

# Pillow가 libraqm(HarfBuzz)로 빌드됐는지 여부.
# raqm이 있으면 draw.text()가 아랍어의 글자 결합(shaping)+방향(bidi)을 '자동'으로 처리한다.
# 이때 우리가 수동 reshape+bidi까지 하면 '이중 처리'가 되어 글자가 깨진다.
#  - Windows 로컬 Pillow: raqm 없음  → 수동 reshape+bidi 필요
#  - GitHub Actions Pillow: raqm 있음 → 원문을 그대로 넘기고 엔진에 맡겨야 함
# 환경에 따라 경로를 갈라, 어디서 실행하든 '항상 올바른' 아랍어가 나오게 한다.
RAQM_AVAILABLE = features.check("raqm")

CANVAS_SIZE = (1080, 1350)

# 청자 비색(翡色) 팔레트: 옅은 옥빛 ~ 짙은 청록
CELADON_LIGHT = (196, 219, 205)
CELADON_MID = (139, 174, 158)
CELADON_DEEP = (76, 107, 92)
CELADON_CRACKLE = (58, 84, 71)

# Windows에만 있는 폰트(맑은 고딕/Tahoma) 대신, 라이선스 걱정 없이 어디서나(GitHub Actions
# 같은 리눅스 서버 포함) 똑같이 렌더링되도록 오픈소스 Noto 폰트를 프로젝트에 동봉해서 쓴다.
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
FONT_KO_PATH = os.path.join(FONTS_DIR, "NotoSansKR.ttf")
FONT_AR_PATH = os.path.join(FONTS_DIR, "NotoNaskhArabic.ttf")

# 실제 비색청자 사진을 여기에 넣어두면 --bg-image 없이도 기본 배경으로 사용됩니다.
DEFAULT_BG_IMAGE = os.path.join(ASSETS_DIR, "celadon_bg.jpg")

# ---------------------------------------------------------------------------
# Instagram API with Instagram Login (Business Login for Instagram) 설정
#
# 인스타그램은 아이디/비밀번호 로그인 자동화를 금지하며(이용약관 위반, 계정 정지 위험),
# 공식적으로는 Business/Creator 계정 + Meta 개발자 앱을 통한 공식 API만 지원한다.
# 단일 계정(자기 소유) 운영에는 Facebook 페이지 연결이 필요 없는 "Instagram API with
# Instagram Login"이 Meta가 권장하는 더 간단한 방식이라 이걸 사용한다.
# 필요한 값은 코드에 직접 적지 말고 환경변수로 설정한다.
#   IG_USER_ID       Instagram Login으로 로그인해서 얻은 Instagram 계정 ID
#   IG_ACCESS_TOKEN  instagram_business_content_publish 권한이 있는 장기 액세스 토큰
#   PUBLIC_BASE_URL  output 폴더 이미지가 실제로 공개 접근 가능한 URL prefix
#                    (Graph API는 서버가 image_url을 직접 fetch하므로 로컬 파일은 불가)
# ---------------------------------------------------------------------------
GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"

DEFAULT_HASHTAGS_KO = ["#비색", "#청자", "#고려청자", "#한국도자기", "#전통색"]
DEFAULT_HASHTAGS_AR = ["#السيراميك_الكوري", "#اللون_الفيروزي", "#كوريا", "#فن_كوري"]


class InstagramUploadError(RuntimeError):
    pass


def build_caption(ko_text, ar_text="", extra_hashtags=None):
    """한국어/아랍어 본문과 해시태그를 하나의 인스타그램 캡션으로 합친다."""
    parts = [t for t in (ar_text, ko_text) if t]
    body = "\n\n".join(parts)
    hashtags = list(DEFAULT_HASHTAGS_AR) + list(DEFAULT_HASHTAGS_KO)
    if extra_hashtags:
        hashtags += list(extra_hashtags)
    hashtags = list(dict.fromkeys(hashtags))  # 순서를 유지하며 중복 제거
    return f"{body}\n.\n.\n.\n{' '.join(hashtags)}"


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise InstagramUploadError(
            f"환경변수 {name}가 설정되어 있지 않습니다. "
            "IG_USER_ID, IG_ACCESS_TOKEN, PUBLIC_BASE_URL을 설정한 뒤 다시 시도하세요."
        )
    return value


def _auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


def create_media_container(ig_user_id, access_token, image_url, caption):
    resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        headers=_auth_headers(access_token),
        data={"image_url": image_url, "caption": caption},
        timeout=30,
    )
    data = resp.json()
    if "id" not in data:
        raise InstagramUploadError(f"미디어 컨테이너 생성 실패: {data}")
    return data["id"]


def wait_for_container(creation_id, access_token, timeout=120, interval=3):
    elapsed = 0
    while elapsed < timeout:
        resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            headers=_auth_headers(access_token),
            params={"fields": "status_code,status"},
            timeout=30,
        )
        data = resp.json()
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise InstagramUploadError(f"미디어 처리 실패: {data}")
        time.sleep(interval)
        elapsed += interval
    raise InstagramUploadError("미디어 컨테이너 처리 대기 시간 초과")


def publish_media(ig_user_id, access_token, creation_id):
    resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
        headers=_auth_headers(access_token),
        data={"creation_id": creation_id},
        timeout=30,
    )
    data = resp.json()
    if "id" not in data:
        raise InstagramUploadError(f"게시 실패: {data}")
    return data["id"]


def refresh_long_lived_token(access_token):
    """60일짜리 장기 토큰의 유효기간을 다시 60일로 연장한다.
    GitHub Actions에서 매 실행마다 호출해 토큰이 만료되지 않게 갱신한다."""
    resp = requests.get(
        f"{GRAPH_API_BASE}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": access_token},
        timeout=30,
    )
    data = resp.json()
    if "access_token" not in data:
        raise InstagramUploadError(f"토큰 갱신 실패: {data}")
    return data["access_token"]


def upload_to_instagram(image_path, caption, public_base_url=None, ig_user_id=None, access_token=None):
    """output 폴더의 이미지를 Instagram Graph API로 게시한다.
    image_path는 반드시 public_base_url 아래에 동일한 파일명으로 이미 공개 호스팅되어 있어야 한다."""
    ig_user_id = ig_user_id or _require_env("IG_USER_ID")
    access_token = access_token or _require_env("IG_ACCESS_TOKEN")
    public_base_url = (public_base_url or _require_env("PUBLIC_BASE_URL")).rstrip("/")
    image_url = f"{public_base_url}/{os.path.basename(image_path)}"

    print(f"[Instagram] 미디어 컨테이너 생성 중... ({image_url})")
    creation_id = create_media_container(ig_user_id, access_token, image_url, caption)
    print(f"[Instagram] 처리 대기 중... (container id: {creation_id})")
    wait_for_container(creation_id, access_token)
    print("[Instagram] 게시 중...")
    media_id = publish_media(ig_user_id, access_token, creation_id)
    print(f"[Instagram] 게시 완료. media id: {media_id}")
    return media_id


def create_reel_container(ig_user_id, access_token, video_url, caption, thumb_offset=None, cover_url=None):
    """릴스(영상) 컨테이너 생성. 이미지와 달리 media_type=REELS + video_url을 쓴다.
    영상은 반드시 공개 URL(GitHub Pages 등)에 올라가 있어야 API가 직접 가져간다.
    thumb_offset(ms): 표지(썸네일)를 영상의 이 지점에서 잡는다. 페이드인 때문에
    맨 첫 프레임이 검정이면 표지가 검게 나오므로, 중간 프레임을 지정해 방지한다."""
    data = {"media_type": "REELS", "video_url": video_url, "caption": caption}
    if cover_url:
        data["cover_url"] = cover_url  # 지정한 공개 이미지 URL을 표지로 사용(브랜드 커버)
    elif thumb_offset is not None:
        data["thumb_offset"] = str(thumb_offset)
    resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        headers=_auth_headers(access_token),
        data=data,
        timeout=30,
    )
    data = resp.json()
    if "id" not in data:
        raise InstagramUploadError(f"릴스 컨테이너 생성 실패: {data}")
    return data["id"]


def publish_reel(video_url, caption, ig_user_id=None, access_token=None, thumb_offset=1200, cover_url=None):
    """공개 video_url의 영상을 Instagram 릴스로 게시한다.
    영상 처리(트랜스코딩)에 시간이 걸리므로 대기 시간을 넉넉히 잡는다.
    cover_url: 지정 시 이 공개 이미지가 표지(브랜드 커버)가 된다.
    thumb_offset(ms): cover_url이 없을 때 표지를 잡을 지점(기본 1.2초 — 검은 첫 프레임 회피)."""
    ig_user_id = ig_user_id or _require_env("IG_USER_ID")
    access_token = access_token or _require_env("IG_ACCESS_TOKEN")

    print(f"[Instagram] 릴스 컨테이너 생성 중... ({video_url})")
    creation_id = create_reel_container(ig_user_id, access_token, video_url, caption,
                                        thumb_offset=thumb_offset, cover_url=cover_url)
    print(f"[Instagram] 영상 처리 대기 중... (container id: {creation_id})")
    wait_for_container(creation_id, access_token, timeout=600, interval=5)
    print("[Instagram] 게시 중...")
    media_id = publish_media(ig_user_id, access_token, creation_id)
    print(f"[Instagram] 릴스 게시 완료. media id: {media_id}")
    return media_id


def load_variable_font(path, size, variation_name):
    """가변 폰트(Variable Font)를 열어 Regular/Bold 등 지정된 굵기 인스턴스로 설정한다."""
    if not os.path.exists(path):
        print(f"[경고] 폰트를 찾을 수 없어 기본 폰트로 대체합니다: {path}")
        return ImageFont.load_default()
    font = ImageFont.truetype(path, size)
    try:
        font.set_variation_by_name(variation_name)
    except (AttributeError, OSError):
        pass  # 가변 폰트가 아니거나 해당 인스턴스가 없으면 기본 굵기로 사용
    return font


# ---------------------------------------------------------------------------
# 배경: 비색 청자 유약 질감 (그라데이션 + 빙렬(氷裂) 크랙 + 스펙클 + 비네트)
# ---------------------------------------------------------------------------

def create_celadon_background(size=CANVAS_SIZE, seed=None):
    rng = random.Random(seed)
    w, h = size
    bg = Image.new("RGB", size, CELADON_MID)

    # 중심에서 가장자리로 퍼지는 방사형 그라데이션 (도자기 유약이 얇게/두껍게 고인 느낌)
    cx, cy = w * rng.uniform(0.35, 0.5), h * rng.uniform(0.3, 0.45)
    max_dist = ((max(cx, w - cx)) ** 2 + (max(cy, h - cy)) ** 2) ** 0.5
    grad = Image.new("L", size)
    grad_px = grad.load()
    for y in range(h):
        for x in range(0, w, 2):  # 2px씩 건너뛰어 속도 확보 후 리사이즈로 보완
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_dist
            v = int(255 * min(1.0, d))
            grad_px[x, y] = v
            if x + 1 < w:
                grad_px[x + 1, y] = v
    bg = Image.composite(
        Image.new("RGB", size, CELADON_DEEP),
        Image.new("RGB", size, CELADON_LIGHT),
        grad,
    )
    bg = Image.blend(bg, Image.new("RGB", size, CELADON_MID), 0.25)

    # 빙렬(유약 크랙) 패턴: 얇고 불규칙한 선을 흐릿하게 겹쳐 도자기 특유의 질감 표현
    crackle = Image.new("RGBA", size, (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(crackle)
    for _ in range(rng.randint(18, 28)):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        points = [(x0, y0)]
        for _ in range(rng.randint(3, 6)):
            x0 += rng.uniform(-90, 90)
            y0 += rng.uniform(-90, 90)
            points.append((x0, y0))
        alpha = rng.randint(18, 40)
        cdraw.line(points, fill=(*CELADON_CRACKLE, alpha), width=1)
    crackle = crackle.filter(ImageFilter.GaussianBlur(0.6))
    bg = Image.alpha_composite(bg.convert("RGBA"), crackle)

    # 미세 스펙클 노이즈로 유광 질감 추가
    speckle = Image.new("RGBA", size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(speckle)
    for _ in range(900):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h)
        r = rng.uniform(0.5, 1.6)
        alpha = rng.randint(6, 22)
        tone = rng.choice([CELADON_LIGHT, CELADON_CRACKLE])
        sdraw.ellipse([x - r, y - r, x + r, y + r], fill=(*tone, alpha))
    speckle = speckle.filter(ImageFilter.GaussianBlur(0.4))
    bg = Image.alpha_composite(bg, speckle)

    # 비네트 (가장자리를 살짝 어둡게)
    vignette = Image.new("L", size, 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse([-w * 0.25, -h * 0.2, w * 1.25, h * 1.2], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(180))
    vignette = ImageOps.invert(vignette)
    dark = Image.new("RGBA", size, (20, 35, 28, 0))
    dark.putalpha(vignette.point(lambda p: int(p * 0.55)))
    bg = Image.alpha_composite(bg, dark)

    return bg.convert("RGB")


def load_photo_background(path, size=CANVAS_SIZE, darken=0.35):
    """실제 청자 사진을 배경으로 쓰고 싶을 때: cover 방식으로 리사이즈/크롭 후 텍스트 가독성을 위해 어둡게 처리."""
    img = Image.open(path).convert("RGB")
    img = ImageOps.fit(img, size, Image.LANCZOS)
    overlay = Image.new("RGB", size, (10, 20, 16))
    return Image.blend(img, overlay, darken)


# ---------------------------------------------------------------------------
# 텍스트 레이아웃
# ---------------------------------------------------------------------------

def shape_arabic(text):
    if not ARABIC_SUPPORT:
        raise RuntimeError(
            "아랍어 렌더링에는 arabic-reshaper, python-bidi 패키지가 필요합니다.\n"
            "설치: pip install arabic-reshaper python-bidi"
        )
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _arabic_draw_kwargs():
    """아랍어를 그릴 때 draw.text()/textbbox()/textlength()에 넘길 추가 인자.
    raqm이 있을 때만 방향을 rtl로 지정한다(없는 환경에서 이 인자를 주면 오류)."""
    return {"direction": "rtl", "language": "ar"} if RAQM_AVAILABLE else {}


def prepare_arabic_line(text):
    """한 줄의 아랍어(논리 순서)를 '실제로 그릴 문자열'로 변환한다.
    - raqm 있음: 원문 그대로 반환(엔진이 shaping+bidi 처리) — 이중 처리 방지
    - raqm 없음: 수동 reshape+bidi로 시각 순서 문자열 생성"""
    if RAQM_AVAILABLE:
        return text
    return shape_arabic(text)


def check_render_env():
    """실행 환경에서 아랍어가 올바르게 렌더링될 수 있는지 점검한다.
    문제가 있으면 SystemExit로 '시끄럽게' 실패시켜, 깨진 이미지가 게시되는 것을 CI 단계에서 막는다."""
    import PIL
    path = "raqm(엔진 자동 shaping)" if RAQM_AVAILABLE else "수동 reshape+bidi"
    print(f"Pillow {PIL.__version__} | raqm={RAQM_AVAILABLE} | arabic_pkgs={ARABIC_SUPPORT} | 아랍어 경로: {path}")

    # raqm이 없는 환경에서는 수동 처리 패키지가 반드시 있어야 한다.
    if not RAQM_AVAILABLE and not ARABIC_SUPPORT:
        raise SystemExit(
            "❌ 아랍어를 렌더링할 방법이 없습니다(raqm 없음 + arabic-reshaper/python-bidi 미설치).\n"
            "   pip install arabic-reshaper python-bidi 또는 raqm 지원 Pillow가 필요합니다."
        )

    # 실제로 한 줄을 그려봐서 예외 없이 통과하는지 확인(스모크 테스트).
    probe = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(probe)
    try:
        f = load_variable_font(FONT_AR_PATH, 40, "Bold")
    except Exception:
        f = ImageFont.truetype(FONT_AR_PATH, 40)
    lines = wrap_arabic(d, "الجمال في السكون", f, 380)
    draw_centered_multiline(d, lines, f, 200, 20, fill=(0, 0, 0), extra_draw_kwargs=_arabic_draw_kwargs())
    print("✅ 아랍어 렌더링 스모크 테스트 통과")


def _break_long_token(draw, token, font, max_width):
    """공백 없이 max_width보다 긴 단어(URL 등)를 글자 단위로 쪼갠다."""
    chunks, chunk = [], ""
    for ch in token:
        trial = chunk + ch
        if draw.textlength(trial, font=font) > max_width and chunk:
            chunks.append(chunk)
            chunk = ch
        else:
            chunk = trial
    if chunk:
        chunks.append(chunk)
    return chunks


def wrap_korean(draw, text, font, max_width):
    """어절(단어) 단위로 줄바꿈하고, 개별 단어가 max_width를 넘으면 글자 단위로 쪼갠다.
    명시적 개행(\\n)은 문단 구분으로 그대로 유지한다."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            if not word:
                continue
            candidate = f"{current} {word}" if current else word
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if draw.textlength(word, font=font) <= max_width:
                current = word
            else:
                *full_chunks, current = _break_long_token(draw, word, font, max_width)
                lines.extend(full_chunks)
        if current:
            lines.append(current)
        if not paragraph:
            lines.append("")
    return lines


def wrap_arabic(draw, text, font, max_width):
    """단어(논리적 순서) 단위로 줄바꿈 후, 줄마다 '그릴 문자열'로 변환한다.
    변환 방식은 prepare_arabic_line()이 환경(raqm 유무)에 맞게 결정한다.
    명시적 개행(\\n)은 문단 구분으로 유지하고, 단어 자체가 max_width를 넘으면 글자 단위로 쪼갠다."""
    kw = _arabic_draw_kwargs()

    def width(logical_text):
        return draw.textlength(prepare_arabic_line(logical_text), font=font, **kw)

    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        current_words = []
        for word in words:
            candidate = " ".join(current_words + [word])
            if width(candidate) <= max_width:
                current_words.append(word)
                continue
            if current_words:
                lines.append(prepare_arabic_line(" ".join(current_words)))
                current_words = []
            if width(word) <= max_width:
                current_words = [word]
            else:
                lines.extend(prepare_arabic_line(c) for c in _break_long_token(draw, word, font, max_width))
        if current_words:
            lines.append(prepare_arabic_line(" ".join(current_words)))
        if not paragraph:
            lines.append("")
    return lines


def draw_centered_multiline(draw, lines, font, center_x, top_y, fill, line_gap=14, stroke_width=0, stroke_fill=None, extra_draw_kwargs=None):
    extra = extra_draw_kwargs or {}
    y = top_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width, **extra)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(
            (center_x - w / 2 - bbox[0], y - bbox[1]),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            **extra,
        )
        y += h + line_gap
    return y


# ---------------------------------------------------------------------------
# 포스트 생성
# ---------------------------------------------------------------------------

def generate_post(
    ko_text,
    ar_text="",
    tag="",
    handle="",
    bg_image=None,
    seed=None,
    size=CANVAS_SIZE,
):
    bg_path = bg_image or (DEFAULT_BG_IMAGE if os.path.exists(DEFAULT_BG_IMAGE) else None)
    bg = load_photo_background(bg_path, size) if bg_path else create_celadon_background(size, seed=seed)
    img = bg.convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = size
    margin = int(w * 0.1)
    content_w = w - margin * 2

    # 텍스트 블록 뒤 반투명 패널 (질감 위에서도 가독성 확보)
    panel_top, panel_bottom = int(h * 0.30), int(h * 0.78)
    panel = Image.new("RGBA", size, (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(panel)
    pdraw.rounded_rectangle(
        [margin * 0.6, panel_top, w - margin * 0.6, panel_bottom],
        radius=36,
        fill=(20, 32, 27, 90),
    )
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

    cx = w / 2
    y = panel_top + 50

    if tag:
        tag_font = load_variable_font(FONT_KO_PATH, 34, "Regular")
        y = draw_centered_multiline(draw, [tag], tag_font, cx, y, fill=(224, 236, 228, 255))
        y += 18
        draw.line([(cx - 60, y), (cx + 60, y)], fill=(224, 236, 228, 160), width=2)
        y += 34

    if ar_text:
        ar_font = load_variable_font(FONT_AR_PATH, 52, "Bold")
        ar_lines = wrap_arabic(draw, ar_text, ar_font, content_w)
        y = draw_centered_multiline(
            draw, ar_lines, ar_font, cx, y, fill=(240, 244, 238, 255), line_gap=18,
            extra_draw_kwargs=_arabic_draw_kwargs(),
        )
        y += 40
        draw.line([(cx - 60, y), (cx + 60, y)], fill=(224, 236, 228, 160), width=2)
        y += 34

    ko_font = load_variable_font(FONT_KO_PATH, 30, "Bold")
    ko_lines = wrap_korean(draw, ko_text, ko_font, content_w)
    y = draw_centered_multiline(
        draw, ko_lines, ko_font, cx, y, fill=(255, 255, 255, 255),
        line_gap=10, stroke_width=1, stroke_fill=(20, 40, 32, 255),
    )

    if handle:
        handle_font = load_variable_font(FONT_KO_PATH, 30, "Regular")
        bbox = draw.textbbox((0, 0), handle, font=handle_font)
        hw, hh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (w - margin - hw, h - margin * 0.6 - hh),
            handle,
            font=handle_font,
            fill=(255, 255, 255, 210),
        )

    return img.convert("RGB")


def save_post(image, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    image.save(output_path, "PNG", quality=95)
    print(f"저장됨: {output_path}")


def run_batch(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    for i, post in enumerate(posts, 1):
        image = generate_post(
            ko_text=post.get("ko", ""),
            ar_text=post.get("ar", ""),
            tag=post.get("tag", ""),
            handle=post.get("handle", ""),
            bg_image=post.get("bg_image"),
            seed=post.get("seed"),
        )
        output = post.get("output") or f"output/post_{i:02d}.png"
        save_post(image, output)
        if post.get("upload"):
            caption = build_caption(post.get("ko", ""), post.get("ar", ""), post.get("hashtags"))
            upload_to_instagram(output, caption, public_base_url=post.get("public_base_url"))


# ---------------------------------------------------------------------------
# 예약 자동 게시 (GitHub Actions 등 스케줄러용)
#
# 매번 posts.json 목록 중 "다음 순서" 하나만 생성하고, 어디까지 올렸는지는
# state.json에 기록해 다음 실행 때 이어서 순환(round-robin)한다.
#
# 이미지 생성과 Instagram 업로드를 분리한 이유: Graph API는 image_url을 자기
# 서버가 직접 fetch하므로, 이미지가 실제로 공개 URL(GitHub Pages)에 반영된
# *뒤에* 업로드를 호출해야 한다. 그 사이에 git commit/push + 배포 대기 시간이
# 필요해서 "생성"과 "게시"를 별도 명령으로 나눴다 (워크플로에서 두 단계로 호출).
# ---------------------------------------------------------------------------

def load_state(state_path):
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": -1}


def save_state(state_path, state):
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def generate_next(json_path, state_path, output_dir):
    with open(json_path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not posts:
        raise InstagramUploadError(f"{json_path}에 포스트가 없습니다.")

    state = load_state(state_path)
    next_index = (state.get("last_index", -1) + 1) % len(posts)
    post = posts[next_index]

    image = generate_post(
        ko_text=post.get("ko", ""),
        ar_text=post.get("ar", ""),
        tag=post.get("tag", ""),
        handle=post.get("handle", ""),
        bg_image=post.get("bg_image"),
        seed=post.get("seed"),
    )
    os.makedirs(output_dir, exist_ok=True)
    filename = f"post_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    output_path = os.path.join(output_dir, filename)
    save_post(image, output_path)

    caption = build_caption(post.get("ko", ""), post.get("ar", ""), post.get("hashtags"))
    caption_path = output_path + ".caption.txt"
    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(caption)

    state["last_index"] = next_index
    save_state(state_path, state)

    print(output_path)
    return output_path


def publish_existing(image_path, public_base_url=None):
    caption_path = image_path + ".caption.txt"
    with open(caption_path, "r", encoding="utf-8") as f:
        caption = f.read()
    return upload_to_instagram(image_path, caption, public_base_url=public_base_url)


def main():
    parser = argparse.ArgumentParser(description="인스타그램 비색 청자 배경 포스트 생성기")
    parser.add_argument("--ko", help="한국어 본문")
    parser.add_argument("--ar", default="", help="아랍어 본문")
    parser.add_argument("--tag", default="", help="상단 태그/카테고리 (한국어)")
    parser.add_argument("--handle", default="", help="우측 하단 워터마크 (예: @account)")
    parser.add_argument(
        "--bg-image", default=None,
        help="실제 청자 사진 경로 (생략 시 assets/celadon_bg.jpg를 찾고, 없으면 자동 생성 배경 사용)",
    )
    parser.add_argument("--seed", type=int, default=None, help="배경 텍스처 시드 (재현 가능한 결과)")
    parser.add_argument("--output", default=None, help="출력 파일 경로")
    parser.add_argument("--batch", default=None, help="여러 포스트를 정의한 JSON 파일 경로 (일괄 자동 생성)")
    parser.add_argument(
        "--upload", action="store_true",
        help="생성 후 Instagram Graph API로 자동 게시 (IG_USER_ID, IG_ACCESS_TOKEN, PUBLIC_BASE_URL 환경변수 필요)",
    )
    parser.add_argument("--hashtags", default="", help="추가 해시태그, 쉼표로 구분 (예: '#전시,#박물관')")
    parser.add_argument("--public-base-url", default=None, help="이미지가 공개 호스팅된 URL prefix (PUBLIC_BASE_URL 환경변수 대체)")
    parser.add_argument(
        "--next", action="store_true",
        help="예약 자동 게시용: --batch 목록 중 다음 순서 1개만 생성하고 --state에 진행 상황 기록 (업로드는 하지 않음)",
    )
    parser.add_argument("--state", default="state.json", help="--next가 사용하는 진행 상황 기록 파일 (기본: state.json)")
    parser.add_argument("--output-dir", default="docs", help="--next로 생성한 이미지를 저장할 폴더 (기본: docs, GitHub Pages 배포용)")
    parser.add_argument("--publish", default=None, help="이미 생성된 이미지 경로를 지정해 Instagram에 게시만 수행 (--next로 만든 파일용)")
    parser.add_argument("--publish-reel", default=None, help="공개 video_url을 지정해 Instagram 릴스(영상)로 게시")
    parser.add_argument("--caption-file", default=None, help="캡션 텍스트 파일 경로 (--publish-reel용)")
    parser.add_argument("--cover-url", default=None, help="릴스 표지로 쓸 공개 이미지 URL (브랜드 커버)")
    parser.add_argument(
        "--refresh-token", action="store_true",
        help="IG_ACCESS_TOKEN(60일 장기 토큰)의 유효기간을 다시 60일로 연장하고 새 토큰을 표준출력으로 출력",
    )
    parser.add_argument(
        "--check-env", action="store_true",
        help="실행 환경의 아랍어 렌더링 경로를 점검하고 종료(문제가 있으면 오류로 종료). CI 로그/디버깅용.",
    )
    args = parser.parse_args()

    if args.check_env:
        check_render_env()
        return

    if args.refresh_token:
        new_token = refresh_long_lived_token(_require_env("IG_ACCESS_TOKEN"))
        print(new_token)
        return

    if args.publish:
        publish_existing(args.publish, public_base_url=args.public_base_url)
        return

    if args.publish_reel:
        caption = ""
        if args.caption_file:
            with open(args.caption_file, encoding="utf-8") as f:
                caption = f.read().strip()
        publish_reel(args.publish_reel, caption, cover_url=args.cover_url)
        return

    if args.next:
        generate_next(args.batch or "posts.json", args.state, args.output_dir)
        return

    if args.batch:
        run_batch(args.batch)
        return

    if not args.ko:
        parser.error("--ko 또는 --batch 중 하나는 필수입니다.")

    image = generate_post(
        ko_text=args.ko,
        ar_text=args.ar,
        tag=args.tag,
        handle=args.handle,
        bg_image=args.bg_image,
        seed=args.seed,
    )
    output = args.output or f"output/post_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    save_post(image, output)

    if args.upload:
        extra_hashtags = [h.strip() for h in args.hashtags.split(",") if h.strip()]
        caption = build_caption(args.ko, args.ar, extra_hashtags)
        upload_to_instagram(output, caption, public_base_url=args.public_base_url)


if __name__ == "__main__":
    main()
