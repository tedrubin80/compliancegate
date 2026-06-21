#!/usr/bin/env node
/** Copy repo skills/ into npm/skills/ for self-contained npm publish. */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const npmRoot = join(__dirname, "..");
const src = join(npmRoot, "..", "skills");
const dest = join(npmRoot, "skills");

if (!existsSync(src)) {
  console.error(`Missing skills source: ${src}`);
  process.exit(1);
}

function copyDir(from, to) {
  mkdirSync(to, { recursive: true });
  for (const entry of readdirSync(from)) {
    const s = join(from, entry);
    const d = join(to, entry);
    if (statSync(s).isDirectory()) copyDir(s, d);
    else cpSync(s, d);
  }
}

if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
copyDir(src, dest);
console.log(`Synced skills → ${dest}`);
