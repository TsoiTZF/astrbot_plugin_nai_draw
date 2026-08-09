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
    preset_help,
    resolve_preset,
    resolve_size,
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
    prompt = build_prompt("hiten", "1girl, white dress")
    check(QUALITY in prompt, "包含 NAI4.5 质量词")
    check("masterpiece" not in prompt, "不含 NAI3 质量词")
    check("year 2024" in prompt, "包含年份标签")
    check("artist:hiten" in prompt, "包含预设画师串")
    check("1girl, white dress" in prompt, "包含用户描述")
    check(prompt.index("artist:") < prompt.index(QUALITY), "画师串在质量词之前")

    empty = build_prompt("laowuyang", "")
    check(QUALITY in empty, "描述为空仍产出有效提示词")
    check(not empty.endswith(", "), "无尾随逗号")


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
        check("artists" in data and bool(data["artists"]), f"{key} 有画师串")
        check("style" in data, f"{key} 有风格词字段")

    print("权重安全性：")
    import re as _re

    for key, data in PRESETS.items():
        text = data["artists"] + data["style"]
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


def test_preset_help():
    print("预设帮助：")
    text = preset_help()
    check("1 = 老五样（通用美脸） [laowuyang]" in text, "显示首个预设编号")
    check(f"{len(PRESET_ORDER)} = 厚涂油画 [oil]" in text, "显示末尾预设编号")
    check("只选择预设：/nai 1" in text, "显示独立选择示例")
    check("选择并绘图：/nai 1 长发女孩" in text, "显示一步绘图示例")


def main():
    print("=" * 56)
    print("NAI 绘画插件 预设模块测试")
    print("=" * 56)
    for func in (
        test_resolve_preset,
        test_resolve_size,
        test_build_prompt,
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
