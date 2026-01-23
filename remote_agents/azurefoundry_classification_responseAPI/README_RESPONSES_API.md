# Classification Agent - Responses API Version

**⚠️ THIS VERSION DOES NOT WORK - DO NOT USE**

This is a **backup/experimental version** of the classification agent migrated to use Azure OpenAI Responses API instead of Assistants API.

## Why This Version Doesn't Work

1. **Responses API not available** - Your Azure OpenAI deployment doesn't support Responses API
2. **Knowledge grounding broken** - Even if it worked, Responses API doesn't support knowledge base grounding
3. **Multi-tenant incompatible** - Would require centralized Azure AI Search infrastructure

## ⚠️ Important Limitations

### 1. Responses API Not Available on Your Deployment
**Your Azure OpenAI resource does not support Responses API.**

Tested API versions (all failed):
- ❌ `2024-02-15-preview` - "API version not supported"
- ❌ `2024-08-01-preview` - "API version not supported"  
- ❌ `2024-10-01-preview` - "API version not supported"
- ❌ `2024-10-21` - "API version not supported"
- ❌ `2024-12-01-preview` - "API version not supported"

**Root Cause**: Responses API is a newer feature not available in all Azure regions or for all model deployments.

### 2. Knowledge Base Grounding NOT Working
**The Responses API does NOT support knowledge base grounding like Assistants API did.**

- ✅ **File upload works** - PDFs can be uploaded successfully
- ❌ **Knowledge grounding broken** - Files are used for vision analysis, NOT RAG/semantic search
- ❌ **No vector stores** - Responses API doesn't have this capability
- ❌ **PDF content not used for reasoning** - Model doesn't search/reference document content

### What This Means
The agent will respond to queries but **cannot reference the Classification_Triage.pdf knowledge base** for answers. It will use only its training data, not your custom documents.

## Why This Version Exists

Created as a backup during migration exploration. Kept for:
1. Future reference if Microsoft adds knowledge grounding to Responses API
2. Understanding the architectural differences between APIs
3. Potential integration with Foundry IQ (Azure AI Search) later

## Differences from Assistants API Version

### Assistants API (azurefoundry_classification/)
- ✅ Uses `AgentsClient` from `azure.ai.agents`
- ✅ Has vector stores with automatic knowledge grounding
- ✅ Supports 20+ file types (.md, .txt, .json, .pdf, etc.)
- ✅ Perfect for multi-tenant (each customer's vector stores isolated)
- ✅ **RECOMMENDED for production**

### Responses API (this folder)
- ✅ Uses `AzureOpenAI` client (OpenAI thin client)
- ❌ No vector stores (files for vision only)
- ❌ Only supports PDFs
- ❌ Requires centralized infrastructure for knowledge grounding (Foundry IQ)
- ⚠️ **NOT recommended for production** (knowledge grounding broken)

## Files Modified

1. **foundry_agent.py** - Completely rewritten for Responses API
   - Uses `client.responses.create()` instead of Assistants API
   - Implements streaming with `event.type == 'response.output_text.delta'`
   - PDF upload works but not used for knowledge base

2. **foundry_agent_executor.py** - Minor changes
   - Removed `.id` attribute access on thread strings
   - Thread handling adjusted for stateless API

3. **pyproject.toml** - Added dependencies (if using PDF conversion)
   - `markdown>=3.5.0`
   - `weasyprint>=60.0`

4. **documents/** - PDF version created
   - Classification_Triage.pdf (converted from .md)
   - Original .md file removed (Responses API requires PDFs)

## To Add Knowledge Grounding (Future)

To make this version functional with knowledge grounding, you would need to:

1. **Set up Azure AI Search service** (~$250-500/month)
2. **Create Foundry IQ knowledge base** with your documents
3. **Integrate via function calling**:
   ```python
   # Add as a tool/function
   tools=[{
       "type": "function",
       "name": "search_knowledge_base",
       "description": "Search classification guidelines"
   }]
   ```
4. **Call knowledge base** before model response
5. **Pass results as context** to Responses API

This is complex and not suitable for multi-tenant distributed agents.

## Recommendation

**Use the Assistants API version** (`azurefoundry_classification/`) instead:
- It's fully functional with knowledge grounding
- Supports your multi-tenant architecture
- NOT deprecated (still fully supported by Microsoft)
- Perfect for distributed agents with customer data isolation

## When to Use This Version

- When you need o1/o3/o4/GPT-5 models specifically
- When you have centralized infrastructure (not distributed agents)
- When you implement custom Azure AI Search integration
- For experimentation/learning purposes

---

**Last Updated:** January 22, 2026
**Status:** Experimental / Not for Production Use
