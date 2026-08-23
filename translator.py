"""中文自然语言转 danbooru 标签。

NAI 只认英文 danbooru 标签，中文描述直接送入基本无效。
采用三层策略：

1. 词典层：常见描述和高频角色按从左到右最长匹配查表，零成本、离线可用。
2. Danbooru 层：词典未覆盖的短中文按角色/作品别名查询官方 wiki 与自动补全。
3. LLM 层：仍未覆盖的部分交给 AstrBot 的 LLM provider，再与前两层结果合并。

任一层失败都不阻断出图，能转多少转多少。
"""

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

from astrbot.api import logger

# 中文描述到 danbooru 标签的映射。
# 键为可能出现的中文写法，值为对应标签，多个标签用逗号分隔。
# 匹配时从左到右取当前位置能命中的最长键，避免「长发」被「发」截断。
LEXICON = {
    # ---- 人数与主体 ----
    "一个女孩": "1girl, solo", "一位少女": "1girl, solo", "一名少女": "1girl, solo",
    "女孩": "1girl", "少女": "1girl", "女生": "1girl", "女性": "1girl",
    "女高中生": "1girl, high school", "女学生": "1girl, student",
    "单人": "solo", "独自": "solo", "一个人": "solo",
    "男孩": "1boy", "少年": "1boy", "男性": "1boy", "男生": "1boy",
    "两个女孩": "2girls", "两个少女": "2girls", "三个女孩": "3girls",
    "双人": "2girls", "多人": "multiple girls", "多人群": "multiple girls",
    "御姐风": "mature female, adult woman",
    "御姐": "mature female, adult woman", "成熟女性": "mature female",
    "少妇": "mature female", "阿姨": "mature female", "熟女": "mature female",
    "正太": "shota", "萝莉": "loli", "幼女": "loli",
    "情侣": "1boy, 1girl", "姐弟": "1boy, 1girl",
    "美人": "beautiful", "美女": "1girl, beautiful",
    "绝美少女": "1girl, beautiful", "空灵少女": "1girl, ethereal",
    "指挥官少女": "1girl, commander",
    "天使": "angel, wings", "恶魔": "demon, demon horns",
    "吸血鬼": "vampire", "魔女": "witch", "女巫": "witch",
    "精灵": "elf, pointy ears", "妖精": "fairy, wings",
    "猫娘": "cat girl, cat ears, cat tail",
    "兔娘": "bunny girl, bunny ears",
    "狐娘": "fox girl, fox ears, fox tail",
    "龙娘": "dragon girl", "人鱼": "mermaid",
    "机甲少女": "1girl, mecha, mecha musume",
    "机能少女": "1girl, cyberpunk, bodysuit",
    "女仆": "maid", "护士": "nurse", "巫女": "miko",
    "偶像": "idol", "公主": "princess", "女王": "queen",
    "骑士": "knight", "武士": "samurai", "忍者": "ninja",
    "魔法少女": "magical girl", "学生": "student",
    "老师": "teacher", "秘书": "secretary",

    # ---- 常用角色与作品 ----
    # 用户经常只发角色名。必须落到 danbooru 实际角色标签，不能当未知中文丢掉。
    "惣流明日香兰格雷": "1girl, souryuu asuka langley, neon genesis evangelion",
    "惣流·明日香·兰格雷": "1girl, souryuu asuka langley, neon genesis evangelion",
    "明日香兰格雷": "1girl, souryuu asuka langley, neon genesis evangelion",
    "式波明日香": "1girl, shikinami asuka langley, neon genesis evangelion",
    "明日香": "1girl, souryuu asuka langley, neon genesis evangelion",
    "アスカ": "1girl, souryuu asuka langley, neon genesis evangelion",
    "绫波丽": "1girl, ayanami rei, neon genesis evangelion",
    "绫波": "1girl, ayanami rei, neon genesis evangelion",
    "碇真嗣": "1boy, ikari shinji, neon genesis evangelion",
    "真嗣": "1boy, ikari shinji, neon genesis evangelion",
    "渚薰": "1boy, nagisa kaworu, neon genesis evangelion",
    "葛城美里": "1girl, katsuragi misato, neon genesis evangelion",
    "初号机": "eva 01, neon genesis evangelion",
    "新世纪福音战士": "neon genesis evangelion",
    "福音战士": "neon genesis evangelion",
    "初音未来": "1girl, hatsune miku, vocaloid",
    "初音": "1girl, hatsune miku, vocaloid",
    "镜音铃": "1girl, kagamine rin, vocaloid",
    "镜音连": "1boy, kagamine len, vocaloid",
    "巡音流歌": "1girl, megurine luka, vocaloid",
    "蕾姆": "1girl, rem (re:zero), re:zero kara hajimeru isekai seikatsu",
    "拉姆": "1girl, ram (re:zero), re:zero kara hajimeru isekai seikatsu",
    "爱蜜莉雅": "1girl, emilia (re:zero), re:zero kara hajimeru isekai seikatsu",
    "艾米莉亚": "1girl, emilia (re:zero), re:zero kara hajimeru isekai seikatsu",
    "祢豆子": "1girl, kamado nezuko, kimetsu no yaiba",
    "炭治郎": "1boy, kamado tanjirou, kimetsu no yaiba",
    "蝴蝶忍": "1girl, kochou shinobu, kimetsu no yaiba",
    "甘露寺": "1girl, kanroji mitsuri, kimetsu no yaiba",
    "路飞": "1boy, monkey d. luffy, one piece",
    "索隆": "1boy, roronoa zoro, one piece",
    "娜美": "1girl, nami (one piece), one piece",
    "鸣人": "1boy, uzumaki naruto, naruto (series)",
    "佐助": "1boy, uchiha sasuke, naruto (series)",
    "雏田": "1girl, hyuuga hinata, naruto (series)",
    "悟空": "1boy, son goku, dragon ball",
    "贝吉塔": "1boy, vegeta, dragon ball",
    "2b": "1girl, 2b (nier:automata), nier:automata",
    "2B": "1girl, 2b (nier:automata), nier:automata",
    "约尔": "1girl, yor briar, spy x family",
    "阿尼亚": "1girl, anya (spy x family), spy x family",
    "芙莉莲": "1girl, frieren, sousou no frieren",
    "菲伦": "1girl, fern (sousou no frieren), sousou no frieren",
    "高木": "1girl, takagi-san, karakai jouzu no takagi-san",
    "喜多川海梦": "1girl, kitagawa marin, sono bisque doll wa koi wo suru",
    "海梦": "1girl, kitagawa marin, sono bisque doll wa koi wo suru",
    "后藤一里": "1girl, gotoh hitori, bocchi the rock!",
    "波奇": "1girl, gotoh hitori, bocchi the rock!",
    "伊蕾娜": "1girl, elaina (majo no tabitabi), majo no tabitabi",
    "薇尔莉特": "1girl, violet evergarden, violet evergarden (series)",

    # ---- 发长与发型 ----
    "拖地长发": "absurdly long hair",
    "及腰长发": "very long hair", "超长发": "very long hair",
    "湿润发丝": "wet hair", "漂浮发丝": "floating hair",
    "长发": "long hair", "短发": "short hair", "中长发": "medium hair",
    "齐肩短发": "short hair, bob cut", "齐肩": "medium hair",
    "双马尾": "twintails", "单马尾": "ponytail", "侧马尾": "side ponytail",
    "高马尾": "high ponytail", "低马尾": "low ponytail", "马尾": "ponytail",
    "双丸子头": "double bun", "双丸子": "double bun",
    "丸子头": "hair bun", "盘发": "hair bun",
    "波波头": "bob cut", "齐刘海": "blunt bangs", "斜刘海": "swept bangs",
    "刘海": "bangs", "无刘海": "hair between eyes",
    "麻花辫": "braid", "双辫": "twin braids", "编发": "braid",
    "单辫": "single braid", "法式辫": "french braid",
    "卷发": "wavy hair", "大波浪": "wavy hair", "直发": "straight hair",
    "凌乱头发": "messy hair", "凌乱发型": "messy hair", "乱发": "messy hair",
    "湿发": "wet hair", "心形发": "heart hair bun", "呆毛": "ahoge",
    "披肩发": "hair over shoulder", "遮眼发": "hair over eyes",
    "侧扫发": "sidelocks", "鬓发": "sidelocks",
    "高髻": "high bun", "散发": "hair down",
    "头发": "hair", "发丝": "hair",

    # ---- 发色 ----
    "紫罗兰发": "lavender hair", "渐变发色": "gradient hair",
    "黑发": "black hair", "白发": "white hair", "银发": "silver hair",
    "金发": "blonde hair", "棕发": "brown hair", "栗发": "chestnut hair",
    "红发": "red hair", "粉发": "pink hair", "粉色头发": "pink hair",
    "蓝发": "blue hair", "绿发": "green hair", "紫发": "purple hair",
    "橙发": "orange hair", "青发": "teal hair",
    "亚麻色": "light brown hair", "挑染": "streaked hair",
    "双色发": "two-tone hair", "彩虹发": "rainbow hair",

    # ---- 瞳色 ----
    "黑眼": "black eyes", "黑瞳": "black eyes",
    "蓝眼": "blue eyes", "蓝瞳": "blue eyes",
    "红眼": "red eyes", "红瞳": "red eyes",
    "绿眼": "green eyes", "绿瞳": "green eyes",
    "紫眼": "purple eyes", "紫瞳": "purple eyes",
    "金眼": "golden eyes", "金瞳": "golden eyes",
    "琥珀眼": "amber eyes", "琥珀瞳": "amber eyes",
    "灰眼": "grey eyes", "灰瞳": "grey eyes",
    "粉眼": "pink eyes", "粉瞳": "pink eyes",
    "异色瞳": "heterochromia", "渐变瞳": "gradient eyes",
    "荧光眼眸": "glowing eyes", "发光眼睛": "glowing eyes",
    "眼眸": "eyes",

    # ---- 眼型与表情 ----
    "精致五官": "detailed face",
    "灿烂笑": ":d", "大笑": "open mouth, laughing",
    "微笑": "soft smile", "笑容": "smile", "笑": "smile",
    "坏笑": "smirk", "得意": "smug", "自信": "confident",
    "冷漠": "expressionless", "无表情": "expressionless",
    "严肃": "serious", "生气": "angry", "愤怒": "angry",
    "皱眉": "furrowed brow", "撅嘴": "pout", "不满": "pout",
    "害羞": "blush, embarrassed", "脸红": "blush",
    "哭": "crying", "流泪": "tears", "落泪": "tears",
    "含泪": "tears, crying", "抽泣": "crying",
    "惊讶": "surprised, wide eyes", "震惊": "shocked",
    "困": "sleepy, half-closed eyes", "困倦": "sleepy",
    "闭眼": "closed eyes", "半闭眼": "half-closed eyes",
    "垂眼": "tareme", "吊眼": "tsurime", "眯眼": "narrowed eyes",
    "妩媚": "seductive smile, half-closed eyes", "诱惑": "seductive smile",
    "温柔": "gentle smile", "治愈": "gentle smile, warm lighting",
    "看着镜头": "looking at viewer", "看向镜头": "looking at viewer",
    "看向别处": "looking away", "看窗外": "looking out window",
    "回头": "looking back", "回眸": "looking back",
    "抬头": "looking up", "低头": "looking down",
    "侧颜": "profile", "侧脸": "profile",
    "吐舌": "tongue out", "舔唇": "licking lips",
    "咬唇": "biting lip", "眨眼": "wink",
    "开朗": "cheerful", "忧郁": "sad", "悲伤": "sad",
    "平静": "calm", "专注": "focused",
    "傲娇": "tsundere", "病娇": "yandere",
    "空灵": "ethereal", "神秘": "mysterious",

    # ---- 服装 ----
    "jk制服": "jk uniform, school uniform",
    "JK制服": "jk uniform, school uniform",
    "水手服上衣": "sailor shirt",
    "水手服": "sailor collar, school uniform",
    "校服": "school uniform", "制服": "uniform",
    "白色连衣裙": "white dress", "黑色连衣裙": "black dress",
    "红色连衣裙": "red dress", "连衣裙": "dress",
    "白裙": "white dress", "长裙": "long dress", "短裙": "skirt",
    "百褶裙": "pleated skirt", "格子裙": "plaid skirt",
    "白衬衫": "white shirt", "衬衫": "shirt",
    "针织衫": "knit sweater", "毛衣": "sweater",
    "皮夹克": "leather jacket", "外套": "jacket",
    "大衣": "coat", "风衣": "trench coat", "西装": "suit",
    "旗袍": "china dress", "汉服": "hanfu", "和服": "kimono",
    "浴衣": "yukata", "婚纱": "wedding dress", "礼服": "evening gown",
    "连体泳衣": "one-piece swimsuit", "泳装": "swimsuit", "比基尼": "bikini",
    "内衣": "lingerie", "蕾丝": "lace",
    "过膝袜": "thighhighs", "黑丝": "black thighhighs",
    "白丝": "white thighhighs", "丝袜": "thighhighs",
    "连裤袜": "pantyhose", "黑裤袜": "black pantyhose",
    "露肩": "off shoulder", "吊带": "camisole", "背心": "tank top",
    "运动服": "sportswear", "睡衣": "pajamas", "浴袍": "bathrobe",
    "女仆装": "maid, maid headdress", "护士服": "nurse",
    "巫女服": "miko", "铠甲": "armor",
    "斗篷": "cape", "披风": "cloak",
    "卫衣": "hoodie", "牛仔裤": "jeans", "短裤": "shorts",
    "热裤": "short shorts", "裸体围裙": "naked apron", "围裙": "apron",
    "洛丽塔洋装": "lolita fashion, dress",
    "洛丽塔": "lolita fashion", "洋装": "dress",
    "哥特洛丽塔": "gothic lolita", "哥特": "gothic",
    "机能风风衣": "techwear, trench coat",
    "机能风": "techwear, cyberpunk",
    "赛博朋克": "cyberpunk", "未来战甲": "futuristic armor",
    "紧身衣": "bodysuit", "胶衣": "latex",
    "晚礼服": "evening gown", "纱裙": "sheer dress",
    "古风黑金汉服": "hanfu, black, gold",
    "黑金汉服": "hanfu, black, gold",
    "古风": "ancient chinese clothes",
    "华美刺绣": "embroidery, ornate",
    "破旧衣服": "torn clothes", "湿衣服": "wet clothes",
    "敞开外套": "open jacket", "解开扣子": "unbuttoned",
    "赤脚": "barefoot", "裸足": "barefoot",

    # ---- 配饰 ----
    "蕾丝发带": "lace, hair ribbon",
    "头戴耳机": "headphones", "战术目镜": "tactical visor, goggles",
    "眼镜": "glasses", "太阳镜": "sunglasses",
    "帽子": "hat", "草帽": "straw hat", "贝雷帽": "beret",
    "发饰": "hair ornament", "发带": "hair ribbon",
    "蝴蝶结领带": "ribbon tie", "蝴蝶结": "bow",
    "项链": "necklace", "耳环": "earrings", "耳钉": "earrings",
    "choker": "choker", "颈环": "choker", "项圈": "choker",
    "长手套": "elbow gloves", "手套": "gloves",
    "皇冠": "tiara", "王冠": "crown", "面纱": "veil", "口罩": "mask",
    "猫耳": "cat ears", "兔耳": "bunny ears", "狐耳": "fox ears",
    "围巾": "scarf", "领带": "necktie",
    "头花": "hair flower", "花饰": "flower",
    "机械义肢": "mechanical arms, cyborg",
    "发光线缆": "glowing cables",
    "全息投影": "hologram",
    "折扇": "folding fan", "团扇": "uchiwa",
    "雨伞": "umbrella", "阳伞": "parasol",
    "背包": "backpack", "书包": "school bag",
    "手提包": "handbag", "公文包": "briefcase",
    "手表": "watch", "手镯": "bracelet", "戒指": "ring",
    "纹身": "tattoo", "眼罩": "eyepatch",
    "翅膀": "wings", "光环": "halo",
    "猫尾": "cat tail", "狐尾": "fox tail", "兔尾": "bunny tail",

    # ---- 姿势与动作 ----
    "站着": "standing", "坐着": "sitting", "躺着": "lying",
    "跪着": "kneeling", "趴着": "lying on stomach",
    "站": "standing", "坐": "sitting", "躺": "lying",
    "跪": "kneeling", "蹲": "squatting",
    "走": "walking", "跑": "running", "跳": "jumping",
    "转身": "turning around", "伸手": "reaching out",
    "举手": "arm up", "双手举起": "arms up",
    "抱膝": "knees to chest", "交腿": "crossed legs",
    "抱臂": "crossed arms", "手扶腰": "hand on hip",
    "托腮": "head rest", "手撑脸": "hand on own cheek",
    "拢发": "hand in own hair", "背手": "arms behind back",
    "伸懒腰": "stretching", "歪头": "head tilt",
    "翘腿": "legs up", "叉腰": "hands on hips",
    "趴": "lying on stomach", "仰躺": "lying on back",
    "侧躺": "lying on side", "瑜伽": "yoga pose", "猫腰": "arched back",
    "飞翔": "flying", "漂浮": "floating",
    "跳舞": "dancing", "战斗": "fighting", "挥剑": "swinging weapon",
    "持剑": "holding sword", "拔刀": "drawing sword",
    "手持": "holding", "拿着": "holding", "握着": "holding",
    "穿着": "wearing", "戴着": "wearing",
    "看书": "reading, book", "写字": "writing",
    "喝茶": "drinking, tea", "喝酒": "drinking, alcohol",
    "吃东西": "eating", "唱歌": "singing",
    "拥抱": "hug", "牵手": "holding hands", "亲吻": "kiss",
    "比心": "heart hands", "挥手": "waving",
    "祈祷": "praying", "沉思": "thinking",
    "倚靠": "leaning", "靠墙": "against wall",
    "从水中升起": "emerging from water",
    "回头看": "looking back",

    # ---- 构图与镜头 ----
    "全身像": "full body", "全身": "full body",
    "半身像": "upper body", "半身": "upper body",
    "特写": "close-up", "面部特写": "portrait, close-up",
    "侧光特写": "close-up, side lighting",
    "从侧面": "from side", "侧面": "from side, profile",
    "正面": "from front, looking at viewer",
    "背面": "from behind", "背影": "from behind",
    "俯视": "from above", "仰视": "from below",
    "鸟瞰": "bird's eye view", "虫视": "worm's eye view",
    "过肩镜头": "over shoulder",
    "三分构图": "rule of thirds",
    "居中构图": "centered",
    "广角": "wide shot", "远景": "wide shot",
    "中景": "medium shot", "近景": "close-up",
    "动态模糊": "motion blur",
    "景深": "depth of field", "虚化": "bokeh",
    "电影级光影": "cinematic lighting",
    "电影感": "cinematic lighting",
    "微光暗调": "dim lighting, chiaroscuro",
    "微光": "soft lighting",
    "唯美仙侠": "xianxia, beautiful, ethereal",
    "仙侠": "xianxia, chinese clothes",

    # ---- 场景 ----
    "雨夜霓虹街头": "night, rain, neon lights, street",
    "雨夜街道": "night, rain, street",
    "雨夜": "night, rain",
    "霓虹街头": "neon lights, street",
    "教室": "classroom", "学校": "school", "图书馆": "library",
    "咖啡厅": "cafe", "卧室": "bedroom", "床上": "on bed",
    "客厅": "living room", "浴室": "bathroom", "厨房": "kitchen",
    "办公室": "office", "街道": "street", "小巷": "alley",
    "城市": "cityscape", "夜景": "night, city lights",
    "海边": "beach, ocean", "海滩": "beach", "沙滩": "beach, sand",
    "泳池": "poolside", "森林": "forest", "花田": "flower field",
    "向日葵花海": "sunflower, flower field",
    "花海": "flower field", "向日葵": "sunflower",
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
    "深海幽蓝幻境": "underwater, deep sea, blue theme, fantasy",
    "深海": "underwater, deep sea", "海底": "underwater",
    "水下": "underwater", "水面": "on water",
    "星际战舰舰桥": "spaceship, bridge, sci-fi",
    "战舰舰桥": "spaceship, bridge",
    "舰桥": "bridge, spaceship", "战舰": "spaceship, warship",
    "星云璀璨": "nebula, starry sky", "星云": "nebula",
    "太空": "space, starry sky", "宇宙": "space",
    "赛博都市": "cyberpunk, cityscape, neon lights",
    "天台": "rooftop", "钟楼": "clock tower",
    "教堂": "church", "钟塔": "clock tower",
    "湖边": "lake", "河边": "river", "溪流": "stream",
    "夜市": "night market", "祭典": "festival",
    "烟火": "fireworks", "灯笼": "lantern",
    "夏日祭": "summer festival", "夏日": "summer",
    "冬日": "winter", "秋日": "autumn", "春日": "spring",
    "微风": "breeze, wind", "大风": "wind",
    "雷雨": "thunderstorm, rain", "雾": "fog", "云": "clouds",

    # ---- 物品与武器 ----
    "青龙偃月刀": "guandao, guan dao, weapon",
    "偃月刀": "guandao, weapon",
    "武士刀": "katana, sword", "太刀": "katana, sword",
    "长剑": "sword", "短剑": "dagger", "匕首": "dagger",
    "剑": "sword", "刀": "sword", "枪": "gun",
    "步枪": "rifle", "手枪": "handgun", "狙击枪": "sniper rifle",
    "弓箭": "bow, arrow", "长弓": "bow", "弩": "crossbow",
    "长枪": "spear", "长矛": "spear", "戟": "halberd",
    "斧": "axe", "锤": "hammer", "鞭": "whip",
    "法杖": "staff", "魔杖": "wand", "魔导书": "grimoire, book",
    "盾": "shield", "镰刀": "scythe",
    "雨夜霓虹": "night, rain, neon lights",
    "发光水母": "jellyfish, glowing", "水母": "jellyfish",
    "梦幻水波倒影": "reflection, water, ripples, dreamy",
    "水波倒影": "reflection, water, ripples",
    "倒影": "reflection", "水波": "ripples, water",
    "红酒玫瑰": "red wine, rose", "红酒": "red wine, wine glass",
    "玫瑰": "rose", "花束": "bouquet",
    "书": "book", "茶杯": "teacup", "咖啡杯": "coffee cup",
    "酒杯": "wine glass", "蜡烛": "candle",
    "灯笼": "lantern", "灯": "lamp",
    "伞": "umbrella", "扇子": "fan",
    "手机": "smartphone", "电脑": "computer",
    "耳机": "headphones", "相机": "camera",
    "自行车": "bicycle", "摩托车": "motorcycle",
    "汽车": "car", "马车": "horse, cart",

    # ---- 光照与氛围 ----
    "柔和逆光": "backlighting, soft lighting",
    "逆光": "backlighting", "侧光": "side lighting",
    "柔光": "soft lighting", "硬光": "hard lighting",
    "阳光": "sunlight", "暖光": "warm lighting", "冷光": "cool lighting",
    "霓虹": "neon lights", "烛光": "candlelight", "光斑": "bokeh",
    "梦幻": "dreamy", "唯美": "beautiful", "氛围感": "atmospheric",
    "丁达尔": "sunbeam", "光线追踪": "ray tracing, realistic lighting",
    "光线": "light rays", "发光": "glowing",
    "体积光": "volumetric lighting",
    "暗调": "dark, dim lighting", "高对比": "high contrast",
    "低饱和": "muted color", "高饱和": "saturated",
    "金色时光": "golden hour", "蓝色时刻": "blue hour",
    "窗光": "window light", "舞台光": "stage lights",

    # ---- 体型 ----
    "巨乳": "large breasts", "大胸": "large breasts",
    "中等胸": "medium breasts", "贫乳": "small breasts", "平胸": "flat chest",
    "曲线": "curvy figure", "纤细": "slender", "苗条": "slim",
    "丰满": "plump", "肌肉": "muscular", "健壮": "muscular",
    "长腿": "long legs", "细腰": "narrow waist",
    "娇小": "petite", "高挑": "tall",
    "尖耳朵": "pointy ears", "虎牙": "fang",

    # ---- 画质与风格 ----
    "虚幻引擎5渲染": "unreal engine 5, realistic",
    "虚幻引擎": "unreal engine, realistic",
    "日系水彩透明感": "watercolor, translucent, anime coloring",
    "水彩透明": "watercolor, translucent",
    "厚涂油画": "oil painting, impasto",
    "高清": "highres", "超清": "ultra-detailed", "精致": "detailed",
    "水彩风": "watercolor", "油画风": "oil painting", "素描": "sketch",
    "赛璐璐": "cel shading", "厚涂": "impasto", "线稿": "lineart",
    "黑白": "monochrome", "单色": "monochrome", "复古风": "retro artstyle",
    "日系": "anime coloring", "厚涂风": "impasto, painterly",
    "写实": "realistic", "半写实": "semi-realistic",
    "像素风": "pixel art", "剪纸风": "paper cutout",
    "水墨": "ink wash painting, chinese style",
    "工笔": "gongbi, chinese style",
    "扁平色块": "flat color", "极简": "minimalism",
    "华丽": "ornate, detailed",
    "复古": "retro artstyle",
    "蒸汽朋克": "steampunk",
    "暗黑": "dark, dark theme",
    "神圣": "holy, glowing",
    "中式": "chinese style",
    "中国风": "chinese style",
    "日式": "japanese clothes",
    "和风": "japanese clothes",
    "西洋": "western",
    "维多利亚": "victorian",

    # ---- 构图补全 ----
    "上半身": "upper body", "下半身": "lower body",
    "头像": "portrait", "肖像": "portrait",
    "过肩": "over shoulder",

    # ---- 科幻与氛围补全 ----
    "星际指挥官少女": "1girl, commander, sci-fi",
    "星际指挥官": "commander, sci-fi",
    "星际": "space, sci-fi",
    "高科技": "high-tech, sci-fi",
    "光辉": "glowing, light rays",
    "极光": "aurora",
    "银河": "milky way, starry sky",
    "月亮": "moon", "太阳": "sun", "星星": "stars",
    "云海": "sea of clouds", "悬崖": "cliff",
    "火焰": "fire", "冰": "ice", "雷电": "lightning",
    "闪电": "lightning", "烟雾": "smoke",
    "花瓣": "petals", "落花": "falling petals",
    "飘雪": "snowing", "粒子": "particles",
    "魔法阵": "magic circle", "符文": "runes",
    "背景": "background", "细节": "detailed",

    # ---- 服装与身体补全 ----
    "超短裙": "miniskirt", "迷你裙": "miniskirt",
    "包臀裙": "pencil skirt", "西装裙": "pencil skirt, suit",
    "职业装": "business suit", "无袖": "sleeveless",
    "短袖": "short sleeves", "长袖": "long sleeves",
    "高领": "turtleneck", "低胸": "cleavage",
    "露脐": "navel", "锁骨": "collarbone",
    "裸肩": "bare shoulders", "裸背": "bare back",
    "绝对领域": "zettai ryouiki",
    "美腿": "long legs, thighs",
    "爆乳": "huge breasts", "乳沟": "cleavage",
    "湿身": "wet, wet clothes", "透视": "see-through",
    "开襟": "open clothes",

    # ---- 独立颜色词 ----
    # 置于词典末尾，因最长匹配会先吃掉「黑发」「黑丝」等复合词，
    # 此处仅接管「黑旗袍」这类未组合成固定词条的散落颜色描述。
    "黑色": "black", "白色": "white", "红色": "red", "蓝色": "blue",
    "绿色": "green", "紫色": "purple", "黄色": "yellow", "粉色": "pink",
    "橙色": "orange", "灰色": "grey", "金色": "gold", "银色": "silver",
    "青色": "teal", "棕色": "brown", "透明": "transparent",
    "黑金": "black, gold", "幽蓝": "blue theme, dark blue",
    "黑": "black", "白": "white", "红": "red", "蓝": "blue",
    "绿": "green", "紫": "purple", "粉": "pink", "灰": "grey",
    "金": "gold", "银": "silver",
}

# 口语虚词、量词和语法残片，命中后不进入残留，也不送给 LLM。
STOPWORDS = {
    "一个", "一位", "一名", "一只", "一件", "一条", "一顶", "一双",
    "一把", "一根", "一张", "一幅", "一些", "一点", "有点", "有些",
    "那种", "这种", "那个", "这个", "那里", "这里", "其中",
    "然后", "而且", "但是", "因为", "所以", "如果", "的话",
    "非常", "特别", "十分", "有点", "稍微", "比较",
    "以及", "或者", "还是", "正在", "已经", "一下",
    "她的", "他的", "它的", "我的", "你的",
    "的", "了", "着", "过", "在", "里", "中", "内",
    "和", "与", "及", "并", "又", "也", "很",
    "把", "被", "给", "让", "向", "从", "到", "对", "用",
    "就", "还", "都", "而", "但", "或", "如", "比",
    "得", "地", "吗", "呢", "吧", "啊", "呀", "哦", "哈",
    "这", "那", "个", "些", "们", "你", "我", "他", "她", "它",
    "其", "所", "是", "有", "会", "能", "要", "去", "来",
    "上", "下", "前", "后", "左", "右",
    "穿", "戴", "拿", "看", "带",
}

_SORTED_KEYS = sorted(LEXICON.keys(), key=len, reverse=True)
_KEYS_BY_FIRST = defaultdict(list)
for _key in _SORTED_KEYS:
    _KEYS_BY_FIRST[_key[0]].append(_key)
_SORTED_STOPWORDS = sorted(STOPWORDS, key=len, reverse=True)

DANBOORU_AUTOCOMPLETE = "https://danbooru.donmai.us/autocomplete.json"
DANBOORU_WIKI = "https://danbooru.donmai.us/wiki_pages.json"
DANBOORU_TAGS = "https://danbooru.donmai.us/tags.json"
DANBOORU_UA = (
    "astrbot_plugin_nai_draw/1.7.4 "
    "(+https://github.com/TsoiTZF/astrbot_plugin_nai_draw)"
)
_LOOKUP_CACHE = {}
_LOOKUP_CACHE_LIMIT = 256
_NAME_TOKEN_RE = re.compile(r"[一-鿿ぁ-んァ-ン]{2,12}")

LLM_INSTRUCTION = (
    "你是 danbooru 标签转换器。把用户的中文画面描述转成英文 danbooru 标签。\n"
    "规则：\n"
    "1. 只输出标签，用英文逗号分隔，不要任何解释、编号或换行。\n"
    "2. 使用 danbooru 实际存在的标签，例如 1girl / long hair / school uniform。\n"
    "3. 不要输出画师名、不要输出 masterpiece 或 best quality 之类的质量词。\n"
    "4. 不要输出括号权重符号（如 {{ }} 或 [ ]）。\n"
    "5. 若描述里有人数，务必保留 1girl 或 1boy 这类标签。\n"
    "6. 控制在 25 个标签以内。\n"
    "7. 颜色、服装、发型、表情、姿势、构图、道具、场景都要转换，不要遗漏。\n"
    "8. 武器要写成具体标签，例如 katana、guandao、spear，不要只写 weapon。\n"
    "9. 不要输出 NSFW 相关的露骨标签。\n"
    "10. 若用户只发角色名、外号或作品名，必须输出 danbooru 角色标签，并补 1girl 或 1boy。\n"
    "    例如明日香 = souryuu asuka langley，初音 = hatsune miku。不要把角色名译成普通英文单词。\n\n"
    "示例：\n"
    "中文描述：一个穿白色连衣裙的长发女孩站在花田里\n"
    "标签：1girl, solo, long hair, white dress, standing, flower field, outdoors\n\n"
    "中文描述：黑发红眼的少女坐在教室里看窗外，穿着校服\n"
    "标签：1girl, black hair, red eyes, sitting, classroom, looking out window, school uniform, indoors\n\n"
    "中文描述：金发双马尾女孩在海边比基尼，夕阳逆光\n"
    "标签：1girl, blonde hair, twintails, beach, bikini, sunset, backlighting, ocean\n\n"
    "中文描述：手持青龙偃月刀的银发女性，全身，废墟\n"
    "标签：1girl, silver hair, holding, guandao, full body, ruins\n\n"
    "中文描述：明日香\n"
    "标签：1girl, souryuu asuka langley, neon genesis evangelion\n\n"
    "中文描述：{text}\n"
    "标签："
)


def contains_chinese(text):
    """判断文本是否含中日韩统一表意文字。"""
    return bool(re.search(r"[一-鿿]", str(text or "")))


def _dedupe_tags(*chunks):
    """按首次出现顺序合并多段标签，忽略大小写重复。"""
    tags = []
    seen = set()
    for chunk in chunks:
        if not chunk:
            continue
        for tag in str(chunk).split(","):
            tag = tag.strip()
            normalized = tag.lower()
            if tag and normalized not in seen:
                seen.add(normalized)
                tags.append(tag)
    return tags


def _strip_stopwords(text):
    """从残留中文里去掉语法虚词，只留下可能有画面意义的片段。"""
    remaining = str(text or "")
    for word in _SORTED_STOPWORDS:
        if word in remaining:
            remaining = remaining.replace(word, ",")
    parts = [part for part in re.findall(r"[一-鿿]+", remaining) if part]
    return " ".join(parts)


def _ascii_word_boundary(text, start, end):
    """ASCII 短键只在词边界命中，避免 2b 吃掉 2boys。"""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    if before.isalnum() or before == "_":
        return False
    if after.isalnum() or after == "_":
        return False
    return True


def translate_by_lexicon(text):
    """用词典替换中文片段，返回 (标签串, 未识别的中文残留)。

    从左到右取最长键，命中后继续扫描后续文字。输入中原有的英文标签会一并
    保留，避免中英混写时丢失用户已经写好的标签。
    """
    remaining = str(text or "")
    matched = []
    rebuilt = []
    index = 0
    length = len(remaining)
    while index < length:
        current = remaining[index]
        hit = None
        for key in _KEYS_BY_FIRST.get(current, ()):
            if not remaining.startswith(key, index):
                continue
            end = index + len(key)
            if key.isascii() and not _ascii_word_boundary(remaining, index, end):
                continue
            hit = key
            break
        if hit:
            matched.append(LEXICON[hit])
            rebuilt.append(",")
            index += len(hit)
            continue
        rebuilt.append(current)
        index += 1

    leftover_source = "".join(rebuilt)
    leftover_cn = _strip_stopwords(
        "".join(re.findall(r"[一-鿿]+", leftover_source))
    )

    # 去掉未识别中文，仅提取用户原本写入的英文标签。中文标点和换行都视为
    # 标签分隔符，ASCII 冒号保留给 artist:xxx 与 NAI 数值权重语法。
    english_text = re.sub(r"[一-鿿]+", ",", leftover_source)
    english_text = re.sub(r"[，、。；;：！!？?\r\n\t]+", ",", english_text)
    existing = [
        part.strip()
        for part in english_text.split(",")
        if part.strip() and re.search(r"[a-z0-9]", part, re.I)
    ]

    tags = _dedupe_tags(*matched, *existing)
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

        prompt = LLM_INSTRUCTION.replace("{text}", str(text))
        if hasattr(provider, "text_chat"):
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


def _fetch_json(url, timeout=2.5):
    """请求 JSON。测试时可替换此函数，避免真实网络。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DANBOORU_UA,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _cache_get(name):
    if name in _LOOKUP_CACHE:
        return True, _LOOKUP_CACHE[name]
    return False, None


def _cache_set(name, value):
    if name in _LOOKUP_CACHE:
        _LOOKUP_CACHE[name] = value
        return
    if len(_LOOKUP_CACHE) >= _LOOKUP_CACHE_LIMIT:
        _LOOKUP_CACHE.pop(next(iter(_LOOKUP_CACHE)))
    _LOOKUP_CACHE[name] = value


def _tag_from_title(title):
    text = str(title or "").strip().replace("_", " ")
    if not text:
        return None
    prefix = text.split(":", 1)[0].lower()
    if prefix in {"help", "howto", "api", "tag group", "list of"}:
        return None
    if text.lower().startswith("list of "):
        return None
    return text


def _name_candidates(leftover):
    """从残留中文里抽出像角色名/作品名的短词，避免整句去查库。"""
    tokens = [part for part in str(leftover or "").split() if part]
    names = []
    for token in tokens:
        if not _NAME_TOKEN_RE.fullmatch(token):
            continue
        # 两字名只在整段残留就是它时查询，避免把「量子 纠缠」拆去乱搜。
        if len(token) >= 3 or len(tokens) == 1:
            names.append(token)
    if names:
        return names[:3]
    compact = re.sub(r"\s+", "", leftover or "")
    if _NAME_TOKEN_RE.fullmatch(compact):
        return [compact]
    return []


def _lookup_autocomplete(name, fetch):
    """Danbooru 自动补全会按 other_names 搜中文，但响应里通常不带回中文别名。"""
    query = urllib.parse.urlencode(
        {
            "search[query]": name,
            "search[type]": "tag",
            "limit": 10,
        }
    )
    data = fetch(f"{DANBOORU_AUTOCOMPLETE}?{query}")
    if not isinstance(data, list):
        return None
    best = None
    best_score = -1
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            category = int(item.get("category"))
        except (TypeError, ValueError):
            continue
        if category not in {3, 4}:
            continue
        value = str(item.get("value") or item.get("label") or "").strip()
        tag = _tag_from_title(value)
        if not tag:
            continue
        try:
            posts = int(item.get("post_count") or 0)
        except (TypeError, ValueError):
            posts = 0
        # 角色优先于作品；官方补全已经按别名排过序。
        score = posts + (1_000_000 if category == 4 else 0)
        if score > best_score:
            best_score = score
            best = tag
    return best


def _lookup_wiki(name, fetch):
    query = urllib.parse.urlencode(
        {
            "search[other_names_match]": name,
            "limit": 8,
        }
    )
    data = fetch(f"{DANBOORU_WIKI}?{query}")
    if not isinstance(data, list):
        return None
    exact = []
    for page in data:
        if not isinstance(page, dict):
            continue
        other_names = page.get("other_names") or []
        if not isinstance(other_names, list) or name not in other_names:
            continue
        tag = _tag_from_title(page.get("title"))
        if tag:
            exact.append(tag)
    if not exact:
        return None
    if len(exact) == 1:
        return exact[0]
    scored = []
    for tag in exact[:3]:
        posts = 0
        try:
            query = urllib.parse.urlencode(
                {"search[name]": tag.replace(" ", "_"), "limit": 1}
            )
            payload = fetch(f"{DANBOORU_TAGS}?{query}")
            if isinstance(payload, list) and payload:
                posts = int(payload[0].get("post_count") or 0)
        except Exception:
            posts = 0
        scored.append((posts, len(tag.split()), tag))
    scored.sort(reverse=True)
    return scored[0][2]


def lookup_name_sync(name, fetch=None):
    """把中文角色/作品名查成 danbooru 标签，查不到返回空串。"""
    token = str(name or "").strip()
    if not token:
        return ""
    hit, cached = _cache_get(token)
    if hit:
        return cached
    fetch = fetch or _fetch_json
    tag = ""
    try:
        tag = _lookup_wiki(token, fetch) or _lookup_autocomplete(token, fetch) or ""
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.debug(f"[叶子的逼] Danbooru 角色查询失败: {exc}")
        tag = ""
    except Exception as exc:
        logger.debug(f"[叶子的逼] Danbooru 角色查询异常: {exc}")
        tag = ""
    _cache_set(token, tag)
    return tag


def _pure_name_query(raw, leftover):
    """只在用户几乎整段都是角色/作品名时查库，避免普通画面描述被外网拖死。"""
    leftover = str(leftover or "").strip()
    if not leftover:
        return []
    compact_raw = re.sub(r"[^一-鿿ぁ-んァ-ン]+", "", str(raw or ""))
    compact_left = re.sub(r"\s+", "", leftover)
    if not compact_raw or compact_raw != compact_left:
        return []
    if not (2 <= len(compact_raw) <= 12):
        return []
    return [compact_raw]


def resolve_unknown_names(leftover, fetch=None, raw=""):
    """把残留短中文查成角色/作品标签，返回 (标签串, 仍未识别的残留)。"""
    leftover = str(leftover or "").strip()
    if not leftover:
        return "", ""
    found = []
    remaining = leftover
    names = _pure_name_query(raw, leftover) or (
        _name_candidates(leftover) if not raw else []
    )
    for name in names[:1]:
        tag = lookup_name_sync(name, fetch=fetch)
        if not tag:
            continue
        found.append(tag)
        remaining = remaining.replace(name, ",")
    leftover_cn = _strip_stopwords("".join(re.findall(r"[一-鿿]+", remaining)))
    return ", ".join(_dedupe_tags(*found)), leftover_cn


async def to_tags(context, text, use_llm=True, fetch=None):
    """把用户输入转为标签串，返回 (标签, 说明)。

    纯英文输入直接返回。中文先走词典，再查 Danbooru 角色/作品别名；
    仍有画面意义的残留时才把整句交给 LLM，并与前两层结果合并。
    fetch 仅测试注入，生产环境走官方 Danbooru JSON。
    """
    raw = str(text or "").strip()
    if not raw:
        return "", ""

    if not contains_chinese(raw):
        return raw, ""

    lexicon_tags, leftover = translate_by_lexicon(raw)
    danbooru_tags = ""
    if leftover and _pure_name_query(raw, leftover):
        try:
            danbooru_tags, leftover = await asyncio.wait_for(
                asyncio.to_thread(resolve_unknown_names, leftover, fetch, raw),
                timeout=3,
            )
        except Exception as exc:
            logger.debug(f"[叶子的逼] 角色查询跳过: {exc}")

    merged = ", ".join(_dedupe_tags(lexicon_tags, danbooru_tags))

    if use_llm and leftover:
        llm_tags = await translate_by_llm(context, raw)
        if llm_tags:
            return ", ".join(_dedupe_tags(merged, llm_tags)), "已智能翻译"

    if leftover and merged:
        return merged, f"未识别部分已忽略：{leftover}"
    if not merged:
        return "", "未能识别中文描述，建议改用英文标签或开启中文智能翻译"
    return merged, ""
