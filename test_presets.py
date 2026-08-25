"""预设与提示词组装的单元测试。

覆盖正常流程、边界条件与错误输入。
不依赖 astrbot 运行时，可直接 python test_presets.py 执行。
"""

import sys

from presets import (
    BASE_NEGATIVE,
    NO_PRESET_KEY,
    PRESET_ORDER,
    PRESETS,
    QUALITY,
    build_negative,
    build_prompt,
    describes_face,
    pick_variant,
    preset_help,
    preset_number,
    random_artist_combo,
    resolve_preset,
    resolve_size,
    sanitize_artist_string,
    variant_count,
)

_failures = []


def check(condition, label):
    """记录单条断言结果。"""
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


def test_resolve_preset():
    print("预设名解析：")
    check(resolve_preset("1") == "iceblue", "编号 1 命中首个预设")
    check(resolve_preset(" 3 ") == "neon_flat", "编号 3 忽略首尾空格")
    check(resolve_preset(str(len(PRESET_ORDER))) == "filmgrain_illustration", "末尾编号命中")
    check(resolve_preset("0") == NO_PRESET_KEY, "编号 0 选择无预设")
    check(resolve_preset("不用预设") == NO_PRESET_KEY, "中文名称选择无预设")
    check(preset_number(NO_PRESET_KEY) == 0, "无预设显示编号 0")
    check(resolve_preset(str(len(PRESET_ORDER) + 1)) is None, "越界编号不可用")
    check(resolve_preset("iceblue") == "iceblue", "英文键直接命中")
    check(resolve_preset("ICEBLUE") == "iceblue", "大写不敏感")
    check(resolve_preset("  neon_flat  ") == "neon_flat", "首尾空格被忽略")
    check(resolve_preset("高光成熟人物") == "glossy_mature", "中文标签命中")
    check(
        tuple(resolve_preset(str(i)) for i in range(6, 10))
        == ("golden_backlight", "dreamy_floral", "pastel_chibi", "filmgrain_illustration"),
        "新增 6～9 号映射固定",
    )
    check(resolve_preset("粉彩无描边 Q版") == "pastel_chibi", "新增中文标签命中")
    check(resolve_preset("不存在的风格") is None, "未知名称返回 None")
    check(resolve_preset("") is None, "空串返回 None")
    check(resolve_preset(None) is None, "None 输入不抛异常")


def test_resolve_size():
    print("尺寸解析：")
    check(resolve_size("832x1216") == "832x1216", "标准写法")
    check(resolve_size("方图") == "832x832", "中文别名")
    check(resolve_size("横") == "1216x832", "单字别名")
    check(resolve_size("832×1216") == "832x1216", "全角乘号")
    check(resolve_size("832*1216") == "832x1216", "星号分隔")
    # 非 64 倍数会被上游拒绝，必须提前回退
    check(resolve_size("800x1200") == "832x1216", "非64倍数回退默认")
    check(resolve_size("100x100") == "832x1216", "低于下限回退")
    check(resolve_size("2048x2048") == "832x1216", "超出上限回退")
    check(resolve_size("abc") == "832x1216", "非法文本回退")
    check(resolve_size("") == "832x1216", "空串回退")
    check(resolve_size(None) == "832x1216", "None 回退")
    check(resolve_size("832x1216", "832x832") == "832x1216", "合法值不受 fallback 影响")


def test_build_prompt():
    print("正面提示词组装：")
    prompt, _ = build_prompt("iceblue", "1girl, white dress", index=0)
    check(QUALITY in prompt, "包含 NAI4.5 质量词")
    check("masterpiece" not in prompt, "不含 NAI3 质量词")
    check("year 2024" in prompt, "包含年份标签")
    check(
        any(name in prompt for name in ("artist:pan_(mimi)", "artist:skinfang")),
        "包含法典清洗后的预设画师串",
    )
    check("1girl, white dress" in prompt, "包含用户描述")
    check(prompt.index("artist:") < prompt.index(QUALITY), "画师串在质量词之前")

    empty, _ = build_prompt("iceblue", "", index=0)
    check(QUALITY in empty, "描述为空仍产出有效提示词")
    check(not empty.endswith(", "), "无尾随逗号")

    no_preset, no_preset_neg = build_prompt(
        NO_PRESET_KEY,
        "1girl, white dress",
        index=0,
        custom_artist="{artist:wlop}",
    )
    check("{artist:wlop}" in no_preset, "无预设可使用个人画师串")
    check(no_preset.index("artist:") < no_preset.index(QUALITY), "个人画师串在质量词之前")
    check("1girl, white dress" in no_preset, "无预设保留用户描述")
    check(no_preset_neg == "", "无预设不产生脸型排他负面词")


def test_artist_sanitization():
    print("个人画师串清洗：")
    tags, rejected = sanitize_artist_string(
        "wlop, {artist:guweiz}, 1.2::artist:sakimichan::, wlop"
    )
    check(tags[0] == "artist:wlop", "裸英文画师名自动补 artist 前缀")
    check("{artist:guweiz}" in tags, "保留花括号画师权重")
    check("1.2::artist:sakimichan::" in tags, "保留合法数值权重")
    check(len(tags) == 3 and rejected == 0, "画师标签保序去重")

    tags, rejected = sanitize_artist_string(
        "2.0::artist:bad::, {artist:broken], 普通描述, artist:valid"
    )
    check(tags == ("artist:valid",), "无效画师标签被剔除")
    check(rejected == 3, "统计超权重、括号错误和非画师输入")

    tags, rejected = sanitize_artist_string("artist:a, artist:b, artist:c", max_tags=2)
    check(tags == ("artist:a", "artist:b"), "画师数量上限生效")
    check(rejected == 1, "超量画师计入忽略数量")

    combo = random_artist_combo()
    check(combo["preset"] in PRESET_ORDER, "随机画师串来自正式预设")
    check(combo["artists"] and combo["text"], "随机画师串包含清洗后的标签")
    tags, rejected = sanitize_artist_string(combo["text"])
    check(tags == combo["artists"] and rejected == 0, "随机画师串可再次通过清洗")


def test_variation():
    print("脸型多样性：")
    # 同一预设连续取不同 index，画师主力与五官必须换掉，
    # 否则会退化成「画什么都一张脸」
    for key in PRESET_ORDER:
        prompts = {build_prompt(key, "1girl", index=i)[0] for i in range(4)}
        check(len(prompts) >= 2, f"{key} 四次取样产出多种提示词")

        count = variant_count(key)
        combinations = [pick_variant(key, index=i) for i in range(count)]
        check(len(set(combinations)) == count, f"{key} 完整周期覆盖全部组合")
        cycle = combinations + combinations[:1]
        if len(PRESETS[key]["artist_variants"]) > 1:
            check(
                all(left[0] != right[0] for left, right in zip(cycle, cycle[1:])),
                f"{key} 相邻画师主力不重复",
            )
        else:
            check(
                all(left[1:] != right[1:] for left, right in zip(cycle, cycle[1:])),
                f"{key} 锁定画师时由画风或五官保持变化",
            )
        # 完整周期必须覆盖画师、画风和五官的全部组合。
        check(
            len({item[0] for item in combinations}) == len(PRESETS[key]["artist_variants"]),
            f"{key} 覆盖全部画师变体",
        )
        check(
            len({item[1] for item in combinations}) == len(PRESETS[key]["positive_variants"]),
            f"{key} 覆盖全部正面画风变体",
        )
        check(
            len({item[2] for item in combinations}) == len(PRESETS[key]["faces"]),
            f"{key} 覆盖全部五官变体",
        )

    print("画师主力轮换：")
    for key in PRESET_ORDER:
        variants = PRESETS[key]["artist_variants"]
        check(len(variants) >= 1, f"{key} 至少 1 个画师变体")
        check(len(set(variants)) == len(variants), f"{key} 画师变体无重复")
        # 每个变体的第一个 artist 标签作为主导画师，必须彼此不同。
        leads = []
        for item in variants:
            match = __import__("re").search(r"artist:([a-z0-9_()]+)", item, __import__("re").I)
            leads.append(match.group(1).lower() if match else item.split(",", 1)[0].strip().lower())
        required = min(3, len(leads))
        check(len(set(leads)) >= required, f"{key} 主力画师数量符合锁定策略")

    print("五官变体互斥：")
    for key in PRESET_ORDER:
        faces = PRESETS[key].get("faces") or ()
        check(len(faces) >= 3, f"{key} 至少 3 个五官变体")
        for face, face_neg in faces:
            check(bool(face_neg), f"{key} 五官变体带排他负面词")
            # 排他负面词不得压制自身特征，否则正负对撞
            own = face.lower()
            collide = [
                word.strip()
                for word in face_neg.split(",")
                if word.strip() and word.strip() in own
            ]
            check(not collide, f"{key} 排他负面词不与自身冲突：{collide}")

    print("五官注入避让：")
    check(describes_face("narrow eyes, red lipstick"), "识别用户自写五官")
    check(describes_face("1girl, SHARP JAWLINE"), "五官识别大小写不敏感")
    check(describes_face("1girl, sharp_eyes"), "识别下划线五官标签")
    check(describes_face("1girl, round face"), "识别明确脸型短语")
    check(not describes_face("1girl, white dress, bedroom"), "无五官描述时不误判")
    check(not describes_face("slippers"), "slippers 不会误命中 lip")
    check(not describes_face("machine room"), "machine 不会误命中 chin")
    check(not describes_face("surface reflection"), "surface 不会误命中 face")
    check(not describes_face("paint on face"), "普通 face 描述不视为指定五官")
    check(not describes_face(""), "空描述不误判")

    # 用户自写五官时不注入变体，避免与用户描述对撞
    custom, custom_neg = build_prompt("glossy_mature", "1girl, round face", index=0)
    check("{{tsurime}}" not in custom, "用户自写五官时不注入变体")
    check(custom_neg == "", "用户自写五官时不注入排他负面词")
    auto, auto_neg = build_prompt("glossy_mature", "1girl, white dress", index=0)
    check("{{tsurime}}" in auto, "未写五官时注入变体")
    check(bool(auto_neg), "未写五官时产出排他负面词")

    disabled, disabled_neg = build_prompt(
        "glossy_mature",
        "1girl, white dress",
        index=0,
        include_face=False,
    )
    check(
        PRESETS["glossy_mature"]["artist_variants"][0] in disabled,
        "关闭自动脸型仍保留画师串",
    )
    check("1girl, white dress" in disabled, "关闭自动脸型仍保留用户描述")
    check("{{tsurime}}" not in disabled, "关闭自动脸型不注入五官正面词")
    check(disabled_neg == "", "关闭自动脸型不注入五官排他负面词")

    disabled_negative = build_negative(
        "glossy_mature",
        face_negative="big eyes, round face",
        include_face=False,
    )
    check("round face" not in disabled_negative.lower(), "关闭自动脸型移除预设脸型负面词")
    check("chubby cheeks" not in disabled_negative.lower(), "关闭自动脸型移除预设五官负面词")
    check("childlike" in disabled_negative.lower(), "关闭自动脸型保留非脸部年龄约束")

    print("变体选择：")
    artist_a, positive_a, face_a, neg_a = pick_variant("glossy_mature", index=0)
    artist_b, positive_b, face_b, neg_b = pick_variant("glossy_mature", index=0)
    check(
        (artist_a, positive_a, face_a, neg_a)
        == (artist_b, positive_b, face_b, neg_b),
        "同 index 结果可复现",
    )
    count = variant_count("glossy_mature")
    check(
        pick_variant("glossy_mature", index=count) == pick_variant("glossy_mature", index=0),
        "完整组合周期结束后回绕",
    )
    check(all(pick_variant("glossy_mature", index=i) for i in range(20)), "大 index 不抛异常")


def test_build_negative():
    print("负面提示词组装：")
    neg = build_negative("iceblue", allow_nsfw=False)
    check("very displeasing" in neg, "含 NAI 美学评分压制词")
    check("{{nude}}" in neg, "关闭 NSFW 时含压制词")
    check("dark background" in neg, "含预设专属负面词")

    allowed = build_negative("iceblue", allow_nsfw=True)
    check("{{nude}}" not in allowed, "开启 NSFW 时不含压制词")

    extra = build_negative("iceblue", extra="my_custom_tag")
    check("my_custom_tag" in extra, "追加自定义负面词生效")

    face = build_negative("glossy_mature", face_negative="round eyes, soft jawline")
    check("round eyes" in face, "五官排他负面词生效")
    check("very displeasing" in face, "五官负面词不覆盖基础负面词")

    custom_mature = build_negative("glossy_mature", user_text="1girl, round face")
    check("round face" not in custom_mature.lower(), "高光成熟预设不压制用户指定圆脸")
    check("childlike" in custom_mature.lower(), "删除冲突时保留其余预设负面词")
    custom_cinematic = build_negative("cinematic", user_text="1girl, big eyes")
    check("big eyes" not in custom_cinematic.lower(), "电影厚涂预设不压制用户指定大眼")
    alias_cinematic = build_negative("cinematic", user_text="1girl, large eyes")
    check("big eyes" not in alias_cinematic.lower(), "大眼同义标签也能解除冲突")

    # 霓虹平涂以 flat color 为核心特征，不可被通用负面词压制
    pop_neg = build_negative("neon_flat")
    check("flat color" not in pop_neg.lower(), "霓虹平涂移除 flat color 压制")
    water_neg = build_negative("neon_flat")
    check("flat color" not in water_neg.lower(), "霓虹平涂保持 flat color 核心特征")
    # 其他预设不应受影响
    gb_neg = build_negative("cinematic")
    check("flat color" in gb_neg.lower(), "电影厚涂保留 flat color 压制")

    film_neg = build_negative("filmgrain_illustration")
    check("film grain" not in film_neg.lower(), "青雾胶片放行 film grain 核心特征")
    check("chromatic aberration" not in film_neg.lower(), "青雾胶片放行色差核心特征")
    check("bad quality" in film_neg.lower(), "青雾胶片仍保留基础质量压制")


def test_preset_integrity():
    print("预设数据完整性：")
    check(len(PRESETS) == 10, f"预设数量为 0 号加九个实测画风（{len(PRESETS)} 个）")
    check(len(PRESET_ORDER) == len(set(PRESET_ORDER)), "数字顺序无重复项")
    check(
        set(PRESET_ORDER) == set(PRESETS) - {NO_PRESET_KEY},
        "九个预设编号与集合一致",
    )
    for key, data in PRESETS.items():
        check("label" in data and bool(data["label"]), f"{key} 有中文标签")
        check(
            bool(data.get("artist_variants")), f"{key} 有画师变体池"
        )
        check("positive_variants" in data, f"{key} 有正面画风变体字段")
        if key == NO_PRESET_KEY:
            check(data["artist_variants"] == ("",), "无预设不注入预设画师串")
            check(
                data["positive_variants"] == ("",) and not data.get("faces"),
                "无预设不注入画风和脸型",
            )
        else:
            check(bool(data.get("faces")), f"{key} 有五官变体池")

        skipped = {
            "masterpiece", "best quality", "amazing quality", "very aesthetic",
            "absurdres", "highres", "year 2024", "year 2025", "1girl", "solo",
            "cowboy shot", "from above", "from below", "indoors", "outdoors",
            "nsfw", "rating:explicit",
        }
        positive_text = ", ".join(data.get("positive_variants") or ()).lower()
        leaked = [word for word in skipped if word in positive_text]
        check(not leaked, f"{key} 正面画风已清除质量/主体/构图/NSFW：{leaked}")
        source = data.get("source") or {}
        if key != NO_PRESET_KEY:
            check(source.get("codex") == "artist_nai45_strings", f"{key} 记录画师串法典来源")
            check(bool(source.get("entries")), f"{key} 记录候选词条 ID")

    print("权重安全性：")
    import re as _re

    for key, data in PRESETS.items():
        faces = "".join(f"{a}{b}" for a, b in data.get("faces") or ())
        positives = "".join(data.get("positive_variants") or ())
        text = "".join(data["artist_variants"]) + positives + faces
        # 数值权重超过 1.5 会推崩去噪，产出纯噪点
        for value in _re.findall(r"(\d+\.?\d*)::", text):
            check(float(value) <= 1.5, f"{key} 数值权重 {value} 未超 1.5")
        # 三层及以上花括号会放大风格词冲突
        check("{{{{" not in text, f"{key} 无四层花括号")

    print("风格词冲突检查：")
    for key, data in PRESETS.items():
        positives = ", ".join(data.get("positive_variants") or ()).lower()
        conflict = "thick brushstrokes" in positives and "soft blended shading" in positives
        check(not conflict, f"{key} 无笔触/柔和混合冲突")

    print("风格词职责边界：")
    # 五官、表情、姿势、视角写进画风正面词会让每张图共用同一张脸与同一机位
    forbidden = (
        "tsurime", "tareme", "narrow sharp eyes", "long eyelashes",
        "lipstick", "glossy lips", "cheekbones", "jawline",
        "close shot", "from side", "from above", "cowboy shot",
        "elegant posture", "sitting", "standing", "looking at viewer",
    )
    for key, data in PRESETS.items():
        positives = ", ".join(data.get("positive_variants") or ()).lower()
        hit = [word for word in forbidden if word in positives]
        check(not hit, f"{key} 正面画风不含五官/构图词：{hit}")


def test_preset_help():
    print("预设帮助：")
    text = preset_help()
    check("0 = 无预设 [none]" in text, "显示 0 号无预设")
    check("/nai画师 添加" in text, "显示个人画师入口")
    check("/nai画师 随机" in text, "显示随机画师串入口")
    check("1 = 冰蓝柔光（日系） [iceblue]" in text, "显示首个预设编号")
    check("9 = 青雾胶片插画 [filmgrain_illustration]" in text, "显示末尾预设")
    check(text.startswith("可用画风预设"), "首行为标题")
    check("只选择预设：/nai 1" in text, "显示独立选择示例")
    check("选择并绘图：/nai 1 长发女孩" in text, "显示一步绘图示例")
    check("种画师/画风/脸型组合" in text, "显示完整组合数量")
    check("轮换" in text and "/nai随机" in text, "说明三维轮换与独立随机行为")


def main():
    print("=" * 56)
    print("NAI 绘画插件 预设模块测试")
    print("=" * 56)
    for func in (
        test_resolve_preset,
        test_resolve_size,
        test_build_prompt,
        test_artist_sanitization,
        test_variation,
        test_build_negative,
        test_preset_integrity,
        test_preset_help,
    ):
        func()
        print()

    print("=" * 56)
    if _failures:
        print(f"失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
