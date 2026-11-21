# -*- coding: utf-8 -*-
"""cmb MCP 服务器测试：通过 stdio 以 JSON-RPC 驱动真实的服务器进程。"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CMB = os.path.join(os.path.dirname(HERE), "bin", "cmb")


class Client(object):
    def __init__(self, root, *extra):
        self.p = subprocess.Popen([sys.executable, CMB, "mcp", "--root", root] + list(extra),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.responses = {}
        self.cond = threading.Condition()
        self.notes = queue.Queue()
        self.next_id = 0
        self.lock = threading.Lock()
        self.t = threading.Thread(target=self._read)
        self.t.daemon = True
        self.t.start()
        r = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "0"}})
        self.init = r
        self.notify("notifications/initialized")

    def _read(self):
        for line in self.p.stdout:
            msg = json.loads(line.decode("utf-8"))
            if "id" in msg and "method" not in msg:
                with self.cond:
                    self.responses[msg["id"]] = msg
                    self.cond.notify_all()
            else:
                self.notes.put(msg)

    def notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _write(self, msg):
        with self.lock:
            self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self.p.stdin.flush()

    def request(self, method, params=None, timeout=30):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        with self.cond:
            while rid not in self.responses:
                left = deadline - time.time()
                if left <= 0:
                    raise AssertionError("等待 %s 响应超时" % method)
                self.cond.wait(left)
            return self.responses.pop(rid)

    def call(self, name, timeout=30, **args):
        r = self.request("tools/call", {"name": name, "arguments": args}, timeout=timeout)
        res = r["result"]
        return res["content"][0]["text"], res["isError"]

    def ok(self, name, **args):
        text, is_err = self.call(name, **args)
        if is_err:
            raise AssertionError("%s 失败：%s" % (name, text))
        return text

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self.p.stdout.close()
        self.p.stderr.close()


class McpBase(unittest.TestCase):
    conf = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmb-mcp-")
        self.root = os.path.join(self.tmp, "mb")
        if self.conf:
            cf = os.path.join(self.tmp, "c.conf")
            with open(cf, "w", encoding="utf-8") as f:
                f.write(self.conf)
            args = ["--conf", cf]
        else:
            args = ["--example"]
        subprocess.run([sys.executable, CMB, "init", self.root] + args, check=True, capture_output=True)
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, member=None, *extra):
        c = Client(self.root, *extra)
        self.clients.append(c)
        if member:
            c.ok("join", member=member)
        return c


class TestProtocol(McpBase):
    def test_handshake_and_tools(self):
        c = self.client()
        res = c.init["result"]
        self.assertEqual(res["protocolVersion"], "2025-06-18")
        self.assertIn("claude/channel", res["capabilities"]["experimental"])
        self.assertIn("join", res["instructions"])
        self.assertIn("唯一的通信渠道", res["instructions"])
        tools = {t["name"] for t in c.request("tools/list")["result"]["tools"]}
        for name in ("join", "send", "unread", "wait", "ack", "forward", "claim", "release"):
            self.assertIn(name, tools)
        self.assertEqual(c.request("ping")["result"], {})
        self.assertEqual(c.request("nope")["error"]["code"], -32601)

    def test_unknown_protocol_falls_back(self):
        c = self.client()
        r = c.request("initialize", {"protocolVersion": "2099-01-01", "capabilities": {}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-11-25")

    def test_requires_join(self):
        c = self.client()
        text, is_err = c.call("send", to="lead", body="x")
        self.assertTrue(is_err)
        self.assertIn("join", text)

    def test_no_channel_flag(self):
        c = self.client(None, "--no-channel")
        self.assertNotIn("experimental", c.init["result"]["capabilities"])


class TestMessaging(McpBase):
    def test_send_unread_ack_roundtrip(self):
        boss = self.client("alpha")
        w = self.client("alpha-1")
        self.assertIn("A-1", boss.ok("send", to="@children", body="请完成页面"))
        text = w.ok("unread")
        self.assertIn("请完成页面", text)
        w.ok("ack", id="A-1", body="已开始")
        text = boss.ok("unread")
        self.assertIn("ACK A-1", text)
        self.assertIn("已开始", text)

    def test_routing_and_secret_errors(self):
        w = self.client("alpha-1")
        text, is_err = w.call("send", to="lead", body="越级")
        self.assertTrue(is_err)
        self.assertIn("转达", text)
        self.assertIn("已投递", w.ok("send", to="lead", body="紧急", escalate=True))
        text, is_err = w.call("send", to="alpha", body="key: sk-" + "x" * 30)
        self.assertTrue(is_err)
        text, is_err = w.call("read", ids=["--root=/etc"])
        self.assertTrue(is_err)

    def test_wait_returns_quickly(self):
        lead = self.client("lead")
        alpha = self.client("alpha")
        res = {}

        def waiter():
            t0 = time.time()
            res["text"] = lead.ok("wait", timeout_seconds=20)
            res["t"] = time.time()
            res["t0"] = t0
        th = threading.Thread(target=waiter)
        th.start()
        time.sleep(0.5)
        sent = time.time()
        alpha.ok("send", to="@parent", body="进度汇报")
        th.join(timeout=25)
        self.assertIn("进度汇报", res["text"])
        latency = res["t"] - sent
        self.assertLess(latency, 1.5, "wait 延迟 %.2f 秒" % latency)
        self.assertIn("没有未读", lead.ok("unread"))

    def test_wait_timeout_and_concurrent_calls(self):
        lead = self.client("lead")
        t0 = time.time()
        text = lead.ok("wait", timeout_seconds=1)
        self.assertIn("没有新信", text)
        self.assertLess(time.time() - t0, 3)
        # wait 进行中，同一服务器的其他调用不被阻塞
        th = threading.Thread(target=lambda: lead.call("wait", timeout_seconds=5, timeout=15))
        th.start()
        time.sleep(0.3)
        t1 = time.time()
        lead.ok("tree")
        self.assertLess(time.time() - t1, 2)
        th.join()

    def test_channel_push(self):
        lead = self.client("lead")
        beta = self.client("beta")
        beta.ok("send", to="@parent", body="推送测试")
        deadline = time.time() + 5
        note = None
        while time.time() < deadline:
            try:
                m = lead.notes.get(timeout=0.5)
            except queue.Empty:
                continue
            if m.get("method") == "notifications/claude/channel":
                note = m
                break
        self.assertIsNotNone(note, "未收到通道推送")
        meta = note["params"]["meta"]
        self.assertEqual(meta["sender"], "beta")
        self.assertEqual(meta["msg_id"], "B-1")
        self.assertTrue(all(re.match(r"^[A-Za-z0-9_]+$", k) for k in meta))
        self.assertIn("推送测试", note["params"]["content"])

    def test_claim_release_and_forward(self):
        a1 = self.client("alpha-1")
        alpha = self.client("alpha")
        lead = self.client("lead")
        alpha.ok("claim", resource="deploy", note="发布", notify="@parent")
        text, is_err = a1.call("claim", resource="deploy")
        self.assertTrue(is_err)
        alpha.ok("release", resource="deploy", notify=["@parent"], body="完成")
        a1.ok("send", to="@parent", body="请转告总指挥")
        alpha.ok("forward", id="A1-1", to="lead", note="转达")
        text = lead.ok("unread")
        self.assertIn("claim:deploy", text)
        self.assertIn("release:deploy", text)
        self.assertIn("> 请转告总指挥", text)


class TestScale(McpBase):
    N = 30
    PER = 20
    conf = "boss - BOSS 总指挥\n" + "".join("w%d boss W%d 执行者\n" % (i, i) for i in range(30))

    def test_many_servers_concurrent(self):
        boss = self.client("boss")
        workers = [self.client("w%d" % i) for i in range(self.N)]
        errors = []

        def run(c, i):
            try:
                for k in range(self.PER):
                    c.ok("send", to="@parent", body="w%d 第 %d 封" % (i, k))
            except Exception as e:  # noqa
                errors.append(e)
        t0 = time.time()
        ths = [threading.Thread(target=run, args=(c, i)) for i, c in enumerate(workers)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        elapsed = time.time() - t0
        self.assertEqual(errors, [])
        total = self.N * self.PER
        text = boss.ok("unread", max=0)
        ids = re.findall(r"^## (W[0-9]+-[0-9]+) ", text, re.M)
        self.assertEqual(len(ids), total)
        self.assertEqual(len(set(ids)), total)
        sys.stderr.write("\n  %d 个 MCP 服务器并发发出 %d 封信，用时 %.2f 秒（%.0f 封/秒）\n"
                         % (self.N, total, elapsed, total / elapsed))

        # 广播：boss 一次发给 30 人，每人的 wait 都能拿到
        res = [None] * self.N

        def w(i):
            res[i] = workers[i].ok("wait", timeout_seconds=15)
        ths = [threading.Thread(target=w, args=(i,)) for i in range(self.N)]
        for t in ths:
            t.start()
        time.sleep(0.5)
        boss.ok("send", to="@children", body="全体注意")
        for t in ths:
            t.join(timeout=20)
        self.assertTrue(all(r and "全体注意" in r for r in res))


if __name__ == "__main__":
    unittest.main()
