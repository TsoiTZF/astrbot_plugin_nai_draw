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
5. ``style`` 只负责画风与渲染，禁止写入五官、表情、姿势、构图与视角。
   这类词一旦固定，同一预设产出的每张图都会共用同一张脸与同一个机位。

出图多样性由两个组合维度保证：

* ``artist_variants``：同一批画师内轮换主导权，画风基底不变、脸型随主力漂移。
  集合不换人，只改权重，避免引入未实测的画师标签。
* ``faces``：五官特征池，按不重复组合顺序取一组，并把其余变体的特征写入负面词，
  强制拉开差距。用户自己写了五官时不注入，避免与用户描述对撞。
"""

import random
import re

# NAI4.5 质量词，与 NAI3/SD 体系不通用
QUALITY = "amazing quality, very aesthetic, absurdres"

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

# 日系少女系：老五样、hiten、pop、水彩、复古共用
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

# 成熟系：mature 预设专用，锐利与柔和两极各两档
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

# 半写实系：鬼刀、油画共用。禁用夸张大眼，五官按写实骨相分化。
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

# ==================== 画师主导权变体 ====================
# 同一集合内轮换主力，不引入新画师标签。
# 首位为主力（双层花括号），其余按方括号层数递减影响力。

# 法典「老五样」：社区沿用多年的美脸基础串。
# 四个变体分别以 ciloranko、ningen_mame、sho、tianliang 为主力。
LAOWUYANG_VARIANTS = (
    "[artist:ningen_mame], {artist:ciloranko}, [artist:sho_(sho_lwlw)], "
    "[[artist:tianliang_duohe_fangdongye]], [[artist:rhasta]]",

    "{artist:ningen_mame}, artist:ciloranko, [[artist:sho_(sho_lwlw)]], "
    "[[artist:tianliang_duohe_fangdongye]], [artist:rhasta]",

    "[[artist:ningen_mame]], artist:ciloranko, {artist:sho_(sho_lwlw)}, "
    "[artist:tianliang_duohe_fangdongye], [[artist:rhasta]]",

    "[artist:ningen_mame], [artist:ciloranko], [[artist:sho_(sho_lwlw)]], "
    "{artist:tianliang_duohe_fangdongye}, artist:rhasta",
)

# 兼容旧引用：默认取第一个变体（ciloranko 主力）
LAOWUYANG = LAOWUYANG_VARIANTS[0]


def _with_hiten(variants):
    """在老五样各变体末尾挂 hiten，用于 hiten 与 pop 预设。"""
    return tuple(f"{item}, [artist:hiten]" for item in variants)


PRESETS = {
    "laowuyang": {
        "label": "老五样（通用美脸）",
        "artist_variants": LAOWUYANG_VARIANTS,
        "style": "soft shading, soft lighting",
        "faces": FACES_ANIME,
        "negative": "",
    },
    "hiten": {
        "label": "hiten 柔和日系",
        "artist_variants": _with_hiten(LAOWUYANG_VARIANTS),
        "style": "soft shading, soft lighting, pastel colors, bright",
        "faces": FACES_ANIME,
        # 深色背景与强轮廓光会造成环境色污染，柔和系必须压制
        "negative": "dark background, black background, harsh shadow, strong rim light",
    },
    "pop": {
        "label": "波普撞色（法典风格串）",
        "artist_variants": _with_hiten(LAOWUYANG_VARIANTS),
        # 用户实测认可的风格串。paint splatter 与 arrogant 属于风格标志，予以保留；
        # close shot 与 from side 已移出，交由用户决定构图。
        "style": (
            "colorful, pop style, realistic, flat color, "
            "paint splatter on face, arrogant, demented, soft shading"
        ),
        "faces": FACES_ANIME,
        # flat color 是本风格核心特征，不可压制
        "negative": "dark background, black background, harsh shadow",
        "skip_negative": ("flat color",),
    },
    "ghostblade": {
        "label": "鬼刀厚涂（wlop 系）",
        # wlop 权重不得超过双层花括号，实测更高会推崩去噪产出纯噪点。
        "artist_variants": (
            "{{artist:wlop}}, artist:guweiz, [artist:sakimichan]",
            "{artist:wlop}, {artist:guweiz}, [[artist:sakimichan]]",
            "artist:wlop, [artist:guweiz], {artist:sakimichan}",
        ),
        "style": (
            "{{digital painting}}, {{soft blended shading}}, semi-realistic, "
            "realistic proportions, detailed skin, "
            "{{dramatic lighting}}, {{rim light}}, volumetric fog, "
            "muted cyan and violet, cold tone, depth of field"
        ),
        "faces": FACES_SEMIREAL,
        "negative": (
            "{{anime style}}, {{cel shading}}, {{flat color}}, {{chibi}}, "
            "{{thick outline}}, {{sketch}}, cute, kawaii, big eyes, round face"
        ),
    },
    "mature": {
        "label": "成熟妩媚",
        "artist_variants": (
            "{{artist:gusha_s}}, artist:as109, [artist:tidsean], "
            "[artist:hews], [[artist:cutesexyrobutts]]",

            "{{artist:as109}}, [artist:gusha_s], [[artist:tidsean]], "
            "[artist:hews], [[artist:cutesexyrobutts]]",

            "{{artist:tidsean}}, [artist:hews], [[artist:as109]], "
            "[[artist:gusha_s]], [[artist:cutesexyrobutts]]",

            "{{artist:hews}}, artist:cutesexyrobutts, [[artist:gusha_s]], "
            "[[artist:as109]], [[artist:tidsean]]",
        ),
        # 只保留成熟感锚点与皮肤质感，五官交由 faces 轮换
        "style": (
            "{{mature female}}, {{adult woman}}, {{curvy figure}}, "
            "glossy skin, soft shading"
        ),
        "faces": FACES_MATURE,
        # mature female 在正面词中，故负面词反向压制幼态
        "negative": (
            "{{loli}}, {{child}}, {{childlike}}, {{young}}, "
            "{{round face}}, {{chubby cheeks}}, {{innocent}}, {{moe}}"
        ),
    },
    "watercolor": {
        "label": "水彩透明",
        "artist_variants": (
            "{artist:alphonse_(white_datura)}, [artist:maccha_(mochancc)], "
            "[[artist:pottsness]]",

            "[artist:alphonse_(white_datura)], {artist:maccha_(mochancc)}, "
            "[artist:pottsness]",

            "[[artist:alphonse_(white_datura)]], [artist:maccha_(mochancc)], "
            "{artist:pottsness}",
        ),
        "style": (
            "{{watercolor (medium)}}, {{traditional media}}, wet on wet, "
            "color bleeding, soft edges, pale palette, paper texture"
        ),
        "faces": FACES_ANIME,
        "negative": "",
        "skip_negative": ("flat color",),
    },
    "retro": {
        "label": "复古赛璐璐",
        "artist_variants": (
            "{artist:yoshida_akihiko}, [artist:minaba_hideo], [[artist:toi8]]",
            "[artist:yoshida_akihiko], {artist:minaba_hideo}, [artist:toi8]",
            "[[artist:yoshida_akihiko]], [artist:minaba_hideo], {artist:toi8}",
        ),
        "style": (
            "{{retro artstyle}}, {{1990s (style)}}, {{cel shading}}, "
            "muted warm palette, anime screencap, hard shadow edge"
        ),
        "faces": FACES_ANIME,
        "negative": "",
    },
    "oil": {
        "label": "厚涂油画",
        "artist_variants": (
            "{artist:nixeu}, [artist:quasarcake], [[artist:chiaroscuro]]",
            "[artist:nixeu], {artist:quasarcake}, [artist:chiaroscuro]",
            "[[artist:nixeu]], [artist:quasarcake], {artist:chiaroscuro}",
        ),
        "style": (
            "{{oil painting (medium)}}, {{impasto}}, visible brushstrokes, "
            "rich texture, classical palette, painterly"
        ),
        "faces": FACES_SEMIREAL,
        "negative": "",
    },
}

# 数字快捷方式属于用户命令契约，必须显式固定，不能依赖字典调整后的顺序。
PRESET_ORDER = (
    "laowuyang",
    "hiten",
    "pop",
    "ghostblade",
    "mature",
    "watercolor",
    "retro",
    "oil",
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
        index = int(key) - 1
        return PRESET_ORDER[index] if 0 <= index < len(PRESET_ORDER) else None
    if key in PRESETS:
        return key
    for preset_key, data in PRESETS.items():
        if key == data["label"].lower() or key in data["label"]:
            return preset_key
    return None


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


def variant_count(preset_key):
    """返回预设可遍历的画师与五官笛卡尔积数量。"""
    preset = PRESETS[preset_key]
    return len(preset["artist_variants"]) * max(1, len(preset.get("faces") or ()))


def pick_variant(preset_key, index=None):
    """选出本次使用的画师串与五官变体，返回 (画师串, 五官词, 排他负面词)。

    index 为 None 时随机；给定整数时遍历完整组合，并保证相邻画师和五官不同。
    """
    preset = PRESETS[preset_key]
    artists = preset["artist_variants"]
    faces = preset.get("faces") or ()

    if index is None:
        artist = random.choice(artists)
        face = random.choice(faces) if faces else ("", "")
    else:
        combination = int(index) % variant_count(preset_key)
        artist_index = combination % len(artists)
        artist = artists[artist_index]
        if faces:
            block = combination // len(artists)
            face = faces[(artist_index + block) % len(faces)]
        else:
            face = ("", "")

    return artist, face[0], face[1]


def build_prompt(preset_key, user_text, year_tag="year 2024", index=None):
    """组装正面提示词：画师串 + 年份 + 质量词 + 风格词 + 五官 + 用户描述。

    年份标签用于定位 NAI4.5 训练数据版本，缺失会混入旧数据画风。
    返回 (提示词, 五官排他负面词)，后者需交给 build_negative 一并使用。
    """
    preset = PRESETS[preset_key]
    artists, face, face_negative = pick_variant(preset_key, index)

    # 用户自定五官时放弃变体注入，其排他负面词同样不生效
    if user_text and describes_face(user_text):
        face, face_negative = "", ""

    segments = [artists, year_tag, QUALITY, preset["style"], face]
    if user_text:
        segments.append(user_text.strip())
    return ", ".join(part for part in segments if part), face_negative


def build_negative(
    preset_key,
    allow_nsfw=False,
    extra="",
    face_negative="",
    user_text="",
):
    """组装负面提示词，并剔除与当前风格冲突的条目。

    face_negative 由 build_prompt 返回，用于压制其余五官变体的特征。
    用户明确指定脸部特征时，同名预设负面词会被删除，避免正负对撞。
    """
    preset = PRESETS[preset_key]
    items = [BASE_NEGATIVE]
    preset_negative = _remove_face_conflicts(preset.get("negative", ""), user_text)
    if preset_negative:
        items.append(preset_negative)
    if face_negative:
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


def preset_help():
    """生成预设清单文本。"""
    lines = ["可用画风预设（发送 /nai 数字 即可选择）："]
    for index, key in enumerate(PRESET_ORDER, start=1):
        preset = PRESETS[key]
        count = variant_count(key)
        lines.append(f"{index} = {preset['label']} [{key}]，{count} 种脸型组合")
    lines.append("")
    lines.append("只选择预设：/nai 1")
    lines.append("选择并绘图：/nai 1 长发女孩")
    lines.append("尺寸：竖图 / 方图 / 横图 / 大图，或直接写 832x1216")
    lines.append("每次出图自动轮换画师主力与五官，想固定脸型就在描述里写五官。")
    return "\n".join(lines)
