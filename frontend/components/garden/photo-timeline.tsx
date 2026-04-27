"use client";

import { useState } from "react";
import { Camera, X, ChevronLeft, ChevronRight } from "lucide-react";
import { GardenPhoto } from "@/lib/garden/types";

interface PhotoTimelineProps {
  photos: GardenPhoto[];
}

function formatPhotoDate(name: string): string {
  // Parse YYYY-MM-DD_HH-MM-SS.jpg
  const match = name.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  if (!match) return name;
  const [, y, mo, d, h, mi] = match;
  const date = new Date(`${y}-${mo}-${d}T${h}:${mi}:00`);
  return date.toLocaleDateString([], { month: "short", day: "numeric" }) + " " +
    date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

export default function PhotoTimeline({ photos }: PhotoTimelineProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  if (photos.length === 0) {
    return (
      <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <div className="flex items-center gap-2 mb-3">
          <Camera className="w-4 h-4" style={{ color: "hsl(220, 10%, 50%)" }} />
          <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>Photo History</span>
        </div>
        <span className="text-xs" style={{ color: "hsl(220, 10%, 35%)" }}>No photos available</span>
      </div>
    );
  }

  return (
    <>
      <div className="rounded-xl p-4" style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}>
        <div className="flex items-center gap-2 mb-3">
          <Camera className="w-4 h-4" style={{ color: "hsl(152, 75%, 50%)" }} />
          <span className="text-[11px] uppercase tracking-wider font-medium" style={{ color: "hsl(220, 10%, 50%)" }}>
            Photo History
          </span>
          <span className="text-[10px] ml-auto" style={{ color: "hsl(220, 10%, 40%)" }}>
            {photos.length} photos
          </span>
        </div>

        <div className="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1 scrollbar-thin scrollbar-thumb-white/10">
          {photos.map((photo, i) => (
            <div
              key={photo.name}
              className="shrink-0 cursor-pointer group"
              onClick={() => setSelectedIndex(i)}
            >
              <div className="w-28 h-20 rounded-lg overflow-hidden border transition-all group-hover:border-white/30 group-hover:scale-[1.03]"
                style={{ borderColor: "hsl(220, 15%, 20%)" }}>
                <img
                  src={photo.url}
                  alt={photo.name}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>
              <p className="text-[9px] mt-1 text-center truncate w-28" style={{ color: "hsl(220, 10%, 45%)" }}>
                {formatPhotoDate(photo.name)}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Lightbox */}
      {selectedIndex !== null && photos[selectedIndex] && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center"
          style={{ background: "hsla(0, 0%, 0%, 0.92)" }}
          onClick={() => setSelectedIndex(null)}
        >
          <button className="absolute top-4 right-4 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors z-10">
            <X className="w-5 h-5 text-white" />
          </button>

          {selectedIndex > 0 && (
            <button
              className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors z-10"
              onClick={(e) => { e.stopPropagation(); setSelectedIndex(selectedIndex - 1); }}
            >
              <ChevronLeft className="w-5 h-5 text-white" />
            </button>
          )}

          {selectedIndex < photos.length - 1 && (
            <button
              className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors z-10"
              onClick={(e) => { e.stopPropagation(); setSelectedIndex(selectedIndex + 1); }}
            >
              <ChevronRight className="w-5 h-5 text-white" />
            </button>
          )}

          <div className="max-w-[90vw] max-h-[85vh] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <img
              src={photos[selectedIndex].url}
              alt={photos[selectedIndex].name}
              className="max-w-full max-h-[80vh] rounded-lg object-contain"
            />
            <p className="text-sm mt-3" style={{ color: "hsl(220, 10%, 60%)" }}>
              {formatPhotoDate(photos[selectedIndex].name)}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
