import { z } from "zod";
import { ToolDefinition } from "../types/tool-definition.js";
import {
  searchQuickbooksJournalEntries,
  getQuickbooksJournalEntry,
  createQuickbooksJournalEntry,
  updateQuickbooksJournalEntry,
  deleteQuickbooksJournalEntry,
} from "../handlers/journal-entry.handler.js";
import { summarizeJournalEntry, summarizeConfirmation } from "../utils/summarizers.js";

// Search Journal Entries Tool
const searchJournalEntriesSchema = z.object({
  docNumber: z.string().optional().describe("Filter by document/entry number"),
  txnDateFrom: z.string().optional().describe("Filter by transaction date (from) - format YYYY-MM-DD"),
  txnDateTo: z.string().optional().describe("Filter by transaction date (to) - format YYYY-MM-DD"),
});

export const SearchJournalEntriesTool: ToolDefinition<typeof searchJournalEntriesSchema> = {
  name: "qbo_search_journal_entries",
  description: "Search journal entries in QuickBooks Online. Use date filters to find entries in a specific period.",
  schema: searchJournalEntriesSchema,
  handler: async (args: any) => {
    const params = (args.params ?? {}) as z.infer<typeof searchJournalEntriesSchema>;
    const criteria: any = {};
    if (params.docNumber) criteria.docNumber = params.docNumber;
    if (params.txnDateFrom) criteria.txnDateFrom = params.txnDateFrom;
    if (params.txnDateTo) criteria.txnDateTo = params.txnDateTo;
    
    const response = await searchQuickbooksJournalEntries(criteria);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error searching journal entries: ${response.error}` }],
      };
    }
    const entries = response.result;
    const summaries = entries?.map((e: any) => summarizeJournalEntry(e)) || [];
    return {
      content: [
        { type: "text" as const, text: `Found ${entries?.length || 0} journal entries: ${JSON.stringify(summaries)}` },
      ],
    };
  },
};

// Get Journal Entry Tool
const getJournalEntrySchema = z.object({
  id: z.string().describe("The ID of the journal entry to retrieve"),
});

export const GetJournalEntryTool: ToolDefinition<typeof getJournalEntrySchema> = {
  name: "qbo_get_journal_entry",
  description: "Get a single journal entry by ID from QuickBooks Online.",
  schema: getJournalEntrySchema,
  handler: async (args: any) => {
    const { id } = (args.params ?? {}) as z.infer<typeof getJournalEntrySchema>;
    const response = await getQuickbooksJournalEntry(id);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error getting journal entry: ${response.error}` }],
      };
    }
    const summary = summarizeJournalEntry(response.result);
    return {
      content: [{ type: "text" as const, text: JSON.stringify(summary) }],
    };
  },
};

// Create Journal Entry Tool
const createJournalEntrySchema = z.object({
  Line: z.array(z.object({
    Amount: z.number().describe("Line amount"),
    DetailType: z.literal("JournalEntryLineDetail").describe("Must be 'JournalEntryLineDetail'"),
    JournalEntryLineDetail: z.object({
      PostingType: z.enum(["Debit", "Credit"]).describe("Debit or Credit"),
      AccountRef: z.object({
        value: z.string().describe("Account ID"),
        name: z.string().optional(),
      }),
      Description: z.string().optional(),
      Entity: z.object({
        EntityRef: z.object({
          value: z.string(),
          name: z.string().optional(),
          type: z.string().optional(),
        }),
      }).optional(),
    }),
  })).describe("Journal entry lines - must have balanced debits and credits"),
  TxnDate: z.string().optional().describe("Transaction date (YYYY-MM-DD)"),
  DocNumber: z.string().optional().describe("Journal entry number"),
  PrivateNote: z.string().optional().describe("Memo/note"),
});

export const CreateJournalEntryTool: ToolDefinition<typeof createJournalEntrySchema> = {
  name: "qbo_create_journal_entry",
  description: "Create a new journal entry in QuickBooks Online. Debits and credits must balance.",
  schema: createJournalEntrySchema,
  handler: async (args: any) => {
    const journalEntryData = (args.params ?? {}) as z.infer<typeof createJournalEntrySchema>;
    const response = await createQuickbooksJournalEntry(journalEntryData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error creating journal entry: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'JournalEntry');
    return {
      content: [
        { type: "text" as const, text: `Journal entry created successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Update Journal Entry Tool
const updateJournalEntrySchema = z.object({
  Id: z.string().describe("The ID of the journal entry to update"),
  SyncToken: z.string().describe("The sync token of the journal entry"),
  Line: z.array(z.any()).optional(),
  TxnDate: z.string().optional(),
  DocNumber: z.string().optional(),
  PrivateNote: z.string().optional(),
});

export const UpdateJournalEntryTool: ToolDefinition<typeof updateJournalEntrySchema> = {
  name: "qbo_update_journal_entry",
  description: "Update an existing journal entry in QuickBooks Online.",
  schema: updateJournalEntrySchema,
  handler: async (args: any) => {
    const journalEntryData = (args.params ?? {}) as z.infer<typeof updateJournalEntrySchema>;
    const response = await updateQuickbooksJournalEntry(journalEntryData);

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error updating journal entry: ${response.error}` }],
      };
    }
    const confirmation = summarizeConfirmation(response.result, 'JournalEntry');
    return {
      content: [
        { type: "text" as const, text: `Journal entry updated successfully: ${JSON.stringify(confirmation)}` },
      ],
    };
  },
};

// Delete Journal Entry Tool
const deleteJournalEntrySchema = z.object({
  Id: z.string().describe("The ID of the journal entry to delete"),
  SyncToken: z.string().describe("The sync token of the journal entry"),
});

export const DeleteJournalEntryTool: ToolDefinition<typeof deleteJournalEntrySchema> = {
  name: "qbo_delete_journal_entry",
  description: "Delete a journal entry from QuickBooks Online.",
  schema: deleteJournalEntrySchema,
  handler: async (args: any) => {
    const { Id, SyncToken } = (args.params ?? {}) as z.infer<typeof deleteJournalEntrySchema>;
    const response = await deleteQuickbooksJournalEntry({ Id, SyncToken });

    if (response.isError) {
      return {
        content: [{ type: "text" as const, text: `Error deleting journal entry: ${response.error}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: "Journal entry deleted successfully." }],
    };
  },
};
