# 🎨 Interview Agent Customization Guide

This guide explains how to customize the AI Consulting Interview Agent for your specific company and use case.

## 📋 Table of Contents

1. [Quick Customization (5 minutes)](#quick-customization-5-minutes)
2. [Interview Questions](#interview-questions)
3. [Agent Personality](#agent-personality)
4. [Company Documents](#company-documents)
5. [Advanced Customization](#advanced-customization)
6. [Testing Your Changes](#testing-your-changes)

---

## Quick Customization (5 minutes)

The fastest way to get started:

### 1. Edit `interview_config.py`

Open `interview_config.py` and update these key sections:

```python
# Line 12-13: Your company information
COMPANY_NAME = "Your AI Consulting Company"  # Change this!
COMPANY_DESCRIPTION = "An AI consulting company specializing in delivering custom AI solutions"  # Change this!
```

### 2. Update the Interview Guide

Edit `documents/INTERVIEW_GUIDE.md` to replace the placeholder content with:
- Your actual services and capabilities
- Real case studies and success stories
- Your pricing models
- Your company's approach and values

### 3. Restart the Agent

```bash
# Stop the agent if it's running (Ctrl+C)
# Then restart it
uv run .
```

That's it! The agent will now use your customizations.

---

## Interview Questions

All interview questions are defined in `interview_config.py` in the `INTERVIEW_QUESTIONS` dictionary.

### Structure

Each category has:
- **priority**: Order in which topics are typically covered (1 = highest)
- **questions**: Main questions to ask
- **follow_ups**: Additional probing questions

### Example

```python
INTERVIEW_QUESTIONS = {
    "company_info": {
        "priority": 1,
        "questions": [
            "What company do you represent?",
            "What industry is your company in?",
            "What is the size of your organization?",
        ],
        "follow_ups": [
            "Can you tell me more about your company's current operations?",
            "What are your company's main business objectives this year?",
        ]
    },
    # Add more categories...
}
```

### Customization Tips

1. **Add New Categories**: Create new keys in the dictionary for additional topics
2. **Prioritize**: Adjust priority numbers to change the typical flow
3. **Industry-Specific**: Add questions specific to your target industries
4. **Qualification Focus**: Emphasize questions that help you qualify leads

### Example: Adding a New Category

```python
"data_maturity": {
    "priority": 4,
    "questions": [
        "What data do you currently collect?",
        "How is your data currently stored and organized?",
        "Do you have data governance policies in place?",
    ],
    "follow_ups": [
        "What data quality challenges do you face?",
        "How do different teams access and use data today?",
    ]
},
```

---

## Agent Personality

The agent's personality and conversation style are configured in `interview_config.py`.

### Key Sections

#### 1. Agent Role

```python
AGENT_ROLE = "Lead Qualification Specialist"
```

Change this to match your desired positioning (e.g., "AI Discovery Consultant", "Technical Assessment Specialist")

#### 2. Personality Traits

```python
AGENT_PERSONALITY_TRAITS = [
    "Professional and consultative",
    "Curious and inquisitive",
    "Empathetic listener",
    "Technical but approachable",
    "Focused on understanding customer needs",
]
```

Modify these to match your brand voice and approach.

#### 3. Conversation Style

```python
CONVERSATION_STYLE = """
- Ask one or two questions at a time, never overwhelm with too many questions
- Listen actively and probe deeper based on responses
- Acknowledge and validate customer pain points
- Use industry terminology appropriately but explain when needed
- Be conversational but maintain professionalism
- Show genuine interest in solving their problems
"""
```

Customize this to match how you want the agent to conduct interviews.

#### 4. Messages

Update the greeting and closing messages:

```python
# First impression
GREETING_MESSAGE = """
Hello! I'm here to learn about your AI and automation needs...
"""

# Final message
CLOSING_MESSAGE = """
Thank you so much for sharing all this information!...
"""
```

---

## Company Documents

Documents in the `documents/` folder are automatically indexed and used by the agent to ground its responses.

### Included Documents

1. **INTERVIEW_GUIDE.md** - Core company information, services, case studies
2. **WELCOME.md** - Sets expectations for the interview process

### Customization Steps

#### 1. Update INTERVIEW_GUIDE.md

Replace these sections with your actual information:

- **Company Overview**: Your services and approach
- **Common AI Use Cases**: Your specific offerings
- **Technology Stack**: Your tech capabilities
- **Success Stories**: Real case studies (with permission)
- **Investment Levels**: Your actual pricing
- **Qualification Criteria**: Your specific criteria

#### 2. Add Additional Documents

Add any relevant documents to help the agent:

```
documents/
├── INTERVIEW_GUIDE.md
├── WELCOME.md
├── case-study-financial.md       # Industry-specific cases
├── case-study-healthcare.md
├── services-catalog.pdf           # Detailed offerings
├── technical-capabilities.md      # Technical deep-dive
└── faq.md                        # Common questions
```

**Supported formats**: `.md`, `.pdf`, `.txt`, `.docx`, `.json`, `.csv`

#### 3. Keep Documents Current

Update documents regularly as your:
- Services evolve
- Case studies accumulate
- Pricing changes
- Success metrics update

---

## Advanced Customization

For more control, you can modify the Python files directly.

### 1. Modify Agent Instructions (`foundry_agent.py`)

The `_get_agent_instructions()` method (line 248) generates the system prompt from `interview_config.py`.

If you need to change the **structure** of how the agent thinks:

```python
def _get_agent_instructions(self) -> str:
    # Import configuration
    from interview_config import ...
    
    # Build custom instructions
    return f"""
    Your custom system prompt here...
    """
```

**When to do this**: Only if you need to fundamentally change how the agent approaches interviews.

### 2. Customize Input Detection (`foundry_agent_executor.py`)

The `_should_request_input()` method (line 233) determines when to use `input_required`.

Modify the detection logic if you want different behavior:

```python
def _should_request_input(self, response: str) -> bool:
    # Add your custom logic
    if "specific keyword" in response.lower():
        return True
    
    # Existing logic...
    return False
```

**When to do this**: If you want to control more precisely when the agent waits for user input.

### 3. Modify Skills (`__main__.py`)

Skills appear in the agent catalog and help with routing.

Update the `_build_agent_skills()` function (line 94) to change:
- Skill names and descriptions
- Tags for discovery
- Example queries

```python
AgentSkill(
    id='custom_skill',
    name='Custom Skill Name',
    description="What this skill does",
    tags=['tag1', 'tag2'],
    examples=[
        'Example query 1',
        'Example query 2',
    ],
),
```

**When to do this**: If you want to change how the agent appears in the catalog or how queries are routed to it.

### 4. Change Agent Identity (`__main__.py`)

The `_create_agent_card()` function (line 133) defines the agent's public identity:

```python
return AgentCard(
    name='Your Agent Name',
    description="Your agent description",
    # ...
)
```

**When to do this**: If you want to rebrand the agent or change its high-level description.

---

## Testing Your Changes

### 1. Test with Gradio UI

```bash
uv run . --ui
```

Visit `http://localhost:9120` and have a test conversation:

✅ **Test Checklist:**
- [ ] Does the greeting feel right?
- [ ] Are questions asked naturally?
- [ ] Does the agent probe for details when needed?
- [ ] Are follow-up questions relevant?
- [ ] Does the agent reference your documents correctly?
- [ ] Is the closing message appropriate?
- [ ] Are next steps clear?

### 2. Test Input Required Feature

The agent should use `input_required` when:
- Asking questions (ends with `?`)
- Using phrases like "Could you tell me..."
- Requesting specific information

**How to verify**: Check the agent logs for `🔄 Agent is requesting additional input from user`

### 3. Test with Host Orchestrator

1. Start the backend:
   ```bash
   cd backend
   python backend_production.py
   ```

2. Start your agent:
   ```bash
   cd remote_agents/azurefoundry_interview
   uv run .
   ```

3. Open frontend at `http://localhost:3000`

4. Look for your agent in the catalog and test through the multi-agent system

### 4. Test Document Grounding

Ask questions that should reference your documents:

- "What services do you offer?"
- "Tell me about your case studies"
- "What's your pricing model?"

The agent should cite specific information from your documents.

---

## Common Customization Scenarios

### Scenario 1: Different Industry Focus

**Goal**: Adapt the agent for healthcare consulting instead of general AI

**Changes**:
1. Update `COMPANY_DESCRIPTION` in `interview_config.py`
2. Modify questions in `INTERVIEW_QUESTIONS` to focus on healthcare:
   - Regulatory requirements (HIPAA, etc.)
   - Clinical workflows
   - Integration with EHR systems
3. Update `INTERVIEW_GUIDE.md` with healthcare case studies
4. Add healthcare-specific documents

### Scenario 2: Technical Pre-Qualification

**Goal**: Focus more on technical assessment, less on business discovery

**Changes**:
1. Adjust priorities in `INTERVIEW_QUESTIONS` (higher priority for technical_context)
2. Add more technical questions:
   - Infrastructure details
   - Data engineering capabilities
   - Security requirements
   - Compliance needs
3. Update qualification criteria in `interview_config.py`
4. Modify agent personality to be more technical

### Scenario 3: High-Volume Lead Capture

**Goal**: Shorter interviews focused on quick qualification

**Changes**:
1. Reduce questions in each category (keep only essentials)
2. Update `CONVERSATION_STYLE` to emphasize efficiency
3. Modify `_should_request_input()` to be more selective about probing
4. Update closing message to emphasize quick next steps

### Scenario 4: Consultative Deep Dives

**Goal**: Longer, more exploratory interviews for enterprise clients

**Changes**:
1. Add more follow-up questions in `INTERVIEW_QUESTIONS`
2. Update `CONVERSATION_STYLE` to encourage deeper exploration
3. Add more probing indicators in `_should_request_input()`
4. Add detailed technical and business assessment documents

---

## Tips for Great Interviews

### Do's ✅

- **Keep it conversational**: Edit questions to sound natural, not robotic
- **Provide context**: Help the agent understand why each question matters
- **Share examples**: Add real examples in your documents
- **Test regularly**: Interview yourself to refine the experience
- **Iterate based on feedback**: Adjust based on actual customer conversations

### Don'ts ❌

- **Don't overwhelm**: Too many questions in one category feels interrogative
- **Don't use jargon**: Unless your audience is highly technical
- **Don't be rigid**: Allow the agent to adapt based on responses
- **Don't skip documents**: The agent needs good documents to be helpful
- **Don't forget to update**: Keep documents current as things change

---

## Troubleshooting

### Agent not asking enough questions

**Fix**: Increase the number of questions and follow-ups in `interview_config.py`

### Agent asking too many questions

**Fix**: Reduce questions in each category, adjust `_should_request_input()` logic

### Agent not using documents

**Fix**: Check that documents are in `documents/` folder and in supported formats

### Agent sounds too robotic

**Fix**: Update `CONVERSATION_STYLE` and make questions more conversational

### Agent not probing deep enough

**Fix**: Add more follow-up questions and update probing strategies

---

## Getting Help

If you need assistance:

1. **Check the logs**: Set `VERBOSE_LOGGING=true` in `.env` for detailed output
2. **Review the template**: Compare with `azurefoundry_template/` for reference
3. **Test incrementally**: Make one change at a time and test
4. **Check documentation**: Review Azure AI Foundry docs and A2A protocol spec

---

**Happy Customizing! 🎨**

Remember: The best interview agents are iteratively refined based on real conversations. Start with the basics, test with real users, and continuously improve.


