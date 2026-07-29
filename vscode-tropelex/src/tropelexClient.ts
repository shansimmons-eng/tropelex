import * as vscode from 'vscode';

/**
 * Minimal REST client for Tropelex's Memory Lens endpoints.
 *
 * Mirrors the pattern already used by the Emacs package
 * (emacs/tropelex-capture.el) and the MCP server (mcp_server/server.py):
 * call the running Tropelex server over HTTP rather than reading memory
 * files directly, since Lens matching (core/lens/annotator.py) runs
 * server-side against a project's full decision list.
 */

export interface LensAnnotation {
  decision_id: string;
  decision_text: string;
  confidence: number;
  line_number: number;
  file_path: string;
  relationship: string;
  reference_count: number;
}

interface LensScanResponse {
  file_path: string;
  annotations: LensAnnotation[];
  total: number;
}

/** Thrown for both network failures and non-2xx API responses. */
export class TropelexClientError extends Error {}

function getServerUrl(): string {
  const configured = vscode.workspace
    .getConfiguration('tropelex')
    .get<string>('serverUrl', 'http://localhost:8766');
  return configured.replace(/\/+$/, '');
}

/**
 * Resolves the Tropelex project name for the current workspace.
 *
 * Uses the `tropelex.project` setting if set, otherwise falls back to the
 * first workspace folder's name — the same convention project names
 * follow elsewhere (they're arbitrary strings, not required to match a
 * repo name, but folder name is a reasonable default).
 */
export function getProjectName(): string | undefined {
  const configured = vscode.workspace
    .getConfiguration('tropelex')
    .get<string>('project', '');
  if (configured) {
    return configured;
  }
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder?.name;
}

/**
 * Scans a file's full content for decision references via
 * POST /api/memory/{project}/lens/scan.
 *
 * Throws TropelexClientError with a message suitable for showing directly
 * to the user (connection refused, project not found, etc.).
 */
export async function scanFileForDecisions(
  project: string,
  filePath: string,
  codeContent: string
): Promise<LensAnnotation[]> {
  const url = `${getServerUrl()}/api/memory/${encodeURIComponent(project)}/lens/scan`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, code_content: codeContent }),
    });
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new TropelexClientError(
      `Could not reach the Tropelex server at ${getServerUrl()}. Is it running? (${detail})`
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON; fall back to statusText.
    }
    throw new TropelexClientError(`Tropelex Lens scan failed (${response.status}): ${detail}`);
  }

  const data = (await response.json()) as LensScanResponse;
  return data.annotations;
}
