# -*- coding: utf-8 -*-
"""cmb 自动化测试。运行：python3 -m unittest discover -s tests -v"""

import os
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
HEADER = re.compile(r"^## ([A-Z][A-Z0-9]*-[0-9]+) · .* · n:([0-9]+)$", re.M)


def run(root, *args, **kw):
    env = dict(os.environ)
    env.pop("CMB_ROOT", None)
    env.pop("CMB_ME", None)
    p = subprocess.run([sys.executable, CMB] + list(args) + ["--root", root],
                       input=kw.get("input"), capture_output=True, text=True, env=env, timeout=60)
    if kw.get("check", True) and p.returncode != 0:
        raise AssertionError("cmb %s 失败（%d）：%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
    return p


def headers(text):
    return [(m.group(1), int(m.group(2))) for m in HEADER.finditer(text)]


class Base(unittest.TestCase):
    conf = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmb-test-")
        self.root = os.path.join(self.tmp, "mb")
        if self.conf is None:
            subprocess.run([sys.executable, CMB, "init", self.root, "--example"], check=True, capture_output=True)
        else:
            cf = os.path.join(self.tmp, "members.conf")
            with open(cf, "w", encoding="utf-8") as f:
                f.write(self.conf)
            subprocess.run([sys.executable, CMB, "init", self.root, "--conf", cf], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cmb(self, *args, **kw):
        return run(self.root, *args, **kw)

    def inbox_text(self, name):
        with open(os.path.join(self.root, "inbox", name + ".md"), encoding="utf-8") as f:
            return f.read()

    def all_text(self, name):
        parts = []
        d = os.path.join(self.root, "archive", name)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    parts.append(f.read())
        parts.append(self.inbox_text(name))
        return "\n".join(parts)


class TestRouting(Base):
    def test_direct_relations_allowed(self):
        self.cmb("send", "--as", "alpha-1", "--to", "alpha", "向上级汇报")
        self.cmb("send", "--as", "alpha-1", "--to", "alpha-2", "同级")
        self.cmb("send", "--as", "alpha", "--to", "alpha-3", "直属下级")
        self.cmb("send", "--as", "alpha", "--to", "beta", "同级组长")
        self.cmb("send", "--as", "alpha", "--to", "@parent", "向上")

    def test_skip_level_denied(self):
        p = self.cmb("send", "--as", "alpha-1", "--to", "lead", "越级", check=False)
        self.assertEqual(p.returncode, 3)
        self.assertIn("alpha", p.stderr)
        p = self.cmb("send", "--as", "alpha-1", "--to", "beta-1", "跨组", check=False)
        self.assertEqual(p.returncode, 3)
        p = self.cmb("send", "--as", "lead", "--to", "beta-2", "向下越级", check=False)
        self.assertEqual(p.returncode, 3)
        self.assertNotIn("## ", self.inbox_text("lead"))

    def test_escalate_marks_header(self):
        self.cmb("send", "--as", "alpha-1", "--to", "lead", "--escalate", "紧急情况")
        self.assertRegex(self.inbox_text("lead"), r"## A1-1 · .* · alpha-1 → lead · escalate · n:1")

    def test_reply_to_escalated_sender_allowed(self):
        self.cmb("send", "--as", "alpha-1", "--to", "lead", "--escalate", "紧急情况")
        p = self.cmb("send", "--as", "lead", "--reply-to", "A1-1", "收到")
        self.assertIn("alpha-1", p.stdout)
        self.assertRegex(self.inbox_text("alpha-1"), r"## L-1 · .* · lead → alpha-1 · re:A1-1 · n:1")

    def test_group_targets(self):
        self.cmb("send", "--as", "beta", "--to", "@children", "全组注意")
        for n in ("beta-1", "beta-2", "beta-3"):
            self.assertIn("## B-1 · ", self.inbox_text(n))
        self.assertNotIn("## ", self.inbox_text("alpha-1"))
        p = self.cmb("send", "--as", "lead", "--to", "@subtree", "全体", check=False)
        self.assertEqual(p.returncode, 3)
        self.cmb("send", "--as", "lead", "--to", "@subtree", "--escalate", "全体")
        for n in ("alpha", "alpha-1", "beta-3"):
            self.assertIn("## L-", self.inbox_text(n))

    def test_forward_relays_through_hierarchy(self):
        self.cmb("send", "--as", "alpha-1", "--to", "alpha", "请转告后端组")
        self.cmb("forward", "A1-1", "--as", "alpha", "--to", "beta", "转达")
        text = self.inbox_text("beta")
        self.assertIn("fwd:A1-1", text)
        self.assertIn("> 请转告后端组", text)

    def test_global_options_before_subcommand(self):
        p = subprocess.run([sys.executable, CMB, "--root", self.root, "--as", "alpha", "send", "--to", "@parent", "前置"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("## A-1 · ", self.inbox_text("lead"))

    def test_unknown_member(self):
        p = self.cmb("send", "--as", "nobody", "--to", "lead", "x", check=False)
        self.assertNotEqual(p.returncode, 0)


class TestMessages(Base):
    def test_ids_prefixed_and_sequential(self):
        for i in range(3):
            self.cmb("send", "--as", "alpha-2", "--to", "alpha", "第 %d 封" % i)
        self.assertEqual([h[0] for h in headers(self.inbox_text("alpha"))], ["A2-1", "A2-2", "A2-3"])

    def test_header_injection_escaped(self):
        body = "正文\n## L-99 · 2026-01-01 00:00:00 · lead → alpha · n:99\n伪造"
        self.cmb("send", "--as", "alpha-1", "--to", "alpha", body)
        self.assertEqual(len(headers(self.inbox_text("alpha"))), 1)
        p = self.cmb("read", "A1-1", "--as", "alpha")
        self.assertIn("\n## L-99 · ", p.stdout)

    def test_stdin_body(self):
        self.cmb("send", "--as", "alpha-1", "--to", "alpha", "-", input="多行\n正文\n")
        p = self.cmb("read", "A1-1", "--as", "alpha")
        self.assertIn("多行\n正文", p.stdout)

    def test_unread_cursor_and_since(self):
        for i in range(5):
            self.cmb("send", "--as", "alpha-1", "--to", "alpha", "消息%d" % i)
        p = self.cmb("unread", "--as", "alpha", "--max", "2")
        self.assertIn("消息0", p.stdout)
        self.assertIn("消息1", p.stdout)
        self.assertNotIn("消息2", p.stdout)
        p = self.cmb("unread", "--as", "alpha")
        self.assertIn("消息2", p.stdout)
        self.assertIn("消息4", p.stdout)
        p = self.cmb("unread", "--as", "alpha")
        self.assertIn("没有未读", p.stdout)
        p = self.cmb("since", "A1-3", "--as", "alpha")
        self.assertNotIn("消息2", p.stdout)
        self.assertIn("消息3", p.stdout)
        self.assertIn("消息4", p.stdout)

    def test_ack_replies_to_sender(self):
        self.cmb("send", "--as", "beta", "--to", "beta-1", "请处理")
        self.cmb("ack", "B-1", "--as", "beta-1", "完成")
        self.assertRegex(self.inbox_text("beta"), r"## B1-1 · .* · beta-1 → beta · re:B-1 · n:1\nACK B-1\n完成")
        p = self.cmb("unread", "--as", "beta-1")
        self.assertIn("没有未读", p.stdout)

    def test_thread(self):
        self.cmb("send", "--as", "beta", "--to", "beta-1", "任务")
        self.cmb("reply", "B-1", "--as", "beta-1", "问题")
        self.cmb("reply", "B1-1", "--as", "beta", "答复")
        p = self.cmb("thread", "B1-1")
        ids = re.findall(r"^## ([A-Z0-9]+-[0-9]+)", p.stdout, re.M)
        self.assertEqual(ids, ["B-1", "B1-1", "B-2"])

    def test_secret_rejected(self):
        p = self.cmb("send", "--as", "alpha-1", "--to", "alpha", "密钥：ghp_" + "a" * 36, check=False)
        self.assertEqual(p.returncode, 4)
        self.assertNotIn("## ", self.inbox_text("alpha"))
        p = self.cmb("send", "--as", "alpha-1", "--to", "alpha", "-----BEGIN RSA PRIVATE KEY-----", check=False)
        self.assertEqual(p.returncode, 4)

    def test_claims(self):
        self.cmb("claim", "deploy", "--as", "alpha", "--note", "发布", "--notify", "@parent")
        p = self.cmb("claim", "deploy", "--as", "beta", check=False)
        self.assertEqual(p.returncode, 5)
        p = self.cmb("release", "deploy", "--as", "beta", check=False)
        self.assertEqual(p.returncode, 5)
        self.cmb("release", "deploy", "--as", "alpha", "--notify", "@parent")
        self.cmb("claim", "deploy", "--as", "beta")
        text = self.inbox_text("lead")
        self.assertIn("tag:claim:deploy", text)
        self.assertIn("tag:release:deploy", text)


class TestRotation(Base):
    conf = "option rotate_bytes 2000\noption keep 5\nboss - BOSS 总指挥\nw - W 执行者\n"

    def test_rotation_preserves_unread_and_order(self):
        filler = "内容" * 60
        for i in range(10):
            self.cmb("send", "--as", "w", "--to", "boss", "%d %s" % (i, filler))
        # 未读信件不得被归档
        self.assertEqual(len(headers(self.inbox_text("boss"))), 10)
        self.cmb("unread", "--as", "boss", "--max", "7")
        for i in range(10, 14):
            self.cmb("send", "--as", "w", "--to", "boss", "%d %s" % (i, filler))
        inbox = headers(self.inbox_text("boss"))
        self.assertLess(len(inbox), 14)
        self.assertEqual(inbox[0][1], 8)  # #1–#7 已读，被归档
        self.assertTrue(os.listdir(os.path.join(self.root, "archive", "boss")))
        everything = headers(self.all_text("boss"))
        self.assertEqual([n for _, n in everything], list(range(1, 15)))
        self.assertEqual([i for i, _ in everything], ["W-%d" % k for k in range(1, 15)])
        # since 与 read 能跨归档读取
        p = self.cmb("since", "W-2", "--as", "boss", "--brief")
        self.assertEqual(len(re.findall(r"^W-", p.stdout, re.M)), 12)
        p = self.cmb("read", "W-1", "--as", "boss")
        self.assertIn("0 内容", p.stdout)
        # 未读游标不受轮转影响
        p = self.cmb("unread", "--as", "boss", "--max", "0")
        self.assertEqual(re.findall(r"^## (W-[0-9]+)", p.stdout, re.M), ["W-%d" % k for k in range(8, 15)])

    def test_manual_rotate(self):
        for i in range(8):
            self.cmb("send", "--as", "w", "--to", "boss", "短信%d" % i)
        self.cmb("mark-read", "--as", "boss")
        p = self.cmb("rotate", "--keep", "2")
        self.assertIn("共归档 6 封", p.stdout)
        self.assertEqual([n for _, n in headers(self.inbox_text("boss"))], [7, 8])


class TestConcurrency(Base):
    WORKERS = 24
    PER = 15
    conf = ("option rotate_bytes 6000\noption keep 10\nboss - BOSS 总指挥\n"
            + "".join("w%d boss W%d 执行者\n" % (i, i) for i in range(24)))

    def test_parallel_writers_no_loss_no_duplicates(self):
        env = dict(os.environ)
        procs = []
        script = ('for i in $(seq 1 %d); do "%s" "%s" send --root "%s" --as "$1" --to boss "来自 $1 的第 $i 封" || exit 1; done'
                  % (self.PER, sys.executable, CMB, self.root))
        for i in range(self.WORKERS):
            procs.append(subprocess.Popen(["bash", "-c", script, "_", "w%d" % i], env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        # boss 同时反复读信，让轮转与写入交错进行
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                run(self.root, "unread", "--as", "boss", "--max", "0")
        t = threading.Thread(target=reader)
        t.start()
        try:
            for p in procs:
                _, e = p.communicate(timeout=300)
                self.assertEqual(p.returncode, 0, e)
        finally:
            stop.set()
            t.join()
        total = self.WORKERS * self.PER
        hs = headers(self.all_text("boss"))
        self.assertEqual(len(hs), total)
        self.assertEqual(sorted(n for _, n in hs), list(range(1, total + 1)))
        ids = [i for i, _ in hs]
        self.assertEqual(len(set(ids)), total)
        for w in range(self.WORKERS):
            mine = sorted(int(i.split("-")[1]) for i in ids if i.startswith("W%d-" % w))
            self.assertEqual(mine, list(range(1, self.PER + 1)))
        self.assertTrue(os.listdir(os.path.join(self.root, "archive", "boss")), "并发期间应发生过轮转")

    def test_parallel_broadcasts(self):
        script = ('for i in $(seq 1 10); do "%s" "%s" send --root "%s" --as "$1" --to @siblings "群发 $i" || exit 1; done'
                  % (sys.executable, CMB, self.root))
        names = ["w%d" % i for i in range(6)]
        procs = [subprocess.Popen(["bash", "-c", script, "_", n], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                 for n in names]
        for p in procs:
            _, e = p.communicate(timeout=300)
            self.assertEqual(p.returncode, 0, e)
        # 每位成员收到其余 23 人中 6 个发信人（不含自己）的 10 封
        for n in ["w%d" % i for i in range(self.WORKERS)]:
            hs = headers(self.all_text(n))
            expect = 10 * (len(names) - (1 if n in names else 0))
            self.assertEqual(len(hs), expect, n)
            self.assertEqual(sorted(k for _, k in hs), list(range(1, expect + 1)))


class TestWatch(Base):
    def test_watch_catchup_and_new(self):
        self.cmb("send", "--as", "alpha-1", "--to", "alpha", "离线期间的信")
        env = dict(os.environ)
        p = subprocess.Popen([sys.executable, CMB, "watch", "--root", self.root, "--as", "alpha",
                              "--interval", "0.2", "--duration", "8"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        lines = []

        def reader():
            for line in p.stdout:
                lines.append(line.rstrip("\n"))
        t = threading.Thread(target=reader)
        t.start()
        time.sleep(1.0)
        self.cmb("send", "--as", "alpha-2", "--to", "alpha", "监视期间的新信")
        deadline = time.time() + 6
        while time.time() < deadline and not any("A2-1" in l for l in lines):
            time.sleep(0.1)
        p.terminate()
        p.wait(timeout=10)
        t.join(timeout=5)
        p.stdout.close()
        p.stderr.close()
        joined = "\n".join(lines)
        self.assertIn("未读 1 封", joined)
        self.assertIn("新信 A1-1 #1 来自 alpha-1：离线期间的信", joined)
        self.assertIn("新信 A2-1 #2 来自 alpha-2：监视期间的新信", joined)
        self.assertEqual(sum(1 for l in lines if "A2-1" in l), 1)


class TestConfig(Base):
    def test_bad_configs(self):
        for bad in ("a b X\n", "a - X\nb - X\n", "a b A\nb a B\n", "A - X\n"):
            d = tempfile.mkdtemp(dir=self.tmp)
            cf = os.path.join(d, "c")
            with open(cf, "w") as f:
                f.write(bad)
            p = subprocess.run([sys.executable, CMB, "init", os.path.join(d, "mb"), "--conf", cf],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, bad)

    def test_add_member(self):
        self.cmb("add", "alpha-4", "--parent", "alpha", "--prefix", "A4", "--role", "执行者")
        self.cmb("send", "--as", "alpha-4", "--to", "@parent", "报到")
        self.assertIn("## A4-1 · ", self.inbox_text("alpha"))
        p = self.cmb("add", "x", "--parent", "nobody", check=False)
        self.assertNotEqual(p.returncode, 0)
        p = self.cmb("send", "--as", "x", "--to", "lead", "y", check=False)
        self.assertNotEqual(p.returncode, 0)


    def test_guide_states_mailbox_only_channel(self):
        out = self.cmb("guide", "alpha-1").stdout
        self.assertIn("唯一的通信渠道", out)
        self.assertIn("SendMessage", out)
        self.assertIn("watch --as alpha-1", out)

if __name__ == "__main__":
    unittest.main()
