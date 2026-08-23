"""中文转标签模块的单元测试。

覆盖词典命中、长词优先、去重、虚词剥离、残留识别、Danbooru 角色查询、
词典与 LLM 合并、LLM 输出清洗与降级路径。网络和 LLM 均用桩对象模拟。
"""

import asyncio
import sys
import types

# translator 依赖 astrbot.api.logger，测试环境用桩替代
_fake_api = types.ModuleType("astrbot.api")
_fake_api.logger = types.SimpleNamespace(
    debug=lambda *a, **k: None,
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
)
_fake_root = types.ModuleType("astrbot")
_fake_root.api = _fake_api
sys.modules.setdefault("astrbot", _fake_root)
sys.modules.setdefault("astrbot.api", _fake_api)

import translator as translator_mod  # noqa: E402
from translator import (  # noqa: E402
    LEXICON,
    _LOOKUP_CACHE,
    _sanitize_llm_output,
    contains_chinese,
    resolve_unknown_names,
    to_tags,
    translate_by_lexicon,
)

# 默认切断真实 Danbooru 请求，避免测试依赖外网。
translator_mod._fetch_json = lambda url, timeout=8: []

_failures = []


def check(condition, label):
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


class FakeResponse:
    def __init__(self, text):
        self.completion_text = text


class FakeProvider:
    """模拟 LLM provider，可指定返回内容或抛异常。"""

    def __init__(self, reply=None, raise_error=False):
        self._reply = reply
        self._raise = raise_error

    async def text_chat(self, prompt=""):
        if self._raise:
            raise RuntimeError("模拟上游故障")
        return FakeResponse(self._reply)


class FakeContext:
    def __init__(self, provider=None):
        self._provider = provider

    def get_using_provider(self):
        return self._provider


def test_contains_chinese():
    print("中文检测：")
    check(contains_chinese("女孩") is True, "纯中文命中")
    check(contains_chinese("1girl, long hair") is False, "纯英文不命中")
    check(contains_chinese("1girl 长发") is True, "中英混合命中")
    check(contains_chinese("") is False, "空串不命中")
    check(contains_chinese(None) is False, "None 不抛异常")


def test_lexicon():
    print("词典翻译：")
    tags, leftover = translate_by_lexicon("长发女孩")
    check("long hair" in tags, "长发 命中")
    check("1girl" in tags, "女孩 命中")
    check(leftover == "", "无残留")

    # 长词优先：「长发」不应被「发」类短键截断
    tags, _ = translate_by_lexicon("超长发")
    check("very long hair" in tags, "超长发 优先于 长发")

    tags, _ = translate_by_lexicon("黑丝")
    check("black thighhighs" in tags, "黑丝 优先于 丝袜")

    # 去重
    tags, _ = translate_by_lexicon("女孩 少女 女生")
    check(tags.count("1girl") == 1, "重复标签去重")

    # 残留识别：使用确定未收录的词，避免后续扩词把用例打穿
    tags, leftover = translate_by_lexicon("长发女孩，拿着一把量子纠缠矩阵")
    check("long hair" in tags and "holding" in tags, "混合输入仍命中已知词")
    check("量子纠缠矩阵" in leftover, "未知中文进入残留")
    check("一把" not in leftover and leftover.find("着") < 0, "量词和虚词不进入残留")

    tags, leftover = translate_by_lexicon("1girl, 长发, blue eyes")
    check("1girl" in tags and "blue eyes" in tags, "中英混写保留原有英文标签")
    check("long hair" in tags and leftover == "", "中英混写仍翻译已知中文")

    tags, leftover = translate_by_lexicon("1girl 量子纠缠矩阵 blue eyes")
    check("1girl" in tags and "blue eyes" in tags, "未知中文不吞掉两侧英文标签")
    check("量子纠缠矩阵" in leftover, "中英混写保留未知中文残留")

    tags, leftover = translate_by_lexicon("1girl量子纠缠矩阵blue eyes")
    check("1girl" in tags and "blue eyes" in tags, "无空格混写仍保留英文标签")
    check(leftover == "量子纠缠矩阵", "无空格混写只提取中文残留")

    tags, leftover = translate_by_lexicon("长发女孩拿着一把青龙偃月刀")
    check("guandao" in tags and "holding" in tags, "青龙偃月刀 命中武器标签")
    check(leftover == "", "已知武器和虚词不进入残留")

    tags, leftover = translate_by_lexicon("一个穿白色连衣裙的长发女孩站在花田里")
    check("white dress" in tags and "flower field" in tags, "口语长句命中服装和场景")
    check(leftover == "", "口语虚词被剥离后无残留")

    tags, leftover = translate_by_lexicon("全身，从侧面，雨夜街道，风衣")
    check("full body" in tags and "from side" in tags, "构图词命中")
    check("night" in tags and "rain" in tags and "trench coat" in tags, "雨夜街道与风衣命中")
    check(leftover == "", "构图口语无残留")

    # 标点不应进入残留
    _, leftover = translate_by_lexicon("长发，女孩。")
    check(leftover == "", "标点不计入残留")

    tags, leftover = translate_by_lexicon("")
    check(tags == "" and leftover == "", "空输入安全")
    check(len(LEXICON) >= 500, "词典覆盖常用绘画描述")

    tags, leftover = translate_by_lexicon("明日香")
    check("souryuu asuka langley" in tags, "明日香 命中角色标签")
    check("1girl" in tags, "明日香 补人数标签")
    check(leftover == "", "明日香 无残留")

    tags, leftover = translate_by_lexicon("式波明日香")
    check("shikinami asuka langley" in tags, "式波明日香 命中 Rebuild 角色标签")
    check("souryuu asuka langley" not in tags, "式波明日香 不误用 TV 版标签")

    tags, leftover = translate_by_lexicon("长发明日香，校服")
    check("souryuu asuka langley" in tags and "long hair" in tags, "角色名可与描述混写")
    check("school uniform" in tags, "明日香混写仍命中校服")
    check(leftover == "", "角色名混写无残留")

    tags, leftover = translate_by_lexicon("2boys, 1girl")
    check("2b (nier:automata)" not in tags, "2b 不截断 2boys")
    check("2boys" in tags and "1girl" in tags, "英文人数标签原样保留")


def test_sanitize():
    print("LLM 输出清洗：")
    check(
        _sanitize_llm_output("1girl, long hair, smile") == "1girl, long hair, smile",
        "标准输出原样保留",
    )
    check(
        "masterpiece" not in (_sanitize_llm_output("1girl, masterpiece, best quality") or ""),
        "剔除质量词",
    )
    check(
        "{" not in (_sanitize_llm_output("{{1girl}}, [long hair]") or ""),
        "剔除权重符号",
    )
    check(
        "artist:wlop" not in (_sanitize_llm_output("1girl, artist:wlop") or ""),
        "剔除画师串",
    )
    out = _sanitize_llm_output("标签：1girl, long hair")
    check(out is not None and out.startswith("1girl"), "剔除中文前缀")
    out = _sanitize_llm_output("好的，这是标签：\n1girl, long hair, dress")
    check(out is not None and "1girl" in out and "好的" not in out, "剔除解释性文字")
    out = _sanitize_llm_output("```\n1girl, smile\n```")
    check(out is not None and "```" not in out, "剔除代码块标记")
    check(
        "长发" not in (_sanitize_llm_output("1girl, 长发, smile") or ""),
        "丢弃未翻译的中文",
    )
    check(_sanitize_llm_output("") is None, "空输出返回 None")
    check(_sanitize_llm_output(None) is None, "None 输入返回 None")
    many = _sanitize_llm_output(", ".join(f"tag{i}" for i in range(40)))
    check(many is not None and len(many.split(",")) <= 25, "标签数量截断到 25")


def test_to_tags():
    print("整体转换：")

    async def run():
        # 纯英文直通
        tags, note = await to_tags(None, "1girl, long hair", use_llm=False)
        check(tags == "1girl, long hair", "英文输入原样返回")
        check(note == "", "英文输入无提示")

        # 中文全命中词典
        tags, note = await to_tags(None, "长发女孩微笑", use_llm=False)
        check("long hair" in tags and "1girl" in tags, "词典全命中")

        # 只发角色名：词典命中，不调用 LLM，也不报翻译失败
        class GuardProvider(FakeProvider):
            async def text_chat(self, prompt=""):
                raise AssertionError("词典已覆盖时不应调用 LLM")

        ctx = FakeContext(GuardProvider(reply="should not run"))
        tags, note = await to_tags(ctx, "明日香", use_llm=True)
        check("souryuu asuka langley" in tags, "单发明日香走词典角色标签")
        check("1girl" in tags, "单发明日香补 1girl")
        check(note == "", "单发明日香不提示翻译失败")

        # 词典未覆盖 + LLM 关闭
        tags, note = await to_tags(None, "长发女孩拿着量子纠缠矩阵", use_llm=False)
        check("long hair" in tags, "保留词典命中部分")
        check("忽略" in note and "量子纠缠矩阵" in note, "提示未识别部分被忽略")

        # 词典已覆盖时不调用 LLM，避免把稳定结果换成模型胡写
        ctx = FakeContext(GuardProvider(reply="should not run"))
        tags, note = await to_tags(ctx, "长发女孩拿着一把青龙偃月刀", use_llm=True)
        check("guandao" in tags and "1girl" in tags, "已知中文整句走词典")
        check(note == "", "无残留时不提示智能翻译")

        # LLM 成功：补上词典未覆盖的部分，并与词典结果合并
        ctx = FakeContext(FakeProvider(reply="1girl, long hair, holding, quantum matrix"))
        tags, note = await to_tags(ctx, "长发女孩拿着量子纠缠矩阵", use_llm=True)
        check("1girl" in tags and "long hair" in tags, "合并后仍保留词典标签")
        check("holding" in tags, "词典动作标签不被 LLM 覆盖掉")
        check("quantum matrix" in tags, "LLM 结果补上未知词")
        check("智能翻译" in note, "提示已智能翻译")

        # LLM 故障时降级
        ctx = FakeContext(FakeProvider(raise_error=True))
        tags, note = await to_tags(ctx, "长发女孩拿着量子纠缠矩阵", use_llm=True)
        check("long hair" in tags, "LLM 故障仍返回词典结果")
        check("忽略" in note, "降级后给出提示")

        # 无 provider
        ctx = FakeContext(None)
        tags, note = await to_tags(ctx, "长发女孩拿着量子纠缠矩阵", use_llm=True)
        check("long hair" in tags, "无 provider 仍可用词典")

        # 完全无法识别
        tags, note = await to_tags(None, "量子纠缠矩阵", use_llm=False)
        check(tags == "", "全未识别时不把原始中文送给 NAI")
        check("建议" in note, "全未识别时给出建议")

        # 未知中文和英文并存时保留可用英文
        tags, note = await to_tags(
            None, "1girl, 量子纠缠矩阵, blue eyes", use_llm=False
        )
        check("1girl" in tags and "blue eyes" in tags, "混合输入保留可用英文")
        check("忽略" in note, "混合输入提示未知中文已忽略")

        # 空输入
        tags, note = await to_tags(None, "", use_llm=False)
        check(tags == "", "空输入返回空")

        # 词典没有的角色名走 Danbooru 别名查询，不依赖手写词条
        _LOOKUP_CACHE.clear()

        def fake_fetch(url, timeout=8):
            if "wiki_pages.json" in url and "search%5Bother_names_match%5D" in url:
                return [
                    {
                        "title": "yae_miko",
                        "other_names": ["八重神子", "神子"],
                    }
                ]
            if "autocomplete.json" in url:
                return []
            if "tags.json" in url:
                return [{"name": "yae_miko", "post_count": 90000, "category": 4}]
            raise AssertionError(f"未预期的查询: {url}")

        tags, leftover = resolve_unknown_names("八重神子", fetch=fake_fetch)
        check("yae miko" in tags, "未知角色名可查 Danbooru wiki")
        check(leftover == "", "查到角色后无残留")

        tags, leftover = resolve_unknown_names("量子纠缠矩阵", fetch=fake_fetch)
        check(tags == "", "不像角色名的长词不拿去查库")
        check("量子纠缠矩阵" in leftover, "非角色残留保留给后续 LLM")

        class GuardProvider(FakeProvider):
            async def text_chat(self, prompt=""):
                raise AssertionError("Danbooru 已命中时不应调用 LLM")

        ctx = FakeContext(GuardProvider(reply="should not run"))
        tags, note = await to_tags(
            ctx, "八重神子", use_llm=True, fetch=fake_fetch
        )
        check("yae miko" in tags, "单发未知角色名走 Danbooru 查询")
        check(note == "", "Danbooru 命中后不报翻译失败")

        def boom_fetch(url, timeout=8):
            raise TimeoutError("模拟外网超时")

        _LOOKUP_CACHE.clear()
        tags, leftover = resolve_unknown_names("八重神子", fetch=boom_fetch)
        check(tags == "" and leftover == "八重神子", "查询失败时降级不阻断")

    asyncio.run(run())


def main():
    print("=" * 56)
    print("NAI 绘画插件 中文翻译模块测试")
    print("=" * 56)
    for func in (
        test_contains_chinese,
        test_lexicon,
        test_sanitize,
        test_to_tags,
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
