#!/usr/bin/env bash
# VOC 工作台 + VOC Agent 自检：每一项打 ✅ / ⚠️ / ❌，❌ 后面写怎么修。不打印任何密钥。
# 用法：bash scripts/doctor.sh [profile名，默认 voc]
P="${1:-voc}"
PD="$HOME/.hermes/profiles/$P"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ok=0; bad=0
pass(){ echo "✅ $1"; ok=$((ok+1)); }
warn(){ echo "⚠️  $1"; }
fail(){ echo "❌ $1"; echo "   → $2"; bad=$((bad+1)); }
has_key(){ [ -f "$1" ] && grep -qE "^$2=.+" "$1"; }

echo "== 基础环境"
command -v python3 >/dev/null && pass "python3 $(python3 -V 2>&1 | cut -d' ' -f2)" || fail "没有 python3" "装 Python 3.9 以上"
command -v git >/dev/null && pass "git" || fail "没有 git" "装 git"
if command -v hermes >/dev/null; then pass "Hermes：$(hermes --version 2>/dev/null | head -1)"; else fail "没有 Hermes" "按 DEPLOY.md 第 2 步安装"; fi

echo "== VOC Agent（Hermes profile：$P）"
[ -d "$PD" ] && pass "profile 已建：$PD" || fail "profile 不存在" "hermes profile install $REPO/agent --alias -y"
[ -f "$PD/SOUL.md" ] && pass "岗位规则 SOUL.md 在" || fail "缺 SOUL.md" "重新跑 profile install"
if [ -f "$PD/SOUL.md" ] && grep -q "{{" "$PD/SOUL.md"; then fail "SOUL.md 里还有没填的 {{占位符}}" "按 DEPLOY.md 第 4 步填好，或删掉不用的飞书两节"; fi
[ -f "$PD/skills/ecommerce/voc-agent/SKILL.md" ] && pass "voc-agent 技能已装进 profile" || fail "技能没装进 profile" "bash $REPO/install.sh --repo $REPO --dest $PD/skills/ecommerce"
has_key "$PD/.env" API_SERVER_KEY && pass "profile 的 API_SERVER_KEY 已设" || fail "profile 没设 API_SERVER_KEY" "在 $PD/.env 里加 API_SERVER_KEY=<随机串>"
has_key "$HOME/.hermes/.env" API_SERVER_KEY && pass "网关 API 已开（~/.hermes/.env）" || fail "网关 API 没开" "在 ~/.hermes/.env 里加 API_SERVER_KEY=<随机串> 和 API_SERVER_HOST=127.0.0.1"
grep -q "sellersprite" "$PD/config.yaml" 2>/dev/null && pass "卖家精灵 MCP 已配置" || fail "没配卖家精灵 MCP" "把 agent/mcp.example.yaml 合并进 $PD/config.yaml"

echo "== 运行状态"
if curl -s -m 3 http://127.0.0.1:8642/v1/health >/dev/null 2>&1; then pass "Hermes 网关在线（127.0.0.1:8642）"; else fail "Hermes 网关没在跑" "hermes gateway install && hermes gateway start（或前台：hermes gateway run）"; fi
H=$(curl -s -m 3 http://127.0.0.1:8790/api/health 2>/dev/null)
if [ -n "$H" ]; then
  echo "$H" | grep -q '"hermes": true' && pass "工作台在线，并连上了 VOC Agent（127.0.0.1:8790）" || fail "工作台在线，但连不上 Agent" "检查 profile 的 API_SERVER_KEY 和网关"
else
  warn "工作台没在跑（需要时：python3 $REPO/workbench/serve.py）"
fi

echo "== 飞书（可选）"
if has_key "$PD/.env" FEISHU_APP_ID; then
  pass "飞书机器人已配置"
  LC=$(command -v lark-cli || echo "$HOME/.hermes/node/bin/lark-cli")
  [ -x "$LC" ] && pass "lark-cli：$LC" || warn "没找到 lark-cli（读写飞书表要用）"
else
  warn "没接飞书：工作台和 Agent 照样能用，只是没有群聊和多维表格"
fi

echo
echo "通过 $ok 项，失败 $bad 项"
[ "$bad" -eq 0 ]
