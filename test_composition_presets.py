"""构图风格法典的独立随机完整场景池测试。"""

import sys

from composition_presets import (
    COMPOSITION_SCENES,
    INSPIRATION_ENTRY_IDS,
    composition_scene,
    composition_scene_count,
    composition_scene_payload,
    inspiration_scene_payload,
    validate_composition_scenes,
)

_failures = []


def check(condition, label):
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


def main():
    print("=" * 56)
    print("NAI 独立随机构图场景测试")
    print("=" * 56)
    check(composition_scene_count() == 64, "完整收录 64 条法典场景")
    check(len(COMPOSITION_SCENES) == len(set(COMPOSITION_SCENES)), "场景三元组无重复")
    check(validate_composition_scenes() == [], "场景 ID、标题与权重安全")

    first = composition_scene(0)
    wrapped = composition_scene(64)
    check(first == wrapped, "场景索引按 64 回绕")
    check(first["entry_id"] == "composition_style_0001", "首条来源 ID 正确")
    check("small wooden boat" in first["prompt"], "完整保留法典场景串")

    payload = composition_scene_payload()
    check(len(payload) == 64, "WebUI 载荷包含全部场景")
    check(all(item["title"] and item["prompt"] for item in payload), "WebUI 场景字段完整")
    check(len({item["entry_id"] for item in payload}) == 64, "WebUI 场景 ID 唯一")

    inspiration = inspiration_scene_payload()
    check(len(INSPIRATION_ENTRY_IDS) == 20, "精选灵感固定 20 条")
    check(len(inspiration) == 20, "绘台灵感池返回 20 条")
    check(
        {item["entry_id"] for item in inspiration} == set(INSPIRATION_ENTRY_IDS),
        "精选灵感全部来自完整法典",
    )
    check(all("2girls" not in item["prompt"] for item in inspiration), "精选灵感不含双人模板")
    check(
        all(0 <= item["index"] < 64 for item in inspiration),
        "精选灵感索引仍指向完整法典",
    )

    random_item = composition_scene()
    check(0 <= random_item["index"] < 64, "随机场景索引合法")
    check(random_item["source"]["version"] == "2025.10.19", "保留法典版本来源")

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
