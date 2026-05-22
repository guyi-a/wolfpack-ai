import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import useSWR from "swr";
import { toast } from "sonner";

import { cn } from "@/lib/cn";
import { createGame, getDefaultConfig, getModels, startGame } from "@/lib/api";
import { MOCK_DEFAULT_CONFIG, MOCK_MODELS, ROLE_LABEL } from "@/lib/mock";
import type { Role } from "@/lib/types";

interface RowState {
  player_id: string;
  role: Role;
  model: string;
}

const ROLE_OPTIONS: Role[] = ["wolf", "seer", "witch", "villager"];

export default function LobbyPage() {
  const navigate = useNavigate();
  const { data: modelsData, error: modelsErr } = useSWR("models", () => getModels());
  const { data: defaultCfg, error: defaultErr } = useSWR("default-config", () => getDefaultConfig());

  const models = modelsData?.models ?? (modelsErr ? MOCK_MODELS : MOCK_MODELS);
  const initial = defaultCfg ?? (defaultErr ? MOCK_DEFAULT_CONFIG : MOCK_DEFAULT_CONFIG);

  const [godModel, setGodModel] = useState(initial.god_model);
  const [rows, setRows] = useState<RowState[]>(initial.players);
  const [maxRounds, setMaxRounds] = useState(8);
  const [submitting, setSubmitting] = useState(false);

  // 后端的 default-config 拉回来后同步
  useEffect(() => {
    if (defaultCfg) {
      setGodModel(defaultCfg.god_model);
      setRows(defaultCfg.players);
    }
  }, [defaultCfg]);

  const updateRow = (i: number, patch: Partial<RowState>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const loadDefault = () => {
    if (defaultCfg) {
      setGodModel(defaultCfg.god_model);
      setRows(defaultCfg.players);
    } else {
      setGodModel(MOCK_DEFAULT_CONFIG.god_model);
      setRows(MOCK_DEFAULT_CONFIG.players);
    }
  };

  const start = async () => {
    setSubmitting(true);
    try {
      const game = await createGame({ god_model: godModel, players: rows });
      await startGame(game.id, maxRounds);
      toast.success(`Game #${game.id} 已启动`);
      navigate(`/games/${game.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 后端缺 key 时回 400 + 含 "ANTHROPIC_API_KEY"; 提示并跳设置页
      if (msg.includes("ANTHROPIC_API_KEY") || msg.includes("API_KEY")) {
        toast.error("尚未配置 API key, 即将前往设置页");
        setTimeout(() => navigate("/settings"), 800);
      } else {
        toast.error(`开局失败: ${msg}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const counts = rows.reduce<Record<Role, number>>(
    (acc, r) => {
      acc[r.role] = (acc[r.role] ?? 0) + 1;
      return acc;
    },
    { wolf: 0, seer: 0, witch: 0, villager: 0 },
  );
  const valid = counts.wolf >= 1 && counts.seer >= 1;

  return (
    <div className="min-h-screen px-10 pt-3 pb-8">
      <header className="drag-region flex items-center gap-6 pb-5 border-b border-line pl-20">
        <Link to="/" className="font-mono text-[12px] text-smoke hover:text-ivory tracking-[0.05em]">
          ← 返回
        </Link>
        <h1 className="font-serif text-2xl font-semibold tracking-[0.06em] text-ivory leading-none">
          NEW GAME <span className="text-smoke font-normal text-base ml-2">· 6 人板</span>
        </h1>
        <span className="flex-1" />
        {(modelsErr || defaultErr) && (
          <span className="font-mono text-[10px] text-blood-dim tracking-[0.1em] mr-4">
            ⚠ 后端未连通, 用 mock 默认
          </span>
        )}
        <button
          onClick={loadDefault}
          className="h-9 inline-flex items-center px-3 border border-line text-smoke font-mono text-[10px] tracking-[0.2em] uppercase
                     hover:text-ivory hover:border-smoke transition-colors"
        >
          载入默认
        </button>
      </header>

      <div className="grid grid-cols-[1fr_320px] gap-12 mt-10 max-w-[1400px]">
        <section>
          <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
            ROLES & MODELS · 角色 / 模型
            <span className="flex-1 h-px bg-line-soft" />
          </div>

          <div className="border border-line">
            {rows.map((r, i) => (
              <div
                key={i}
                className={cn(
                  "grid grid-cols-[60px_1fr_2fr] gap-4 items-center px-5 py-3.5",
                  i !== 0 && "border-t border-line-soft",
                )}
              >
                <div className="font-serif text-2xl font-light text-ivory tabular">
                  {r.player_id}<span className="text-smoke text-base ml-1">号</span>
                </div>
                <RoleSelect value={r.role} onChange={(v) => updateRow(i, { role: v })} />
                <ModelSelect value={r.model} options={models} onChange={(v) => updateRow(i, { model: v })} />
              </div>
            ))}

            <div className="grid grid-cols-[60px_1fr_2fr] gap-4 items-center px-5 py-3.5 border-t border-line bg-bg-card/40">
              <div className="font-serif text-base text-candle tracking-[0.1em] tabular">GOD</div>
              <div className="font-mono text-[10px] text-smoke tracking-[0.15em] uppercase">上帝 · 主持人</div>
              <ModelSelect value={godModel} options={models} onChange={setGodModel} />
            </div>
          </div>

          <div className="mt-6 font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-3">
            RULES · 规则
            <span className="flex-1 h-px bg-line-soft" />
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-3">
              <span className="font-mono text-[11px] text-smoke tracking-[0.05em]">最大轮数</span>
              <input
                type="number"
                value={maxRounds}
                min={1}
                max={20}
                onChange={(e) => setMaxRounds(Number(e.target.value) || 8)}
                className="w-20 bg-bg-card border border-line px-3 py-1.5 text-ivory font-mono text-[12px] tabular text-center
                           focus:border-candle focus:outline-none"
              />
            </label>
            <span className="font-mono text-[10px] text-smoke-dim tracking-[0.1em]">
              暂时不做: 守卫 / 猎人 / 警长
            </span>
          </div>

          <div className="mt-10 flex items-center gap-4">
            <button
              onClick={start}
              disabled={!valid || submitting}
              className={cn(
                "px-8 py-3 font-mono text-[11px] tracking-[0.25em] uppercase transition-colors",
                valid && !submitting
                  ? "border border-candle text-candle hover:bg-candle hover:text-bg cursor-pointer"
                  : "border border-line text-smoke-dim cursor-not-allowed",
              )}
            >
              {submitting ? "提交中..." : "开始对局 →"}
            </button>
            {!valid && <span className="font-mono text-[10px] text-blood">至少需要 1 狼 + 1 预言家</span>}
          </div>
        </section>

        <aside>
          <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
            SUMMARY
            <span className="flex-1 h-px bg-line-soft" />
          </div>

          <div className="bg-bg-card border border-line p-5 space-y-4">
            <div>
              <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-smoke mb-2">阵营</div>
              <div className="grid grid-cols-2 gap-2">
                <RoleStat role="wolf" count={counts.wolf} />
                <RoleStat role="seer" count={counts.seer} />
                <RoleStat role="witch" count={counts.witch} />
                <RoleStat role="villager" count={counts.villager} />
              </div>
            </div>

            <div>
              <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-smoke mb-2">模型分布</div>
              <div className="space-y-1.5">
                {Object.entries(
                  rows.reduce<Record<string, number>>((acc, r) => {
                    acc[r.model] = (acc[r.model] ?? 0) + 1;
                    return acc;
                  }, {}),
                ).map(([m, n]) => (
                  <div key={m} className="flex items-center gap-2 font-mono text-[10px]">
                    <span className="text-ivory truncate flex-1">{m.split("/").pop()}</span>
                    <span className="text-smoke tabular">×{n}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="pt-2 border-t border-line-soft font-mono text-[9px] tracking-[0.15em] uppercase text-smoke-dim">
              GOD · {godModel.split("/").pop()}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function RoleSelect({ value, onChange }: { value: Role; onChange: (v: Role) => void }) {
  return (
    <div className="flex items-center gap-2 bg-bg-card border border-line px-3 py-1.5">
      <span className="text-base">{ROLE_LABEL[value].icon}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Role)}
        className="flex-1 bg-transparent font-mono text-[11px] tracking-[0.1em] uppercase text-ivory
                   focus:outline-none cursor-pointer appearance-none"
      >
        {ROLE_OPTIONS.map((r) => (
          <option key={r} value={r} className="bg-bg-card text-ivory">
            {ROLE_LABEL[r].upper} · {ROLE_LABEL[r].cn}
          </option>
        ))}
      </select>
    </div>
  );
}

function ModelSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 bg-bg-card border border-line px-3 py-1.5">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 bg-transparent font-mono text-[11px] text-ivory
                   focus:outline-none cursor-pointer appearance-none"
      >
        {options.map((m) => (
          <option key={m} value={m} className="bg-bg-card text-ivory">
            {m}
          </option>
        ))}
      </select>
    </div>
  );
}

function RoleStat({ role, count }: { role: Role; count: number }) {
  const label = ROLE_LABEL[role];
  return (
    <div className="flex items-center gap-2 bg-bg/60 border border-line-soft px-2.5 py-1.5">
      <span className="text-sm">{label.icon}</span>
      <span className="font-mono text-[10px] text-smoke tracking-[0.05em] flex-1">{label.cn}</span>
      <span className="font-serif text-base text-ivory tabular">{count}</span>
    </div>
  );
}
