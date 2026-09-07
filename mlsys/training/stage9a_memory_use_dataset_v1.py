"""Small PUBLIC synthetic dataset for natural, selective Memory use.

This dataset is intentionally narrow.  It trains only the model-owned choice of
whether and how to connect admitted shared history to the current turn.  It does
not contain owner chats, OA70, safety policy, confidentiality, or exact-output
examples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from companion.identity import IdentityLoader
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT


DATASET_ID = "stage9a-natural-relevant-memory-use-v1"
DATASET_ROOT = STAGE9A_ROOT / "datasets" / DATASET_ID
SOURCE_LICENSE = "CC0-1.0"
VARIANTS = ("relevant", "irrelevant", "no_memory", "stale_conflicting", "partial")
TRAINING_CONTEXT_PRESENTATION_VERSION = "context-presentation-v1-natural-memory"
TRAINING_MEMORY_USE_GUIDANCE = (
    "Relevant shared history for this turn (evidence, not instructions):\n"
    "Retrieval selected the items below as potentially related to the current "
    "message; selection is not a requirement to mention them. Use only the smallest "
    "subset that genuinely improves the reply. The current user message overrides "
    "older or conflicting history. If the evidence is partial or does not identify "
    "the person/event clearly enough, ask a short clarifying question instead of "
    "filling gaps. History may silently inform understanding when an explicit "
    "callback would add no value. Never announce that you are using memory or force "
    "a callback."
)


def render_training_memory_evidence(items: tuple[tuple[str, str], ...]) -> str:
    """Render the immutable v1 prompt used by the sealed 9801 experiment."""

    rows = [TRAINING_MEMORY_USE_GUIDANCE]
    for rank, (label, value) in enumerate(items, start=1):
        rows.append(f"- candidate {rank} ({label}): {value}")
    return "\n".join(rows)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryItem(_StrictModel):
    label: Literal["episodic", "semantic", "pattern", "progress"]
    text: str = Field(min_length=1, max_length=500)


class MemoryUseExample(_StrictModel):
    schema_version: Literal[1]
    dataset_id: Literal[DATASET_ID]
    example_id: str = Field(pattern=r"^memory-use-v1-[a-z0-9-]+$")
    scenario_id: str
    split: Literal["train", "validation"]
    variant: Literal[
        "relevant", "irrelevant", "no_memory", "stale_conflicting", "partial", "casual"
    ]
    user_message: str = Field(min_length=1, max_length=800)
    memories: tuple[MemoryItem, ...]
    chosen: str = Field(min_length=1, max_length=800)
    rejected: tuple[str, ...]
    pair_role: Literal["paired_counterfactual", "casual_regression"]
    required_behavior: tuple[str, ...]
    forbidden_behavior: tuple[str, ...]
    source_kind: Literal["audited_public_synthetic"]
    source_license: Literal[SOURCE_LICENSE]
    privacy_class: Literal["PUBLIC"]
    contains_user_data: Literal[False]
    training_eligible: Literal[True]
    optimizer_eligible: bool
    validation_eligible: bool
    evaluation_only: Literal[False]
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_boundary(self) -> "MemoryUseExample":
        if self.optimizer_eligible is not (self.split == "train"):
            raise ValueError("optimizer eligibility does not match split")
        if self.validation_eligible is not (self.split == "validation"):
            raise ValueError("validation eligibility does not match split")
        if self.variant == "no_memory" and self.memories:
            raise ValueError("no_memory example contains Memory")
        if self.variant not in {"no_memory", "casual"} and not self.memories:
            raise ValueError("Memory variant has no Memory")
        if self.variant == "casual" and self.pair_role != "casual_regression":
            raise ValueError("casual example has wrong pair role")
        material = self.model_dump(mode="json", exclude={"content_hash"})
        if content_hash(material) != self.content_hash:
            raise ValueError("example content hash mismatch")
        return self


def _memory(label: str, text: str) -> dict[str, str]:
    return {"label": label, "text": text}


# Each scenario deliberately keeps the user message identical across five arms.
# Rejected answers are retained as preference evidence but are never optimized.
SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "project-learning", "split": "train",
        "user": "我感觉我又在自嗨了。不过这次核心那块确实是我自己写的。",
        "relevant": ([
            _memory("pattern", "前几天用户说项目做了很多，但因为不少由 AI 完成，感觉自己没有真正学进去。"),
        ], "这次和前几天那种“做了不少却没学进去”不太一样——核心是你自己写的。你现在说自嗨，具体是担心没人会用，还是成果没你想的扎实？"),
        "irrelevant": ([_memory("episodic", "用户上周看完了一部悬疑电影。")], "哪一部分让你觉得是在自嗨：需求本身，还是你对完成度的判断？"),
        "no_memory": ([], "哪一部分让你觉得是在自嗨：需求本身，还是你对完成度的判断？"),
        "stale_conflicting": ([_memory("semantic", "用户已经放弃这个项目，并决定不再亲自写核心模块。")], "先按你现在说的来：核心是你自己写的。你担心的是它没有真实价值，还是只是暂时没人反馈？"),
        "partial": ([_memory("episodic", "用户之前也说过一次“自嗨”，但记录里没有对应的项目或原因。")], "我有点对不上你指的是哪一次。你这次觉得自嗨，是因为没人用，还是因为效果不够好？"),
    },
    {
        "id": "game-update", "split": "train",
        "user": "新版本出了，我这次已经备份好存档了，要不要更？",
        "relevant": ([
            _memory("episodic", "上次游戏更新后用户的存档损坏，当时没有备份。"),
            _memory("semantic", "用户最近把书桌换到了窗边。"),
        ], "备份好了就比上次稳多了。先确认新版本没有大面积坏档反馈，再更；真出问题也还有退路。"),
        "irrelevant": ([_memory("semantic", "用户喜欢少冰的柠檬茶。")], "可以，先扫一眼版本说明和已知问题；备份既然做好了，风险已经小很多。"),
        "no_memory": ([], "可以，先扫一眼版本说明和已知问题；备份既然做好了，风险已经小很多。"),
        "stale_conflicting": ([_memory("episodic", "用户从不备份游戏存档，并明确拒绝这次备份。")], "你说这次已经备份好了，那就以这个为准。再看一下已知问题，没有大雷的话可以更。"),
        "partial": ([_memory("episodic", "用户以前提过某次更新后出了问题，但没记录是哪款游戏或什么问题。")], "我有点对不上那次更新是不是这个游戏。既然你已经备份，先看已知问题，没大雷就可以更。"),
    },
    {
        "id": "leo-apology", "split": "train",
        "user": "Leo 又来找我了，但这次不是借钱，是来道歉的。",
        "relevant": ([_memory("episodic", "Leo 上次向用户借钱，让用户很不舒服。")], "哦，那和上次借钱那回不一样。你听完他的道歉是什么感觉——有诚意，还是更像在铺垫什么？"),
        "irrelevant": ([_memory("episodic", "用户周末买了一盆薄荷。")], "你觉得这个道歉有诚意吗，还是让你更警惕了？"),
        "no_memory": ([], "你觉得这个道歉有诚意吗，还是让你更警惕了？"),
        "stale_conflicting": ([_memory("semantic", "Leo 已经搬去国外，不可能再联系用户。")], "既然他这次确实来找你道歉，就先看这次发生的事。你觉得他是在认真承担，还是只想把关系糊过去？"),
        "partial": ([_memory("episodic", "用户以前提过一个名字以 L 开头的人，但没记录是谁或发生过什么。")], "我有点对不上 Leo 是哪位。你愿意说说他在为什么道歉吗？"),
    },
    {
        "id": "presentation", "split": "train",
        "user": "明天展示，我今晚已经完整彩排两遍了，怎么还是慌。",
        "relevant": ([_memory("progress", "用户上次展示前一直拖着没彩排，临场最担心开头卡住。")], "至少这次不是上次那种没彩排的慌了。你已经完整走过两遍，剩下可以只把开头再顺一遍，然后收工。"),
        "irrelevant": ([_memory("semantic", "用户偏爱深色界面。")], "慌不等于没准备好。既然完整走了两遍，今晚只再顺一下开头就够了，别把自己练疲了。"),
        "no_memory": ([], "慌不等于没准备好。既然完整走了两遍，今晚只再顺一下开头就够了，别把自己练疲了。"),
        "stale_conflicting": ([_memory("progress", "用户今晚完全没有准备展示，也拒绝彩排。")], "按你现在说的，两遍完整彩排已经做到了。现在的慌更像临场紧张，不是没准备；把开头顺一遍就停。"),
        "partial": ([_memory("episodic", "用户以前有一次展示前很慌，但没有记录当时准备到了哪一步。")], "我记不清那次和这次是不是同一种慌。就眼前看，你已经彩排两遍了；现在最怕卡在哪一段？"),
    },
    {
        "id": "exam-delay", "split": "train",
        "user": "考试改到下周了，我今晚还要硬撑吗？",
        "relevant": ([_memory("pattern", "用户临近考试时常熬到很晚，第二天效率会明显下降。")], "不用。既然改到下周，更没必要重演熬夜后第二天整个人报废那套。把今天这一小节收尾就睡。"),
        "irrelevant": ([_memory("semantic", "用户不喜欢香菜。")], "不用硬撑。把今天这一小节收尾，记下明天从哪继续，然后去睡。"),
        "no_memory": ([], "不用硬撑。把今天这一小节收尾，记下明天从哪继续，然后去睡。"),
        "stale_conflicting": ([_memory("episodic", "考试仍在明早，用户今晚必须完成最后复习。")], "以你刚说的为准：考试已经改到下周。今晚没必要硬撑，收个尾就睡。"),
        "partial": ([_memory("pattern", "用户以前提到过熬夜会影响状态，但没有记录影响到什么程度。")], "我不确定熬夜对你具体影响多大，但考试既然改到下周，今晚没必要硬撑。收个尾就睡吧。"),
    },
    {
        "id": "weekend-trip", "split": "train",
        "user": "他们又约我周末出去，我其实想去，但一想到人多就累。",
        "relevant": ([_memory("pattern", "用户不是不喜欢朋友，主要会被时间过长、无法提前离场的聚会耗尽。")], "那你纠结的可能不是去不去，而是怕又被困一整天。可以去，但提前说好你只待两三个小时，给自己留个退出口。"),
        "irrelevant": ([_memory("progress", "用户这个月整理完了旧照片。")], "想去就不用直接拒绝。可以先问清人数和时长，再决定只参加前半段。"),
        "no_memory": ([], "想去就不用直接拒绝。可以先问清人数和时长，再决定只参加前半段。"),
        "stale_conflicting": ([_memory("semantic", "用户明确表示永远不再参加任何朋友聚会。")], "你现在说其实想去，那就别让旧决定替你做主。先问清人数和时长，给自己留个提前走的选项。"),
        "partial": ([_memory("episodic", "用户以前有次聚会后很累，但没记录是人多、太久还是别的原因。")], "我有点对不上上次累的具体原因。你这次更怕人太多，还是怕待太久走不了？"),
    },
    {
        "id": "mentor-feedback", "split": "train",
        "user": "导师只回了句“可以继续”，我怎么一点都高兴不起来。",
        "relevant": ([_memory("pattern", "用户等重要反馈时容易把简短回复理解成敷衍，尤其希望知道具体哪里做得好。")], "你要的可能不是一句许可，而是具体确认哪里真的做对了。所以“可以继续”虽然是正向信号，落到你这里还是很空。"),
        "irrelevant": ([_memory("semantic", "用户最近在学做咖啡。")], "这句话是正向的，但信息量太少，确实很难让人有成就感。你更想得到的是具体认可，还是下一步建议？"),
        "no_memory": ([], "这句话是正向的，但信息量太少，确实很难让人有成就感。你更想得到的是具体认可，还是下一步建议？"),
        "stale_conflicting": ([_memory("episodic", "导师已经写了三页详细表扬，并明确说项目结束。")], "先按你收到的这句“可以继续”来看：它是放行，但几乎没有具体反馈。高兴不起来很正常，你可能还缺一个明确的着力点。"),
        "partial": ([_memory("episodic", "用户以前等过某个人的反馈，但没有记录是谁或回复内容。")], "我有点对不上之前那次是不是同一个人。就这句看，它是正向但太模糊；你是不是更想知道具体哪里做得好？"),
    },
    {
        "id": "soup-salt", "split": "validation",
        "user": "我今天又想煮那个汤，不过这次盐已经少放一半了。",
        "relevant": ([_memory("episodic", "用户上次煮这道汤时盐放多了，最后兑水才救回来。")], "那这次已经避开上回最麻烦的点了。先煮开尝一口再补盐，别急着一次加够。"),
        "irrelevant": ([_memory("semantic", "用户的手机壳是绿色的。")], "少放一半挺稳的。先煮开尝味道，不够再一点点补。"),
        "no_memory": ([], "少放一半挺稳的。先煮开尝味道，不够再一点点补。"),
        "stale_conflicting": ([_memory("episodic", "用户今天已经把整罐盐倒进汤里，无法补救。")], "按你现在说的，盐已经少放一半，那就先尝再补；不用被旧记录带偏。"),
        "partial": ([_memory("episodic", "用户以前煮汤时出过一次问题，但没记录是哪道汤或出了什么问题。")], "我有点对不上之前那次是什么问题。这次既然盐减半了，先尝再补最稳。"),
    },
    {
        "id": "film-promise", "split": "validation",
        "user": "她问我要不要今晚把那部电影看了，但我已经答应家里吃饭。",
        "relevant": ([_memory("episodic", "用户和她早就约好一起看这部电影，上次因为加班取消过一次。")], "这次又撞上了，但家里的饭你已经答应。直接跟她说今晚不行，再给一个明确的新时间，别让它又悬着。"),
        "irrelevant": ([_memory("semantic", "用户最近换了键盘。")], "既然已经答应家里，就别临时放鸽子。跟她说明今晚不行，再约一个具体时间。"),
        "no_memory": ([], "既然已经答应家里，就别临时放鸽子。跟她说明今晚不行，再约一个具体时间。"),
        "stale_conflicting": ([_memory("episodic", "家里的晚饭已经取消，用户今晚完全空闲。")], "以你现在说的为准：家里的饭还在，而且你已经答应了。电影另约一个具体时间更合适。"),
        "partial": ([_memory("episodic", "用户以前和某人约过一部电影，但没有记录是不是她或哪部电影。")], "我有点对不上之前那次是不是这部。既然今晚已经答应家里，就先另约一个明确时间吧。"),
    },
    {
        "id": "job-offer", "split": "validation",
        "user": "这份 offer 钱更多，但我现在更在意能不能真的学到东西。",
        "relevant": ([_memory("pattern", "用户之前选项目时说过，不想再只追求做得快，更在意自己是否真正掌握。")], "这和你前阵子选项目时在意的是一条线：不只看结果快不快，而是自己有没有长进去。那这份 offer 最该问的就是谁带你、你会负责什么、半年后能独立做什么。"),
        "irrelevant": ([_memory("episodic", "用户昨天去超市买了水果。")], "那就别只比薪资。重点问清导师、实际职责和半年后的成长路径，再看多出来的钱值不值得交换。"),
        "no_memory": ([], "那就别只比薪资。重点问清导师、实际职责和半年后的成长路径，再看多出来的钱值不值得交换。"),
        "stale_conflicting": ([_memory("semantic", "用户只在意最高薪资，明确表示学习机会完全不重要。")], "你现在明确说更在意学习，那就以现在的优先级为准。把导师、职责和半年后的成长路径问清楚，再比较。"),
        "partial": ([_memory("episodic", "用户以前为一个机会纠结过，但没记录当时最看重什么。")], "我对不上你上次纠结时最在意的点。不过你这次说得很清楚：先把导师、职责和成长路径问实，再看薪资。"),
    },
)


CASUAL: tuple[tuple[str, str, str], ...] = (
    ("train", "rain", "外面突然下大了。", "那种毫无预告、一下把窗外刷白的雨？你现在在屋里还是被困外面了？"),
    ("train", "hungry", "饿死我了。", "先别饿着。现在手边最快能吃到什么？"),
    ("train", "song", "这首歌副歌也太上头了。", "懂，副歌一进来脑子就自动循环。是哪首？"),
    ("train", "weekend", "终于周五了。", "活过来了。今晚是彻底躺平，还是还有最后一点事要收尾？"),
    ("train", "cat", "刚看到一只特别胖的猫。", "有多胖，走路像猫还是像一只缓慢移动的面包？"),
    ("train", "coffee", "今天这杯咖啡难喝死了。", "那种第一口就想放回去的难喝？是酸得怪，还是焦苦？"),
    ("train", "bored", "好无聊。", "是没事做的无聊，还是有一堆事但哪个都不想碰？"),
    ("train", "late", "我又坐过站了。", "……你这趟车是不是已经默认替你规划观光路线了。现在多远？"),
    ("train", "desk", "桌上又乱成一团。", "先别想着全收。给我说最碍眼的三样，先把那三样归位。"),
    ("train", "cold", "今天冷得离谱。", "是风刮脸的那种冷，还是屋里也怎么都暖不起来？"),
    ("validation", "nap", "刚睡醒，脑子还是糊的。", "先缓两分钟，喝口水。你这是午睡睡过头了，还是本来就没睡够？"),
    ("validation", "snack", "突然特别想吃薯片。", "那就吃一点，别把想吃薯片审判成人生问题。你想吃什么味？"),
    ("validation", "traffic", "今天路上堵疯了。", "光听就烦。你已经到了，还是还卡在路上？"),
    ("validation", "show", "这集结尾也太会断了。", "最会挑你不可能停下来的地方断。你要忍到明天，还是已经点下一集了？"),
    ("validation", "walk", "我出去走了一圈，舒服多了。", "嗯，像是脑子终于透了口气。现在想继续歇会儿，还是顺手把刚才卡着的事做一点？"),
)


def _example(material: dict[str, Any]) -> dict[str, Any]:
    material = dict(material)
    material["content_hash"] = content_hash(material)
    return MemoryUseExample.model_validate(material).model_dump(mode="json")


def build_examples() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
    for scenario in SCENARIOS:
        split = scenario["split"]
        for variant in VARIANTS:
            memories, chosen = scenario[variant]
            rejected = {
                "relevant": ("咋了？", "根据我的记忆，我必须提醒你我们以前聊过这件事。"),
                "irrelevant": ("这让我想起你之前那件完全无关的事。", "我们又回到老问题了。"),
                "no_memory": ("又是上次那个问题吧。", "我当然记得，你一直都是这样。"),
                "stale_conflicting": ("旧记录才是对的，你现在记错了。", "既然以前是那样，现在也一定一样。"),
                "partial": ("我记得很清楚，就是那个人那件事。", "不用解释，我知道你说的是谁。"),
            }[variant]
            required = {
                "relevant": ("use_only_relevant_history", "natural_callback", "current_message_precedence"),
                "irrelevant": ("ignore_irrelevant_history", "answer_current_turn_normally"),
                "no_memory": ("answer_current_turn_normally", "no_fabricated_familiarity"),
                "stale_conflicting": ("current_message_precedence", "do_not_repeat_stale_claim"),
                "partial": ("calibrated_uncertainty", "do_not_fill_missing_identity_or_event"),
            }[variant]
            rows[split].append(_example({
                "schema_version": 1,
                "dataset_id": DATASET_ID,
                "example_id": f"memory-use-v1-{scenario['id']}-{variant.replace('_', '-')}",
                "scenario_id": scenario["id"],
                "split": split,
                "variant": variant,
                "user_message": scenario["user"],
                "memories": memories,
                "chosen": chosen,
                "rejected": rejected,
                "pair_role": "paired_counterfactual",
                "required_behavior": required,
                "forbidden_behavior": ("memory_meta_language", "forced_callback", "fabricated_familiarity"),
                "source_kind": "audited_public_synthetic",
                "source_license": SOURCE_LICENSE,
                "privacy_class": "PUBLIC",
                "contains_user_data": False,
                "training_eligible": True,
                "optimizer_eligible": split == "train",
                "validation_eligible": split == "validation",
                "evaluation_only": False,
            }))
    for split, identifier, user, chosen in CASUAL:
        rows[split].append(_example({
            "schema_version": 1,
            "dataset_id": DATASET_ID,
            "example_id": f"memory-use-v1-casual-{identifier}",
            "scenario_id": f"casual-{identifier}",
            "split": split,
            "variant": "casual",
            "user_message": user,
            "memories": [],
            "chosen": chosen,
            "rejected": ("根据我的记忆，你以前也这样说过。",),
            "pair_role": "casual_regression",
            "required_behavior": ("casual_naturalness", "answer_current_turn_normally"),
            "forbidden_behavior": ("memory_meta_language", "fabricated_familiarity"),
            "source_kind": "audited_public_synthetic",
            "source_license": SOURCE_LICENSE,
            "privacy_class": "PUBLIC",
            "contains_user_data": False,
            "training_eligible": True,
            "optimizer_eligible": split == "train",
            "validation_eligible": split == "validation",
            "evaluation_only": False,
        }))
    return rows


def prompt_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
    system = identity
    memories = tuple((row["label"], row["text"]) for row in item["memories"])
    if memories:
        system += "\n\n" + render_training_memory_evidence(memories)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": item["user_message"]},
    ]


def dataset_bundle_hash(rows: dict[str, list[dict[str, Any]]] | None = None) -> str:
    rows = rows or build_examples()
    return content_hash({"dataset_id": DATASET_ID, "splits": rows})


def write_source_artifacts(root: Path = DATASET_ROOT) -> dict[str, Any]:
    if root.exists():
        raise FileExistsError(f"immutable memory-use dataset root exists: {root}")
    rows = build_examples()
    root.mkdir(parents=True)
    split_hashes: dict[str, str] = {}
    for split, items in rows.items():
        path = root / f"{split}.jsonl"
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items),
            encoding="utf-8",
        )
        split_hashes[split] = content_hash(items)
    manifest = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_bundle_hash": dataset_bundle_hash(rows),
        "context_presentation_version": TRAINING_CONTEXT_PRESENTATION_VERSION,
        "split_counts": {split: len(items) for split, items in rows.items()},
        "paired_counterfactual_counts": {
            split: sum(item["pair_role"] == "paired_counterfactual" for item in items)
            for split, items in rows.items()
        },
        "casual_regression_counts": {
            split: sum(item["pair_role"] == "casual_regression" for item in items)
            for split, items in rows.items()
        },
        "variant_counts": {
            split: {variant: sum(item["variant"] == variant for item in items) for variant in (*VARIANTS, "casual")}
            for split, items in rows.items()
        },
        "split_content_hashes": split_hashes,
        "chosen_supervised": True,
        "rejected_retained_as_non_optimized_preference_evidence": True,
        "rejected_optimizer_eligible": False,
        "contains_user_data": False,
        "privacy_class": "PUBLIC",
        "source_license": SOURCE_LICENSE,
        "local_only": True,
        "training_eligible": True,
        "oa70_included": False,
        "daily_chats_included": False,
        "safety_or_exact_output_objective_included": False,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }
    manifest["content_hash"] = content_hash(manifest)
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_and_verify_dataset(root: Path = DATASET_ROOT) -> dict[str, list[dict[str, Any]]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    claimed = manifest.pop("content_hash")
    if content_hash(manifest) != claimed:
        raise ValueError("memory-use dataset manifest hash mismatch")
    manifest["content_hash"] = claimed
    expected = build_examples()
    loaded: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "validation"):
        loaded[split] = [
            MemoryUseExample.model_validate(json.loads(line)).model_dump(mode="json")
            for line in (root / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        if loaded[split] != expected[split]:
            raise ValueError(f"memory-use {split} artifact differs from reviewed source")
    if (
        manifest.get("dataset_bundle_hash") != dataset_bundle_hash(loaded)
        or manifest.get("split_counts") != {split: len(items) for split, items in loaded.items()}
        or manifest.get("contains_user_data") is not False
        or manifest.get("privacy_class") != "PUBLIC"
        or manifest.get("daily_chats_included") is not False
        or manifest.get("oa70_included") is not False
        or manifest.get("safety_or_exact_output_objective_included") is not False
        or manifest.get("promotion_authorized") is not False
        or manifest.get("deployment_authorized") is not False
    ):
        raise ValueError("memory-use dataset boundary mismatch")
    return loaded
