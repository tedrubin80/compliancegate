import { cpSync, existsSync, mkdirSync, readdirSync, statSync } from "fs";
import { homedir } from "os";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const NPM_ROOT = join(__dirname, "..");
const REPO_SKILLS = join(NPM_ROOT, "..", "skills");

export const SKILL_IDS = {
  compliancegate: "compliancegate",
  "compliance-review": "compliance-review",
};

export const PERSONAL_TARGETS = {
  cursor: {
    compliancegate: join(homedir(), ".cursor", "skills", "compliancegate"),
    "compliance-review": join(homedir(), ".cursor", "skills", "compliance-review"),
  },
  claude: {
    compliancegate: join(homedir(), ".claude", "skills", "compliancegate"),
    "compliance-review": join(homedir(), ".claude", "skills", "compliance-review"),
  },
};

function skillsRoot() {
  const inPackage = join(NPM_ROOT, "skills");
  if (existsSync(inPackage)) return inPackage;
  if (existsSync(REPO_SKILLS)) return REPO_SKILLS;
  throw new Error(`Skills source not found. Expected ${inPackage} or ${REPO_SKILLS}`);
}

function copyDir(src, dest) {
  mkdirSync(dest, { recursive: true });
  for (const entry of readdirSync(src)) {
    const s = join(src, entry);
    const d = join(dest, entry);
    if (statSync(s).isDirectory()) copyDir(s, d);
    else cpSync(s, d);
  }
}

export function installSkill(skillId, harness, destOverride) {
  if (!SKILL_IDS[skillId]) {
    throw new Error(`Unknown skill: ${skillId}. Use: ${Object.keys(SKILL_IDS).join(", ")}`);
  }

  const src = join(skillsRoot(), skillId);
  if (!existsSync(join(src, "SKILL.md"))) {
    throw new Error(`Skill source missing: ${join(src, "SKILL.md")}`);
  }

  let dest = destOverride;
  if (!dest) {
    if (harness === "project") {
      dest = join(process.cwd(), ".cursor", "skills", skillId);
    } else {
      dest = PERSONAL_TARGETS[harness]?.[skillId];
    }
  }
  if (!dest) throw new Error(`Unknown harness: ${harness}. Use cursor, claude, or project.`);

  copyDir(src, dest);
  return dest;
}

export function installSkills(options = {}) {
  const harness = options.harness || "cursor";
  const which = options.skills || "compliancegate";
  const ids = which === "all"
    ? Object.keys(SKILL_IDS)
    : which.split(",").map(s => s.trim()).filter(Boolean);

  const installed = [];
  for (const id of ids) {
    installed.push({
      id,
      dest: installSkill(id, harness, options.dest),
    });
  }
  return installed;
}

export function checkSkillInstall(skillId, dest) {
  return existsSync(join(dest, "SKILL.md"));
}

export function checkSkills(harness = "cursor") {
  const rows = [];
  if (harness === "project") {
    for (const id of Object.keys(SKILL_IDS)) {
      const dest = join(process.cwd(), ".cursor", "skills", id);
      rows.push({ id, harness: "project", dest, installed: checkSkillInstall(id, dest) });
    }
    return rows;
  }

  for (const [name, targets] of Object.entries(PERSONAL_TARGETS)) {
    if (harness !== "all" && harness !== name) continue;
    for (const [id, dest] of Object.entries(targets)) {
      rows.push({ id, harness: name, dest, installed: checkSkillInstall(id, dest) });
    }
  }
  return rows;
}

export function skillsRootPath() {
  return skillsRoot();
}
