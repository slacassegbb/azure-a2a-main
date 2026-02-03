"use client";

import { Agent } from "@/lib/api";

interface AgentCardProps {
  agent: Agent;
  isEnabled?: boolean;
  onToggle?: (agent: Agent) => void;
  isLoading?: boolean;
}

export function AgentCard({ agent, isEnabled = false, onToggle, isLoading = false }: AgentCardProps) {
  const isOnline = agent.status === "online";
  const canToggle = isOnline && onToggle;

  const handleClick = () => {
    if (canToggle && !isLoading) {
      onToggle(agent);
    }
  };

  return (
    <div
      onClick={handleClick}
      className={`group relative bg-white dark:bg-slate-800 rounded-xl border p-4 transition-all duration-200 ${
        canToggle ? "cursor-pointer" : ""
      } ${
        isEnabled
          ? "border-green-400 dark:border-green-600 bg-green-50 dark:bg-green-900/20 shadow-md"
          : isOnline
          ? "border-gray-200 dark:border-gray-700 hover:shadow-lg hover:border-primary-300 dark:hover:border-primary-700"
          : "border-gray-100 dark:border-gray-800 opacity-60"
      } ${isLoading ? "opacity-70 pointer-events-none" : ""}`}
    >
      {/* Enabled Checkmark Badge */}
      {isEnabled && (
        <div className="absolute -top-2 -right-2 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center shadow-lg">
          <svg
            className="w-4 h-4 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={3}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 13l4 4L19 7"
            />
          </svg>
        </div>
      )}

      {/* Loading Spinner */}
      {isLoading && (
        <div className="absolute -top-2 -right-2 w-6 h-6 bg-primary-500 rounded-full flex items-center justify-center shadow-lg">
          <svg
            className="w-4 h-4 text-white animate-spin"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        {/* Agent Icon */}
        <div
          className={`shrink-0 w-10 h-10 sm:w-12 sm:h-12 rounded-xl flex items-center justify-center text-lg font-bold ${
            isEnabled
              ? "bg-gradient-to-br from-green-100 to-green-200 dark:from-green-900/50 dark:to-green-800/50 text-green-700 dark:text-green-300"
              : isOnline
              ? "bg-gradient-to-br from-primary-100 to-primary-200 dark:from-primary-900/50 dark:to-primary-800/50 text-primary-700 dark:text-primary-300"
              : "bg-gray-100 dark:bg-gray-800 text-gray-400"
          }`}
        >
          {agent.iconUrl ? (
            <img
              src={agent.iconUrl}
              alt={agent.name}
              className="w-6 h-6 sm:w-7 sm:h-7 object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            agent.name?.charAt(0).toUpperCase() || "A"
          )}
        </div>

        {/* Name & Status */}
        <div className="flex-1 min-w-0">
          <h3
            className={`font-semibold line-clamp-1 text-sm sm:text-base ${
              isEnabled
                ? "text-green-800 dark:text-green-200"
                : isOnline
                ? "text-gray-900 dark:text-white"
                : "text-gray-500 dark:text-gray-400"
            }`}
          >
            {agent.name}
          </h3>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span
              className={`w-2 h-2 rounded-full ${
                isEnabled
                  ? "bg-green-500"
                  : isOnline
                  ? "bg-green-500 animate-pulse"
                  : "bg-gray-400"
              }`}
            ></span>
            <span
              className={`text-xs ${
                isEnabled
                  ? "text-green-600 dark:text-green-400 font-medium"
                  : isOnline
                  ? "text-green-600 dark:text-green-400"
                  : "text-gray-500 dark:text-gray-500"
              }`}
            >
              {isEnabled ? "Enabled" : isOnline ? "Online" : "Offline"}
            </span>
          </div>
        </div>
      </div>

      {/* Description */}
      {agent.description && (
        <p
          className={`text-sm line-clamp-2 mb-3 ${
            isEnabled
              ? "text-green-700 dark:text-green-300"
              : isOnline
              ? "text-gray-600 dark:text-gray-400"
              : "text-gray-400 dark:text-gray-500"
          }`}
        >
          {agent.description}
        </p>
      )}

      {/* Capabilities & Provider */}
      <div className="flex items-center justify-between pt-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-2">
          {agent.capabilities?.streaming && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400 rounded-full">
              <svg
                className="w-3 h-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
              Stream
            </span>
          )}
        </div>
        {agent.provider?.organization && (
          <span className="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[100px]">
            {agent.provider.organization}
          </span>
        )}
      </div>

      {/* Tap hint for online agents */}
      {isOnline && !isEnabled && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/5 dark:group-hover:bg-white/5 rounded-xl transition-colors">
          <span className="opacity-0 group-hover:opacity-100 text-xs font-medium text-primary-600 dark:text-primary-400 bg-white dark:bg-slate-800 px-2 py-1 rounded-full shadow transition-opacity">
            Tap to enable
          </span>
        </div>
      )}
    </div>
  );
}
