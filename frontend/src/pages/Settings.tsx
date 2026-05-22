import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router";
import useSWR from "swr";
import { toast } from "sonner";

import { getSettings, updateSettings, type AppSettings } from "@/lib/api";
import { cn } from "@/lib/cn";

export default function SettingsPage() {
  const navigate = useNavigate();
  const { data, error, isLoading, mutate } = useSWR<AppSettings>(
    "settings",
    () => getSettings(),
  );

  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [revealKey, setRevealKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data) {
      setApiKey(data.anthropic_api_key);
      setBaseUrl(data.anthropic_base_url);
      setDirty(false);
    }
  }, [data]);

  const save = async () => {
    setSubmitting(true);
    try {
      await updateSettings({
        anthropic_api_key: apiKey.trim(),
        anthropic_base_url: baseUrl.trim(),
      });
      toast.success("设置已保存");
      setDirty(false);
      await mutate();
    } catch (e) {
      toast.error(`保存失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  const hasKey = (data?.anthropic_api_key ?? "").length > 0;

  return (
    <div className="min-h-screen px-10 pt-3 pb-8">
      <header className="drag-region flex items-center gap-6 pb-5 border-b border-line pl-20">
        <Link to="/" className="font-mono text-[12px] text-smoke hover:text-ivory tracking-[0.05em]">
          ← 返回
        </Link>
        <h1 className="font-serif text-2xl font-semibold tracking-[0.06em] text-ivory leading-none">
          SETTINGS <span className="text-smoke font-normal text-base ml-2">· 应用设置</span>
        </h1>
        <span className="flex-1" />
        {error && (
          <span className="font-mono text-[10px] text-blood-dim tracking-[0.1em]">
            ⚠ 后端未连通
          </span>
        )}
      </header>

      <div className="max-w-[720px] mt-10">
        <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
          ANTHROPIC CREDENTIALS · 接入凭据
          <span className="flex-1 h-px bg-line-soft" />
        </div>

        <div className="bg-bg-card border border-line p-6 space-y-6">
          <Field
            label="API Key"
            hint="走 Novita 中转的 Anthropic 兼容 key (sk_...)"
          >
            <div className="flex gap-2">
              <input
                type={revealKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setDirty(true);
                }}
                placeholder={isLoading ? "loading..." : "sk_..."}
                disabled={isLoading}
                className="flex-1 bg-bg border border-line px-3 py-2 text-ivory font-mono text-[12px]
                           focus:border-candle focus:outline-none disabled:opacity-50"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                onClick={() => setRevealKey((v) => !v)}
                className="px-3 py-2 border border-line text-smoke font-mono text-[10px] tracking-[0.15em] uppercase
                           hover:text-ivory hover:border-smoke transition-colors"
                type="button"
              >
                {revealKey ? "隐藏" : "显示"}
              </button>
            </div>
            {hasKey && !dirty && (
              <p className="font-mono text-[10px] text-candle/70 tracking-[0.05em] mt-2">
                ✓ 已配置 key (尾段 ***{(data?.anthropic_api_key ?? "").slice(-6)})
              </p>
            )}
            {!hasKey && !isLoading && (
              <p className="font-mono text-[10px] text-blood-dim tracking-[0.05em] mt-2">
                ⚠ 尚未配置, 没有 key 无法开启对局
              </p>
            )}
          </Field>

          <Field
            label="Base URL"
            hint="Anthropic 协议兼容端点, 默认走 Novita"
          >
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
                setDirty(true);
              }}
              placeholder="https://api.novita.ai/anthropic"
              disabled={isLoading}
              className="w-full bg-bg border border-line px-3 py-2 text-ivory font-mono text-[12px]
                         focus:border-candle focus:outline-none disabled:opacity-50"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>

          <div className="pt-4 border-t border-line-soft flex items-center gap-4">
            <button
              onClick={save}
              disabled={submitting || isLoading || !dirty}
              className={cn(
                "px-6 py-2.5 font-mono text-[11px] tracking-[0.25em] uppercase transition-colors",
                dirty && !submitting
                  ? "border border-candle text-candle hover:bg-candle hover:text-bg cursor-pointer"
                  : "border border-line text-smoke-dim cursor-not-allowed",
              )}
            >
              {submitting ? "保存中..." : dirty ? "保存设置" : "无更改"}
            </button>
            {hasKey && (
              <button
                onClick={() => navigate("/lobby")}
                className="px-4 py-2.5 border border-line text-smoke font-mono text-[10px] tracking-[0.2em] uppercase
                           hover:text-ivory hover:border-smoke transition-colors cursor-pointer"
              >
                去开一局 →
              </button>
            )}
          </div>
        </div>

        <p className="font-mono text-[10px] text-smoke-dim tracking-[0.05em] mt-6 leading-relaxed">
          凭据存在本地 SQLite (app_settings 表), 不上传任何第三方.
          保存后会立即生效, 无需重启 server.
        </p>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <label className="font-mono text-[11px] text-ivory tracking-[0.1em] uppercase">
          {label}
        </label>
        {hint && (
          <span className="font-mono text-[10px] text-smoke-dim tracking-[0.05em]">
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
