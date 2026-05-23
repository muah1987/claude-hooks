---
name: analysis
description: >
  Structured analysis using the Ishikawa diagram, 9 deep-dive questions, agent roles, and
  Ja/Nee elimination loop — for EVERYTHING: problems, research, prompt analysis, concepts,
  decisions, strategies, or any topic worth decomposing. Auto-saves to memory. Trigger on
  "/analysis", "analyseer", "onderzoek dit", "wat betekent dit", "ontleed deze prompt",
  "breaks down", "decompose", "investigate", "uitzoeken", "root cause", "fishbone",
  "ishikawa", "wat houdt X in", "hoe werkt X", "help me begrijpen", "analyseer deze prompt",
  "wat wordt hiermee bedoeld", or any request to systematically examine, decompose, or
  understand something — whether it's a bug, a business question, a prompt, a concept,
  a strategy, or a decision.
allowed-tools: Bash, Read, Write, WebSearch, Agent
---

# Analysis Skill — Ishikawa + Agent Roles + Deep Questions + Elimination Loop

> **⚙️ Claude Code CLI Environment** — This skill runs inside Claude Code (terminal CLI), NOT claude.ai.
> Interactive widgets, `ask_user_input_v0`, `visualize:show_widget`, `tool_search`, `suggest_connectors`,
> and `search_mcp_registry` are **not available**. All interactions are plain text/markdown.
> Visualizations are rendered as ASCII art. Memory saves use the Write tool to `.md` files.
> Tool discovery uses the `ToolSearch` tool. MCP suggestions are plain text recommendations.

This skill guides a structured analysis session for ANY type of investigation — not only
problems, but also research, prompt analysis, concept exploration, decision-making, and
strategy evaluation. It works in five phases:

0. **Mode & Agent Assembly** — Determine analysis type + spawn domain-specific expert agents
1. **Ishikawa Diagram** — Decompose the subject across 6 categories (causes, factors, or dimensions)
2. **Deep-Dive Questions** — Interrogate each element with 9 analytical questions
3. **Elimination Loop** — Systematically include/exclude elements via Ja/Nee
4. **Action Plan / Conclusion** — Assign actions or deliver findings
5. **Memory Save** — Persist everything automatically

---

## Phase 0: Analysis Mode & Agent Assembly (ALTIJD EERST — voor alles)

### Step 0.0 — Determine Analysis Mode

Before assembling agents, determine WHAT KIND of analysis is needed. This changes how the
Ishikawa diagram is used and how the 9 questions are framed.

Ask the user in plain text:

**"Wat wil je analyseren? Kies een modus (typ het nummer):**
```
1. 🔴 Probleem Analyse  — Iets gaat mis, ik zoek de oorzaak
2. 🔵 Onderzoek         — Ik wil een onderwerp of concept begrijpen
3. 🟡 Prompt Analyse    — Ik wil begrijpen wat een prompt bedoelt/doet/mist
4. 🟢 Beslissing / Keuze — Ik moet kiezen tussen opties
5. 🟣 Strategie / Plan  — Ik wil een aanpak of strategie doorlichten
```"

Wait for the user's typed reply (1-5 or mode name). If ARGS already contains the topic/mode, infer it automatically and confirm before proceeding.

Each mode changes how the Ishikawa is used:

| Mode | Ishikawa Gebruik | Fish Head | Bones Bevatten |
|------|-----------------|-----------|----------------|
| 🔴 Probleem | Oorzaak-analyse | Het probleem | Mogelijke oorzaken |
| 🔵 Onderzoek | Decompositie | Het onderwerp | Dimensies/aspecten om te onderzoeken |
| 🟡 Prompt | Prompt-ontleding | De prompt | Componenten: doel, context, instructies, constraints, output, toon |
| 🟢 Beslissing | Factor-analyse | De keuze | Factoren die de beslissing beïnvloeden |
| 🟣 Strategie | SWOT-achtig | De strategie | Sterktes, zwaktes, kansen, bedreigingen, afhankelijkheden |

### Step 0.1 — Identify the Domain

Ask the user in plain text:

**"In welk domein speelt dit? (typ het nummer)**
```
1. Software / Web Development
2. Business / Management
3. IT Infrastructure / DevOps
4. Marketing / Sales
5. Manufacturing / Productie
6. Healthcare / Zorg
7. Education / Onderwijs
8. Finance / Administratie
9. AI / Prompt Engineering
10. Anders (beschrijf het domein)
```"

Wait for typed reply. If inferable from ARGS, infer and confirm.

### Step 0.2 — Spawn Role Agents

Based on the domain, assemble a team of 4-7 specialist agents. Each agent has:
- **Naam** — Their role title
- **Verantwoordelijkheid** — What they own in the analysis
- **Ishikawa Focus** — Which 6M categories they primarily investigate
- **Perspectief** — The lens through which they analyze causes

Below are the PRESET role templates per domain. Always adapt and extend based on the
specific problem — these are starting points, not rigid lists.

#### Software / Web Development
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🧑‍💼 Product Owner | Eigenaar product visie | Business requirements, prioriteiten, impact op gebruiker | Mens, Methode |
| 👨‍💻 Lead Developer | Technisch eigenaar | Code kwaliteit, architectuur, technische schuld | Machine, Methode |
| 🎨 UI/UX Specialist | Gebruikerservaring | Interface, usability, toegankelijkheid, design patterns | Mens, Meting |
| 🔧 DevOps Engineer | Infrastructuur | Deployment, servers, CI/CD, monitoring, performance | Machine, Meting |
| 🧪 QA / Tester | Kwaliteitsborging | Test coverage, reproduceerbaar, edge cases | Meting, Materiaal |
| 🔒 Security Specialist | Veiligheid | Kwetsbaarheden, data, compliance | Machine, Milieu |

#### Business / Management
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🧑‍💼 Directeur/CEO | Strategische visie | Bedrijfsdoelen, resource allocatie | Methode, Milieu |
| 📊 Operations Manager | Processen | Workflow efficiëntie, bottlenecks, SLA's | Methode, Meting |
| 👥 HR Manager | Mensen | Team capaciteit, kennis, cultuur, communicatie | Mens, Methode |
| 💰 Financial Controller | Financiën | Budget, kosten, ROI, financiële impact | Materiaal, Meting |
| 📣 Marketing Manager | Markt & klant | Klantimpact, merkperceptie, concurrentie | Milieu, Mens |
| ⚖️ Compliance Officer | Regelgeving | Juridisch, audit, regelgeving, risico | Milieu, Methode |

#### IT Infrastructure / DevOps
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🖥️ Systeembeheerder | Server & OS | Uptime, configuratie, patches, capaciteit | Machine, Materiaal |
| 🌐 Netwerkbeheerder | Netwerk | Connectiviteit, latency, firewall, DNS | Machine, Meting |
| 🔒 Security Engineer | Beveiliging | Threats, access control, encryption | Machine, Milieu |
| 📊 Monitoring Specialist | Observability | Logs, alerts, metrics, dashboards | Meting, Methode |
| 🔄 Release Manager | Deployments | Change management, rollbacks, pipelines | Methode, Machine |

#### Manufacturing / Productie
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🏭 Productiemanager | Productielijn | Output, efficiency, planning, flow | Methode, Machine |
| 🔧 Maintenance Engineer | Onderhoud | Machine uptime, preventief onderhoud | Machine, Materiaal |
| 📋 Quality Manager | Kwaliteit | Specs, toleranties, defect rate, audits | Meting, Methode |
| 📦 Supply Chain Manager | Aanvoer | Leveranciers, grondstoffen, levertijden | Materiaal, Milieu |
| 👷 Operator/Werkvloer | Uitvoering | Handmatige stappen, ergonomie, training | Mens, Machine |
| 🧪 Process Engineer | Procesoptimalisatie | Parameters, variabelen, recepturen | Methode, Meting |

#### Healthcare / Zorg
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 👨‍⚕️ Behandelend Arts | Medisch beleid | Diagnose, behandelplan, protocollen | Methode, Mens |
| 👩‍⚕️ Hoofdverpleegkundige | Zorguitvoering | Werkdruk, overdracht, patiëntveiligheid | Mens, Methode |
| 💊 Apotheker | Medicatie | Medicijninteracties, dosering, beschikbaarheid | Materiaal, Meting |
| 📊 Kwaliteitsmedewerker | Kwaliteit & veiligheid | Incidentanalyse, protocollen, audits | Meting, Methode |
| 🏥 Manager Bedrijfsvoering | Operatie | Capaciteit, roostering, budget, faciliteiten | Machine, Milieu |

#### AI / Prompt Engineering
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🧠 Prompt Engineer | Prompt architectuur | Structuur, instructies, constraints, output format | Methode, Materiaal |
| 🎯 Intent Analyst | Doel & intentie | Wat wil de prompt bereiken? Impliciete vs expliciete doelen | Mens, Methode |
| 📐 Context Specialist | Context & framing | System prompt, few-shot examples, rolbepaling, tone | Materiaal, Milieu |
| 🔍 Edge Case Tester | Randgevallen | Ambiguïteit, misinterpretatie, failure modes, hallucinations | Meting, Machine |
| 📊 Output Evaluator | Kwaliteitsbeoordeling | Evalueert of output matcht met intentie, meet consistentie | Meting, Methode |
| 🔄 Iteration Specialist | Optimalisatie | Prompt versioning, A/B testing, iteratieve verbetering | Methode, Meting |

#### Research / Onderzoek (generiek — voor elke onderzoeksvraag)
| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| 🔬 Onderzoeker | Diepte-analyse | Bronnen vinden, feiten verifiëren, hypotheses vormen | Materiaal, Methode |
| 🤔 Criticus / Devil's Advocate | Tegenargumenten | Aannames uitdagen, bias detecteren, zwakke punten vinden | Mens, Meting |
| 🗺️ Context Expert | Achtergrond & kader | Historische context, gerelateerde onderwerpen, bredere impact | Milieu, Materiaal |
| 📋 Synthesizer | Samenvatting | Bevindingen combineren tot coherent verhaal, conclusies trekken | Methode, Meting |
| 🎯 Praktijk Expert | Toepassing | Hoe vertaalt kennis naar actie? Wat is bruikbaar? | Mens, Machine |

#### Custom Domain (user specifies)
When the domain is "Anders", interview the user:
1. **"Welke rollen of expertises zijn relevant voor dit onderwerp?"**
2. **"Wie heeft de meeste kennis over dit specifieke vraagstuk?"**
3. **"Zijn er externe perspectieven (leveranciers, klanten, regelgevers, eindgebruikers) die relevant zijn?"**

Then construct 4-7 custom agents following the same template structure.

### Step 0.3 — Present the Team & Confirm

Present the assembled team as a markdown table in plain text:

```
## 🧑‍🤝‍🧑 Analyse-Team

| Agent | Rol | Verantwoordelijkheid | Ishikawa Focus |
|-------|-----|----------------------|----------------|
| [emoji] [naam] | [rol] | [verantwoordelijkheid] | [focus] |
...
```

Then ask in plain text:
**"Dit is het analyse-team. Typ je keuze:**
```
1. Ziet er goed uit — doorgaan
2. Rol toevoegen
3. Rol verwijderen
4. Rol aanpassen
```"

Only proceed to Phase 1 after the user confirms (or types "1" / "ok" / "doorgaan" / "go").

### Step 0.4 — Agent Behavior During Analysis

Throughout the ENTIRE analysis, each agent contributes from their perspective:

**Phase 1 (Ishikawa):**
- Each agent brainstorms causes WITHIN their Ishikawa Focus categories
- Present causes grouped by agent: "🧑‍💼 Product Owner ziet: ...", "👨‍💻 Developer ziet: ..."
- This ensures every 6M category has at least one expert covering it

**Phase 2 (9 Vragen):**
- For each cause, the MOST relevant agent leads the questioning
- Other agents add supplementary perspective where their expertise overlaps
- Example: a database performance cause → Lead Developer leads, DevOps adds infra context

**Phase 3 (Eliminatie):**
- The responsible agent for each cause gives their professional verdict first
- The user makes the final Ja/Nee decision informed by the agent's recommendation
- Format: "👨‍💻 Developer adviseert: Ja, dit is waarschijnlijk een oorzaak omdat..."

**Phase 4 (Actieplan):**
- Each confirmed cause is ASSIGNED to the agent whose role owns the fix
- The agent formulates the specific action from their expertise

---

## Tool Discovery & Usage (DOORLOPEND — geldt voor ELKE fase)

Throughout the entire analysis, actively discover and use available tools to enrich the
investigation. Do not rely solely on the user's input — USE tools to gather data, verify
claims, search for context, and access connected systems.

> **Claude Code CLI note**: Use `ToolSearch` (built-in) to discover available deferred tools.
> Use `WebSearch` for web research. Use `Bash`, `Grep`, `Read`, `Glob` for codebase investigation.
> There is no `tool_search`, `suggest_connectors`, or `search_mcp_registry` — use equivalents below.

### Step T.1 — Tool Discovery at Start (run ONCE at beginning)

Immediately after Phase 0, use the `ToolSearch` tool to discover what deferred tools are
available. Run these searches in parallel:

```
ToolSearch("web search")           — for research & fact-checking
ToolSearch("calendar")             — if time/scheduling is relevant
ToolSearch("email")                — if correspondence is relevant
ToolSearch("github")               — if code/PRs are relevant
ToolSearch("database")             — if data/storage is relevant
ToolSearch("[domain keyword]")     — domain-specific (e.g. "stripe", "deploy", "slack")
```

**Available Claude Code tools to use per domain:**

| Domain | Tools to use |
|--------|-------------|
| Software / Web Dev | Grep, Glob, Read, Bash, WebSearch, ToolSearch("github") |
| Business / Management | WebSearch, ToolSearch("spreadsheet analytics") |
| IT / DevOps | Bash (docker/kubectl), WebSearch, ToolSearch("cloud logging") |
| AI / Prompt | WebSearch, ToolSearch("hugging face"), Read (local files) |
| Any domain | WebSearch for research, Bash for data collection |

Store discovered tools in a running **Tool Inventory** note in the conversation.

### Step T.2 — Human Interaction Protocol (Claude Code CLI)

In Claude Code CLI there are no interactive widgets. All questions are plain text with
numbered options. The user types their answer.

**Decision tree for asking the human:**

```
Is the question...
├─ A choice between options?
│   └─ Present numbered list, ask user to type number or name
├─ Multi-select?
│   └─ Present numbered list, ask user to type comma-separated numbers
├─ Ranking/prioritization?
│   └─ Present list, ask user to type items in priority order
├─ Open-ended?
│   └─ Ask as plain markdown prose, user types free text
└─ A binary Ja/Nee?
    └─ Ask "Ja / Nee / Onzeker" as plain text
```

**Specific interaction points — plain text format:**

| Moment | Vraag | Formaat |
|--------|-------|---------|
| Phase 0.0 | Analyse mode | Numbered list 1-5 |
| Phase 0.1 | Domein | Numbered list 1-10 |
| Phase 0.3 | Team bevestigen | Numbered list 1-4 |
| Phase 1 per categorie | Oorzaken bevestigen | Numbered list + "Anders: ..." |
| Phase 2 per oorzaak | Verder uitdiepen? | "Ja / Nee / Genoeg" |
| Phase 3 per element | Ja/Nee eliminatie | "Ja / Nee / Onzeker" |
| Phase 3 convergentie | Klopt het beeld? | "Ja / Nee / Opnieuw" |
| Phase 4 | Deliverable type | "1=Actieplan / 2=Rapport / 3=Beide" |

### Step T.3 — Tool Usage During Each Phase

**Phase 1 (Ishikawa) — Verrijk met data:**
- Use `WebSearch` to find background info when description is vague
- Use `Grep`/`Read`/`Glob` to investigate codebases, configs, logs
- Use `Bash` to query databases, run diagnostics, check system state
- Use `ToolSearch` to find any deferred MCP tools that might have relevant data

**Phase 2 (9 Vragen) — Onderbouw antwoorden:**
- For question 4 (Waarom? 3x diep) → Use `WebSearch` for technical/industry explanations
- For question 6 (Wanneer?) → Use `Bash` to check git logs, system logs, timestamps
- For question 9 (Recreëren?) → Use `Bash` to run tests or reproduce the issue
- If analyzing a prompt (🟡 mode) → Use `WebSearch` for prompt engineering best practices

**Phase 3 (Eliminatie) — Verifieer met bewijs:**
- Before each Ja/Nee, use `Grep`/`Bash`/`WebSearch` to gather hard evidence
- Check git history (`Bash git log`) for timeline clues
- Check server logs, metrics, error rates via `Bash`

**Phase 4 (Deliverable) — Verrijk het eindresultaat:**
- Use `WebSearch` for best practices related to proposed actions
- Use `Bash` to verify proposed fixes are technically feasible
- Suggest relevant MCP servers/tools in plain text if they would help

### Step T.4 — Tool Search Patterns (Claude Code CLI)

```bash
# Discover deferred tools
ToolSearch("web search")
ToolSearch("github repository")
ToolSearch("database query")
ToolSearch("slack telegram")

# Investigate codebase
Grep(pattern, path)
Glob("**/*.{js,ts,go,py}")
Read(file_path)
Bash("git log --oneline -20")

# Web research
WebSearch("best practices for [topic]")
WebSearch("[technology] error handling patterns")
```

If a useful MCP is not connected, suggest it in plain text:
> "🔌 Voor deze analyse zou [tool/MCP] nuttig zijn — je kunt het installeren via
> `claude mcp add [name]`. Voor nu gebruik ik WebSearch als alternatief."

### Step T.5 — Proactive Tool Suggestions (Plain Text)

During the analysis, if a missing tool would significantly help, mention it naturally:

```
Example suggestions (plain text, no special tool needed):
- "Voor diepere monitoring-data zou Grafana/Datadog MCP nuttig zijn."
- "Als je Jira hebt, kan ik de tickethistorie analyseren — voeg de MCP toe met 'claude mcp add jira'."
- "GitHub MCP (al beschikbaar via ToolSearch) kan PR-geschiedenis ophalen."
```

Do NOT block the analysis waiting for tools to be connected — continue with available tools.

---

## Phase 1: Subject Definition & Ishikawa Diagram

### Step 1 — Capture the Subject

Get a crystal-clear statement of what is being analyzed. The question depends on the mode:

| Mode | Vraag aan gebruiker |
|------|---------------------|
| 🔴 Probleem | "Beschrijf het probleem in één zin. Wat gaat er precies mis?" |
| 🔵 Onderzoek | "Wat wil je precies onderzoeken of begrijpen? Formuleer je onderzoeksvraag." |
| 🟡 Prompt | "Plak de prompt die je wilt analyseren. Wat wil je erover weten?" |
| 🟢 Beslissing | "Welke keuze moet je maken? Wat zijn de opties?" |
| 🟣 Strategie | "Welke strategie of plan wil je doorlichten?" |

Take their answer and reformulate it as a sharp, specifieke statement.

**Examples per mode:**
- 🔴 "De website laadt langzamer dan 5 seconden sinds vorige week dinsdag."
- 🔵 "Hoe werkt vector embedding in LLMs en wanneer gebruik je het?"
- 🟡 "Deze system prompt instrueert een chatbot maar mist duidelijke constraints."
- 🟢 "Kiezen tussen React Native of Flutter voor onze nieuwe app."
- 🟣 "Ons go-to-market plan voor Q3 heeft mogelijk blinde vlekken."

### Step 2 — Build the Ishikawa Diagram

The 6M categories adapt their meaning based on the analysis mode:

#### 🔴 Probleem Mode (klassiek — oorzaken zoeken)
| Category | Focus |
|----------|-------|
| **Mens** | Kennis, training, motivatie, communicatie |
| **Methode** | Processen, procedures, workflows, beleid |
| **Machine** | Tools, software, hardware, infrastructuur |
| **Materiaal** | Input, data, grondstoffen, bronnen |
| **Meting** | KPI's, monitoring, feedback, metrics |
| **Milieu** | Externe factoren, markt, regelgeving, context |

#### 🔵 Onderzoek Mode (decompositie — dimensies ontdekken)
| Category | Focus |
|----------|-------|
| **Mens** | Wie is betrokken? Doelgroep, stakeholders, gebruikers |
| **Methode** | Hoe werkt het? Processen, mechanismen, methoden |
| **Machine** | Welke tools/technologie? Implementatie, platformen |
| **Materiaal** | Welke bronnen/input? Data, kennis, grondstoffen |
| **Meting** | Hoe meet je succes? Criteria, benchmarks, vergelijking |
| **Milieu** | Welke context? Markt, concurrentie, trends, regelgeving |

#### 🟡 Prompt Mode (prompt-ontleding — componenten isoleren)
| Category | Focus |
|----------|-------|
| **Mens** | Wie is de doelgebruiker? Welke rol neemt het model aan? |
| **Methode** | Welke instructies/stappen? Chain-of-thought, format, constraints |
| **Machine** | Welk model/platform? Token limits, capabilities, temperature |
| **Materiaal** | Welke context/input? System prompt, examples, knowledge base |
| **Meting** | Hoe evalueer je output? Kwaliteitscriteria, consistentie |
| **Milieu** | Waar wordt het ingezet? Use case, productie vs test, edge cases |

#### 🟢 Beslissing Mode (factor-analyse — wat beïnvloedt de keuze)
| Category | Focus |
|----------|-------|
| **Mens** | Wie wordt geraakt? Team, klanten, stakeholders |
| **Methode** | Hoe implementeer je elke optie? Complexiteit, haalbaarheid |
| **Machine** | Welke tooling/tech is nodig? Vendor lock-in, compatibiliteit |
| **Materiaal** | Welke resources? Budget, tijd, kennis, data |
| **Meting** | Hoe vergelijk je? KPI's, success metrics, risico-scores |
| **Milieu** | Externe factoren? Markt, timing, concurrentie, regelgeving |

#### 🟣 Strategie Mode (doorlichting — sterktes en zwaktes)
| Category | Focus |
|----------|-------|
| **Mens** | Team capaciteit, skills gaps, cultuur, buy-in |
| **Methode** | Uitvoerbaarheid plan, procesgaten, afhankelijkheden |
| **Machine** | Technische gereedheid, tooling, schaalbaarheid |
| **Materiaal** | Budget, resources, time-to-market, partnerships |
| **Meting** | Success metrics, milestones, feedback loops |
| **Milieu** | Markt timing, concurrentie, risico's, regelgeving |

For each category, brainstorm 2-4 possible causes WITH the user. Present them as a numbered list and ask the user to confirm, add, or remove. Don't assume — ask.

After collecting all causes, render an ASCII fishbone (Ishikawa) diagram in the terminal. The problem statement is the "fish head" on the right; each bone is a category with causes as sub-branches. Example format:

```
                    MENS                METHODE
                   /                   /
 oorzaak A ───────/    oorzaak C ─────/
 oorzaak B ───────/    oorzaak D ─────/
                  \                   \
                   \                   \
════════════════════╪═══════════════════╪══════════════▶ [ PROBLEEM ]
                   /                   \
 oorzaak E ───────/    oorzaak G ──────\
 oorzaak F ───────/    oorzaak H ──────\
                  \                     \
                MACHINE                MILIEU
```

Adapt the layout to fit the actual causes and all 6 categories (Mens/Methode/Machine/Materiaal/Meting/Milieu).

---

## Phase 2: Deep-Dive Questions (De 9 Vragen)

For every element identified in Phase 1, systematically ask these 9 analytical questions.
The framing adapts to the analysis mode, but the core questions stay the same.

### The 9 Questions — Adapted Per Mode

| # | Vraag | 🔴 Probleem | 🔵 Onderzoek | 🟡 Prompt | 🟢 Beslissing | 🟣 Strategie |
|---|-------|-------------|-------------|-----------|--------------|-------------|
| 1 | **Hoe?** | Hoe manifesteert dit zich? | Hoe werkt dit aspect? | Hoe is dit in de prompt verwoord? | Hoe beïnvloedt dit de keuze? | Hoe wordt dit uitgevoerd? |
| 2 | **Wat?** | Wat is de impact? | Wat houdt dit precies in? | Wat doet dit onderdeel? | Wat zijn de gevolgen per optie? | Wat is het verwachte resultaat? |
| 3 | **Hoezo?** | Hoezo is dit een oorzaak? | Hoezo is dit relevant? | Hoezo staat dit erin / ontbreekt dit? | Hoezo is dit een factor? | Hoezo is dit belangrijk? |
| 4 | **Waarom?** | Waarom gebeurt dit? (3x diep) | Waarom werkt het zo? (3x diep) | Waarom deze keuze? (3x diep) | Waarom weegt dit mee? (3x diep) | Waarom deze aanpak? (3x diep) |
| 5 | **Waar?** | Waar in het systeem? | Waar is dit van toepassing? | Waar in de prompt zit dit? | Waar heeft dit de meeste impact? | Waar zitten de risico's? |
| 6 | **Wanneer?** | Wanneer begon dit? | Wanneer is dit relevant? | Wanneer triggered dit gedrag? | Wanneer moet je kiezen? | Wanneer zijn milestones? |
| 7 | **Hoe gebeurt dit?** | Stap-voor-stap mechanisme | Stap-voor-stap werking | Stap-voor-stap prompt flow | Stap-voor-stap implementatie | Stap-voor-stap uitvoering |
| 8 | **Wat kan eraan gedaan worden?** | Oplossingen? Quick wins vs structureel | Wat zijn open vragen? Gaps? | Hoe verbeter je dit onderdeel? | Hoe mitigeer je nadelen? | Hoe versterk je zwaktes? |
| 9 | **Kan ik het zelf recreëren?** | Reproduceerbaar? Onder welke condities? | Kan ik dit zelf testen/valideren? | Kan ik deze prompt zelf testen? | Kan ik een pilot draaien? | Kan ik dit simuleren/prototypen? |

### How to Execute Phase 2

Do NOT dump all 9 questions for all causes at once — that overwhelms the user.

Instead, process elements **one at a time**:
- Present the element and the responsible agent
- Ask the 9 questions in batches of 2-3 as plain text; for choice questions, present options as a numbered list
- **BETWEEN questions**: use `WebSearch` to verify claims, find data, or add context
  that enriches the investigation. Don't wait for the user to ask — be proactive.
- **For "Onzeker" answers**: immediately use `ToolSearch` + `WebSearch` to find
  supporting data. Use `Grep`/`Bash` to check codebases, logs, or git history.
- Summarize the findings per element before moving to the next one
- After each element, ask in plain text:
  **"Wat wil je met deze bevinding? (1) Ja, dieper — (2) Nee, door naar volgende — (3) Dit is genoeg"**

Track findings in a running evidence table:

```
| Oorzaak | Bewijs Vóór | Bewijs Tegen | Status |
```

---

## Phase 3: Elimination Loop (Ja/Nee Uitsluiting)

This is the core decision engine. After Phase 2 has produced evidence for each element,
systematically filter through binary decisions. The QUESTION adapts per mode:

| Mode | Eliminatie Vraag |
|------|-----------------|
| 🔴 Probleem | "Is dit een waarschijnlijke (mede)oorzaak?" |
| 🔵 Onderzoek | "Is dit aspect relevant en belangrijk genoeg om verder uit te diepen?" |
| 🟡 Prompt | "Is dit component goed ingevuld / functioneel in de prompt?" |
| 🟢 Beslissing | "Is dit een doorslaggevende factor voor de keuze?" |
| 🟣 Strategie | "Is dit een reëel risico / kans dat aandacht verdient?" |

### The Elimination Protocol

Present each element one by one with the collected evidence summary, then ask:

**Format:**
```
🔍 Element: [name]
📂 Categorie: [Ishikawa category]
📋 Bewijs/bevindingen vóór: [summary of supporting evidence]
📋 Bewijs/bevindingen tegen: [summary of contradicting evidence]
🤖 Agent advies: [relevant agent's recommendation]

➡️ [Mode-specific elimination question]
```

Ask in plain text: **"➡️ [eliminatie vraag] Type: ja / nee / onzeker"**

Wait for the user's typed reply.

### Loop Rules

1. **"Ja"** → Mark as CONFIRMED cause. Keep in the active list. Later: prioritize for action.
2. **"Nee"** → Mark as ELIMINATED. Remove from active list. Log the reason.
3. **"Onzeker"** → Park it. Come back after all others are evaluated. Then force a Ja/Nee based on new context.

### The Loop Continues Until:

- All causes are either CONFIRMED or ELIMINATED
- Any "Onzeker" items are revisited and resolved
- The user agrees the remaining confirmed causes represent the true root cause(s)

### After Elimination: Convergence Check

When the loop ends, present the final result adapted to the mode:

**🔴 Probleem:**
```
✅ BEVESTIGDE OORZAKEN: [list with evidence]
❌ UITGESLOTEN OORZAKEN: [list with reason]
```

**🔵 Onderzoek:**
```
✅ RELEVANTE ASPECTEN: [key findings worth pursuing]
❌ NIET RELEVANT / BUITEN SCOPE: [aspects eliminated]
```

**🟡 Prompt:**
```
✅ GOED WERKENDE COMPONENTEN: [what works in the prompt]
❌ ONTBREKEND / ZWAK: [what needs improvement]
⚡ VERBETERVOORSTELLEN: [specific rewrites per component]
```

**🟢 Beslissing:**
```
✅ DOORSLAGGEVENDE FACTOREN: [factors that matter most]
❌ NIET DOORSLAGGEVEND: [factors that don't tip the scale]
🏆 AANBEVELING: [which option wins on basis of confirmed factors]
```

**🟣 Strategie:**
```
✅ REËLE RISICO'S & KANSEN: [confirmed threats and opportunities]
❌ ONWAARSCHIJNLIJK: [eliminated concerns]
```

Ask the user: **"Klopt dit beeld? Missen we iets, of kunnen we door naar conclusies/acties?"**

---

## Phase 4: Action Plan / Conclusion (altijd aanbieden)

The deliverable of Phase 4 depends on the analysis mode:

### 🔴 Probleem → Actieplan
| Oorzaak | Actie | Type | Agent | Eigenaar | Deadline | Status |
|---------|-------|------|-------|----------|----------|--------|
| [cause] | [fix] | Quick Win / Structureel | [agent rol] | [who] | [when] | Open |

### 🔵 Onderzoek → Kennisrapport
Lever een gestructureerde samenvatting op:
- **Kernbevindingen** — De bevestigde relevante aspecten, helder uitgelegd
- **Open vragen** — Wat is nog onbeantwoord?
- **Aanbevolen vervolgstappen** — Wat moet er nog onderzocht worden?
- **Bronnen/referenties** — Indien van toepassing

### 🟡 Prompt → Verbeterde Prompt
Lever op:
- **Originele prompt** — Zoals aangeleverd
- **Analyse per component** — Wat werkt, wat mist, wat is zwak
- **Verbeterde prompt** — Herschreven versie met alle verbeteringen verwerkt
- **Changelog** — Wat is er veranderd en waarom
- **Test suggesties** — Hoe de verbeterde prompt te testen

### 🟢 Beslissing → Adviesrapport
- **Overzicht opties** — Elke optie met score op bevestigde factoren
- **Aanbeveling** — Welke optie wint en waarom
- **Risico's per optie** — Wat kan misgaan
- **Implementatie stappen** — Hoe de gekozen optie uit te voeren

### 🟣 Strategie → Strategisch Advies
- **Bevestigde sterktes** — Waar op voortbouwen
- **Bevestigde zwaktes** — Waar op te letten
- **Kansen** — Bevestigde kansen om te grijpen
- **Risico mitigatie** — Per bevestigd risico een tegenactie

### Agent Toewijzing (alle modes)
Use the Ishikawa category to suggest which agent/discipline owns the follow-up:
- Mens → HR, Training, Teamlead
- Methode → Process Owner, QA
- Machine → IT, DevOps, Engineering
- Materiaal → Procurement, Data Team
- Meting → Analytics, QA, Management
- Milieu → Strategy, Legal, External Affairs

---

## Phase 5: Automatic Memory Save (VERPLICHT — nooit overslaan)

After EVERY completed analysis — regardless of whether the user explicitly asks for it —
the entire analysis must be persisted to the memory system. This is automatic and non-negotiable.

### How to Save

Use the **Write tool** to create a structured `.md` memory file. The memory directory is:
`/home/mohammed/.claude/projects/-mnt-d-Projects-zyratv/memory/`

**File naming:** `analysis_<slug>_<YYYYMMDD>.md`
(e.g. `analysis_stream_error_handling_20260331.md`)

**File format** (use this exact frontmatter + body structure):

```markdown
---
name: Analysis: <TITEL>
description: <one-line summary of what was analysed and the key finding>
type: project
---

## Analyse: <TITEL>

**Mode:** 🔴 Probleem / 🔵 Onderzoek / 🟡 Prompt / 🟢 Beslissing / 🟣 Strategie
**Domein:** <SOFTWARE/BUSINESS/IT/AI/etc>
**Datum:** <YYYY-MM-DD>

### Agent Team
| Agent | Rol | Ishikawa Focus |
|-------|-----|----------------|
| <emoji> <naam> | <verantwoordelijkheid> | <Mens, Methode, ...> |

### Ishikawa Oorzaken
| Categorie | Oorzaken |
|-----------|----------|
| Mens | <oorzaak1>, <oorzaak2> |
| Methode | <oorzaak1> |
| Machine | <oorzaak1> |
| Materiaal | <oorzaak1> |
| Meting | <oorzaak1> |
| Milieu | <oorzaak1> |

### Deep-Dive Bevindingen
Per oorzaak: antwoorden op de 9 vragen + verantwoordelijke agent + waarom-ketting (3 niveaus).

### Eliminatie Resultaten
**✅ Bevestigd:** <oorzaak1> — <reden>; <oorzaak2> — <reden>
**❌ Uitgesloten:** <oorzaak3> — <reden uitsluiting>

### Root Causes / Conclusie
<De uiteindelijk bevestigde oorzaken of bevindingen>

### Actieplan
| Actie | Type | Agent | Eigenaar | Deadline |
|-------|------|-------|----------|----------|
| <beschrijving> | Quick Win / Structureel | <agent rol> | <wie> | <wanneer> |

### Meta
- Oorzaken geanalyseerd: X | Bevestigd: Y | Uitgesloten: Z
- Tools gebruikt: WebSearch, ToolSearch, Grep, Bash, Read, Write
- Tools aanbevolen: <niet-verbonden tools die zijn gesuggereerd>
```

After writing, also **update** `MEMORY.md` in the same directory to add a pointer line:
```
- [analysis_<slug>_<date>.md](analysis_<slug>_<date>.md) — <one-line description>
```

### What to Save — Completeness Checklist

Every memory entry MUST contain ALL of the following. Do not skip fields:

1. **Probleemstelling** — De exacte probleemomschrijving
2. **Domein** — Het geïdentificeerde domein (Software, Business, IT, etc.)
3. **Agent Team** — Alle gespawnde rollen met hun verantwoordelijkheden en focus
4. **Ishikawa Oorzaken** — Alle oorzaken per 6M-categorie (ook de uitgesloten), per agent
5. **Deep-Dive Bevindingen** — Per oorzaak de antwoorden op alle 9 vragen + welke agent leidde
6. **Waarom-Ketting** — De volledige "waarom?" chain (minimaal 3 niveaus diep)
7. **Eliminatie Resultaten** — Elke oorzaak met status (bevestigd/uitgesloten), reden, en agent-advies
8. **Root Causes** — De uiteindelijke bevestigde oorzaken
9. **Actieplan** — Alle acties met type, eigenaar, toegewezen agent, en deadline
10. **Meta** — Totalen, statistieken, gebruikte tools, en voorgestelde connectors

### When to Save

Save happens at THREE moments during an analysis:

1. **Na Phase 1** (Ishikawa compleet) — Tussentijdse save met type `pre-compact`
   zodat de diagram-data niet verloren gaat als het gesprek lang wordt.
   Titel: `"Analysis WIP: {probleem} — Ishikawa compleet"`

2. **Na Phase 3** (Eliminatie compleet) — Tussentijdse save met alle bewijs en eliminatie.
   Titel: `"Analysis WIP: {probleem} — Eliminatie compleet"`

3. **Na Phase 4** (Actieplan klaar) — Finale complete save met ALLES.
   Titel: `"Analysis FINAL: {probleem}"`

### Retrieving Past Analyses

When the user asks about previous analyses ("wat was de conclusie van die analyse over X?",
"laat vorige analyses zien", "hebben we dit eerder geanalyseerd?"), use the Read and Glob tools:

```
# List all analysis memory files
Glob("analysis_*.md", path="/home/mohammed/.claude/projects/-mnt-d-Projects-zyratv/memory/")

# Read a specific analysis
Read("/home/mohammed/.claude/projects/-mnt-d-Projects-zyratv/memory/analysis_<slug>_<date>.md")

# Search for analyses by topic
Grep(pattern="<topic keyword>", path="/home/mohammed/.claude/projects/-mnt-d-Projects-zyratv/memory/", glob="analysis_*.md")
```

### Memory Notification

After each save, confirm to the user with:
```
🔒 Analyse opgeslagen in geheugen: "{titel}"
   📊 {X} oorzaken geanalyseerd | ✅ {Y} bevestigd | ❌ {Z} uitgesloten
```

---

## Visual Output Requirements

All visuals are rendered as **ASCII/markdown in the terminal** (no SVG, no widgets):

1. **Ishikawa Diagram** — ASCII fishbone diagram after Phase 1 (see Phase 1 Step 2 for format)
2. **Tool Inventory** — Markdown bullet list of discovered tools after tool discovery
3. **Evidence Matrix** — Markdown table after Phase 2:
   ```
   | Oorzaak | Bewijs Vóór | Bewijs Tegen | Status |
   |---------|-------------|--------------|--------|
   | ...     | ...         | ...          | 🔍     |
   ```
4. **Elimination Scoreboard** — Running count shown as a status line during Phase 3:
   ```
   📊 Voortgang: ✅ Y bevestigd | ❌ Z uitgesloten | 🔍 N nog te beoordelen
   ```
5. **Final Report** — Clean markdown summary combining all findings, actions, and root causes

---

## Conversation Flow Summary

```
START
  │
  ▼
[0a] Analyse MODE bepalen (Probleem/Onderzoek/Prompt/Beslissing/Strategie)
  │                        └─ numbered list → user types 1-5
  ▼
[0b] Domein bepalen + Agent rollen spawnen
  │                  └─ numbered list → user types 1-10
  ▼
[0c] Team presenteren als markdown tabel → gebruiker bevestigt (ja / aanpassen)
  │
  ▼
[🔧] TOOL DISCOVERY — ToolSearch per domein, WebSearch achtergrond, MCP check
  │
  ▼
[1] Onderwerp definiëren (aangepast aan mode)
  │
  ▼
[2] Ishikawa: 6 categorieën — elke agent levert + tools verrijken
  │                            └─ WebSearch voor context, Grep/Bash voor codebase data
  ▼
[3] Fishbone diagram renderen als ASCII art in terminal
  │
  ▼
[💾] MEMORY SAVE — Tussentijds: Write .md to memory dir
  │
  ▼
[4] Per element: 9 Vragen (aangepast aan mode) — relevante agent leidt
  │              └─ plain text per vraaggroep + WebSearch verificatie
  ▼
[5] Bewijs verzamelen in markdown evidence table
  │
  ▼
[6] Eliminatie Loop: Agent adviseert → gebruiker beslist Ja / Nee / Onzeker
  │     │            └─ plain text per element, user types ja/nee/onzeker
  │     ├─ Ja → Bevestigd / Relevant / Goed
  │     ├─ Nee → Uitgesloten / Niet relevant / Zwak
  │     └─ Onzeker → ToolSearch + WebSearch voor meer data, dan opnieuw vragen
  │
  ▼
[7] Herhaal loop tot alles Ja of Nee is
  │
  ▼
[💾] MEMORY SAVE — Tussentijds: Write .md to memory dir
  │
  ▼
[8] Convergentie check met gebruiker (mode-specifiek) — plain text
  ▼
[9] Deliverable genereren (Actieplan / Rapport / Verbeterde Prompt / Advies)
  │                        └─ WebSearch best practices
  ▼
[💾] MEMORY SAVE — Finaal: Write complete .md + update MEMORY.md index
  │
  ▼
END — "✅ Analyse opgeslagen in geheugen: <bestandsnaam>"
```

## Language

Default to **Dutch (NL)** for all user-facing text, questions, and labels. Switch to English only if the user communicates in English. The analytical framework labels (6M categories, 9 questions) always remain available in both languages.

## Important Behavioral Notes

- ALTIJD starten met Phase 0 (Agent Assembly) — analyseer nooit zonder team
- ALTIJD `ToolSearch` draaien na Phase 0 — ontdek beschikbare tools VOOR je begint
- ALTIJD plain text numbered lists gebruiken voor keuzes — de gebruiker typt hun antwoord
- Never skip the elimination loop — it's the core value of this skill
- Never skip the memory save — ELKE analyse MOET worden opgeslagen via Write tool
- Always render ASCII fishbone — the Ishikawa diagram is not optional, it must be drawn in text
- Agents zijn GEEN decoratie — elke agent MOET actief bijdragen in elke fase
- Presenteer oorzaken altijd met de emoji + rol van de agent die het aandraagt
- In de eliminatie loop: laat de verantwoordelijke agent EERST adviseren, dan beslist de gebruiker
- Bij het actieplan: wijs elke actie toe aan de agent wiens rol het meest past
- Be patient in Phase 2 — don't rush through questions, each cause deserves proper interrogation
- The "Waarom?" question (question 4) should go at least 3 levels deep (like Toyota's 5 Whys)
- Keep a running count visible: "📊 X bevestigd | Y uitgesloten | Z resterend"
- If the user gets impatient, offer to fast-track by only deep-diving the top 3 most likely causes
- Memory saves happen 3x per analyse: na Ishikawa, na Eliminatie, en Finaal met alles
- Bij een nieuwe analyse, Glob+Read eerdere analyses uit memory — misschien is het probleem al eerder onderzocht
- Als de context lang wordt, maak een extra tussentijdse memory save met alle huidige data
- Als het domein verandert mid-analyse, bied aan om het team aan te passen
- Bij "Onzeker" in eliminatie: gebruik `WebSearch` en `ToolSearch` PROACTIEF om meer data te vinden
- Stel MCP-tools voor in plain text als ze de analyse significant zouden verbeteren — maar forceer niet
- Log alle gebruikte tools in de memory save onder meta.tools_used
