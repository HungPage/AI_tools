#!/usr/bin/env python3
"""Build the importable Dify workflow DSL from prepare.py, merge.py and prompt.txt.

Two files are written next to this script:
  workflow_webhook.yml  start node = Webhook Trigger (what Apify calls on schedule)
  workflow_start.yml    start node = plain Start with a datasetId input, for
                        Dify versions/plans without triggers and for manual test runs

Run `python3 build_dsl.py` after editing any of the three source files.
"""
import uuid
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PREPARE = (HERE / "prepare.py").read_text(encoding="utf-8")
MERGE = (HERE / "merge.py").read_text(encoding="utf-8")
PROMPT = (HERE / "prompt.txt").read_text(encoding="utf-8").rstrip("\n")

APIFY_ITEMS_URL = "https://api.apify.com/v2/datasets/{{#1.datasetId#}}/items?clean=true&format=json"
NO_TIMEOUT = {"max_connect_timeout": 0, "max_read_timeout": 0, "max_write_timeout": 0}
RETRY = {"enabled": True, "max_retries": 3, "retry_interval": 1000}


def env(name, value_type, description):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "amazon-bestsellers/env/" + name)), "name": name, "value": "", "value_type": value_type,
            "description": description, "selector": ["env", name]}


def node(node_id, x, data, y=300, **extra):
    n = {"id": node_id, "type": "custom", "data": {"selected": False, "desc": "", **data},
         "position": {"x": x, "y": y}, "positionAbsolute": {"x": x, "y": y},
         "width": 244, "height": 90, "sourcePosition": "right", "targetPosition": "left"}
    n.update(extra)
    return n


def edge(src, src_type, dst, dst_type, iteration=None):
    data = {"sourceType": src_type, "targetType": dst_type, "isInIteration": bool(iteration)}
    if iteration:
        data["iteration_id"] = iteration
    return {"id": f"{src}-source-{dst}-target", "source": src, "sourceHandle": "source",
            "target": dst, "targetHandle": "target", "type": "custom",
            "zIndex": 1002 if iteration else 0, "data": data}


def start_node(kind):
    if kind == "webhook":
        return node("1", 30, {
            "type": "trigger-webhook", "title": "接收通知",
            "method": "POST", "content_type": "application/json",
            "headers": [], "params": [],
            "body": [{"name": "datasetId", "type": "string", "required": True}],
            "status_code": 200, "response_body": "",
        })
    return node("1", 30, {
        "type": "start", "title": "接收通知",
        "variables": [{"variable": "datasetId", "label": "datasetId", "type": "text-input",
                       "required": True, "max_length": 256, "options": []}],
    })


def build(kind):
    start_type = "trigger-webhook" if kind == "webhook" else "start"
    nodes = [
        start_node(kind),
        node("2", 330, {
            "type": "http-request", "title": "取資料", "method": "get", "url": APIFY_ITEMS_URL,
            "authorization": {"type": "no-auth", "config": None},
            "headers": "Authorization:Bearer {{#env.APIFY_TOKEN#}}", "params": "",
            "body": {"type": "none", "data": []}, "timeout": NO_TIMEOUT, "ssl_verify": True,
            "variables": [], "retry_config": RETRY,
        }),
        node("3", 630, {
            "type": "code", "title": "整理", "code_language": "python3", "code": PREPARE,
            "variables": [{"variable": "body", "value_selector": ["2", "body"]}],
            "outputs": {"items_json": {"type": "string", "children": None},
                        "batches": {"type": "array[string]", "children": None},
                        "count": {"type": "number", "children": None}},
        }),
        node("4", 930, {
            "type": "iteration", "title": "分批",
            "iterator_selector": ["3", "batches"], "iterator_input_type": "array[string]",
            "output_selector": ["5", "text"], "output_type": "array[string]",
            "start_node_id": "4start", "is_parallel": False, "parallel_nums": 4,
            "error_handle_mode": "terminated", "width": 400, "height": 200,
        }, width=400, height=200, zIndex=1),
        node("4start", 24, {"type": "iteration-start", "title": "", "isInIteration": True},
             y=68, parentId="4", draggable=False, selectable=False,
             type="custom-iteration-start", width=44, height=48, zIndex=1002),
        node("5", 128, {
            "type": "llm", "title": "分類", "isInIteration": True, "iteration_id": "4",
            "model": {"provider": "langgenius/openai/openai", "name": "gpt-4o-mini",
                      "mode": "chat", "completion_params": {"temperature": 0}},
            "prompt_template": [{"id": "llm-user", "role": "user",
                                 "text": PROMPT.replace("{{ITEMS}}", "{{#4.item#}}")}],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False}, "variables": [],
        }, y=65, parentId="4", extent="parent", zIndex=1002),
        node("6", 1430, {
            "type": "code", "title": "合併", "code_language": "python3", "code": MERGE,
            "variables": [{"variable": "items_json", "value_selector": ["3", "items_json"]},
                          {"variable": "results", "value_selector": ["4", "output"]}],
            "outputs": {"payload": {"type": "string", "children": None},
                        "count": {"type": "number", "children": None}},
        }),
        node("7", 1730, {
            "type": "http-request", "title": "寫入試算表", "method": "post",
            "url": "{{#env.SHEET_URL#}}?token={{#env.SHEET_TOKEN#}}",
            "authorization": {"type": "no-auth", "config": None},
            "headers": "Content-Type:application/json", "params": "",
            "body": {"type": "json", "data": [{"id": "body-payload", "key": "", "type": "text",
                                               "value": "{{#6.payload#}}"}]},
            "timeout": NO_TIMEOUT, "ssl_verify": True, "variables": [], "retry_config": RETRY,
        }),
        node("8", 2030, {
            "type": "end", "title": "結束",
            "outputs": [{"variable": "count", "value_selector": ["6", "count"]},
                        {"variable": "sheet_response", "value_selector": ["7", "body"]}],
        }),
    ]
    edges = [
        edge("1", start_type, "2", "http-request"),
        edge("2", "http-request", "3", "code"),
        edge("3", "code", "4", "iteration"),
        edge("4start", "iteration-start", "5", "llm", iteration="4"),
        edge("4", "iteration", "6", "code"),
        edge("6", "code", "7", "http-request"),
        edge("7", "http-request", "8", "end"),
    ]
    return {
        "app": {"name": "Amazon 熱銷分類", "mode": "workflow", "icon": "🛒",
                "icon_background": "#DFF0F1", "description": "Apify 熱銷榜 → LLM 分類 → Google 試算表",
                "use_icon_as_answer_icon": False},
        "kind": "app",
        "version": "0.3.0",
        "dependencies": [],
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [
                env("APIFY_TOKEN", "secret", "Apify Personal API token"),
                env("SHEET_URL", "string", "Apps Script 網頁應用程式網址（結尾 /exec）"),
                env("SHEET_TOKEN", "secret", "Apps Script 第 2 行的 TOKEN"),
            ],
            "features": {
                "file_upload": {"enabled": False}, "opening_statement": "",
                "retriever_resource": {"enabled": False},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False}, "suggested_questions": [],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False},
            },
            "graph": {"nodes": nodes, "edges": edges,
                      "viewport": {"x": 0, "y": 0, "zoom": 0.6}},
        },
    }


class LiteralDumper(yaml.SafeDumper):
    pass


LiteralDumper.add_representer(
    str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


def main():
    for kind in ("webhook", "start"):
        out = HERE / f"workflow_{kind}.yml"
        out.write_text(yaml.dump(build(kind), Dumper=LiteralDumper, allow_unicode=True,
                                 sort_keys=False, width=1000), encoding="utf-8")
        print("wrote", out.name)


if __name__ == "__main__":
    main()
