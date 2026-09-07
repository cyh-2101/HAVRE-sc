"""Small synthetic multilingual regression probe, not owner-quality acceptance."""

import argparse
import json
import statistics
from pathlib import Path
from time import perf_counter

from companion.memory.embedding import DeterministicEmbeddingProvider
from companion.memory.lexical import overlap
from companion.memory.semantic import LocalSemanticEmbeddingProvider

MEMORIES = [
    "我最近总是睡得很晚", "我不喜欢吃香菜", "帮朋友解决问题让我很开心",
    "我最近在学钢琴", "我每周六去游泳", "我正在准备下周的物理考试",
    "I prefer quiet places when I need to concentrate.", "我喜欢看科幻小说",
]
CASES = [
    ("这几天又熬夜了", 0), ("面里怎么放了这么多香菜", 1),
    ("帮他把电脑修好了，开心", 2), ("今天练琴练了半小时", 3),
    ("这周末还想去泳池", 4), ("物理快考试了我还没复习完", 5),
    ("图书馆太吵了我没法专心", 6), ("想买一本讲宇宙飞船的小说", 7),
    ("你觉得这件蓝色外套怎么样", None), ("西兰花要怎么清洗", None),
    ("帮我算一下三十七乘二十一", None), ("这个包裹到了吗", None),
]


def evaluate(encoder):
    semantic = getattr(encoder, "semantic", False)
    vectors = [encoder.embed(text) for text in MEMORIES]
    rows, durations = [], []
    for query, expected in CASES:
        started = perf_counter()
        vector = encoder.embed(query)
        scores = [sum(a*b for a,b in zip(vector,stored,strict=True)) for stored in vectors]
        admitted = [i for i,s in enumerate(scores) if (s>=.45 or (s>=.20 and overlap(query,MEMORIES[i])>=.25))] if semantic else [i for i,s in enumerate(scores) if s>=.35]
        ranked = sorted(admitted,key=lambda i:-(.70*scores[i]+.15*overlap(query,MEMORIES[i]) if semantic else scores[i]))
        durations.append((perf_counter()-started)*1000)
        rows.append({"query":query,"expected":expected,"selected":ranked,"correct_top_one":bool(ranked and ranked[0]==expected) if expected is not None else not ranked})
    return {"embedding_version":encoder.version.embedding_version_id,
            "correct_top_one":sum(row["correct_top_one"] for row in rows),"cases":len(rows),
            "irrelevant_admissions":sum(sum(i!=row["expected"] for i in row["selected"]) for row in rows),
            "p50_ms":statistics.median(durations),"max_ms":max(durations),"results":rows}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-root',type=Path,default=Path('var/models/memory-minilm-v1'))
    parser.add_argument('--output',type=Path,default=Path('var/benchmarks/semantic_memory_v1.json'))
    args=parser.parse_args()
    result={"fixture_version":"synthetic-multilingual-memory-v1","limit":"12 synthetic cases; no owner-quality claim or database latency measurement",
            "baseline":evaluate(DeterministicEmbeddingProvider()),"semantic":evaluate(LocalSemanticEmbeddingProvider(args.model_root))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:{k:v for k,v in value.items() if k!='results'} for key,value in result.items() if isinstance(value,dict)},ensure_ascii=False))


if __name__=='__main__':
    main()
