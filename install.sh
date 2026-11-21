#!/usr/bin/env bash
# 安装 cmb 命令与 Claude Code skill。
#
#   ./install.sh            把 bin/cmb 链接到 ~/.local/bin/cmb，并把 skill 复制到 ~/.claude/skills/claude-mailbox
#   ./install.sh --uninstall
#
# 可用环境变量改变安装位置：
#   CMB_BIN_DIR         命令目录，默认 ~/.local/bin
#   CLAUDE_SKILLS_DIR   skill 目录，默认 ~/.claude/skills
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${CMB_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
SKILL_DST="$SKILLS_DIR/claude-mailbox"

if [ "${1:-}" = "--uninstall" ]; then
  if [ -L "$BIN_DIR/cmb" ]; then rm "$BIN_DIR/cmb"; echo "已移除 $BIN_DIR/cmb"; fi
  if [ -f "$SKILL_DST/SKILL.md" ]; then rm -r "$SKILL_DST"; echo "已移除 $SKILL_DST"; fi
  exit 0
fi

command -v python3 >/dev/null 2>&1 || { echo "需要 python3（3.9 或更高版本）。" >&2; exit 1; }

mkdir -p "$BIN_DIR"
if [ -e "$BIN_DIR/cmb" ] && [ ! -L "$BIN_DIR/cmb" ]; then
  echo "$BIN_DIR/cmb 已存在且不是本工具的链接，未覆盖。" >&2
  exit 1
fi
ln -sfn "$HERE/bin/cmb" "$BIN_DIR/cmb"
chmod +x "$HERE/bin/cmb"
echo "已链接 $BIN_DIR/cmb → $HERE/bin/cmb"

mkdir -p "$SKILL_DST"
cp "$HERE/skills/claude-mailbox/SKILL.md" "$SKILL_DST/SKILL.md"
echo "已安装 skill → $SKILL_DST/SKILL.md"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "提示：$BIN_DIR 不在 PATH 中，请把它加入 shell 配置，例如：export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
"$BIN_DIR/cmb" version
