"use client";

import { useState } from "react";
import { Camera, X } from "lucide-react";
import { formatTimeAgo } from "@/lib/garden/calculations";

interface CameraFeedProps {
  url: string | null | undefined;
  timestamp: string | null | undefined;
}

export default function CameraFeed({ url, timestamp }: CameraFeedProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const isRecent = timestamp ? (Date.now() - new Date(timestamp).getTime()) < 5 * 60 * 1000 : false;

  return (
    <>
      <div
        className="rounded-xl overflow-hidden relative cursor-pointer group h-full min-h-[280px]"
        style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}
        onClick={() => url && setFullscreen(true)}
      >
        {url ? (
          <img
            src={url}
            alt="Garden camera"
            className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
            style={{ minHeight: "280px" }}
          />
        ) : (
          <div className="w-full h-full min-h-[280px] flex flex-col items-center justify-center gap-3" style={{ color: "hsl(220, 10%, 35%)" }}>
            <Camera className="w-10 h-10" />
            <span className="text-sm">No camera feed</span>
          </div>
        )}

        {/* Overlays */}
        {url && (
          <>
            {/* Live indicator */}
            {isRecent && (
              <div className="absolute top-3 right-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wider"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)" }}>
                <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "hsl(152, 75%, 50%)" }} />
                <span style={{ color: "hsl(152, 75%, 50%)" }}>Live</span>
              </div>
            )}

            {/* Timestamp */}
            {timestamp && (
              <div className="absolute bottom-3 left-3 px-2.5 py-1 rounded-full text-[11px]"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)", color: "hsl(220, 10%, 75%)" }}>
                {formatTimeAgo(timestamp)}
              </div>
            )}
          </>
        )}
      </div>

      {/* Fullscreen modal */}
      {fullscreen && url && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          style={{ background: "hsla(0, 0%, 0%, 0.9)" }}
          onClick={() => setFullscreen(false)}
        >
          <button className="absolute top-4 right-4 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors">
            <X className="w-5 h-5 text-white" />
          </button>
          <img src={url} alt="Garden camera full" className="max-w-full max-h-full rounded-lg object-contain" />
        </div>
      )}
    </>
  );
}
