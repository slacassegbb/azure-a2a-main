"use client";

import { Sprout, BarChart2, Leaf, Calendar, FlaskConical, Droplets, Target, BookOpen } from "lucide-react";
import { GardenConfig, GrowthAssessment } from "@/lib/garden/types";

const STAGE_LABELS: Record<GrowthAssessment["stage"], string> = {
  empty: "Empty",
  germination: "Germination",
  seedling: "Seedling",
  vegetative: "Vegetative",
  flowering: "Flowering",
  harvest: "Ready to Harvest",
};

const STAGE_COLOR: Record<GrowthAssessment["stage"], string> = {
  empty: "hsl(220, 10%, 45%)",
  germination: "hsl(185, 80%, 55%)",
  seedling: "hsl(120, 60%, 50%)",
  vegetative: "hsl(140, 65%, 45%)",
  flowering: "hsl(280, 65%, 60%)",
  harvest: "hsl(48, 95%, 55%)",
};

// Internal keys that shouldn't be shown to the user
const HIDDEN_KEYS = new Set(["pending_question_cleared"]);

// Human-readable labels + icons for known note keys
const NOTE_META: Record<string, { label: string; icon: React.ElementType }> = {
  seeds:        { label: "Seeds / Plants", icon: Leaf },
  plants:       { label: "Seeds / Plants", icon: Leaf },
  soil_mix:     { label: "Soil Mix",       icon: FlaskConical },
  pot_size:     { label: "Pot Size",       icon: Droplets },
  grow_goal:    { label: "Goal",           icon: Target },
  experience:   { label: "Experience",     icon: BookOpen },
  location:     { label: "Location",       icon: BookOpen },
  nutrients:    { label: "Nutrients",      icon: FlaskConical },
  planted_at:   { label: "Planted",        icon: Calendar },
  planting_date:{ label: "Planted",        icon: Calendar },
};

function formatNoteKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

interface Props {
  config: GardenConfig | null;
}

export default function PlantInfoTile({ config }: Props) {
  const growth = config?.growth_assessment;
  const notes = config?.notes ?? {};

  // Filter out hidden internal keys
  const visibleNotes = Object.entries(notes).filter(([k]) => !HIDDEN_KEYS.has(k));
  const hasAnyInfo = visibleNotes.length > 0 || growth;

  return (
    <div
      className="rounded-xl p-3 space-y-2.5"
      style={{ background: "hsl(220, 18%, 13%)", border: "1px solid hsl(220, 15%, 20%)" }}
    >
      <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "hsl(220, 10%, 45%)" }}>
        Agent Knowledge
      </p>

      {!hasAnyInfo && (
        <p className="text-[11px]" style={{ color: "hsl(220, 10%, 40%)" }}>
          No info yet — agent will learn as it monitors the garden.
        </p>
      )}

      {growth && growth.stage !== "empty" && (
        <div className="flex items-start gap-2">
          <BarChart2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: STAGE_COLOR[growth.stage] }} />
          <div className="flex-1 min-w-0">
            <p className="text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "hsl(220, 10%, 40%)" }}>Growth Stage</p>
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium" style={{ color: STAGE_COLOR[growth.stage] }}>
                {STAGE_LABELS[growth.stage]}
              </p>
              {growth.height_pct > 0 && (
                <span className="text-[10px]" style={{ color: "hsl(220, 10%, 45%)" }}>
                  {growth.height_pct}% mature
                </span>
              )}
            </div>
            {growth.notes && (
              <p className="text-[10px] mt-0.5 leading-relaxed" style={{ color: "hsl(220, 10%, 50%)" }}>
                {growth.notes}
              </p>
            )}
          </div>
        </div>
      )}

      {visibleNotes.map(([key, value]) => {
        const meta = NOTE_META[key];
        const Icon = meta?.icon ?? Sprout;
        const label = meta?.label ?? formatNoteKey(key);
        return (
          <div key={key} className="flex items-start gap-2">
            <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: "hsl(152, 60%, 45%)" }} />
            <div>
              <p className="text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "hsl(220, 10%, 40%)" }}>{label}</p>
              <p className="text-xs leading-relaxed" style={{ color: "hsl(220, 10%, 70%)" }}>{value}</p>
            </div>
          </div>
        );
      })}

      {config?.updated_at && (
        <p className="text-[9px]" style={{ color: "hsl(220, 10%, 30%)" }}>
          Last updated {new Date(config.updated_at).toLocaleDateString()}
        </p>
      )}
    </div>
  );
}
