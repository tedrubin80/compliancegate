import { existsSync } from "fs";
import { join } from "path";
import { spawnSync } from "child_process";

const PYTHON_CANDIDATES = ["python3", "python"];

export function findPython() {
  for (const cmd of PYTHON_CANDIDATES) {
    const probe = spawnSync(cmd, ["-c", "import sys; print(sys.version_info[:2])"], {
      encoding: "utf8",
    });
    if (probe.status !== 0) continue;
    const match = probe.stdout.match(/\(\s*(\d+)\s*,\s*(\d+)/);
    if (!match) continue;
    const major = Number(match[1]);
    const minor = Number(match[2]);
    if (major > 3 || (major === 3 && minor >= 10)) {
      return cmd;
    }
  }
  return null;
}

export function venvDir(repoRoot) {
  return join(repoRoot, ".venv");
}

export function venvPython(repoRoot) {
  return join(venvDir(repoRoot), "bin", "python");
}

export function cgBinary(repoRoot) {
  const inVenv = join(venvDir(repoRoot), "bin", "compliancegate");
  return existsSync(inVenv) ? inVenv : "compliancegate";
}

export function runCommand(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, {
    cwd: options.cwd,
    env: { ...process.env, ...options.env },
    encoding: "utf8",
    stdio: options.quiet ? "pipe" : "inherit",
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    const msg = detail ? `${cmd} ${args.join(" ")} failed:\n${detail}` : `${cmd} ${args.join(" ")} failed`;
    throw new Error(msg);
  }
  return result;
}

export function runCapture(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, {
    cwd: options.cwd,
    env: { ...process.env, ...options.env },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(detail || `${cmd} ${args.join(" ")} failed`);
  }
  return (result.stdout || "").trim();
}
