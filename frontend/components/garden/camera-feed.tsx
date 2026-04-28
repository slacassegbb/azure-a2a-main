"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Camera, X, ChevronLeft, ChevronRight, Play, Square } from "lucide-react";
import { formatTimeAgo } from "@/lib/garden/calculations";
import { GardenPhoto } from "@/lib/garden/types";

interface CameraFeedProps {
  url: string | null | undefined;
  timestamp: string | null | undefined;
  photos?: GardenPhoto[];
}

function formatPhotoDate(name: string): string {
  const match = name.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  if (!match) return name;
  const [, y, mo, d, h, mi] = match;
  const date = new Date(`${y}-${mo}-${d}T${h}:${mi}:00`);
  return date.toLocaleDateString([], { month: "short", day: "numeric" }) + " " +
    date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

export default function CameraFeed({ url, timestamp, photos = [] }: CameraFeedProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const stripRef = useRef<HTMLDivElement>(null);
  const playRef = useRef<NodeJS.Timeout | null>(null);
  const prevTimestampRef = useRef(timestamp);
  const isRecent = timestamp ? (Date.now() - new Date(timestamp).getTime()) < 5 * 60 * 1000 : false;

  // Auto-return to live when new image arrives
  useEffect(() => {
    if (timestamp && timestamp !== prevTimestampRef.current) {
      prevTimestampRef.current = timestamp;
      if (selectedPhoto !== null && !playing) {
        setSelectedPhoto(null); // snap back to live
      }
    }
  }, [timestamp, selectedPhoto, playing]);

  // Slideshow logic
  const startSlideshow = useCallback(() => {
    if (photos.length < 2) return;
    setPlaying(true);
    // Start from oldest (last in array since photos are newest-first)
    setSelectedPhoto(photos.length - 1);
  }, [photos]);

  const stopSlideshow = useCallback(() => {
    setPlaying(false);
    if (playRef.current) clearInterval(playRef.current);
    playRef.current = null;
    setSelectedPhoto(null); // back to live
  }, []);

  useEffect(() => {
    if (!playing) return;
    playRef.current = setInterval(() => {
      setSelectedPhoto(prev => {
        if (prev === null || prev <= 0) {
          // Reached newest photo — stop and go back to live
          setTimeout(stopSlideshow, 1500);
          return 0;
        }
        return prev - 1;
      });
    }, 1500);
    return () => {
      if (playRef.current) clearInterval(playRef.current);
    };
  }, [playing, stopSlideshow]);

  // The displayed image
  const displayUrl = selectedPhoto !== null && photos[selectedPhoto] ? photos[selectedPhoto].url : url;
  const displayTimestamp = selectedPhoto !== null && photos[selectedPhoto] ? photos[selectedPhoto].timestamp : timestamp;
  const isLive = selectedPhoto === null;

  const scrollStrip = (dir: number) => {
    stripRef.current?.scrollBy({ left: dir * 150, behavior: "smooth" });
  };

  return (
    <>
      <div
        className="rounded-xl overflow-hidden relative h-full min-h-[200px] md:min-h-[240px] xl:min-h-[280px]"
        style={{ background: "hsl(220, 18%, 11%)", border: "1px solid hsl(220, 15%, 16%)" }}
      >
        {/* Main image */}
        {displayUrl ? (
          <img
            src={displayUrl}
            alt="Garden camera"
            className="w-full h-full object-cover cursor-pointer"
            onClick={() => !playing && setFullscreen(true)}
          />
        ) : (
          <div className="w-full h-full min-h-[200px] flex flex-col items-center justify-center gap-3" style={{ color: "hsl(220, 10%, 35%)" }}>
            <Camera className="w-10 h-10" />
            <span className="text-sm">No camera feed</span>
          </div>
        )}

        {/* Top overlays */}
        {displayUrl && (
          <>
            {isLive && isRecent && !playing && (
              <div className="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)" }}>
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "hsl(152, 75%, 50%)" }} />
                <span style={{ color: "hsl(152, 75%, 50%)" }}>Live</span>
              </div>
            )}
            {playing && (
              <div className="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)" }}>
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "hsl(48, 95%, 65%)" }} />
                <span style={{ color: "hsl(48, 95%, 65%)" }}>Timelapse</span>
              </div>
            )}
            {!isLive && !playing && (
              <button
                className="absolute top-2 right-2 px-2 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider cursor-pointer"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)", color: "hsl(185, 90%, 55%)" }}
                onClick={() => setSelectedPhoto(null)}
              >
                ← Live
              </button>
            )}
            {displayTimestamp && (
              <div className="absolute top-2 left-2 px-2 py-0.5 rounded-full text-[9px]"
                style={{ background: "hsla(0, 0%, 0%, 0.5)", backdropFilter: "blur(8px)", color: "hsl(220, 10%, 75%)" }}>
                {isLive ? formatTimeAgo(displayTimestamp) : formatPhotoDate(photos[selectedPhoto!]?.name || "")}
              </div>
            )}
          </>
        )}

        {/* Photo filmstrip overlay at bottom */}
        {photos.length > 0 && (
          <div className="absolute bottom-0 left-0 right-0" style={{ background: "linear-gradient(transparent, hsla(0,0%,0%,0.8) 30%)" }}>
            <div className="relative px-8 py-2">
              {/* Play/Stop button */}
              <button
                className="absolute left-0 top-1/2 -translate-y-1/2 w-7 h-7 flex items-center justify-center rounded-full z-10 transition-colors"
                style={{ background: playing ? "hsl(0, 70%, 50%, 0.6)" : "hsla(0,0%,0%,0.5)" }}
                onClick={playing ? stopSlideshow : startSlideshow}
              >
                {playing ? <Square className="w-3 h-3 text-white" /> : <Play className="w-3 h-3 text-white ml-0.5" />}
              </button>

              {/* Scroll right button */}
              <button
                className="absolute right-0 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full z-10"
                style={{ background: "hsla(0,0%,0%,0.5)" }}
                onClick={() => scrollStrip(1)}
              >
                <ChevronRight className="w-3 h-3 text-white/70" />
              </button>

              {/* Thumbnails */}
              <div
                ref={stripRef}
                className="flex gap-1.5 overflow-x-auto scrollbar-none"
                style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
              >
                {photos.map((photo, i) => (
                  <div
                    key={photo.name}
                    className="shrink-0 cursor-pointer transition-all"
                    onClick={() => { if (!playing) setSelectedPhoto(selectedPhoto === i ? null : i); }}
                  >
                    <div
                      className="w-16 h-12 md:w-20 md:h-14 xl:w-24 xl:h-16 rounded overflow-hidden transition-all"
                      style={{
                        border: selectedPhoto === i ? "2px solid hsl(185, 90%, 55%)" : "1px solid hsla(220, 15%, 30%, 0.5)",
                        opacity: selectedPhoto === i ? 1 : 0.7,
                      }}
                    >
                      <img
                        src={photo.url}
                        alt=""
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Fullscreen modal */}
      {fullscreen && displayUrl && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          style={{ background: "hsla(0, 0%, 0%, 0.92)" }}
          onClick={() => setFullscreen(false)}
        >
          <button className="absolute top-4 right-4 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors">
            <X className="w-5 h-5 text-white" />
          </button>
          <img src={displayUrl} alt="Garden camera full" className="max-w-full max-h-full rounded-lg object-contain" />
        </div>
      )}
    </>
  );
}
