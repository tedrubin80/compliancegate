import { existsSync } from "fs";
import { join, resolve } from "path";
import { updateRulePacks } from "./config.mjs";
import {
  cgBinary,
  findPython,
  runCapture,
  runCommand,
  venvDir,
  venvPython,
} from "./python.mjs";

export const DEFAULT_INSTALL_SOURCE =
  process.env.CG_INSTALL_SOURCE ||
  "git+https://github.com/tedrubin80/compliancegate.git";

const VALID_MODES = new Set(["sqlite", "markdown", "remote", "sqlite_markdown", "all"]);

export function resolveRepo(repoArg) {
  const repo = resolve(repoArg || process.cwd());
  if (!existsSync(join(repo, ".git"))) {
    throw new Error(`${repo} is not a git repository (missing .git)`);
  }
  return repo;
}

export function resolveInstallSource(sourceArg) {
  if (sourceArg) return sourceArg;
  return DEFAULT_INSTALL_SOURCE;
}

export function installComplianceGate(options = {}) {
  const repo = resolveRepo(options.repo);
  const mode = options.mode || "sqlite_markdown";
  const packs = (options.packs || "base")
    .split(",")
    .map(p => p.trim())
    .filter(Boolean);
  const useVenv = options.venv !== false;
  const source = resolveInstallSource(options.source);

  if (!VALID_MODES.has(mode)) {
    throw new Error(`Invalid mode: ${mode}. Use one of: ${[...VALID_MODES].join(", ")}`);
  }

  const python = findPython();
  if (!python) {
    throw new Error("Python 3.10+ is required. Install python3 and retry.");
  }

  console.log("==> ComplianceGate install (compliancegate.dev)");
  console.log(`    Repo:    ${repo}`);
  console.log(`    Mode:    ${mode}`);
  console.log(`    Packs:   ${packs.join(", ")}`);
  console.log(`    Source:  ${source}`);

  let pipPython = python;
  if (useVenv) {
    if (!existsSync(venvDir(repo))) {
      console.log("\n==> Creating .venv");
      runCommand(python, ["-m", "venv", ".venv"], { cwd: repo });
    }
    pipPython = venvPython(repo);
    runCommand(pipPython, ["-m", "pip", "install", "-q", "--upgrade", "pip"], { cwd: repo });
  }

  console.log("\n==> Installing Python package");
  runCommand(pipPython, ["-m", "pip", "install", "-q", source], { cwd: repo });

  if (mode === "remote" || mode === "all") {
    console.log("==> Installing optional database drivers");
    runCommand(
      pipPython,
      ["-m", "pip", "install", "-q", `${source}[postgres,mysql]`],
      { cwd: repo, quiet: true },
    );
  }

  const cg = cgBinary(repo);
  console.log("\n==> Initializing project");
  runCommand(cg, ["init", "--repo", repo, "--mode", mode], { cwd: repo });

  const configPath = join(repo, "config.yaml");
  if (existsSync(configPath)) {
    updateRulePacks(configPath, packs);
    console.log(`==> Updated rule_packs in ${configPath}`);
  }

  console.log("\n==> Done");
  try {
    runCommand(cg, ["status"], { cwd: repo });
  } catch {
    // status may warn if session db not ready yet
  }

  console.log("\nNext:");
  console.log(`  ${cg} watch`);
  console.log("  npx compliancegate skills install --project   # agent skill in repo");
  console.log("  CG_SKIP=1 git commit   # emergency bypass (logged)");
  return { repo, cg, configPath };
}

export function checkInstallation(repoArg) {
  const repo = resolve(process.cwd());
  const target = repoArg ? resolve(repoArg) : repo;
  const checks = [];

  checks.push({
    name: "git repo",
    ok: existsSync(join(target, ".git")),
    detail: join(target, ".git"),
  });

  const venv = venvDir(target);
  checks.push({
    name: "venv",
    ok: existsSync(venvPython(target)),
    detail: venv,
  });

  const config = join(target, "config.yaml");
  checks.push({
    name: "config.yaml",
    ok: existsSync(config),
    detail: config,
  });

  for (const hook of ["pre-commit", "pre-push"]) {
    const path = join(target, ".git", "hooks", hook);
    checks.push({
      name: `${hook} hook`,
      ok: existsSync(path),
      detail: path,
    });
  }

  let cgOk = false;
  let cgDetail = cgBinary(target);
  try {
    if (existsSync(venvPython(target))) {
      runCapture(venvPython(target), ["-m", "compliancegate", "--version"], { cwd: target });
      cgOk = true;
    }
  } catch {
    cgOk = false;
  }
  checks.push({
    name: "compliancegate CLI",
    ok: cgOk,
    detail: cgDetail,
  });

  return { repo: target, checks };
}
