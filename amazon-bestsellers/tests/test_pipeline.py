"""Offline tests: Dify code nodes, generated DSL, Apify setup script and the Apps Script.

    python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "apify_items_sample.json"
TOKEN = "test-token-0123456789"
DIFY_CODE_MAX_STRING_LENGTH = 80000  # Dify default for code node string outputs


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prepare = load(ROOT / "dify" / "prepare.py", "prepare")
merge = load(ROOT / "dify" / "merge.py", "merge")
build_dsl = load(ROOT / "dify" / "build_dsl.py", "build_dsl")
setup_apify = load(ROOT / "apify" / "setup_apify.py", "setup_apify")


def fake_llm(batch):
    """Stand-in for the LLM node: the reply format the prompt asks for, plus typical noise."""
    out = ["ASIN | 子品類 | 品牌 | 賣點", "```"]
    for line in batch.splitlines():
        asin, title = [p.strip() for p in line.split("|", 1)]
        sub = "廚房家電" if "Air Fryer" in title else ("耳機與音訊" if "Earbuds" in title else "不在清單")
        out.append(f"{asin} | {sub} | {title.split()[0]} | 無線、快充")
    out.append("```")
    return "\n".join(out)


def run_dify_pipeline():
    body = FIXTURE.read_text()
    prep = prepare.main(body)
    results = [fake_llm(b) for b in prep["batches"]]
    return prep, merge.main(prep["items_json"], results)


def run_apps_script(requests):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(requests, f)
    out = subprocess.run(["node", str(ROOT / "tests" / "apps_script_harness.js"), f.name],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class DifyCodeNodes(unittest.TestCase):
    def test_prepare_cleans_and_batches(self):
        prep = prepare.main(FIXTURE.read_text())
        items = json.loads(prep["items_json"])
        self.assertEqual(prep["count"], 100)  # duplicate and error rows dropped
        self.assertEqual([len(b.splitlines()) for b in prep["batches"]], [25, 25, 25, 25])
        self.assertEqual({i["category"] for i in items}, {"Electronics", "Appliances"})
        self.assertTrue(all(re.fullmatch(r"B0\d{8}", i["asin"]) for i in items))
        self.assertTrue(all("|" not in i["title"] and "&amp;" not in i["title"] for i in items))
        self.assertLess(len(prep["items_json"]), DIFY_CODE_MAX_STRING_LENGTH)

    def test_merge_classifies_and_tiers(self):
        _, res = run_dify_pipeline()
        rows = json.loads(res["payload"])["rows"]
        self.assertEqual(res["count"], 100)
        self.assertLess(len(res["payload"]), DIFY_CODE_MAX_STRING_LENGTH)
        subs = {r["sub_category"] for r in rows}
        self.assertLessEqual(subs, set(merge.SUBS))  # "不在清單" folded into 其他
        for r in rows:
            p = r["price"]
            want = "未知" if p == "" else ("低" if p < 25 else "中" if p <= 100 else "高")
            self.assertEqual(r["price_tier"], want)
            self.assertRegex(r["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_merge_survives_missing_llm_output(self):
        prep = prepare.main(FIXTURE.read_text())
        rows = json.loads(merge.main(prep["items_json"], [])["payload"])["rows"]
        self.assertEqual({(r["sub_category"], r["brand"]) for r in rows}, {("其他", "未知")})


class DifyDsl(unittest.TestCase):
    def check_graph(self, dsl):
        graph = dsl["workflow"]["graph"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        for e in graph["edges"]:
            self.assertIn(e["source"], nodes)
            self.assertIn(e["target"], nodes)
            self.assertEqual(nodes[e["source"]]["data"]["type"], e["data"]["sourceType"])
            self.assertEqual(nodes[e["target"]]["data"]["type"], e["data"]["targetType"])
        outputs = {
            "1": {"datasetId"}, "2": {"body", "status_code", "headers"},
            "3": set(nodes["3"]["data"]["outputs"]), "4": {"output", "item", "index"},
            "5": {"text"}, "6": set(nodes["6"]["data"]["outputs"]), "7": {"body", "status_code"},
        }
        env = {v["name"] for v in dsl["workflow"]["environment_variables"]}
        text = yaml.dump(graph, allow_unicode=True)
        for nid, var in re.findall(r"\{\{#([\w.]+?)\.(\w+)#\}\}", text):
            if nid == "env":
                self.assertIn(var, env)
            else:
                self.assertIn(var, outputs[nid], f"{nid}.{var}")
        for n in graph["nodes"]:
            for v in n["data"].get("variables", []):
                if "value_selector" in v:
                    nid, var = v["value_selector"]
                    self.assertIn(var, outputs[nid])
        # Embedded code is the tested source, and still runs.
        self.assertEqual(nodes["3"]["data"]["code"], prepare.__loader__.get_data(prepare.__file__).decode())
        ns = {}
        exec(nodes["6"]["data"]["code"], ns)
        self.assertEqual(ns["main"]("[]", [])["count"], 0)

    def test_both_variants(self):
        for kind in ("webhook", "start"):
            with self.subTest(kind=kind):
                dsl = yaml.safe_load(yaml.dump(build_dsl.build(kind), Dumper=build_dsl.LiteralDumper,
                                               allow_unicode=True, sort_keys=False))
                self.check_graph(dsl)

    def test_committed_yaml_is_up_to_date(self):
        for kind in ("webhook", "start"):
            committed = yaml.safe_load((ROOT / "dify" / f"workflow_{kind}.yml").read_text())
            self.assertEqual(committed, build_dsl.build(kind), "run python3 dify/build_dsl.py")


class ApifySetup(unittest.TestCase):
    def run_setup(self, existing, env, args=()):
        calls = []

        def call(self_, method, path, body=None):
            calls.append((method, path, body))
            if method == "GET":
                key = path.split("?")[0]
                return {"items": existing.get(key, [])}
            return {"id": "new-id"}

        with mock.patch.object(setup_apify.Apify, "call", call), \
                mock.patch.dict("os.environ", env, clear=True), \
                mock.patch("sys.stdout"):
            setup_apify.main(list(args))
        return [c for c in calls if c[0] != "GET"]

    def test_fresh_account(self):
        writes = self.run_setup({}, {"APIFY_TOKEN": "x", "DIFY_WEBHOOK_URL": "https://dify/hook"})
        (m1, p1, task), (m2, p2, sched), (m3, p3, hook) = writes
        self.assertEqual((m1, p1), ("POST", "/actor-tasks"))
        self.assertEqual(task["actId"], "junglee~amazon-bestsellers")
        self.assertEqual(task["input"]["maxItemsPerStartUrl"], 50)
        self.assertEqual(len(task["input"]["categoryUrls"]), 2)
        self.assertEqual((sched["cronExpression"], sched["timezone"]), ("0 9 * * 1,4", "Asia/Taipei"))
        self.assertEqual(sched["actions"], [{"type": "RUN_ACTOR_TASK", "actorTaskId": "new-id"}])
        self.assertEqual(hook["eventTypes"], ["ACTOR.RUN.SUCCEEDED"])
        self.assertEqual(hook["condition"], {"actorTaskId": "new-id"})
        self.assertIn('"datasetId": {{resource.defaultDatasetId}}', hook["payloadTemplate"])

    def test_rerun_updates_instead_of_duplicating(self):
        existing = {
            "/actor-tasks": [{"id": "t1", "name": "amazon-3c-bestsellers"}],
            "/schedules": [{"id": "s1", "name": "amazon-3c-bestsellers-mon-thu"}],
            "/actor-tasks/t1/webhooks": [{"id": "w1", "requestUrl": "https://dify/hook"}],
        }
        writes = self.run_setup(existing, {"APIFY_TOKEN": "x", "DIFY_WEBHOOK_URL": "https://dify/hook"})
        self.assertEqual([(m, p) for m, p, _ in writes],
                         [("PUT", "/actor-tasks/t1"), ("PUT", "/schedules/s1"), ("PUT", "/webhooks/w1")])

    def test_no_run_unless_asked(self):
        writes = self.run_setup({}, {"APIFY_TOKEN": "x"})
        self.assertFalse(any(p.endswith("/runs") for _, p, _ in writes))
        writes = self.run_setup({}, {"APIFY_TOKEN": "x"}, ["--run"])
        self.assertEqual(writes[-1][:2], ("POST", "/actor-tasks/new-id/runs"))

    def test_webhook_template_renders_valid_json(self):
        rendered = setup_apify.PAYLOAD_TEMPLATE.replace("{{resource.defaultDatasetId}}", '"abc123"')
        self.assertEqual(json.loads(rendered), {"datasetId": "abc123"})


class AppsScript(unittest.TestCase):
    def payload_for(self, date, rows):
        return {"rows": [dict(r, date=date) for r in rows]}

    def test_end_to_end_two_scrapes(self):
        _, res = run_dify_pipeline()
        day1 = json.loads(res["payload"])["rows"]
        # Second scrape: first two electronics swap places, one item drops out, one enters.
        day2 = [dict(r) for r in day1]
        day2[0]["rank"], day2[1]["rank"] = day1[1]["rank"], day1[0]["rank"]
        day2[-1] = dict(day2[-1], asin="B0NEWITEM1", rank=50)
        out = run_apps_script([
            {"token": "wrong", "body": self.payload_for("2026-10-12", day1)},
            {"token": TOKEN, "body": self.payload_for("2026-10-12", day1)},
            {"token": TOKEN, "body": self.payload_for("2026-10-12", day1)},  # same-day rerun
            {"token": TOKEN, "body": self.payload_for("2026-10-15", day2)},
        ])
        r = out["responses"]
        self.assertEqual(r[0], {"ok": False, "error": "bad token"})
        self.assertEqual(r[1], {"ok": True, "added": 100, "skipped": 0})
        self.assertEqual(r[2], {"ok": True, "added": 0, "skipped": 100})
        self.assertEqual(r[3], {"ok": True, "added": 100, "skipped": 0})

        header, *data = out["sheet"]
        self.assertEqual(len(data), 200)
        col = {h: i for i, h in enumerate(header)}
        first = data[:100]
        self.assertTrue(all(row[col["is_new"]] == "" and row[col["prev_rank"]] == "" for row in first))
        second = {row[col["asin"]]: row for row in data[100:]}
        a0, a1 = day1[0]["asin"], day1[1]["asin"]
        self.assertEqual((second[a0][col["prev_rank"]], second[a0][col["rank_change"]]), (1, -1))
        self.assertEqual((second[a1][col["prev_rank"]], second[a1][col["rank_change"]]), (2, 1))
        self.assertEqual(second["B0NEWITEM1"][col["is_new"]], "新進榜")
        self.assertEqual(sum(1 for row in data[100:] if row[col["is_new"]]), 1)
        self.assertEqual(second[a0][col["url"]], f"https://www.amazon.com/dp/{a0}")


if __name__ == "__main__":
    unittest.main()
