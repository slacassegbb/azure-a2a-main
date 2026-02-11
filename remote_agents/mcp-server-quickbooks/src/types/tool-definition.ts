import { z } from "zod";

export interface ToolDefinition<T extends z.ZodObject<any>> {
  name: string;
  description: string;
  schema: T;
  handler: (args: { params: z.infer<T> }) => Promise<{ content: Array<{ type: "text"; text: string }> }>;
}
