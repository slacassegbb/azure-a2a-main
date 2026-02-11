import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ToolDefinition } from "../types/tool-definition.js";
import { z } from "zod";

export function registerTool<T extends z.ZodObject<any>>(
  server: McpServer,
  toolDefinition: ToolDefinition<T>
) {
  server.tool(
    toolDefinition.name,
    toolDefinition.description,
    toolDefinition.schema.shape,
    async (args: any) => {
      // Wrap args in params for handler compatibility
      return toolDefinition.handler({ params: args });
    }
  );
}
