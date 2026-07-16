/**
 * Tropelex OpenCode Plugin
 * Automatically compresses prompts and injects project memory context
 * before every prompt reaches the AI.
 *
 * Install: place in ~/.config/opencode/plugins/tropelex.js
 * or reference from opencode.json as a plugin path.
 */

const TROPELEX_URL = process.env.TROPELEX_URL || "http://localhost:8766";
const TROPELEX_PROJECT = process.env.TROPELEX_PROJECT || null;
const COMPRESS_THRESHOLD = parseInt(process.env.TROPELEX_COMPRESS_MIN || "80");
const INJECT_CONTEXT = process.env.TROPELEX_INJECT_CONTEXT !== "false";

/** Detect the current project name from cwd or git remote */
async function detectProject() {
    if (TROPELEX_PROJECT) return TROPELEX_PROJECT;
    try {
        const { execSync } = await import("child_process");
        // Try git remote name
        const remote = execSync("git remote get-url origin 2>/dev/null", { encoding: "utf8" })
            .trim()
            .split("/")
            .pop()
            ?.replace(/\.git$/, "");
        if (remote && /^[a-zA-Z0-9_-]+$/.test(remote)) return remote;
        // Fall back to directory name
        return process.cwd().split("/").pop() || "default";
    } catch {
        return process.cwd().split("/").pop() || "default";
    }
}

/** Fetch from Tropelex server, returns null on failure */
async function tropelex(path, opts = {}) {
    try {
        const res = await fetch(`${TROPELEX_URL}${path}`, {
            headers: { "Content-Type": "application/json" },
            ...opts,
        });
        if (!res.ok) return null;
        return res.json();
    } catch {
        return null;
    }
}

/** Check server is alive */
async function isServerUp() {
    const data = await tropelex("/api/health");
    return data?.status === "ok";
}

/** Compress a prompt via Tropelex AI compression */
async function compress(prompt) {
    if (prompt.length < COMPRESS_THRESHOLD) return { prompt, compressed: false };
    const data = await tropelex("/api/compress", {
        method: "POST",
        body: JSON.stringify({ prompt }),
    });
    if (data?.compressed && data.compressed !== prompt) {
        return {
            prompt: data.compressed,
            compressed: true,
            backend: data.backend,
            saved_pct: data.saved_pct,
        };
    }
    return { prompt, compressed: false };
}

/** Pull project memory context */
async function getContext(project) {
    const data = await tropelex(
        `/api/memory/${encodeURIComponent(project)}/context?include_deps=true`
    );
    return data?.context || null;
}

/** Record a session summary at end */
async function recordSession(project, summary) {
    await tropelex(`/api/memory/${encodeURIComponent(project)}`, {
        method: "PATCH",
        body: JSON.stringify({ description: summary }),
    });
}

// ── Plugin export ────────────────────────────────────────────────────────────

export default {
    name: "tropelex",
    version: "1.1.0",
    description: "Persistent memory, prompt compression, and context injection for OpenCode",

    /**
     * Called before every prompt is sent to the AI.
     * Can modify the prompt and/or inject system context.
     */
    async beforePrompt(ctx) {
        if (!(await isServerUp())) return ctx;

        const project = await detectProject();
        let   prompt  = ctx.prompt || "";
        const logs    = [];

        // 1. Compress the prompt
        const compResult = await compress(prompt);
        if (compResult.compressed) {
            prompt = compResult.prompt;
            logs.push(
                `[Tropelex] Compressed via ${compResult.backend} (saved ${compResult.saved_pct}%)`
            );
        }

        // 2. Inject memory context into system prompt
        let system = ctx.system || "";
        if (INJECT_CONTEXT) {
            const context = await getContext(project);
            if (context) {
                system = `${context}\n\n---\n\n${system}`;
                logs.push(`[Tropelex] Injected context for project: ${project}`);
            }
        }

        if (logs.length > 0) {
            console.log(logs.join("\n"));
        }

        return { ...ctx, prompt, system };
    },

    /**
     * Called after a session completes.
     * Records a brief summary into Tropelex memory.
     */
    async afterSession(ctx) {
        if (!(await isServerUp())) return;
        const project = await detectProject();
        const summary = ctx.summary || ctx.lastMessage || "";
        if (summary) {
            await recordSession(project, summary.slice(0, 500));
        }
    },

    /**
     * Slash command: /tropelex <subcommand>
     * Usage: /tropelex compress, /tropelex context, /tropelex sync <path>
     */
    async onCommand(cmd, args, ctx) {
        if (cmd !== "tropelex") return null;

        const project = await detectProject();
        const sub     = args[0];

        if (sub === "compress" && ctx.prompt) {
            const r = await compress(ctx.prompt);
            return { message: `Compressed (${r.backend}): ${r.prompt}` };
        }

        if (sub === "context") {
            const c = await getContext(project);
            return { message: c || "No context available" };
        }

        if (sub === "sync" && args[1]) {
            const data = await tropelex("/api/git/sync", {
                method: "POST",
                body: JSON.stringify({ repo_path: args[1], project }),
            });
            return { message: data ? JSON.stringify(data, null, 2) : "Sync failed" };
        }

        if (sub === "template") {
            const data = await tropelex(`/api/memory/${encodeURIComponent(project)}/template`);
            return { message: data?.template || "No template available" };
        }

        return {
            message: `Tropelex commands:\n  /tropelex compress\n  /tropelex context\n  /tropelex sync <repo-path>\n  /tropelex template`,
        };
    },
};
