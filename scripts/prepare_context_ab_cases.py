"""Export an owner-review packet locally; never authorize or run an evaluation.

Only ordinary NORMAL/cloud-eligible Web sources are copied. Historical replies
are evidence, never reference answers. No source bodies are printed to stdout.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
from collections import Counter
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
PROBE = re.compile(r"probe|smoke|synthetic|calibration|course-import|fixture|test-", re.I)
CATEGORIES = (
    "casual", "cross_day", "old_recall", "correction", "goal",
    "ambiguity", "stale", "no_callback",
)


def body(row):
    return "\n".join(p.get("text", "") for p in row["payload"].get("content_parts", ())
                     if p.get("type", "text") == "text")


def eligible(row):
    return row["privacy_class"] == "NORMAL" and row["cloud_eligible"] is True


def draft_tags(text, prior, instant, section_types):
    """Sampling hints only. These deliberately do not claim semantic coverage."""
    tags = []
    if len(text) <= 80:
        tags.append("casual")
    if prior and datetime.fromisoformat(prior[-1]["recorded_at"]).astimezone(ZoneInfo("America/Chicago")).date() < instant.astimezone(ZoneInfo("America/Chicago")).date():
        tags.append("cross_day")
    if re.search(r"记得|之前|上次|昨天|昨晚|previous|remember", text, re.I):
        tags.append("old_recall")
    if re.search(r"不是|不对|记错|说错|纠正|别分析|不要分析|没让|别再", text):
        tags.append("correction")
    if re.search(r"目标|计划|作业|实验|任务|考试|做完|完成|goal|lab|quiz|demo", text, re.I):
        tags.append("goal")
    if re.search(r"那个人|她|他|那个项目|这件事|那个", text):
        tags.append("ambiguity")
    if re.search(r"已经不|不再|现在改|过期|取消|改成|不是.*是", text):
        tags.append("stale")
    if re.search(r"随便聊|只是聊|别分析|不要分析|不要提|不想说|早安|晚安|吃饭|吃了", text):
        tags.append("no_callback")
    return tags


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def prepare(database_url, expected_database, owner_id, output):
    target = urlparse(database_url)
    if target.hostname not in {"localhost", "127.0.0.1"} or target.path != "/" + expected_database:
        raise ValueError("explicit loopback database and exact expected name required")
    output = output.resolve()
    if not output.is_relative_to(ROOT / "var") or output.exists():
        raise ValueError("use a new, ignored repository var directory; no overwrite")
    output.mkdir(parents=True)
    if os.name == "nt":
        principal = next(csv.reader(subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], text=True).strip().splitlines()))[1]
        subprocess.run(["icacls", str(output), "/inheritance:r", "/grant:r", f"*{principal}:(OI)(CI)F"],
                       check=True, capture_output=True)
    with psycopg.connect(database_url, row_factory=dict_row,
                         options="-c default_transaction_read_only=on -c statement_timeout=15000") as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        c.execute("SET TIME ZONE 'UTC'")
        verified = c.execute("SELECT current_database() db, current_setting('transaction_read_only') ro, now() captured_at").fetchone()
        if verified["db"] != expected_database or verified["ro"] != "on":
            raise ValueError("read-only target verification failed")
        requests = c.execute("""
            SELECT r.request_id,r.user_event_id,r.created_at,r.status,r.idempotency_key,
                   p.builder_version,p.sections
            FROM havre.interaction_requests r
            JOIN havre.events e ON e.owner_id=r.owner_id AND e.event_id=r.user_event_id
            LEFT JOIN havre.context_packs p ON p.owner_id=r.owner_id AND p.context_pack_id=r.context_pack_id
            WHERE r.owner_id=%s AND r.request_kind='interaction'
              AND e.privacy_class='NORMAL' AND e.cloud_eligible
              AND e.payload->>'channel'='web'
              AND NOT EXISTS (SELECT 1 FROM havre.offline_source_revocations x
                              WHERE x.owner_id=e.owner_id AND x.source_event_id=e.event_id)
            ORDER BY e.recorded_at,e.event_id
        """, (owner_id,)).fetchall()
        requests = [r for r in requests if not PROBE.search(r["idempotency_key"])]
        ids = [r["request_id"] for r in requests]
        events = c.execute("""
            SELECT e.* FROM havre.events e WHERE e.owner_id=%s AND e.request_id=ANY(%s::uuid[])
              AND e.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
              AND e.privacy_class='NORMAL' AND e.cloud_eligible
              AND NOT EXISTS (SELECT 1 FROM havre.offline_source_revocations x
                              WHERE x.owner_id=e.owner_id AND x.source_event_id=e.event_id)
            ORDER BY e.recorded_at,e.event_id
        """, (owner_id, ids)).fetchall()
    sources = []
    for row in events:
        if not eligible(row) or str(row["owner_id"]) != str(owner_id):
            raise ValueError("source isolation failed")
        sources.append({
            "event_id": str(row["event_id"]), "request_id": str(row["request_id"]),
            "owner_id": str(owner_id), "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
            "recorded_at": row["recorded_at"].isoformat(), "text": body(row),
            "source_content_hash": row["content_hash"],
            "source_policy": {k: row[k] for k in (
                "privacy_class", "cloud_eligible", "memory_eligible", "training_eligible",
                "policy_version", "policy_authorization_ref")},
        })
    source_map = {s["event_id"]: s for s in sources}
    cases = []
    for i, request in enumerate(requests, 1):
        current = source_map[str(request["user_event_id"])]
        instant = datetime.fromisoformat(current["recorded_at"])
        prior = [s for s in sources if datetime.fromisoformat(s["recorded_at"]) < instant
                 and s["request_id"] != current["request_id"]]
        types = sorted({s["section_type"] for s in request["sections"] or ()})
        cases.append({
            "case_id": f"R{i:03d}", "current_event_id": current["event_id"],
            "as_of": current["recorded_at"], "available_prior_event_ids": [s["event_id"] for s in prior],
            "sampling_hints_only": draft_tags(current["text"], prior, instant, types),
            "historical_builder_version": request["builder_version"],
            "historical_section_types_not_current_replay": types,
            "owner_real_daily_case_confirmed": False, "approved_for_experiment": False,
            "owner_primary_category": None, "owner_expected_facts": [], "owner_forbidden_claims": [],
        })
    policy = {"privacy_class": "LOCAL_ONLY", "cloud_eligible": False, "training_eligible": False,
              "purpose": "owner review of potential real evaluation cases; no evaluation approval yet",
              "product_ingestion": False}
    corpus = {"schema_version": 1, "policy": policy, "owner_id": str(owner_id),
              "captured_at": verified["captured_at"], "sources": sources, "cases": cases}
    write_json(output / "candidate-corpus.LOCAL_ONLY.json", corpus)
    summary = {"candidate_cases": len(cases), "raw_sources": len(sources),
               "hints_not_verified_coverage": dict(Counter(t for c in cases for t in c["sampling_hints_only"])),
               "actual_case_approvals": 0, "cloud_calls": 0,
               "oldest_source": min((s["recorded_at"] for s in sources), default=None),
               "newest_source": max((s["recorded_at"] for s in sources), default=None)}
    write_json(output / "structural-summary.json", summary)
    esc = lambda x: html.escape(str(x))
    pre = lambda x: "<pre>" + esc(x) + "</pre>"
    rows = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'>",
            "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'\">",
            "<title>HAVRE 真实案例本机审阅</title><style>body{max-width:960px;margin:36px auto;padding:0 20px;font:16px/1.7 system-ui;background:#fafaf7;color:#233}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2ef;padding:14px}article{border-top:1px solid #acb;padding:20px 0}summary{cursor:pointer}a{color:#175b56}</style>",
            "<h1>Context A/B：真实案例候选</h1><p>LOCAL_ONLY。本页不联网。尚未批准用于实验；没有云端实验调用，也没有训练。</p>",
            "<p>只包含普通 NORMAL、允许云端处理的 Web 来源，排除已标识测试请求与已撤销来源。标记仅帮助抽样，不证明案例真实、符合某个场景或适合评价。</p>",
            "<p>请确认哪些确为日常互动，可在本次实验中以去标识版本交给固定 GPT 生成和独立语义盲评。原始备份、映射、source IDs 与审阅笔记始终只在本机。LOCAL_ONLY 与一次性 HIGHLY_PRIVATE 授权不在此清单中。</p>",
            "<p>目标：八类各至少四个有效案例。历史原文按当时可知时间截断；不得把之后的纠正提前加入。旧经历尚不足数月或数年的真实历史时，长期 stress 单独使用明确标注的合成案例，不冒充真实使用证据。</p>",
            "<p>类别：闲聊 / 跨天续聊 / 旧经历 / 事实纠正 / Goal / 多人歧义 / stale / 不应 callback。下方保留全部候选，避免只挑投诉或某个架构的优势例。</p>",
            "<p>" + " · ".join(f"<a href='#{c['case_id']}'>{c['case_id']}</a>" for c in cases) + "</p>",
            pre(json.dumps(summary, ensure_ascii=False, indent=2))]
    for case in cases:
        current = source_map[case["current_event_id"]]
        prior = [source_map[e] for e in case["available_prior_event_ids"]]
        rows += [f"<article id='{case['case_id']}'><h2>{case['case_id']} · {esc(case['as_of'])}</h2>",
                 "<p>候选标签（未核实）: " + esc(", ".join(case["sampling_hints_only"])) + "</p>",
                 "<h3>原始当前消息</h3>", pre(current["text"]),
                 "<details><summary>之前最近 16 条符合本次来源范围的原始对话</summary>",
                 *[pre(s["recorded_at"] + " · " + s["role"] + "\n" + s["text"]) for s in prior[-16:]],
                 "</details><details><summary>完整时点来源与 hash（原始回复仅作历史证据，不作标准答案）</summary>",
                 pre(json.dumps({"case": case, "current": current, "prior": prior}, ensure_ascii=False, indent=2)),
                 "</details></article>"]
    rows.append("</html>")
    (output / "owner-review.LOCAL_ONLY.html").write_text("".join(rows), encoding="utf-8")
    manifest = {"schema_version": 1, "policy": policy, "approval_status": "pending",
                "source_identity": "exact owner-qualified IDs, source hashes and source policies in candidate corpus",
                "erasure": "invalidate this whole packet and any downstream run if any included source is revoked or erased; recheck before each export/run",
                "files": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}}
    write_json(output / "artifact-manifest.LOCAL_ONLY.json", manifest)
    return {**summary, "packet_manifest_sha256": sha((output / "artifact-manifest.LOCAL_ONLY.json").read_bytes()),
            "review_path": str(output / "owner-review.LOCAL_ONLY.html")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.database_url, args.expected_database, args.owner_id, args.output)))


if __name__ == "__main__":
    main()
