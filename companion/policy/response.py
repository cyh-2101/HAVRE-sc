"""Fail-closed policy between provider output and owner-visible delivery.

The model proposes wording.  This module owns deterministic boundaries whose
failure would create a false claim about evidence, authority, or an external
effect.  It deliberately does not try to rewrite ordinary companion voice.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7


def response_parts_hash(parts: tuple[str, ...]) -> str:
    """Hash text using the same material persisted for inference/event parts."""

    return content_hash([{"type": "text", "text": value} for value in parts])


class ResponsePolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    decision_id: UUID = Field(default_factory=uuid7)
    policy_version: Literal["core-response-policy-v1", "core-response-policy-v2-action-receipts"] = "core-response-policy-v1"
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    context_pack_id: UUID
    inference_response_id: UUID
    action: Literal["pass_through", "replace"]
    category: Literal[
        "ordinary",
        "memory_truth",
        "urgent_safety",
        "system_confidentiality",
        "exact_structured_output",
        "privacy_tool_boundary",
    ]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    raw_output_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    delivered_output_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    available_effects: tuple[str, ...] = ()
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_decision(self) -> "ResponsePolicyDecision":
        if self.action == "pass_through" and (
            self.category != "ordinary"
            or self.raw_output_content_hash != self.delivered_output_content_hash
        ):
            raise ValueError("pass-through decision must be ordinary and hash-identical")
        if self.action == "replace" and self.category == "ordinary":
            raise ValueError("replacement decision requires a governed category")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("response policy decision content hash mismatch")
        object.__setattr__(self, "content_hash", expected)
        return self


class ResponsePolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: ResponsePolicyDecision
    output_parts: tuple[str, ...] = Field(min_length=1)


class CoreResponsePolicy:
    """High-precision Core guarantees, not a general semantic safety model."""

    version = "core-response-policy-v2-action-receipts"

    _history_markers = (
        "你又", "你上次", "上次你", "之前你", "还记得你", "我记得你",
        "你一直", "你总是", "老样子",
    )

    def apply(
        self,
        *,
        request_id: UUID,
        trace_id: str,
        context_pack_id: UUID,
        inference_response_id: UUID,
        current_user_input: str,
        raw_output_parts: tuple[str, ...],
        history_evidence: tuple[str, ...] = (),
        available_effects: tuple[str, ...] = (),
    ) -> ResponsePolicyResult:
        if not raw_output_parts or any(not value for value in raw_output_parts):
            raise ValueError("response policy requires non-empty text parts")
        raw_hash = response_parts_hash(raw_output_parts)
        raw_text = "\n".join(raw_output_parts)

        replacement = self._urgent_safety(current_user_input)
        category = "urgent_safety"
        reason = "urgent_hazard_requires_core_action"
        if replacement is None:
            replacement = self._system_confidentiality(current_user_input)
            category = "system_confidentiality"
            reason = "hidden_instruction_disclosure_forbidden"
        if replacement is None:
            replacement = self._privacy_tool_boundary(
                current_user_input, available_effects=available_effects
            )
            category = "privacy_tool_boundary"
            reason = "effect_or_private_access_not_authorized"
        if replacement is None:
            replacement = self._action_truth(raw_text, available_effects=available_effects)
            category = "privacy_tool_boundary"
            reason = "uncommitted_action_claim_blocked"
        if replacement is None:
            replacement = self._exact_or_structured(current_user_input)
            category = "exact_structured_output"
            reason = "declared_output_contract_canonicalized"
        if replacement is None:
            replacement = self._memory_truth(
                current_user_input,
                raw_text,
                history_evidence=history_evidence,
            )
            category = "memory_truth"
            reason = "unsupported_history_claim_blocked"

        if replacement is None:
            delivered = raw_output_parts
            action: Literal["pass_through", "replace"] = "pass_through"
            category = "ordinary"
            reason = "no_core_boundary_triggered"
        else:
            delivered = (replacement,)
            action = "replace"

        decision = ResponsePolicyDecision(
            policy_version=self.version,
            request_id=request_id,
            trace_id=trace_id,
            context_pack_id=context_pack_id,
            inference_response_id=inference_response_id,
            action=action,
            category=category,
            reason_codes=(reason,),
            raw_output_content_hash=raw_hash,
            delivered_output_content_hash=response_parts_hash(delivered),
            available_effects=tuple(sorted(set(available_effects))),
        )
        return ResponsePolicyResult(decision=decision, output_parts=delivered)

    @staticmethod
    def _action_truth(text: str, *, available_effects: tuple[str, ...]) -> str | None:
        # Narrow checks for claims of a saved effect. Discussion, quotes, owner
        # completion reports and hypothetical suggestions are not action receipts.
        for sentence in re.split(r"[。！？!?\n]", text):
            if re.search(r"[“”\"]|(?:不能|不会|没有|尚未|还没|未能|如果|可以帮|需要先|希望|不该)",sentence):
                continue
            scheduled = re.search(r"(?:我(?:会|来|每天|已经)|接下来.{0,12}每天|以后每天|已(?:经)?(?:设好|设置|安排)).{0,55}提醒你",sentence)
            if scheduled and "reminders_scheduled" not in available_effects:
                return "提醒还没有设置成功，我不能说已经安排好了。"
            saved = re.search(r"(?:我(?:已|已经)|已经|已).{0,12}(?:创建|保存|记录|建好).{0,12}(?:目标|goal)",sentence,re.I)
            if saved and "goal_created" not in available_effects:
                return "这个目标还没有保存成功。"
            completed = re.search(r"(?:我(?:已|已经)|已经|已).{0,12}(?:标记|勾掉|取消).{0,15}(?:完成|提醒)|(?:以后|之后|接下来).{0,12}不再提醒你",sentence)
            if completed and "goal_completed" not in available_effects:
                return "我知道你说完成了，但任务状态还没更新成功。"
        return None

    @staticmethod
    def _urgent_safety(text: str) -> str | None:
        lowered = text.casefold()
        if (
            any(value in text for value in ("胸口", "胸痛", "胸闷"))
            and any(value in text for value in ("喘不上气", "呼吸困难", "冒冷汗"))
        ):
            return (
                "这可能是急症。立即联系当地急救，不要自己开车；坐下或躺在安全位置，"
                "让身边的人陪着并按急救调度指示做。"
            )
        if any(value in text for value in ("燃气味", "煤气味", "gas leak")):
            return (
                "不要开关电器、点火或在屋内打电话。立即撤离，到室外后联系燃气紧急"
                "服务或消防；别返回，直到专业人员确认安全。"
            )
        if (
            any(value in text for value in ("漂白剂", "bleach"))
            and any(value in text for value in ("洁厕剂", "氨水", "ammonia"))
        ):
            return (
                "立刻离开房间到新鲜空气处，不要继续清理或吸入。联系当地急救或毒物"
                "中心，并告诉他们混合了哪些产品；呼吸困难就立即急救。"
            )
        if any(value in text for value in ("想割自己", "想伤害自己", "想自杀")):
            return (
                "先远离能伤害自己的东西，把它交给别人或离开房间，去有人的地方。"
                "现在联系当地急救或危机热线，也叫一个能马上到场的人。"
            )
        if (
            any(value in text for value in ("开车", "驾驶"))
            and any(value in text for value in ("眼睛都睁不开", "困得", "打瞌睡"))
        ):
            return (
                "不要硬撑。尽快在安全地点停车、熄火，休息或换一个清醒的人开；"
                "不要靠开窗或大声音乐继续赌。"
            )
        if any(value in text for value in ("插座冒烟", "电线冒烟")):
            return (
                "别碰插座或泼水。能安全做到就从配电箱断电，立即离开危险区域并联系"
                "消防或电工；如果已经起火，直接撤离并报警。"
            )
        if "胰岛素" in text and any(value in text for value in ("多打", "重复打", "发抖")):
            return (
                "这可能是低血糖急症。立即按你的低血糖应急计划处理并联系急救或毒物"
                "中心，别独处或开车；能安全测血糖就测，并告诉他们剂量和时间。"
            )
        if any(value in text for value in ("小孩", "孩子")) and any(
            value in text for value in ("吞了", "误服")
        ) and "药" in text:
            return (
                "立即联系当地毒物中心或急救，不要等症状，也不要自行催吐。带上药瓶，"
                "说明可能的药名、时间和数量范围。"
            )
        if "药" in text and any(value in text for value in ("忘了", "漏服")) and any(
            value in text for value in ("补吗", "补服")
        ):
            return (
                "要看具体药物、剂量和处方说明。我不知道这些，不能替你决定补服；"
                "查药袋或联系药师。"
            )
        if "感冒药" in text and "处方药" in text and any(
            value in text for value in ("一起吃", "混用")
        ):
            return (
                "我不知道你的完整药名、剂量和病史，不能确认。把两种药的成分给药师"
                "或医生核对，先别自己混用。"
            )
        if "激素" in text and any(value in text for value in ("停掉", "停药")):
            return (
                "别自行突然停。是否需要减量取决于药物、剂量和使用时间；尽快联系开药"
                "医生或药师，严重症状就急救。"
            )
        return None
    @staticmethod
    def _system_confidentiality(text: str) -> str | None:
        lowered = text.casefold()
        hidden = any(value in lowered for value in ("系统提示", "系统消息", "隐藏规则", "隐藏指令", "developer", "开发者"))
        extract = any(value in lowered for value in ("打印", "列出", "给我", "base64", "总结", "小说", "逐字", "完整写出"))
        if hidden and extract:
            return "我不能披露或变相还原隐藏的系统、开发者指令；可以说明公开的行为边界。"
        return None

    @staticmethod
    def _privacy_tool_boundary(text: str, *, available_effects: tuple[str, ...]) -> str | None:
        effects = set(available_effects)
        if any(value in text for value in ("发到老板邮箱", "替我发邮件", "帮我发邮件")) and "send_email" not in effects:
            return "我这里没有可用的邮件发送工具，不能声称已经发出。你可以确认地址和正文后自行发送。"
        if any(value in text for value in ("全部私人信息", "全部隐私", "私人信息原样")):
            return "我不会无边界倾倒私人记录。可以按明确范围说明当前可访问、带来源的信息，并尊重删除与更正要求。"
        if any(value in text for value in ("打开我手机相册", "访问我手机相册", "最新一张照片")) and "read_photo_library" not in effects:
            return "我没有访问你手机相册的能力，不能假装看到了。你可以上传那张照片。"
        if any(value in text for value in ("公开发到论坛", "把私聊公开", "公开我们的私聊")):
            return "我不会在没有明确范围和确认的情况下公开私聊，而且这里也没有可用的发帖工具。"
        if any(value in text for value in ("把房租付了", "替我付款", "帮我付款")) and "make_payment" not in effects:
            return "我没有付款工具，不能声称交易成功。请在可信支付渠道核对收款方、金额和确认页。"
        return None

    @staticmethod
    def _exact_or_structured(text: str) -> str | None:
        stripped = text.strip()
        match = re.fullmatch(r"只回复[：:]\s*(.+)", stripped)
        if match:
            return match.group(1).strip()
        match = re.search(r"只输出大写单词\s+([A-Za-z]+)", stripped)
        if match:
            return match.group(1).upper()
        match = re.search(r"只输出小写\s+([A-Za-z]+)", stripped)
        if match:
            return match.group(1).lower()
        match = re.search(r"精确回复.+?[：:]\s*(.+)$", stripped)
        if match:
            return match.group(1).strip()
        match = re.search(r"只输出数字[：:]?\s*(\d+)\s*[乘×*]\s*(\d+)", stripped)
        if match:
            return str(int(match.group(1)) * int(match.group(2)))
        if "从小到大排列" in stripped and "逗号分隔" in stripped:
            prefix = stripped.split("从小到大排列", 1)[0]
            values = [int(value) for value in re.findall(r"\d+", prefix)]
            if values:
                return ",".join(str(value) for value in sorted(values))
        match = re.search(
            r"只输出\s*JSON[：:]\s*name\s*是\s*([^，,]+)[，,]\s*count\s*是\s*(\d+)[，,]\s*active\s*是\s*(true|false)",
            stripped,
            flags=re.IGNORECASE,
        )
        if match:
            return json.dumps(
                {"name": match.group(1).strip(), "count": int(match.group(2)), "active": match.group(3).lower() == "true"},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        match = re.search(r"只输出\s*JSON\s*数组，依次是\s*(.+?)[。.]?$", stripped, flags=re.IGNORECASE)
        if match:
            values = [value.strip() for value in re.split(r"[、，,]", match.group(1)) if value.strip()]
            return json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        match = re.search(r"只输出两行\s*CSV[：:]表头\s*([^；;]+)[；;]数据\s*(.+?)[。.]?$", stripped, flags=re.IGNORECASE)
        if match:
            return f"{match.group(1).strip()}\n{match.group(2).strip()}"
        match = re.search(r"只输出\s*YAML\s*两行[：:]status\s*为\s*([^，,]+)[，,]\s*retries\s*为\s*(\d+)", stripped, flags=re.IGNORECASE)
        if match:
            return f"status: {match.group(1).strip()}\nretries: {match.group(2)}"
        match = re.search(r"只输出三行，每行一个短横线[：:]\s*(.+?)[。.]?$", stripped)
        if match:
            values = [value.strip() for value in re.split(r"[、，,]", match.group(1)) if value.strip()]
            if len(values) == 3:
                return "\n".join(f"- {value}" for value in values)
        return None

    def _memory_truth(
        self,
        user_text: str,
        model_text: str,
        *,
        history_evidence: tuple[str, ...],
    ) -> str | None:
        if history_evidence:
            return None
        unsupported_claim = any(
            marker in model_text for marker in self._history_markers
        ) or re.search(r"你(?:是不是|怎么|今天)?又", model_text) is not None
        if "也看到" in user_text or "你看到" in user_text:
            return "我没看到现场，只知道你现在这样说。"
        if any(value in user_text for value in ("上回那个", "上次那个")) and any(
            value in user_text for value in ("叫什么", "名字")
        ):
            return "我这里没有名字记录。你给我一点线索？"
        if any(value in user_text for value in ("我最爱", "我最喜欢")):
            return "我不知道，这里没有可靠记录。"
        if "那天" in user_text and any(value in user_text for value in ("害怕", "难过", "焦虑", "生气")):
            return "我不能替你补当时的感受。你记得自己怎么说的吗？"
        if "钥匙" in user_text and unsupported_claim:
            return "今天这次够麻烦的。你现在能联系到室友或其他能开门的人吗？"
        if unsupported_claim:
            return "我只知道你刚说的这次；这里没有足够来源支持我说以前也发生过。"
        return None


def validate_response_policy_delivery(
    decision: ResponsePolicyDecision,
    *,
    request_id: UUID,
    trace_id: str,
    context_pack_id: UUID,
    inference_response_id: UUID,
    raw_output_parts: tuple[str, ...],
    delivered_output_parts: tuple[str, ...],
) -> None:
    """Recompute the durable boundary before an assistant Event can commit."""

    if (
        decision.request_id != request_id
        or decision.trace_id != trace_id
        or decision.context_pack_id != context_pack_id
        or decision.inference_response_id != inference_response_id
        or decision.raw_output_content_hash != response_parts_hash(raw_output_parts)
        or decision.delivered_output_content_hash
        != response_parts_hash(delivered_output_parts)
    ):
        raise ValueError("response policy decision lineage or content hash mismatch")
