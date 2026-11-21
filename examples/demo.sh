#!/usr/bin/env bash
# 演示：用虚构团队跑一遍完整的往来（派活 → 汇报 → 越级被拒 → 转达 → 占用资源 → ACK）。
# 用法：examples/demo.sh [信箱目录]   （默认在临时目录中创建，不影响其他信箱）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CMB="$HERE/../bin/cmb"
ROOT="${1:-$(mktemp -d)/demo-mailbox}"

"$CMB" init "$ROOT" --conf "$HERE/demo-team.conf"
c() { "$CMB" "$@" --root "$ROOT"; }

echo; echo "== 1. 总指挥给两位组长派活"
c send --as lead --to @children "本周目标：完成订单页改版。前端组负责页面，后端组负责接口与数据迁移。完成后各自回报。"

echo; echo "== 2. 组长读信、回 ACK，并把任务分派给组员"
c unread --as alpha
c ack L-1 --as alpha "收到，前端组今天开始。"
c send --as alpha --to @children "订单页改版：alpha-1 做页面，alpha-2 补组件，alpha-3 写端到端测试。"
c ack L-1 --as beta "收到。"
c send --as beta --to beta-2 "请准备订单表的数据迁移脚本，执行前先登记占用 db-staging。"

echo; echo "== 3. 执行者越级直接写给总指挥：默认被拒绝"
c send --as alpha-1 --to lead "页面做完了" || echo "（已按规则拒绝，退出码 $?）"

echo; echo "== 4. 正确做法：写给直属上级，由上级转达"
c send --as alpha-1 --to @parent "订单页页面已完成，截图与说明见 docs/order-page.md。"
c forward A1-1 --as alpha --to lead "前端页面部分已完成。"

echo; echo "== 5. 占用共享资源：执行前登记并通知，完成后释放并再通知"
c claim db-staging --as beta-2 --note "订单表数据迁移" --notify @parent
c claim db-staging --as beta-3 || echo "（beta-3 无法同时占用，退出码 $?）"
c release db-staging --as beta-2 --notify @parent "迁移完成，行数核对一致。"

echo; echo "== 6. 总指挥查看收件箱与层级"
c inbox --as lead
c tree

echo; echo "演示信箱位于：$ROOT"
