"use client";

import { Sprout, BarChart2, FileText } from "lucide-react";
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

interface Props {
  config: GardenConfig | null;
}

export default function PlantInfoTile({ config }: Props) {
  const plants = config?.plants;
  const growth = config?.growth_assessment;
  const description = config?.description;

  const hasAnyInfo = plants || growth || description;

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

      {plants && (
        <div className="flex items-start gap-2">
          <Sprout className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: "hsl(140, 60%, 50%)" }} />
          <div>
            <p className="text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "hsl(220, 10%, 40%)" }}>Growing</p>
            <p className="text-xs font-medium text-white">{plants}</p>
          </div>
        </div>
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

      {description && (
        <div className="flex items-start gap-2">
          <FileText className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: "hsl(220, 10%, 45%)" }} />
          <div>
            <p className="text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "hsl(220, 10%, 40%)" }}>Description</p>
            <p className="text-[10px] leading-relaxed" style={{ color: "hsl(220, 10%, 55%)" }}>{description}</p>
          </div>
        </div>
      )}
    </div>
  );
}
