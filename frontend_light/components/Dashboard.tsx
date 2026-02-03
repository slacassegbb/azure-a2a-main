"use client";

import { useState, useEffect, useCallback } from "react";
import { getUserWorkflows, getAgents, getSessionAgents, enableSessionAgent, disableSessionAgent, getActivatedWorkflowIds, saveActivatedWorkflowIds, Workflow, Agent, UserInfo } from "@/lib/api";
import { WorkflowCard, getRequiredAgents, AgentStatus } from "./WorkflowCard";
import { AgentCard } from "./AgentCard";
import { VoiceButton } from "./VoiceButton";

// Get API URL for voice
const API_BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || "http://localhost:12000";

// Message type for conversation history
export interface VoiceMessage {
  id: string;
  timestamp: Date;
  userQuery: string;
  response: string;
}

interface DashboardProps {
  user: UserInfo | null;
  onLogout: () => void;
}

type TabType = "workflows" | "agents" | "messages";

export function Dashboard({ user, onLogout }: DashboardProps) {
  const [activeTab, setActiveTab] = useState<TabType>("messages");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [enabledAgentUrls, setEnabledAgentUrls] = useState<Set<string>>(new Set());
  const [loadingAgentUrls, setLoadingAgentUrls] = useState<Set<string>>(new Set());
  const [activatedWorkflowIds, setActivatedWorkflowIds] = useState<Set<string>>(new Set());
  const [loadingWorkflowIds, setLoadingWorkflowIds] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Handler for new messages from VoiceButton
  const handleNewMessage = useCallback((message: VoiceMessage) => {
    setMessages(prev => [message, ...prev]); // Add to beginning (newest first)
  }, []);

  // Toggle workflow activation - auto-enables required agents
  const handleToggleWorkflow = useCallback(async (workflow: Workflow) => {
    const workflowId = workflow.id;
    if (!workflowId) return;

    setLoadingWorkflowIds(prev => {
      const next = new Set(Array.from(prev));
      next.add(workflowId);
      return next;
    });

    try {
      const isCurrentlyActivated = activatedWorkflowIds.has(workflowId);
      
      if (isCurrentlyActivated) {
        // Deactivate workflow - just update local state, don't disable agents
        // (agents might be used by other workflows)
        setActivatedWorkflowIds(prev => {
          const next = new Set(Array.from(prev));
          next.delete(workflowId);
          saveActivatedWorkflowIds(next);
          return next;
        });
      } else {
        // Activate workflow and auto-enable required agents
        const requiredAgents = getRequiredAgents(workflow, agents);
        
        // Enable each required agent that is online and not already enabled
        for (const agentStatus of requiredAgents) {
          if (agentStatus.isOnline) {
            const matchingAgent = agents.find(a => 
              a.name.toLowerCase() === agentStatus.agentName.toLowerCase() ||
              a.name.toLowerCase().includes(agentStatus.agentName.toLowerCase()) ||
              agentStatus.agentName.toLowerCase().includes(a.name.toLowerCase())
            );
            
            if (matchingAgent && !enabledAgentUrls.has(matchingAgent.url)) {
              const success = await enableSessionAgent(matchingAgent);
              if (success) {
                setEnabledAgentUrls(prev => {
                  const next = new Set(Array.from(prev));
                  next.add(matchingAgent.url);
                  return next;
                });
              }
            }
          }
        }

        // Mark workflow as activated
        setActivatedWorkflowIds(prev => {
          const next = new Set(Array.from(prev));
          next.add(workflowId);
          saveActivatedWorkflowIds(next);
          return next;
        });
      }
    } catch (err) {
      console.error("Failed to toggle workflow:", err);
    } finally {
      setLoadingWorkflowIds(prev => {
        const next = new Set(Array.from(prev));
        next.delete(workflowId);
        return next;
      });
    }
  }, [activatedWorkflowIds, agents, enabledAgentUrls]);

  // Toggle agent enabled/disabled
  const handleToggleAgent = useCallback(async (agent: Agent) => {
    const agentUrl = agent.url;
    if (!agentUrl) return;

    // Set loading state
    setLoadingAgentUrls(prev => {
      const next = new Set(Array.from(prev));
      next.add(agentUrl);
      return next;
    });

    try {
      const isCurrentlyEnabled = enabledAgentUrls.has(agentUrl);
      
      if (isCurrentlyEnabled) {
        // Disable the agent
        const success = await disableSessionAgent(agentUrl);
        if (success) {
          setEnabledAgentUrls(prev => {
            const next = new Set(Array.from(prev));
            next.delete(agentUrl);
            return next;
          });
        }
      } else {
        // Enable the agent
        const success = await enableSessionAgent(agent);
        if (success) {
          setEnabledAgentUrls(prev => {
            const next = new Set(Array.from(prev));
            next.add(agentUrl);
            return next;
          });
        }
      }
    } catch (err) {
      console.error("Failed to toggle agent:", err);
    } finally {
      setLoadingAgentUrls(prev => {
        const next = new Set(Array.from(prev));
        next.delete(agentUrl);
        return next;
      });
    }
  }, [enabledAgentUrls]);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const [workflowsData, agentsData, sessionAgentsData] = await Promise.all([
        getUserWorkflows(),
        getAgents(),
        getSessionAgents(),
      ]);
      
      setWorkflows(workflowsData);
      setAgents(agentsData);
      
      // Track which agents are enabled in this session
      const enabledUrls = new Set(sessionAgentsData.map(a => a.url).filter(Boolean));
      setEnabledAgentUrls(enabledUrls);
      
      // Restore activated workflows from sessionStorage
      const storedActivatedWorkflows = getActivatedWorkflowIds();
      setActivatedWorkflowIds(storedActivatedWorkflows);
      
      // Re-enable agents for any activated workflows that aren't already enabled
      if (storedActivatedWorkflows.size > 0 && agentsData.length > 0) {
        console.log('[Dashboard] Re-enabling agents for activated workflows...');
        const workflowIds = Array.from(storedActivatedWorkflows);
        for (const workflowId of workflowIds) {
          const workflow = workflowsData.find(w => w.id === workflowId);
          if (workflow) {
            const { getRequiredAgents } = await import("./WorkflowCard");
            const requiredAgents = getRequiredAgents(workflow, agentsData);
            
            for (const agentStatus of requiredAgents) {
              if (agentStatus.isOnline) {
                const matchingAgent = agentsData.find(a => 
                  a.name.toLowerCase() === agentStatus.agentName.toLowerCase() ||
                  a.name.toLowerCase().includes(agentStatus.agentName.toLowerCase()) ||
                  agentStatus.agentName.toLowerCase().includes(a.name.toLowerCase())
                );
                
                if (matchingAgent && !enabledUrls.has(matchingAgent.url)) {
                  const success = await enableSessionAgent(matchingAgent);
                  if (success) {
                    enabledUrls.add(matchingAgent.url);
                    console.log(`[Dashboard] Re-enabled agent: ${matchingAgent.name}`);
                  }
                }
              }
            }
          }
        }
        // Update state with any newly enabled agents
        setEnabledAgentUrls(new Set(enabledUrls));
      }
    } catch (err) {
      console.error("Failed to load data:", err);
      setError("Failed to load data. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const onlineAgents = agents.filter((a) => a.status === "online");
  const offlineAgents = agents.filter((a) => a.status === "offline");
  const enabledAgentCount = enabledAgentUrls.size;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg border-b border-gray-200 dark:border-gray-800">
        <div className="px-4 sm:px-6 lg:px-8 py-3 sm:py-4">
          <div className="flex items-center justify-between">
            {/* Logo & Title */}
            <div className="flex items-center gap-2 sm:gap-3">
              <div className="w-8 h-8 sm:w-10 sm:h-10 bg-gradient-to-br from-primary-500 to-primary-700 rounded-lg sm:rounded-xl flex items-center justify-center">
                <svg
                  className="w-4 h-4 sm:w-5 sm:h-5 text-white"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13 10V3L4 14h7v7l9-11h-7z"
                  />
                </svg>
              </div>
              <h1 className="text-lg sm:text-xl font-bold text-gray-900 dark:text-white">
                A2A Light
              </h1>
            </div>

            {/* User menu */}
            <div className="flex items-center gap-2 sm:gap-4">
              {user && (
                <div className="hidden sm:flex items-center gap-2">
                  <div
                    className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-semibold"
                    style={{ backgroundColor: user.color || "#6B7280" }}
                  >
                    {user.name?.charAt(0).toUpperCase() || "U"}
                  </div>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    {user.name}
                  </span>
                </div>
              )}
              <button
                onClick={onLogout}
                className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 
                         hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
                title="Sign out"
              >
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="sticky top-[57px] sm:top-[73px] z-40 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg border-b border-gray-200 dark:border-gray-800">
        <div className="px-4 sm:px-6 lg:px-8">
          <nav className="flex gap-1 sm:gap-2 -mb-px" aria-label="Tabs">
            <button
              onClick={() => setActiveTab("workflows")}
              className={`flex-1 sm:flex-none px-4 sm:px-6 py-3 text-sm sm:text-base font-medium border-b-2 transition-colors
                ${
                  activeTab === "workflows"
                    ? "border-primary-500 text-primary-600 dark:text-primary-400"
                    : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:border-gray-300"
                }`}
            >
              <span className="flex items-center justify-center gap-2">
                <svg
                  className="w-4 h-4 sm:w-5 sm:h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
                  />
                </svg>
                Workflows
                <span className="hidden sm:inline-flex items-center justify-center px-2 py-0.5 text-xs font-medium rounded-full"
                  style={{
                    backgroundColor: activatedWorkflowIds.size > 0 ? 'rgb(220, 252, 231)' : 'rgb(243, 244, 246)',
                    color: activatedWorkflowIds.size > 0 ? 'rgb(21, 128, 61)' : 'rgb(75, 85, 99)',
                  }}
                >
                  {activatedWorkflowIds.size > 0 ? `${activatedWorkflowIds.size} active` : workflows.length}
                </span>
              </span>
            </button>

            <button
              onClick={() => setActiveTab("agents")}
              className={`flex-1 sm:flex-none px-4 sm:px-6 py-3 text-sm sm:text-base font-medium border-b-2 transition-colors
                ${
                  activeTab === "agents"
                    ? "border-primary-500 text-primary-600 dark:text-primary-400"
                    : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:border-gray-300"
                }`}
            >
              <span className="flex items-center justify-center gap-2">
                <svg
                  className="w-4 h-4 sm:w-5 sm:h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
                Agents
                {enabledAgentCount > 0 ? (
                  <span className="hidden sm:inline-flex items-center justify-center px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400 rounded-full">
                    {enabledAgentCount} enabled
                  </span>
                ) : (
                  <span className="hidden sm:inline-flex items-center justify-center px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 rounded-full">
                    {onlineAgents.length} online
                  </span>
                )}
              </span>
            </button>

            <button
              onClick={() => setActiveTab("messages")}
              className={`flex-1 sm:flex-none px-4 sm:px-6 py-3 text-sm sm:text-base font-medium border-b-2 transition-colors
                ${
                  activeTab === "messages"
                    ? "border-primary-500 text-primary-600 dark:text-primary-400"
                    : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:border-gray-300"
                }`}
            >
              <span className="flex items-center justify-center gap-2">
                <svg
                  className="w-4 h-4 sm:w-5 sm:h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
                Messages
                {messages.length > 0 && (
                  <span className="hidden sm:inline-flex items-center justify-center px-2 py-0.5 text-xs font-medium bg-primary-100 dark:bg-primary-900/50 text-primary-600 dark:text-primary-400 rounded-full">
                    {messages.length}
                  </span>
                )}
              </span>
            </button>
          </nav>
        </div>
      </div>

      {/* Content */}
      <main className="flex-1 px-4 sm:px-6 lg:px-8 py-4 sm:py-6 pb-32">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Loading...
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 gap-4">
            <div className="p-4 bg-red-50 dark:bg-red-900/30 rounded-xl">
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
            <button
              onClick={loadData}
              className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Retry
            </button>
          </div>
        ) : activeTab === "workflows" ? (
          <WorkflowsTab 
            workflows={workflows}
            agents={agents}
            activatedWorkflowIds={activatedWorkflowIds}
            loadingWorkflowIds={loadingWorkflowIds}
            enabledAgentUrls={enabledAgentUrls}
            onToggleWorkflow={handleToggleWorkflow}
          />
        ) : activeTab === "agents" ? (
          <AgentsTab 
            onlineAgents={onlineAgents} 
            offlineAgents={offlineAgents}
            enabledAgentUrls={enabledAgentUrls}
            loadingAgentUrls={loadingAgentUrls}
            onToggleAgent={handleToggleAgent}
          />
        ) : (
          <MessagesTab messages={messages} />
        )}
      </main>

      {/* Voice Button */}
      {user && (
        <VoiceButton 
          userId={user.user_id} 
          apiUrl={API_BASE_URL} 
          onNewMessage={handleNewMessage}
          disabled={enabledAgentCount === 0}
          disabledMessage="Activate a workflow or enable agents to start"
        />
      )}
    </div>
  );
}

function WorkflowsTab({ 
  workflows, 
  agents,
  activatedWorkflowIds,
  loadingWorkflowIds,
  enabledAgentUrls,
  onToggleWorkflow,
}: { 
  workflows: Workflow[];
  agents: Agent[];
  activatedWorkflowIds: Set<string>;
  loadingWorkflowIds: Set<string>;
  enabledAgentUrls: Set<string>;
  onToggleWorkflow: (workflow: Workflow) => void;
}) {
  if (workflows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 bg-gray-100 dark:bg-gray-800 rounded-2xl flex items-center justify-center mb-4">
          <svg
            className="w-8 h-8 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
            />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
          No workflows yet
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Workflows you create will appear here
        </p>
      </div>
    );
  }

  // Get agent statuses for each workflow
  const getWorkflowAgentStatuses = (workflow: Workflow): AgentStatus[] => {
    const requiredAgents = getRequiredAgents(workflow, agents);
    return requiredAgents.map(agentStatus => {
      const matchingAgent = agents.find(a => 
        a.name.toLowerCase() === agentStatus.agentName.toLowerCase() ||
        a.name.toLowerCase().includes(agentStatus.agentName.toLowerCase()) ||
        agentStatus.agentName.toLowerCase().includes(a.name.toLowerCase())
      );
      return {
        ...agentStatus,
        isEnabled: matchingAgent ? enabledAgentUrls.has(matchingAgent.url) : false,
      };
    });
  };

  return (
    <div className="space-y-4">
      {/* Info bar */}
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Tap a workflow to activate it. Required agents will be enabled automatically.
      </p>
      
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {workflows.map((workflow) => (
          <WorkflowCard 
            key={workflow.id} 
            workflow={workflow}
            isActivated={activatedWorkflowIds.has(workflow.id)}
            isLoading={loadingWorkflowIds.has(workflow.id)}
            agentStatuses={getWorkflowAgentStatuses(workflow)}
            onToggle={() => onToggleWorkflow(workflow)}
          />
        ))}
      </div>
    </div>
  );
}

function AgentsTab({
  onlineAgents,
  offlineAgents,
  enabledAgentUrls,
  loadingAgentUrls,
  onToggleAgent,
}: {
  onlineAgents: Agent[];
  offlineAgents: Agent[];
  enabledAgentUrls: Set<string>;
  loadingAgentUrls: Set<string>;
  onToggleAgent: (agent: Agent) => void;
}) {
  const enabledCount = Array.from(enabledAgentUrls).filter(url => 
    onlineAgents.some(a => a.url === url)
  ).length;

  return (
    <div className="space-y-6">
      {/* Enabled count summary */}
      {enabledCount > 0 && (
        <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl">
          <p className="text-sm text-green-700 dark:text-green-300 flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <span><strong>{enabledCount}</strong> agent{enabledCount !== 1 ? 's' : ''} enabled for this session</span>
          </p>
        </div>
      )}

      {/* Online Agents */}
      <section>
        <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
          <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
          Online ({onlineAgents.length})
          <span className="text-xs font-normal text-gray-500 dark:text-gray-400 ml-2">
            Tap to enable
          </span>
        </h2>
        {onlineAgents.length === 0 ? (
          <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-xl text-center">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No agents online
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {onlineAgents.map((agent) => (
              <AgentCard 
                key={agent.url || agent.name} 
                agent={agent}
                isEnabled={enabledAgentUrls.has(agent.url)}
                isLoading={loadingAgentUrls.has(agent.url)}
                onToggle={onToggleAgent}
              />
            ))}
          </div>
        )}
      </section>

      {/* Offline Agents */}
      {offlineAgents.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 mb-3 flex items-center gap-2">
            <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
            Offline ({offlineAgents.length})
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 opacity-60">
            {offlineAgents.map((agent) => (
              <AgentCard key={agent.url || agent.name} agent={agent} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// Simple markdown to HTML converter for messages
function formatMarkdown(text: string): string {
  return text
    .replace(/^### (.*$)/gm, '<h3 class="text-base font-semibold mt-3 mb-1">$1</h3>')
    .replace(/^## (.*$)/gm, '<h2 class="text-lg font-semibold mt-4 mb-2">$1</h2>')
    .replace(/^# (.*$)/gm, '<h1 class="text-xl font-bold mt-4 mb-2">$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^- (.*$)/gm, '<li class="ml-4">• $1</li>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>');
}

function MessagesTab({ messages }: { messages: VoiceMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 bg-gray-100 dark:bg-gray-800 rounded-2xl flex items-center justify-center mb-4">
          <svg
            className="w-8 h-8 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
          No messages yet
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Add agents or enable your workflows and start a conversation
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 max-w-3xl mx-auto">
      {messages.map((message) => (
        <MessageCard key={message.id} message={message} />
      ))}
    </div>
  );
}

function MessageCard({ message }: { message: VoiceMessage }) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div
      className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden transition-all duration-200"
    >
      {/* Collapsed header - click to expand */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 dark:hover:bg-slate-700/50 transition-colors text-left"
      >
        {/* Mic icon */}
        <div className="w-8 h-8 bg-primary-100 dark:bg-primary-900/50 rounded-full flex items-center justify-center flex-shrink-0">
          <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          </svg>
        </div>

        {/* Query text */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
            {message.userQuery}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {new Date(message.timestamp).toLocaleTimeString()}
          </p>
        </div>

        {/* Expand/collapse chevron */}
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded response */}
      {isExpanded && (
        <div className="px-4 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-slate-900/30">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 bg-green-100 dark:bg-green-900/50 rounded-full flex items-center justify-center flex-shrink-0">
              <svg className="w-4 h-4 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div 
              className="flex-1 min-w-0 text-sm text-gray-700 dark:text-gray-300 prose prose-sm dark:prose-invert max-w-none"
              dangerouslySetInnerHTML={{ __html: formatMarkdown(message.response) }}
            />
          </div>
        </div>
      )}
    </div>
  );
}