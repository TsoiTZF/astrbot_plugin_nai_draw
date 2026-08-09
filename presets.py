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
"""

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

# 法典「老五样」：社区沿用多年的美脸基础串，以 ciloranko 为主力。
LAOWUYANG = (
    "[artist:ningen_mame], artist:ciloranko, [artist:sho_(sho_lwlw)], "
    "[[artist:tianliang_duohe_fangdongye]], [[artist:rhasta]]"
)

PRESETS = {
    "laowuyang": {
        "label": "老五样（通用美脸）",
        "artists": LAOWUYANG,
        "style": "{{detailed eyes}}, soft shading, soft lighting",
        "negative": "",
    },
    "hiten": {
        "label": "hiten 柔和日系",
        "artists": LAOWUYANG + ", [artist:hiten]",
        "style": (
            "{{detailed eyes}}, soft shading, soft lighting, pastel colors, bright"
        ),
        # 深色背景与强轮廓光会造成环境色污染，柔和系必须压制
        "negative": "dark background, black background, harsh shadow, strong rim light",
    },
    "pop": {
        "label": "波普撞色（法典风格串）",
        "artists": LAOWUYANG + ", [artist:hiten]",
        "style": (
            "colorful, pop style, realistic, flat color, close shot, from side, "
            "paint splatter on face, arrogant, demented, "
            "{{detailed eyes}}, soft shading"
        ),
        # flat color 是本风格核心特征，不可压制
        "negative": "dark background, black background, harsh shadow",
        "skip_negative": ("flat color",),
    },
    "ghostblade": {
        "label": "鬼刀厚涂（wlop 系）",
        "artists": "{{artist:wlop}}, artist:guweiz, [artist:sakimichan]",
        "style": (
            "{{digital painting}}, {{soft blended shading}}, semi-realistic, "
            "realistic proportions, detailed skin, "
            "{{dramatic lighting}}, {{rim light}}, volumetric fog, "
            "muted cyan and violet, cold tone, cinematic composition, depth of field"
        ),
        "negative": (
            "{{anime style}}, {{cel shading}}, {{flat color}}, {{chibi}}, "
            "{{thick outline}}, {{sketch}}, cute, kawaii, big eyes, round face"
        ),
    },
    "mature": {
        "label": "成熟妩媚",
        "artists": (
            "{{artist:gusha_s}}, artist:as109, [artist:tidsean], "
            "[artist:hews], [artist:cutesexyrobutts]"
        ),
        "style": (
            "{{mature female}}, {{adult woman}}, "
            "{{narrow sharp eyes}}, {{tsurime}}, {{long eyelashes}}, "
            "{{red lipstick}}, {{glossy lips}}, {{defined cheekbones}}, "
            "{{elegant posture}}, {{curvy figure}}, "
            "{{detailed eyes}}, glossy skin, soft shading"
        ),
        # mature female 在正面词中，故负面词反向压制幼态
        "negative": (
            "{{loli}}, {{child}}, {{childlike}}, {{young}}, "
            "{{round face}}, {{chubby cheeks}}, {{innocent}}, {{moe}}"
        ),
    },
    "watercolor": {
        "label": "水彩透明",
        "artists": (
            "{artist:alphonse_(white_datura)}, {artist:maccha_(mochancc)}, "
            "[artist:pottsness]"
        ),
        "style": (
            "{{watercolor (medium)}}, {{traditional media}}, wet on wet, "
            "color bleeding, soft edges, pale palette, paper texture"
        ),
        "negative": "",
        "skip_negative": ("flat color",),
    },
    "retro": {
        "label": "复古赛璐璐",
        "artists": (
            "{artist:yoshida_akihiko}, {artist:minaba_hideo}, [artist:toi8]"
        ),
        "style": (
            "{{retro artstyle}}, {{1990s (style)}}, {{cel shading}}, "
            "muted warm palette, anime screencap, hard shadow edge"
        ),
        "negative": "",
    },
    "oil": {
        "label": "厚涂油画",
        "artists": "{artist:nixeu}, {artist:quasarcake}, [artist:chiaroscuro]",
        "style": (
            "{{oil painting (medium)}}, {{impasto}}, visible brushstrokes, "
            "rich texture, classical palette, painterly"
        ),
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


def build_prompt(preset_key, user_text, year_tag="year 2024"):
    """组装正面提示词：画师串 + 年份 + 质量词 + 风格词 + 用户描述。

    年份标签用于定位 NAI4.5 训练数据版本，缺失会混入旧数据画风。
    """
    preset = PRESETS[preset_key]
    segments = [preset["artists"], year_tag, QUALITY, preset["style"]]
    if user_text:
        segments.append(user_text.strip())
    return ", ".join(part for part in segments if part)


def build_negative(preset_key, allow_nsfw=False, extra=""):
    """组装负面提示词，并剔除与当前风格冲突的条目。"""
    preset = PRESETS[preset_key]
    items = [BASE_NEGATIVE]
    if preset.get("negative"):
        items.append(preset["negative"])
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
        lines.append(f"{index} = {PRESETS[key]['label']} [{key}]")
    lines.append("")
    lines.append("只选择预设：/nai 1")
    lines.append("选择并绘图：/nai 1 长发女孩")
    lines.append("尺寸：竖图 / 方图 / 横图 / 大图，或直接写 832x1216")
    return "\n".join(lines)
