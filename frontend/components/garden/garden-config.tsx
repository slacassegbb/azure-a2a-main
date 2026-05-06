"use client";

import { useState, useEffect } from "react";
import { Settings, X, Check, Loader2, Trash2 } from "lucide-react";

export default function GardenConfig() {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    if (open && !loaded) {
      fetch("/api/garden/config")
        .then(r => r.json())
        .then(d => { setDescription(d.description || ""); setLoaded(true); })
        .catch(() => setLoaded(true));
    }
  }, [open, loaded]);

  const save = async () => {
    setSaving(true);
    try {
      await fetch("/api/garden/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description }),
      });
      setSaved(true);
      setTimeout(() => { setSaved(false); setOpen(false); }, 1000);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  };

  const resetGarden = async () => {
    setResetting(true);
    try {
      await fetch("/api/garden/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reset_garden" }),
      });
      setDescription("");
      setLoaded(false);
      setConfirmReset(false);
      setOpen(false);
    } catch { /* ignore */ }
    finally { setResetting(false); }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="w-7 h-7 xl:w-8 xl:h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-white/10"
        style={{ background: "hsl(220, 15%, 16%)", border: "1px solid hsl(220, 15%, 20%)" }}
        title="Garden Settings"
      >
        <Settings className="w-3.5 h-3.5 xl:w-4 xl:h-4" style={{ color: "hsl(220, 10%, 55%)" }} />
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-[200]" style={{ background: "rgba(0,0,0,0.6)" }} onClick={() => setOpen(false)} />

          {/* Modal — positioned below header */}
          <div
            className="fixed left-1/2 -translate-x-1/2 z-[201] w-[90vw] max-w-lg rounded-xl p-4 space-y-3"
            style={{ top: "80px", background: "hsl(220, 18%, 13%)", border: "1px solid hsl(220, 15%, 22%)", boxShadow: "0 20px 60px rgba(0,0,0,0.5)" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white">Garden Configuration</h2>
                <p className="text-[10px] mt-0.5" style={{ color: "hsl(220, 10%, 45%)" }}>
                  The AI agent will use this for every decision.
                </p>
              </div>
              <button onClick={() => setOpen(false)} className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10">
                <X className="w-4 h-4" style={{ color: "hsl(220, 10%, 50%)" }} />
              </button>
            </div>

            {/* Textarea */}
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder={"Describe your garden:\n• What plants do you have?\n• Growth stage?\n• Growing medium?\n• Any special notes?"}
              rows={5}
              className="w-full rounded-lg p-3 text-sm leading-relaxed resize-none outline-none placeholder:text-[hsl(220,10%,30%)]"
              style={{
                background: "hsl(220, 20%, 8%)",
                border: "1px solid hsl(220, 15%, 20%)",
                color: "hsl(220, 10%, 80%)",
              }}
            />

            {/* Buttons */}
            <div className="flex justify-between items-center">
              {/* Reset — left side */}
              <div>
                {!confirmReset ? (
                  <button
                    onClick={() => setConfirmReset(true)}
                    className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[10px] font-medium transition-colors hover:bg-red-500/10"
                    style={{ color: "hsl(0, 70%, 55%)" }}
                  >
                    <Trash2 className="w-3 h-3" />
                    New Garden
                  </button>
                ) : (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={resetGarden}
                      disabled={resetting}
                      className="px-2 py-1.5 rounded-lg text-[10px] font-medium"
                      style={{ background: "hsl(0, 70%, 50%, 0.2)", border: "1px solid hsl(0, 70%, 50%, 0.4)", color: "hsl(0, 70%, 60%)" }}
                    >
                      {resetting ? <Loader2 className="w-3 h-3 animate-spin" /> : "Yes, reset all"}
                    </button>
                    <button
                      onClick={() => setConfirmReset(false)}
                      className="px-2 py-1.5 rounded-lg text-[10px] font-medium"
                      style={{ color: "hsl(220, 10%, 55%)" }}
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>

              {/* Save/Cancel — right side */}
              <div className="flex gap-2">
                <button
                  onClick={() => setOpen(false)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium"
                  style={{ color: "hsl(220, 10%, 55%)" }}
                >
                  Cancel
                </button>
                <button
                  onClick={save}
                  disabled={saving}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95"
                  style={{
                    background: saved ? "hsl(152, 75%, 50%, 0.3)" : "hsl(152, 75%, 50%, 0.15)",
                    border: `1px solid ${saved ? "hsl(152, 75%, 50%)" : "hsl(152, 75%, 50%, 0.3)"}`,
                    color: "hsl(152, 75%, 55%)",
                  }}
                >
                  {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : saved ? <><Check className="w-3 h-3 inline mr-1" />Saved</> : "Save"}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
