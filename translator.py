"""中文自然语言转 danbooru 标签。

NAI 只认英文 danbooru 标签，中文描述直接送入基本无效。
采用两层策略：

1. 词典层：常见描述直接查表命中，零成本、离线可用、结果稳定。
2. LLM 层：词典未覆盖的部分交给 AstrBot 的 LLM provider 转换。

LLM 不可用时降级为仅词典结果，不阻断出图。
"""

import re

from astrbot.api import logger

# 中文描述到 danbooru 标签的映射。
# 键为可能出现的中文写法，值为对应标签，多个标签用逗号分隔。
# 按键长度倒序匹配，长词优先命中，避免「长发」被「发」截断。
LEXICON = {
    # ---- 人数与主体 ----
    "女孩": "1girl", "少女": "1girl", "女生": "1girl", "女性": "1girl",
    "一个女孩": "1girl, solo", "单人": "solo", "独自": "solo",
    "男孩": "1boy", "少年": "1boy", "男性": "1boy",
    "两个女孩": "2girls", "三个女孩": "3girls",
    "御姐": "mature female, adult woman", "成熟女性": "mature female",
    "少妇": "mature female", "阿姨": "mature female",
    "正太": "shota", "萝莉": "loli",
    "情侣": "1boy, 1girl", "双人": "2girls", "多人群": "multiple girls",

    # ---- 发长与发型 ----
    "长发": "long hair", "短发": "short hair", "中长发": "medium hair",
    "超长发": "very long hair", "及腰长发": "very long hair",
    "拖地长发": "absurdly long hair",
    "双马尾": "twintails", "马尾": "ponytail", "单马尾": "ponytail",
    "丸子头": "hair bun", "双丸子": "double bun", "盘发": "hair bun",
    "波波头": "bob cut", "齐肩": "medium hair", "齐刘海": "blunt bangs",
    "刘海": "bangs", "编发": "braid", "麻花辫": "braid", "双辫": "twin braids",
    "卷发": "wavy hair", "大波浪": "wavy hair", "直发": "straight hair",
    "凌乱头发": "messy hair", "湿发": "wet hair", "侧马尾": "side ponytail",
    "心形发": "heart hair bun", "呆毛": "ahoge",

    # ---- 发色 ----
    "黑发": "black hair", "白发": "white hair", "银发": "silver hair",
    "金发": "blonde hair", "棕发": "brown hair", "栗发": "chestnut hair",
    "红发": "red hair", "粉发": "pink hair", "蓝发": "blue hair",
    "绿发": "green hair", "紫发": "purple hair", "橙发": "orange hair",
    "青发": "teal hair", "紫罗兰发": "lavender hair", "亚麻色": "light brown hair",
    "渐变发色": "gradient hair", "挑染": "streaked hair",

    # ---- 瞳色 ----
    "黑眼": "black eyes", "蓝眼": "blue eyes", "红眼": "red eyes",
    "绿眼": "green eyes", "紫眼": "purple eyes", "金眼": "golden eyes",
    "琥珀眼": "amber eyes", "灰眼": "grey eyes", "粉眼": "pink eyes",
    "异色瞳": "heterochromia", "渐变瞳": "gradient eyes",

    # ---- 眼型与表情 ----
    "笑": "smile", "微笑": "soft smile", "笑容": "smile",
    "大笑": "open mouth, laughing", "灿烂笑": ":d",
    "坏笑": "smirk", "得意": "smug", "自信": "confident",
    "冷漠": "expressionless", "无表情": "expressionless",
    "严肃": "serious", "生气": "angry", "皱眉": "furrowed brow",
    "撅嘴": "pout", "不满": "pout", "害羞": "blush, embarrassed",
    "脸红": "blush", "哭": "crying", "流泪": "tears",
    "落泪": "tears", "含泪": "tears, crying",
    "惊讶": "surprised, wide eyes", "困": "sleepy, half-closed eyes",
    "闭眼": "closed eyes", "半闭眼": "half-closed eyes",
    "垂眼": "tareme", "吊眼": "tsurime", "眯眼": "narrowed eyes",
    "妩媚": "seductive smile, half-closed eyes", "诱惑": "seductive smile",
    "温柔": "gentle smile", "看着镜头": "looking at viewer",
    "看向别处": "looking away", "回头": "looking back",
    "抬头": "looking up", "低头": "looking down",
    "侧颜": "profile", "侧脸": "profile",
    "吐舌": "tongue out", "舔唇": "licking lips",

    # ---- 服装 ----
    "校服": "school uniform", "水手服": "sailor collar, school uniform",
    "制服": "uniform", "连衣裙": "dress", "白裙": "white dress",
    "长裙": "long dress", "短裙": "skirt", "百褶裙": "pleated skirt",
    "衬衫": "shirt", "白衬衫": "white shirt", "毛衣": "sweater",
    "针织衫": "knit sweater", "外套": "jacket", "皮夹克": "leather jacket",
    "大衣": "coat", "风衣": "trench coat", "西装": "suit",
    "旗袍": "china dress", "汉服": "hanfu", "和服": "kimono",
    "浴衣": "yukata", "婚纱": "wedding dress", "礼服": "evening gown",
    "泳装": "swimsuit", "比基尼": "bikini", "连体泳衣": "one-piece swimsuit",
    "内衣": "lingerie", "蕾丝": "lace", "丝袜": "thighhighs",
    "过膝袜": "thighhighs", "黑丝": "black thighhighs", "白丝": "white thighhighs",
    "露肩": "off shoulder", "吊带": "camisole", "背心": "tank top",
    "运动服": "sportswear", "睡衣": "pajamas", "浴袍": "bathrobe",
    "女仆装": "maid, maid headdress", "护士服": "nurse",
    "铠甲": "armor", "斗篷": "cape", "披风": "cloak",
    "jk制服": "jk uniform", "格子裙": "plaid skirt",
    "卫衣": "hoodie", "牛仔裤": "jeans", "短裤": "shorts",
    "热裤": "short shorts", "围裙": "apron", "裸体围裙": "naked apron",
    "水手服上衣": "sailor shirt",

    # ---- 配饰 ----
    "眼镜": "glasses", "帽子": "hat", "草帽": "straw hat",
    "发饰": "hair ornament", "发带": "hair ribbon", "蝴蝶结": "bow",
    "项链": "necklace", "耳环": "earrings", "choker": "choker",
    "颈环": "choker", "手套": "gloves", "长手套": "elbow gloves",
    "皇冠": "tiara", "面纱": "veil", "口罩": "mask",
    "猫耳": "cat ears", "兔耳": "bunny ears", "头戴耳机": "headphones",
    "围巾": "scarf", "领带": "necktie", "蝴蝶结领带": "ribbon tie",
    "太阳镜": "sunglasses", "头花": "hair flower",

    # ---- 姿势与动作 ----
    "站": "standing", "站着": "standing", "坐": "sitting", "坐着": "sitting",
    "躺": "lying", "躺着": "lying", "跪": "kneeling", "跪着": "kneeling",
    "蹲": "squatting", "走": "walking", "跑": "running",
    "跳": "jumping", "转身": "turning around", "伸手": "reaching out",
    "举手": "arm up", "抱膝": "knees to chest", "交腿": "crossed legs",
    "抱臂": "crossed arms", "手扶腰": "hand on hip", "托腮": "head rest",
    "手撑脸": "hand on own cheek", "拢发": "hand in own hair",
    "背手": "arms behind back", "伸懒腰": "stretching",
    "回眸": "looking back", "歪头": "head tilt",
    "翘腿": "legs up", "叉腰": "hands on hips",
    "趴": "lying on stomach", "趴着": "lying on stomach",
    "仰躺": "lying on back", "侧躺": "lying on side",
    "瑜伽": "yoga pose", "猫腰": "arched back",
    "飞翔": "flying", "漂浮": "floating",

    # ---- 场景 ----
    "教室": "classroom", "学校": "school", "图书馆": "library",
    "咖啡厅": "cafe", "卧室": "bedroom", "床上": "on bed",
    "客厅": "living room", "浴室": "bathroom", "厨房": "kitchen",
    "办公室": "office", "街道": "street", "小巷": "alley",
    "城市": "cityscape", "夜景": "night, city lights", "海边": "beach, ocean",
    "泳池": "poolside", "森林": "forest", "花田": "flower field",
    "樱花": "cherry blossoms", "雪": "snow", "雨": "rain",
    "屋顶": "rooftop", "阳台": "balcony", "窗边": "window",
    "神社": "shrine", "宫殿": "palace", "废墟": "ruins",
    "竹林": "bamboo forest", "山": "mountain", "天空": "sky",
    "星空": "starry sky", "月光": "moonlight", "夕阳": "sunset",
    "黄昏": "dusk", "清晨": "morning", "白天": "daytime", "夜晚": "night",
    "室内": "indoors", "室外": "outdoors",
    "草原": "grassland", "沙漠": "desert", "瀑布": "waterfall",
    "车站": "train station", "列车": "train", "飞机": "airplane",
    "花园": "garden", "桥": "bridge", "城堡": "castle",

    # ---- 光照与氛围 ----
    "逆光": "backlighting", "侧光": "side lighting", "柔光": "soft lighting",
    "阳光": "sunlight", "暖光": "warm lighting", "冷光": "cool lighting",
    "霓虹": "neon lights", "烛光": "candlelight", "光斑": "bokeh",
    "梦幻": "dreamy", "唯美": "beautiful", "氛围感": "atmospheric",
    "电影感": "cinematic lighting", "景深": "depth of field",
    "丁达尔": "sunbeam", "光线": "light rays", "发光": "glowing",
    "体积光": "volumetric lighting",

    # ---- 体型 ----
    "巨乳": "large breasts", "大胸": "large breasts",
    "中等胸": "medium breasts", "贫乳": "small breasts", "平胸": "flat chest",
    "曲线": "curvy figure", "纤细": "slender", "苗条": "slim",
    "丰满": "plump", "肌肉": "muscular", "健壮": "muscular",
    "长腿": "long legs", "细腰": "narrow waist",

    # ---- 画质与风格 ----
    "高清": "highres", "超清": "ultra-detailed", "精致": "detailed",
    "水彩风": "watercolor", "油画风": "oil painting", "素描": "sketch",
    "赛璐璐": "cel shading", "厚涂": "impasto", "线稿": "lineart",
    "黑白": "monochrome", "单色": "monochrome", "复古风": "retro artstyle",

    # ---- 独立颜色词 ----
    # 置于词典末尾，因按键长度倒序匹配，「黑发」「黑丝」等复合词会先命中，
    # 此处仅接管「黑旗袍」这类未组合成固定词条的散落颜色描述。
    "黑色": "black", "白色": "white", "红色": "red", "蓝色": "blue",
    "绿色": "green", "紫色": "purple", "黄色": "yellow", "粉色": "pink",
    "橙色": "orange", "灰色": "grey", "金色": "gold", "银色": "silver",
    "黑": "black", "白": "white", "红": "red", "蓝": "blue",
    "绿": "green", "紫": "purple", "粉": "pink", "灰": "grey",
}

# 按键长度倒序，优先匹配长词，避免「长发」被「发」截断
_SORTED_KEYS = sorted(LEXICON.keys(), key=len, reverse=True)

LLM_INSTRUCTION = (
    "你是 danbooru 标签转换器。把用户的中文画面描述转成英文 danbooru 标签。\n"
    "规则：\n"
    "1. 只输出标签，用英文逗号分隔，不要任何解释、编号或换行。\n"
    "2. 使用 danbooru 实际存在的标签，例如 1girl / long hair / school uniform。\n"
    "3. 不要输出画师名、不要输出 masterpiece 或 best quality 之类的质量词。\n"
    "4. 不要输出括号权重符号（如 {{ }} 或 [ ]）。\n"
    "5. 若描述里有人数，务必保留 1girl 或 1boy 这类标签。\n"
    "6. 控制在 25 个标签以内。\n"
    "7. 描述中的颜色、服装、发型、表情、姿势都要转换，不要遗漏。\n"
    "8. 不要输出 NSFW 相关的露骨标签。\n\n"
    "示例：\n"
    "中文描述：一个穿白色连衣裙的长发女孩站在花田里\n"
    "标签：1girl, solo, long hair, white dress, standing, flower field, outdoors\n\n"
    "中文描述：黑发红眼的少女坐在教室里看窗外，穿着校服\n"
    "标签：1girl, black hair, red eyes, sitting, classroom, looking out window, school uniform, indoors\n\n"
    "中文描述：金发双马尾女孩在海边比基尼，夕阳逆光\n"
    "标签：1girl, blonde hair, twintails, beach, bikini, sunset, backlighting, ocean\n\n"
    "中文描述：{text}\n"
    "标签："
)


def contains_chinese(text):
    """判断文本是否含中日韩统一表意文字。"""
    return bool(re.search(r"[一-鿿]", str(text or "")))


def translate_by_lexicon(text):
    """用词典替换中文片段，返回 (标签串, 未识别的中文残留)。

    命中的键会从原文中移除，剩余中文即词典未覆盖的部分；输入中原有的
    英文标签会一并保留，避免中英混写时丢失用户已经写好的标签。
    """
    remaining = str(text or "")
    matched = []
    for key in _SORTED_KEYS:
        if key in remaining:
            matched.append(LEXICON[key])
            # 用分隔符占位，避免相邻英文片段在移除中文后粘成一个错误标签。
            remaining = remaining.replace(key, ",")

    # 去掉未识别中文，仅提取用户原本写入的英文标签。中文标点和换行都视为
    # 标签分隔符，ASCII 冒号保留给 artist:xxx 与 NAI 数值权重语法。
    english_text = re.sub(r"[一-鿿]+", ",", remaining)
    english_text = re.sub(r"[，、。；;：！!？?\r\n\t]+", ",", english_text)
    existing = [
        part.strip()
        for part in english_text.split(",")
        if part.strip() and re.search(r"[a-z0-9]", part, re.I)
    ]

    # 去重并保持首次出现顺序
    tags = []
    seen = set()
    for chunk in (*matched, *existing):
        for tag in chunk.split(","):
            tag = tag.strip()
            normalized = tag.lower()
            if tag and normalized not in seen:
                seen.add(normalized)
                tags.append(tag)

    # 只提取连续中文片段，避免无空格混写时把两侧英文一起交给 LLM。
    leftover_cn = " ".join(re.findall(r"[一-鿿]+", remaining))
    return ", ".join(tags), leftover_cn


async def translate_by_llm(context, text, timeout=30):
    """调用 AstrBot 的 LLM provider 转换，失败返回 None。

    兼容 4.x 的 get_using_provider().text_chat 与旧版 context.llm。
    """
    if not context or not text:
        return None
    try:
        provider = None
        if hasattr(context, "get_using_provider"):
            provider = context.get_using_provider()
        elif hasattr(context, "llm"):
            provider = context.llm
        if not provider:
            logger.debug("[叶子的逼] 无可用 LLM provider，跳过智能翻译")
            return None

        prompt = LLM_INSTRUCTION.format(text=text)
        if hasattr(provider, "text_chat"):
            import asyncio

            response = await asyncio.wait_for(
                provider.text_chat(prompt=prompt), timeout=timeout
            )
            raw = (
                getattr(response, "completion_text", None)
                or getattr(response, "text", None)
                or str(response)
            )
        elif hasattr(provider, "complete"):
            raw = str(await provider.complete(prompt))
        else:
            return None

        return _sanitize_llm_output(raw)
    except Exception as exc:
        logger.warning(f"[叶子的逼] LLM 翻译失败，降级为词典结果: {exc}")
        return None


def _sanitize_llm_output(raw):
    """清洗 LLM 输出：去掉解释性文字、权重符号与质量词。"""
    text = str(raw or "").strip()
    if not text:
        return None

    # 模型可能带前缀说明或代码块，取最后一段非空内容
    text = re.sub(r"^```[a-z]*|```$", "", text, flags=re.M).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    # 含逗号的行才可能是标签串，取最长的那行
    candidates = [line for line in lines if "," in line] or lines
    text = max(candidates, key=len)

    # 去掉「标签：」这类前缀和权重符号
    text = re.sub(r"^[^:：]{0,12}[:：]\s*", "", text)
    text = re.sub(r"[{}\[\]]", "", text)

    banned = {
        # 质量词
        "masterpiece", "best quality", "amazing quality", "very aesthetic",
        "absurdres", "highres", "high quality", "best aesthetic",
        # NSFW 露骨标签
        "nude", "naked", "nipples", "pussy", "penis", "cum", "sex",
        "vaginal", "anal", "oral", "penetration", "ejaculation",
    }
    tags = []
    seen = set()
    for tag in text.split(","):
        tag = tag.strip().strip(".")
        low = tag.lower()
        if not tag or low in banned or low in seen:
            continue
        if contains_chinese(tag):        # 未转换成功的中文直接丢弃
            continue
        if low.startswith("artist:"):    # 画师串由预设负责
            continue
        seen.add(low)
        tags.append(tag)

    return ", ".join(tags[:25]) if tags else None


async def to_tags(context, text, use_llm=True):
    """把用户输入转为标签串，返回 (标签, 说明)。

    纯英文输入直接返回；中文先查词典，残留部分再交 LLM。
    """
    raw = str(text or "").strip()
    if not raw:
        return "", ""

    if not contains_chinese(raw):
        return raw, ""

    lexicon_tags, leftover = translate_by_lexicon(raw)

    if leftover:
        # 仅在开启 LLM 时尝试补翻译，失败则走下方的降级分支
        if use_llm:
            llm_tags = await translate_by_llm(context, leftover)
            if llm_tags:
                merged = ", ".join(part for part in (lexicon_tags, llm_tags) if part)
                return merged, f"已智能翻译：{leftover}"
        if not lexicon_tags:
            # NAI 不识别中文，返回空标签交由命令层终止，避免浪费生成额度。
            return "", "未能识别中文描述，建议改用英文标签或开启中文智能翻译"
        return lexicon_tags, f"未识别部分已忽略：{leftover}"

    if not lexicon_tags:
        return "", "未能识别中文描述，建议改用英文标签或开启中文智能翻译"
    return lexicon_tags, ""
