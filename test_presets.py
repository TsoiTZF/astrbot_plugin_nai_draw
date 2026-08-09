"""预设与提示词组装的单元测试。

覆盖正常流程、边界条件与错误输入。
不依赖 astrbot 运行时，可直接 python test_presets.py 执行。
"""

import sys

from presets import (
    BASE_NEGATIVE,
    PRESET_ORDER,
    PRESETS,
    QUALITY,
    build_negative,
    build_prompt,
    describes_face,
    pick_variant,
    preset_help,
    resolve_preset,
    resolve_size,
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
    check(resolve_preset("1") == "laowuyang", "编号 1 命中首个预设")
    check(resolve_preset(" 3 ") == "pop", "编号 3 忽略首尾空格")
    check(resolve_preset(str(len(PRESET_ORDER))) == "oil", "末尾编号命中")
    check(resolve_preset("0") is None, "编号 0 不可用")
    check(resolve_preset(str(len(PRESET_ORDER) + 1)) is None, "越界编号不可用")
    check(resolve_preset("hiten") == "hiten", "英文键直接命中")
    check(resolve_preset("HITEN") == "hiten", "大写不敏感")
    check(resolve_preset("  pop  ") == "pop", "首尾空格被忽略")
    check(resolve_preset("成熟妩媚") == "mature", "中文标签命中")
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
    prompt, _ = build_prompt("hiten", "1girl, white dress", index=0)
    check(QUALITY in prompt, "包含 NAI4.5 质量词")
    check("masterpiece" not in prompt, "不含 NAI3 质量词")
    check("year 2024" in prompt, "包含年份标签")
    check("artist:hiten" in prompt, "包含预设画师串")
    check("1girl, white dress" in prompt, "包含用户描述")
    check(prompt.index("artist:") < prompt.index(QUALITY), "画师串在质量词之前")

    empty, _ = build_prompt("laowuyang", "", index=0)
    check(QUALITY in empty, "描述为空仍产出有效提示词")
    check(not empty.endswith(", "), "无尾随逗号")


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
        check(
            all(left[0] != right[0] for left, right in zip(cycle, cycle[1:])),
            f"{key} 相邻画师主力不重复",
        )
        check(
            all(left[1] != right[1] for left, right in zip(cycle, cycle[1:])),
            f"{key} 相邻五官不重复",
        )

    print("画师主力轮换：")
    for key in PRESET_ORDER:
        variants = PRESETS[key]["artist_variants"]
        check(len(variants) >= 3, f"{key} 至少 3 个画师变体")
        check(len(set(variants)) == len(variants), f"{key} 画师变体无重复")
        # 每个变体都须有唯一主力（花括号提权的画师）
        leads = []
        for item in variants:
            lead = [
                seg.strip()
                for seg in item.split(",")
                if seg.strip().startswith("{")
            ]
            leads.append(tuple(lead))
        check(len(set(leads)) == len(leads), f"{key} 各变体主力不同")

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
    custom, custom_neg = build_prompt("mature", "1girl, round face", index=0)
    check("{{tsurime}}" not in custom, "用户自写五官时不注入变体")
    check(custom_neg == "", "用户自写五官时不注入排他负面词")
    auto, auto_neg = build_prompt("mature", "1girl, white dress", index=0)
    check("{{tsurime}}" in auto, "未写五官时注入变体")
    check(bool(auto_neg), "未写五官时产出排他负面词")

    print("变体选择：")
    artist_a, face_a, neg_a = pick_variant("mature", index=0)
    artist_b, face_b, neg_b = pick_variant("mature", index=0)
    check((artist_a, face_a, neg_a) == (artist_b, face_b, neg_b), "同 index 结果可复现")
    count = len(PRESETS["mature"]["artist_variants"])
    check(pick_variant("mature", index=count)[0] == artist_a, "index 越界按取模回绕")
    check(all(pick_variant("mature", index=i) for i in range(20)), "大 index 不抛异常")


def test_build_negative():
    print("负面提示词组装：")
    neg = build_negative("hiten", allow_nsfw=False)
    check("very displeasing" in neg, "含 NAI 美学评分压制词")
    check("{{nude}}" in neg, "关闭 NSFW 时含压制词")
    check("dark background" in neg, "含预设专属负面词")

    allowed = build_negative("hiten", allow_nsfw=True)
    check("{{nude}}" not in allowed, "开启 NSFW 时不含压制词")

    extra = build_negative("hiten", extra="my_custom_tag")
    check("my_custom_tag" in extra, "追加自定义负面词生效")

    face = build_negative("mature", face_negative="round eyes, soft jawline")
    check("round eyes" in face, "五官排他负面词生效")
    check("very displeasing" in face, "五官负面词不覆盖基础负面词")

    custom_mature = build_negative("mature", user_text="1girl, round face")
    check("round face" not in custom_mature.lower(), "成熟预设不压制用户指定圆脸")
    check("childlike" in custom_mature.lower(), "删除冲突时保留其余预设负面词")
    custom_ghostblade = build_negative("ghostblade", user_text="1girl, big eyes")
    check("big eyes" not in custom_ghostblade.lower(), "鬼刀预设不压制用户指定大眼")
    alias_ghostblade = build_negative("ghostblade", user_text="1girl, large eyes")
    check("big eyes" not in alias_ghostblade.lower(), "大眼同义标签也能解除冲突")

    # pop 与 watercolor 以 flat color 为核心特征，不可被通用负面词压制
    pop_neg = build_negative("pop")
    check("flat color" not in pop_neg.lower(), "pop 预设移除 flat color 压制")
    water_neg = build_negative("watercolor")
    check("flat color" not in water_neg.lower(), "watercolor 预设移除 flat color 压制")
    # 其他预设不应受影响
    gb_neg = build_negative("ghostblade")
    check("flat color" in gb_neg.lower(), "ghostblade 保留 flat color 压制")


def test_preset_integrity():
    print("预设数据完整性：")
    check(len(PRESETS) >= 8, f"预设数量充足（{len(PRESETS)} 个）")
    check(len(PRESET_ORDER) == len(set(PRESET_ORDER)), "数字顺序无重复项")
    check(set(PRESET_ORDER) == set(PRESETS), "所有预设均有稳定编号")
    for key, data in PRESETS.items():
        check("label" in data and bool(data["label"]), f"{key} 有中文标签")
        check(
            bool(data.get("artist_variants")), f"{key} 有画师变体池"
        )
        check("style" in data, f"{key} 有风格词字段")
        check(bool(data.get("faces")), f"{key} 有五官变体池")

    print("权重安全性：")
    import re as _re

    for key, data in PRESETS.items():
        faces = "".join(f"{a}{b}" for a, b in data.get("faces") or ())
        text = "".join(data["artist_variants"]) + data["style"] + faces
        # 数值权重超过 1.5 会推崩去噪，产出纯噪点
        for value in _re.findall(r"(\d+\.?\d*)::", text):
            check(float(value) <= 1.5, f"{key} 数值权重 {value} 未超 1.5")
        # 三层及以上花括号会放大风格词冲突
        check("{{{{" not in text, f"{key} 无四层花括号")

    print("风格词冲突检查：")
    for key, data in PRESETS.items():
        style = data["style"].lower()
        conflict = "thick brushstrokes" in style and "soft blended shading" in style
        check(not conflict, f"{key} 无笔触/柔和混合冲突")

    print("风格词职责边界：")
    # 五官、表情、姿势、视角写进 style 会让每张图共用同一张脸与同一机位
    forbidden = (
        "tsurime", "tareme", "narrow sharp eyes", "long eyelashes",
        "lipstick", "glossy lips", "cheekbones", "jawline",
        "close shot", "from side", "from above", "cowboy shot",
        "elegant posture", "sitting", "standing", "looking at viewer",
    )
    for key, data in PRESETS.items():
        style = data["style"].lower()
        hit = [word for word in forbidden if word in style]
        check(not hit, f"{key} 风格词不含五官/构图词：{hit}")


def test_preset_help():
    print("预设帮助：")
    text = preset_help()
    check("1 = 老五样（通用美脸） [laowuyang]" in text, "显示首个预设编号")
    check("厚涂油画 [oil]" in text, "显示末尾预设")
    check(text.startswith("可用画风预设"), "首行为标题")
    check("只选择预设：/nai 1" in text, "显示独立选择示例")
    check("选择并绘图：/nai 1 长发女孩" in text, "显示一步绘图示例")
    check("种脸型组合" in text, "显示脸型组合数量")
    check("轮换" in text, "说明自动轮换行为")


def main():
    print("=" * 56)
    print("NAI 绘画插件 预设模块测试")
    print("=" * 56)
    for func in (
        test_resolve_preset,
        test_resolve_size,
        test_build_prompt,
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
