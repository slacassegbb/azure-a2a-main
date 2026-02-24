import {
  Mail,
  DollarSign,
  Code,
  Search,
  Scale,
  Shield,
  Palette,
  Users,
  Monitor,
  Brain,
  FileSpreadsheet,
  MapPin,
  Briefcase,
  Hand,
  Bot,
  type LucideIcon,
} from "lucide-react"

const TAG_TO_CATEGORY: Record<string, string> = {
  email: "Communication",
  teams: "Communication",
  twilio: "Communication",
  sms: "Communication",
  quickbooks: "Finance",
  stripe: "Finance",
  billing: "Finance",
  stockmarket: "Finance",
  stocks: "Finance",
  stock: "Finance",
  github: "Developer Tools",
  search: "Research",
  web: "Research",
  knowledge: "Research",
  "deep-search": "Research",
  legal: "Legal & Compliance",
  compliance: "Legal & Compliance",
  claims: "Insurance",
  insurance: "Insurance",
  fraud: "Security",
  image: "Creative",
  branding: "Creative",
  video: "Creative",
  salesforce: "CRM",
  hubspot: "CRM",
  crm: "CRM",
  servicenow: "IT Operations",
  classification: "AI & Analytics",
  sentiment: "AI & Analytics",
  assessment: "AI & Analytics",
  estimation: "AI & Analytics",
  timeseries: "AI & Analytics",
  "time-series": "AI & Analytics",
  excel: "Productivity",
  word: "Productivity",
  powerpoint: "Productivity",
  document: "Productivity",
  reporter: "Productivity",
  google: "Location & Maps",
  maps: "Location & Maps",
  interview: "HR",
  "human-interaction": "Human-in-the-Loop",
}

export const CATEGORY_ICONS: Record<string, LucideIcon> = {
  Communication: Mail,
  Finance: DollarSign,
  "Developer Tools": Code,
  Research: Search,
  "Legal & Compliance": Scale,
  Insurance: Shield,
  Security: Shield,
  Creative: Palette,
  CRM: Users,
  "IT Operations": Monitor,
  "AI & Analytics": Brain,
  Productivity: FileSpreadsheet,
  "Location & Maps": MapPin,
  HR: Briefcase,
  "Human-in-the-Loop": Hand,
  General: Bot,
}

export function deriveCategory(agent: any): string {
  const skills = agent.skills || []
  for (const skill of skills) {
    for (const tag of skill.tags || []) {
      const normalized = tag.toLowerCase()
      if (TAG_TO_CATEGORY[normalized]) {
        return TAG_TO_CATEGORY[normalized]
      }
    }
  }
  // Fallback: try agent name keywords
  const nameLower = (agent.name || "").toLowerCase()
  for (const [keyword, category] of Object.entries(TAG_TO_CATEGORY)) {
    if (nameLower.includes(keyword)) return category
  }
  return "General"
}

export function getAllCategories(agents: any[]): string[] {
  const cats = new Set(agents.map(deriveCategory))
  return Array.from(cats).sort()
}
