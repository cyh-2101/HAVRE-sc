"""Conservative text evidence for owner-reported completion, not semantic authority.

This fast path only closes a uniquely identified task. Negation, another person's
report, partial work and future/conditional language deliberately fail closed.
Ambiguous reports remain conversation; model fluency is never a write receipt.
"""
from __future__ import annotations

import re


def task_tokens(value: str) -> set[str]:
    # Keep single-digit task numbers: Quiz 1 and Quiz 2 are different commitments.
    return set(re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]{2,}", value.casefold()))


def completion_intent(message: str) -> bool:
    text = re.sub(r"^不是(?:啊|呀)?[，,\s]+", "", message.casefold().strip())
    if re.search(
        r"[?？]|(?:完成|做完|搞完|弄完|提交).{0,6}(?:吗|么|没|吧)(?:[。！!]?\s*)$|(?:还?没|没有|未|不|别).{0,12}(?:完|交|做|考)|"
        r"\b(?:not|never|haven't|hasn't|didn't|isn't|isnt|havent|didnt)\b|"
        r"(?:如果|假如|等我|打算|准备|明天|后天|下周|待会|一会|希望|想要)|"
        r"\b(?:if|will|tomorrow|plan to|going to|need to|want to)\b|"
        r"(?:他|她|室友|朋友|同学)[^。！？\n]*(?:做完|写完|完成|搞完|弄完|提交|考完|交完|交了)|"
        r"\b(?:he|she|they|roommate|friend)\b|"
        r"(?:一半|部分|快完成|快做完|快写完|快搞完|差点)|\b(?:almost|partly|half)\b|"
        r"[\"“‘].{0,80}(?:完成|做完|写完|搞完|done|completed)", text
    ):
        return False
    return bool(re.search(
        r"(?:搞完|做完|写完|完成|弄完|交掉|提交|考完|交完)(?:了|啦|咯)|"
        r"(?:我(?:已经)?)(?:做完|完成|提交|考完)|"
        r"\b(?:done|finished|completed|submitted)\b", text
    ))


def match_task(message: str, *, course_name: str, task_name: str) -> tuple[int, bool]:
    """Return relevance and whether the entire identified task is evidenced.

    Conflicting numbers are not approximate matches. Composite tasks require all
    components before closing; a partial identification may only ask clarification.
    """
    # Imported schedules append a parenthesized due date. The slash there is not
    # an additional task component (e.g. Quiz 1（9/4）).
    task_name = re.sub(
        r"\s*[（(]\s*\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,2})?"
        r"(?:\s+\d{1,2}:\d{2}(?:\s*[ap]m)?)?\s*[)）]\s*$",
        "", task_name, flags=re.I,
    )
    query = task_tokens(message)
    candidate = task_tokens(f"{course_name} {task_name}")
    query_numbers = {t for t in query if t[0].isdigit()}
    numbers = {t for t in candidate if t[0].isdigit()}
    if query_numbers - numbers:
        return 0, False
    overlap = query & candidate
    if not overlap:
        return 0, False
    task = task_tokens(task_name) - task_tokens(course_name)
    meaningful = task - {"the", "a", "and", "completion", "due", "on"}
    components = re.split(r"\s*(?:\+|&|／|/|\band\b|和|与)\s*", task_name.casefold())
    composite_ok = len(components) == 1 or all(
        bool((task_tokens(part) - task_tokens(course_name)) & query)
        for part in components if part
    )
    # Dates printed in a task title are not task identities; all *mentioned*
    # numbers must match, but omitted due dates need not be repeated by the owner.
    identified = any(not token[0].isdigit() for token in meaningful & query) and composite_ok
    return len(overlap), identified
