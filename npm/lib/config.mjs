import { readFileSync, writeFileSync } from "fs";

export function updateRulePacks(configPath, packs) {
  const list = packs.filter(Boolean);
  if (!list.length) return;

  let text = readFileSync(configPath, "utf8");
  const block = "  rule_packs:\n" + list.map(p => `    - ${p}`).join("\n") + "\n";

  if (/  rule_packs:\n(?:    - .+\n)+/.test(text)) {
    text = text.replace(/  rule_packs:\n(?:    - .+\n)+/, block);
  } else if (/^compliance:\n/m.test(text)) {
    text = text.replace(/^compliance:\n/m, `compliance:\n${block}`);
  } else {
    text += `\ncompliance:\n${block}`;
  }

  writeFileSync(configPath, text);
}
