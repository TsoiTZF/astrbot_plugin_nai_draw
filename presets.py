"""画风预设与提示词组装。

预设中的画师串均为实测可用配方，若需新增请遵循以下约束：

1. 质量词必须用 NAI4.5 体系的 ``amazing quality, very aesthetic, absurdres``。
   NAI3/SD 的 ``masterpiece, best quality`` 在 4.5 上等同无效。
2. 括号权重每层约 1.05 倍，``{}`` 增强、``[]`` 降低。
   数值语法 ``1.2::tag::`` 一旦超过 1.5 会推崩去噪过程，产出纯噪点，不得超限。
3. 风格词避免语义冲突。``thick brushstrokes`` 与 ``soft blended shading`` 并存
   会互相抵消，三层括号只会放大冲突。
4. 平涂系画师（modare、mignon、kukka 等）与精细渲染要求互斥，
   仅在需要极简风格时使用。
5. ``positive_variants`` 只负责画风与渲染，禁止写入五官、表情、姿势、构图与视角。
   这类词一旦固定，同一预设产出的每张图都会共用同一张脸与同一个机位。
6. 法典原始串必须拆成 ``artist_variants``、``positive_variants`` 与 ``negative``。
   质量词、年份、主体、构图、NSFW 和超限权重不得混入画风字段。

出图多样性由三个组合维度保证：

* ``artist_variants``：清洗后的 NAI4.5 画师配方轮换，单项权重不超过 1.5。
* ``positive_variants``：同一风格下轮换上色、笔触、光影、材质与色板。
* ``faces``：五官特征池，按不重复组合顺序取一组，并把其余变体的特征写入负面词，
  强制拉开差距。用户自己写了五官时不注入，避免与用户描述对撞。
"""

import random
import re

try:
    from .random_artist_pool import RANDOM_ARTIST_COMBOS, RANDOM_ARTIST_SOURCE
except ImportError:
    from random_artist_pool import RANDOM_ARTIST_COMBOS, RANDOM_ARTIST_SOURCE

# NAI4.5 质量词，与 NAI3/SD 体系不通用
QUALITY = "amazing quality, very aesthetic, absurdres"
NO_PRESET_KEY = "none"
MAX_CUSTOM_ARTISTS = 12

# 通用负面词。前段压制未完成感，中段为常规崩坏防护。
# very displeasing 与 bad quality 是 NAI 自带美学评分标签，对成品率影响最大。
BASE_NEGATIVE = (
    "blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, "
    "jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, "
    "multiple views, artist collaboration, censored, "
    "bad hands, extra digits, missing fingers, fused fingers, "
    "{{noise}}, {{grainy}}, artifacts, "
    "multiple girls, watermark, text"
)

# 关闭 allow_nsfw 时追加
NSFW_NEGATIVE = "{{nude}}, {{nsfw}}, {{explicit}}, nipples, sex"

ARTIST_TOKEN_PATTERN = re.compile(
    r"^(?:(?P<weight>\d+(?:\.\d+)?)::)?"
    r"(?P<prefix>[{[]*)"
    r"artist:(?P<name>[a-z0-9][a-z0-9_ .()'+-]{0,95})"
    r"(?P<suffix>[]}]*)(?P<weighted_end>::)?$",
    re.I,
)

# 只匹配完整标签或明确脸型短语，避免 slippers、machine、surface 等普通词误判。
FACE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"eyes?|eyelashes?|eyebrows?|jawline|cheekbones?|cheeks?|"
    r"lips?|lipstick|noses?|chin|mouth|tsurime|tareme|"
    r"beauty[ _-]+marks?|"
    r"(?:round|oval|long|angular|square|wide|narrow|small|heart[ _-]+shaped)"
    r"[ _-]+face"
    r")(?![a-z0-9])",
    re.I,
)

# NAI 中含义等价但写法不同的标签，用于删除与用户要求冲突的预设负面词。
FACE_TRAIT_GROUPS = (
    frozenset(("big eyes", "large eyes")),
)

# ==================== 五官变体池 ====================
# 每项为 (五官正面词, 排他负面词)。负面词写入其余变体的特征，
# 单靠正面词不足以拉开脸型差距，实测必须双向施压。

# 日系少女系：冰蓝柔光与霓虹平涂共用
FACES_ANIME = (
    ("{{round eyes}}, {{thick eyelashes}}, {{soft jawline}}, {{small nose}}, "
     "{{detailed eyes}}",
     "tsurime, narrow eyes, sharp jawline"),

    ("{{tsurime}}, {{narrow eyes}}, {{thin eyebrows}}, {{sharp jawline}}, "
     "{{detailed eyes}}",
     "round eyes, droopy eyes, soft jawline"),

    ("{{tareme}}, {{droopy eyes}}, {{long eyelashes}}, {{soft cheeks}}, "
     "{{detailed eyes}}",
     "tsurime, narrow eyes, sharp jawline"),

    ("{{large eyes}}, {{sparkling eyes}}, {{thick eyebrows}}, {{small mouth}}, "
     "{{detailed eyes}}",
     "narrow eyes, tsurime, thin eyebrows"),
)

# 成熟人物系：高光成熟人物与暗夜轻熟肖像共用
FACES_MATURE = (
    ("{{tsurime}}, {{sharp eyes}}, {{thin eyebrows}}, {{high nose bridge}}, "
     "{{sharp jawline}}, {{dark red lipstick}}, {{detailed eyes}}",
     "round eyes, soft jawline, full lips"),

    ("{{tareme}}, {{droopy eyes}}, {{thick eyelashes}}, {{soft jawline}}, "
     "{{full lips}}, {{beauty mark}}, {{detailed eyes}}",
     "sharp jawline, narrow eyes, thin lips"),

    ("{{narrow eyes}}, {{half-lidded eyes}}, {{arched eyebrows}}, "
     "{{defined cheekbones}}, {{thin lips}}, {{pale skin}}, {{detailed eyes}}",
     "round eyes, thick eyebrows, full lips"),

    ("{{large eyes}}, {{long eyelashes}}, {{glossy lips}}, {{red lipstick}}, "
     "{{rosy cheeks}}, {{detailed eyes}}",
     "narrow eyes, thin lips, pale skin"),
)

# 半写实系：冷调电影厚涂与青雾胶片插画共用。禁用夸张大眼，五官按写实骨相分化。
FACES_SEMIREAL = (
    ("{{realistic eyes}}, {{detailed iris}}, {{straight nose}}, "
     "{{defined jawline}}, {{natural lips}}",
     "big eyes, round face, chubby cheeks"),

    ("{{almond eyes}}, {{heavy eyelids}}, {{high cheekbones}}, {{thin lips}}, "
     "{{sharp nose}}",
     "big eyes, round face, full lips"),

    ("{{soft realistic eyes}}, {{long eyelashes}}, {{small nose}}, "
     "{{full lips}}, {{smooth jawline}}",
     "big eyes, angular face, thin lips"),

    ("{{deep-set eyes}}, {{arched eyebrows}}, {{prominent cheekbones}}, "
     "{{narrow chin}}, {{natural lips}}",
     "big eyes, round face, wide jaw"),
)

# Q 版系：粉彩无描边 Q 版专用。压写实五官，拉开圆眼、下垂眼、猫眼和点状眼。
FACES_CHIBI = (
    ("{{round eyes}}, {{sparkling eyes}}, {{small nose}}, {{tiny mouth}}, "
     "{{detailed eyes}}",
     "narrow eyes, tsurime, realistic eyes"),

    ("{{tareme}}, {{droopy eyes}}, {{long eyelashes}}, {{soft cheeks}}, "
     "{{detailed eyes}}",
     "tsurime, narrow eyes, sharp jawline"),

    ("{{cat eyes}}, {{slit pupils}}, {{small mouth}}, {{round face}}, "
     "{{detailed eyes}}",
     "round eyes, realistic eyes, thin lips"),

    ("{{dot eyes}}, {{simple eyes}}, {{tiny nose}}, {{small mouth}}, "
     "{{round face}}",
     "realistic eyes, detailed iris, sharp jawline"),
)

# ==================== 法典来源与清洗后的画风变体 ====================
CODEX_ARTIST_SOURCE = {
    "codex": "artist_nai45_strings",
    "version": "2026.7.10",
    "url": "https://novelai.quicktagcloud.com/?codex=artist_nai45_strings",
}

PRESETS = {
    NO_PRESET_KEY: {
        "label": "无预设",
        "artist_variants": ("",),
        "positive_variants": ("",),
        "faces": (),
        "negative": "",
        "source": {},
    },
    "iceblue": {
        "label": "冰蓝柔光（日系）",
        "artist_variants": (
            "0.45::artist:pan_(mimi)::, 0.6::artist:skinfang::, "
            "0.7::artist:hoshi_(snacherubi)::, 0.75::artist:comodox::, "
            "0.8::artist:chen_bin::",
        ),
        "positive_variants": (
            "cool color palette, neutral lighting, soft lighting, pale skin",
            "plain light background, soft even lighting, cool blue-white color scheme",
            "pale blue pastel palette, soft cool rim lighting, ethereal clean mood, gentle focus",
        ),
        "faces": FACES_ANIME,
        "negative": "dark background, black background, harsh shadow, oversaturated, text",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 010",)},
    },
    "cinematic": {
        "label": "冷调电影厚涂",
        "artist_variants": (
            "0.9::artist:wlop::, 0.3::artist:domo_(domokizusuki)::, "
            "1.1::artist:au_(d_elete)::",
            "artist:murata_yuusuke, 1.05::artist:tianliang_duohe_fangdongye::, "
            "0.95::artist:ciloranko::, 0.95::artist:ningen_mame::, "
            "0.95::artist:healthyman::",
            "artist:ningen_mame, artist:mika_pikazo, [artist:reoen], "
            "[artist:tianliang_duohe_fangdongye], [artist:kantoku]",
        ),
        "positive_variants": (
            "animated painting, best illumination, best shadow, dramatic light and shadow",
            "chiaroscuro, cinematic lighting, sharp focus, vibrant colors, realistic illustration",
            "shiny skin, tyndall effect, backlighting, sidelighting, lens flare, depth of field",
        ),
        "faces": FACES_SEMIREAL,
        "negative": "anime screencap, cel shading, flat color, chibi, thick outline, sketch, simple illustration, text",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 029", "W.O.F 030", "W.O.F 041", "W.O.F 042")},
    },
    "neon_flat": {
        "label": "霓虹平涂",
        "artist_variants": (
            "1.2::artist:vanripper::, 0.8::artist:batrobin_k::, "
            "0.5::artist:take_(illustrator)::, 0.5::artist:j.k.::, "
            "0.4::artist:jtveemo::",
            "1.16::artist:kedama_milk::, 0.86::artist:mika_pikazo::, "
            "[artist:ciloranko], [artist:reoen]",
            "0.8::artist:furau::, 0.75::artist:wagashi_(dagashiya)::, "
            "0.9::artist:deadflow::, [artist:mx2j]",
        ),
        "positive_variants": (
            "style parody, muse dash (style), cartoonized, toon (style), animated, thick outline, bold color",
            "blue theme, polka dot background, graphic design, bold flat colors, clean shapes",
            "colorful, shiny color accents, azpainter style, thin rough lines, energetic palette",
        ),
        "faces": FACES_ANIME,
        "negative": "artist collaboration, multiple views, text, muted colors, dull palette",
        "skip_negative": ("flat color",),
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 123", "W.O.F 180", "W.O.F 019")},
    },
    "glossy_mature": {
        "label": "高光成熟人物",
        "artist_variants": (
            "0.95::artist:healthyman::, 0.9::artist:modare::, "
            "0.85::artist:fuzichoco::, 0.85::artist:wanke::, [artist:ciloranko]",
            "1.3::artist:wagashi_(dagashiya)::, artist:wlop, "
            "0.4::artist:ratatatat::, 0.7::artist:imamura_ryou::, [artist:healthyman]",
            "0.8::artist:furau::, 0.75::artist:wagashi_(dagashiya)::, "
            "0.9::artist:deadflow::, 1.2::artist:mdf_an::, [artist:freng]",
        ),
        "positive_variants": (
            "mature female, adult woman, curvy figure, glossy skin, soft shading",
            "mature female, elegant illustration, detailed skin, cinematic lighting, refined coloring",
            "adult woman, polished rendering, shiny skin, rich contrast, glamorous atmosphere",
        ),
        "faces": FACES_MATURE,
        "negative": "loli, child, childlike, young, round face, chubby cheeks, innocent, moe, simple illustration, text",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 041", "梦神NAI4.5F画风合集 0166", "W.O.F 019")},
    },
    "dark_portrait": {
        "label": "暗夜轻熟肖像",
        "artist_variants": (
            "0.7::artist:ciloranko::, 0.6::artist:mika_pikazo::, "
            "0.5::artist:mx2j::, 0.5::artist:dramz::, artist:96yottea",
            "artist:ciloranko, 0.95::artist:sho_(sho_lwlw)::, "
            "0.91::artist:tianliang_duohe_fangdongye::, 0.74::artist:kani_biimu::",
            "artist:ningen_mame, artist:mika_pikazo, [artist:reoen], "
            "[artist:tianliang_duohe_fangdongye], [artist:ask_(askzy)], [artist:kantoku]",
            "1.16::artist:kedama_milk::, 0.86::artist:mika_pikazo::, "
            "[artist:ciloranko], [artist:sho_(sho_lwlw)]",
        ),
        "positive_variants": (
            "vivid details, soft shading, smooth skin texture, natural skin glow, novel illustration, dark background, low-key lighting",
            "clean illustration, detailed shading, gentle contrast, polished coloring, dark background, dim ambient light",
            "official art, shiny skin, cinematic lighting, depth of field, night atmosphere, deep shadow background",
        ),
        "faces": FACES_MATURE,
        "negative": "simple illustration, artist collaboration, multiple views, text, Japanese text, blurry, bright white background",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 005", "W.O.F 103", "W.O.F 152", "W.O.F 180")},
    },
    "golden_backlight": {
        "label": "暖金逆光",
        "artist_variants": (
            "0.3::artist:toosaka_asagi::, 0.3::artist:miv4t::, "
            "0.3::artist:huashijw::, 0.1::artist:quasarcake::, "
            "artist:hibioes, artist:konya_karasue, artist:rella",
        ),
        "positive_variants": (
            "light and dark contrast, light rays, intense shadow, 1.4::warm lighting::, 1.3::backlighting::, golden hour, depth of field, blurred background",
            "amber color palette, warm rim lighting, sunlit haze, glowing highlights, gentle cinematic contrast",
            "golden hour color grading, radiant backlight, soft bloom, warm skin glow, atmospheric depth",
        ),
        "faces": FACES_ANIME,
        "negative": "flat lighting, dull colors, cold blue lighting, muddy shadows, text",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 008", "W.O.F 009")},
    },
    "dreamy_floral": {
        "label": "暮光花境",
        "artist_variants": (
            "artist:ichigoyama, artist:ashima_(roro046), artist:rella, artist:onineko",
        ),
        "positive_variants": (
            "pastel colors, golden hour lighting, moody lighting, metallic luster, luminous floral color palette, soft dreamy illustration",
            "rose-violet pastel palette, petal-shaped bokeh, iridescent highlights, romantic twilight glow, soft bloom",
            "lavender dusk color grading, pearlescent light, sparkling particles, gentle contrast, ethereal illustration",
        ),
        "faces": FACES_ANIME,
        "negative": "harsh contrast, muddy colors, heavy black shadows, horror, text",
        "skip_negative": ("chromatic aberration",),
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 137",)},
    },
    "pastel_chibi": {
        "label": "粉彩无描边 Q版",
        "artist_variants": ("",),
        "positive_variants": (
            "minimalism, pastel color, flat color, 1.1::no lineart::, 1.4::chibi only, super deformed, big head, small body::, clean simple shapes",
            "soft pastel palette, lineless illustration, 1.4::chibi only, super deformed, big head, small body::, rounded shapes, minimal shading, cute graphic design",
            "1.4::chibi only, super deformed, big head, small body::, powdery pastel coloring, no lineart, soft flat shading, clean sticker-like illustration",
        ),
        "faces": FACES_CHIBI,
        "negative": "normal proportions, realistic proportions, tall body, photorealistic, detailed background, heavy lineart, complex shading, character sheet, inset, text",
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 145",)},
    },
    "filmgrain_illustration": {
        "label": "青雾胶片插画",
        "artist_variants": (
            "artist:chen_bin, 0.7::artist:fuzichoco::, 0.7::artist:reoen::, "
            "0.6::artist:tianliang_duohe_fangdongye::, 0.5::artist:mikozin::",
        ),
        "positive_variants": (
            "official art, oil painting (medium), backlighting, sidelighting, film grain, chromatic aberration, depth of field, lens flare, cinematic anime illustration",
            "cyan mist color grading, fine film grain, soft lens bloom, cool rim lighting, atmospheric anime illustration",
            "teal-blue palette, analog film texture, subtle chromatic aberration, diffused highlights, cinematic illustration",
        ),
        "faces": FACES_SEMIREAL,
        "negative": "flat lighting, simple illustration, harsh digital sharpening, muddy colors, double exposure, face in background, background portrait, split composition, collage, text",
        "skip_negative": ("film grain", "chromatic aberration"),
        "source": {**CODEX_ARTIST_SOURCE, "entries": ("W.O.F 172",)},
    },
}

# 数字快捷方式属于用户命令契约，必须显式固定，不能依赖字典调整后的顺序。
PRESET_ORDER = (
    "iceblue",
    "cinematic",
    "neon_flat",
    "glossy_mature",
    "dark_portrait",
    "golden_backlight",
    "dreamy_floral",
    "pastel_chibi",
    "filmgrain_illustration",
)

# 常用尺寸别名，值须为 64 的倍数
SIZE_ALIASES = {
    "竖": "832x1216",
    "竖图": "832x1216",
    "portrait": "832x1216",
    "方": "832x832",
    "方图": "832x832",
    "square": "832x832",
    "横": "1216x832",
    "横图": "1216x832",
    "landscape": "1216x832",
    "大": "1024x1024",
    "large": "1024x1024",
}


def resolve_preset(name):
    """按编号、名称或中文标签查找预设，未命中返回 None。"""
    if not name:
        return None
    key = str(name).strip().lower()
    if key.isdecimal():
        if int(key) == 0:
            return NO_PRESET_KEY
        index = int(key) - 1
        return PRESET_ORDER[index] if 0 <= index < len(PRESET_ORDER) else None
    if key in {"无", "不用预设", "不使用预设"}:
        return NO_PRESET_KEY
    if key in PRESETS:
        return key
    for preset_key, data in PRESETS.items():
        if key == data["label"].lower() or key in data["label"]:
            return preset_key
    return None


def preset_number(preset_key):
    """返回聊天中显示的预设编号，无预设固定为 0。"""
    if preset_key == NO_PRESET_KEY:
        return 0
    return PRESET_ORDER.index(preset_key) + 1


def sanitize_artist_string(text, max_tags=MAX_CUSTOM_ARTISTS):
    """解析个人画师串，返回 (合法标签元组, 被拒数量)。"""
    raw = str(text or "").strip()
    if not raw:
        return (), 0

    accepted = []
    seen = set()
    rejected = 0
    for part in re.split(r"[,，;；\r\n]+", raw):
        token = part.strip()
        if not token:
            continue
        if "artist:" not in token.lower() and re.fullmatch(
            r"[a-z0-9][a-z0-9_()'+-]{0,95}", token, re.I
        ):
            token = f"artist:{token}"
        if len(token) > 128:
            rejected += 1
            continue

        match = ARTIST_TOKEN_PATTERN.fullmatch(token)
        if not match:
            rejected += 1
            continue

        prefix = match.group("prefix")
        suffix = match.group("suffix")
        expected_suffix = "".join(
            "}" if char == "{" else "]" for char in reversed(prefix)
        )
        if len(prefix) > 3 or suffix != expected_suffix:
            rejected += 1
            continue

        weight = match.group("weight")
        weighted_end = match.group("weighted_end")
        if bool(weight) != bool(weighted_end):
            rejected += 1
            continue
        if weight and not (0 < float(weight) <= 1.5):
            rejected += 1
            continue

        normalized = token.lower()
        if normalized in seen:
            continue
        if len(accepted) >= max(1, int(max_tags)):
            rejected += 1
            continue
        seen.add(normalized)
        accepted.append(token)

    return tuple(accepted), rejected


def random_artist_combo():
    """从清洗后的独立画师串池中抽取一组。"""
    if not RANDOM_ARTIST_COMBOS:
        raise ValueError("没有可用的随机画师串")
    title, entry_id, raw = random.choice(RANDOM_ARTIST_COMBOS)
    tags, rejected = sanitize_artist_string(raw)
    if not tags or rejected:
        raise ValueError(f"随机画师串清洗失败：{entry_id}")
    return {
        "preset": entry_id,
        "label": title,
        "artists": tags,
        "text": ", ".join(tags),
        "source": dict(RANDOM_ARTIST_SOURCE),
    }


def resolve_size(text, fallback="832x1216"):
    """解析尺寸文本，支持中文别名与 宽x高 写法。

    非 64 倍数或超出范围时回退到 fallback，避免上游报错。
    """
    if not text:
        return fallback
    raw = str(text).strip().lower()
    if raw in SIZE_ALIASES:
        return SIZE_ALIASES[raw]
    parts = raw.replace("×", "x").replace("*", "x").split("x")
    if len(parts) != 2:
        return fallback
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        return fallback
    if width % 64 or height % 64:
        return fallback
    if not (256 <= width <= 1536 and 256 <= height <= 1536):
        return fallback
    if width * height > 1024 * 1536:
        return fallback
    return f"{width}x{height}"


def describes_face(user_text):
    """判断用户描述里是否已自行指定五官。

    命中时不注入五官变体，避免与用户描述对撞。
    """
    return bool(FACE_PATTERN.search(str(user_text or "")))


def _normalize_tag(text):
    """去掉 NAI 权重符号并统一标签分隔，供冲突比较使用。"""
    value = str(text or "").lower().replace("_", " ").replace("-", " ")
    value = re.sub(r"\d+(?:\.\d+)?::", "", value).replace("::", "")
    value = re.sub(r"[{}\[\]]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _trait_aliases(trait):
    """返回脸部标签的等价写法集合。"""
    for group in FACE_TRAIT_GROUPS:
        if trait in group:
            return group
    return (trait,)


def _mentions_trait(user_text, trait):
    """判断用户描述是否明确包含某个完整脸部标签。"""
    normalized = _normalize_tag(user_text)
    for alias in _trait_aliases(_normalize_tag(trait)):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            return True
    return False


def _remove_face_conflicts(negative, user_text):
    """从预设负面词中删除用户明确要求的同名脸部特征。"""
    if not negative or not describes_face(user_text):
        return negative
    kept = []
    for token in str(negative).split(","):
        normalized = _normalize_tag(token)
        if describes_face(normalized) and _mentions_trait(user_text, normalized):
            continue
        kept.append(token.strip())
    return ", ".join(token for token in kept if token)


def _remove_face_constraints(negative):
    """删除预设负面词中的全部脸部约束，保留其他风格和质量压制词。"""
    kept = []
    for token in str(negative or "").split(","):
        normalized = _normalize_tag(token)
        if normalized and describes_face(normalized):
            continue
        if token.strip():
            kept.append(token.strip())
    return ", ".join(kept)


def variant_count(preset_key):
    """返回画师、正面画风与五官笛卡尔积数量。"""
    preset = PRESETS[preset_key]
    return (
        len(preset["artist_variants"])
        * len(preset.get("positive_variants") or ("",))
        * max(1, len(preset.get("faces") or ()))
    )


def pick_variant(preset_key, index=None):
    """选出画师、正面画风与五官变体。

    返回 ``(画师串, 正面画风, 五官词, 排他负面词)``。给定 index 时遍历
    完整笛卡尔积；随机模式在三个维度分别抽取。
    """
    preset = PRESETS[preset_key]
    artists = preset["artist_variants"]
    positives = preset.get("positive_variants") or ("",)
    faces = preset.get("faces") or ()

    if index is None:
        artist = random.choice(artists)
        positive = random.choice(positives)
        face = random.choice(faces) if faces else ("", "")
    else:
        combination = int(index) % variant_count(preset_key)
        artist_index = combination % len(artists)
        positive_index = (combination // len(artists)) % len(positives)
        artist = artists[artist_index]
        positive = positives[positive_index]
        if faces:
            face_block = combination // (len(artists) * len(positives))
            face = faces[(artist_index + positive_index + face_block) % len(faces)]
        else:
            face = ("", "")

    return artist, positive, face[0], face[1]


def build_prompt(
    preset_key,
    user_text,
    year_tag="year 2024",
    index=None,
    include_face=True,
    custom_artist="",
):
    """组装正面提示词：画师串 + 年份 + 质量词 + 风格词 + 五官 + 用户描述。

    年份标签用于定位 NAI4.5 训练数据版本，缺失会混入旧数据画风。
    include_face 为假时保留画师串轮换，但不注入自动五官及其排他负面词。
    custom_artist 为当前用户通过聊天设置的额外画师串。
    返回 (提示词, 五官排他负面词)，后者需交给 build_negative 一并使用。
    """
    preset = PRESETS[preset_key]
    artists, positive, face, face_negative = pick_variant(preset_key, index)

    # 显式关闭或用户自定五官时放弃变体注入，排他负面词同样不生效。
    if not include_face or (user_text and describes_face(user_text)):
        face, face_negative = "", ""

    segments = [
        artists,
        str(custom_artist or "").strip(),
        year_tag,
        QUALITY,
        positive,
        face,
    ]
    if user_text:
        segments.append(user_text.strip())
    return ", ".join(part for part in segments if part), face_negative


def build_negative(
    preset_key,
    allow_nsfw=False,
    extra="",
    face_negative="",
    user_text="",
    include_face=True,
):
    """组装负面提示词，并剔除与当前风格冲突的条目。

    face_negative 由 build_prompt 返回，用于压制其余五官变体的特征。
    用户明确指定脸部特征时，同名预设负面词会被删除，避免正负对撞。
    include_face 为假时，预设内置的脸部约束也会删除。
    """
    preset = PRESETS[preset_key]
    items = [BASE_NEGATIVE]
    preset_negative = preset.get("negative", "")
    if include_face:
        preset_negative = _remove_face_conflicts(preset_negative, user_text)
    else:
        preset_negative = _remove_face_constraints(preset_negative)
    if preset_negative:
        items.append(preset_negative)
    if include_face and face_negative:
        items.append(str(face_negative).strip())
    if not allow_nsfw:
        items.append(NSFW_NEGATIVE)
    if extra:
        items.append(str(extra).strip())
    merged = ", ".join(part for part in items if part)

    # 风格核心特征若被通用负面词压制，需要移除该条目
    for skip in preset.get("skip_negative", ()):
        merged = ", ".join(
            token.strip()
            for token in merged.split(",")
            if skip not in token.strip().lower()
        )
    return merged


def preset_source(preset_key):
    """返回画风法典来源信息，便于日志与页面追溯。"""
    return dict(PRESETS[preset_key].get("source") or {})


def preset_help():
    """生成预设清单文本。"""
    lines = ["可用画风预设（发送 /nai 数字 即可选择）："]
    lines.append("0 = 无预设 [none]，仅使用质量词、个人画师串和画面描述")
    for index, key in enumerate(PRESET_ORDER, start=1):
        preset = PRESETS[key]
        count = variant_count(key)
        lines.append(
            f"{index} = {preset['label']} [{key}]，{count} 种画师/画风/脸型组合"
        )
    lines.append("")
    lines.append("无预设：/nai 0 或 /nai 0 长发女孩")
    lines.append("只选择预设：/nai 1")
    lines.append("选择并绘图：/nai 1 长发女孩")
    lines.append("个人画师：/nai画师 添加 artist:名称")
    lines.append("随机画师串：/nai画师 随机")
    lines.append("随机完整场景：/nai随机 -风格 1 -尺寸 横图（64 条构图法典）")
    lines.append("尺寸：竖图 / 方图 / 横图 / 大图，或直接写 832x1216")
    lines.append("每次出图轮换法典画师、正面画风与五官；/nai随机 才会注入完整场景。")
    return "\n".join(lines)
