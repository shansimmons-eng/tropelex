import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { getProjectName } from './tropelexClient';

/**
 * Singleton Webview panel for displaying Tropelex memory content.
 *
 * Handles JSON rendering with syntax highlighting, theme awareness,
 * and bidirectional message passing for refresh commands.
 */
export class MemoryWebviewPanel {
  public static readonly viewType = 'tropelexMemoryViewer';

  private static _instance: MemoryWebviewPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private _disposables: vscode.Disposable[] = [];
  private _memoryFilePath: string | undefined;

  /**
   * Creates or reveals the singleton panel instance.
   *
   * @param extensionUri - The root URI of the extension
   * @param memoryFilePath - Optional path to a specific memory file to display
   * @returns The active panel instance
   */
  public static createOrShow(
    extensionUri: vscode.Uri,
    memoryFilePath?: string
  ): MemoryWebviewPanel {
    const column = vscode.ViewColumn.One;

    if (MemoryWebviewPanel._instance) {
      MemoryWebviewPanel._instance._panel.reveal(column);
      if (memoryFilePath) {
        MemoryWebviewPanel._instance._loadMemoryFile(memoryFilePath);
      }
      return MemoryWebviewPanel._instance;
    }

    const panel = vscode.window.createWebviewPanel(
      MemoryWebviewPanel.viewType,
      'Tropelex Memory',
      column,
      {
        enableScripts: true,
        localResourceRoots: [extensionUri],
        retainContextWhenHidden: true,
      }
    );

    MemoryWebviewPanel._instance = new MemoryWebviewPanel(
      panel,
      extensionUri,
      memoryFilePath
    );
    return MemoryWebviewPanel._instance;
  }

  /**
   * Revive panel from serialized state (webview persistence).
   */
  public static revive(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri
  ): void {
    MemoryWebviewPanel._instance = new MemoryWebviewPanel(
      panel,
      extensionUri
    );
  }

  private constructor(
    panel: vscode.WebviewPanel,
    _extensionUri: vscode.Uri,
    memoryFilePath?: string
  ) {
    this._panel = panel;
    this._memoryFilePath = memoryFilePath;

    this._panel.webview.html = this._getHtmlContent(
      this._panel.webview,
      'Loading...'
    );

    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    this._panel.webview.onDidReceiveMessage(
      (message) => this._handleMessage(message),
      null,
      this._disposables
    );

    if (memoryFilePath) {
      this._loadMemoryFile(memoryFilePath);
    } else {
      this._discoverAndLoadMemory();
    }
  }

  /**
   * Discovers memory files in the workspace and loads the first one found.
   */
  private _discoverAndLoadMemory(): void {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
      this._updateContent('No workspace open. Open a project with Tropelex memory files.');
      return;
    }

    const memoryPattern = new vscode.RelativePattern(
      workspaceFolders[0],
      'memory/*.json'
    );

    vscode.workspace.findFiles(memoryPattern).then((files) => {
      if (files.length === 0) {
        this._updateContent(
          'No Tropelex memory files found. Expected memory/*.json in workspace root.'
        );
        return;
      }

      // Prefer the file matching this workspace's actual resolved project
      // name (tropelex.project setting, else the workspace folder name --
      // the same resolution getProjectName() already uses for every write),
      // not a hardcoded literal filename: that used to unconditionally
      // prefer "tropelex.json" over whatever the real project name was,
      // which silently pointed this exact panel at the wrong one of two
      // case-diverged projects for weeks.
      const projectName = getProjectName();
      const expectedFile = projectName
        ? files.find((f) => path.basename(f.fsPath) === `${projectName}.json`)
        : undefined;
      this._loadMemoryFile((expectedFile ?? files[0]).fsPath);
    });
  }

  /**
   * Reads a memory JSON file and renders it in the webview.
   */
  private _loadMemoryFile(filePath: string): void {
    this._memoryFilePath = filePath;
    const fileName = path.basename(filePath);

    fs.readFile(filePath, 'utf-8', (err, data) => {
      if (err) {
        this._updateContent(`Error reading ${fileName}: ${err.message}`);
        return;
      }

      try {
        const parsed = JSON.parse(data);
        const formatted = JSON.stringify(parsed, null, 2);
        this._updateContent(
          this._renderMemoryContent(fileName, formatted)
        );
      } catch {
        this._updateContent(
          this._renderMemoryContent(fileName, data)
        );
      }
    });
  }

  /**
   * Pushes new HTML content to the webview.
   */
  private _updateContent(content: string): void {
    this._panel.webview.html = this._getHtmlContent(
      this._panel.webview,
      content
    );
  }

  /**
   * Handles messages received from the webview.
   */
  private _handleMessage(message: { command: string; data?: unknown }): void {
    switch (message.command) {
      case 'refresh':
        if (this._memoryFilePath) {
          this._loadMemoryFile(this._memoryFilePath);
        } else {
          this._discoverAndLoadMemory();
        }
        return;

      case 'openFile':
        if (this._memoryFilePath) {
          vscode.commands.executeCommand(
            'vscode.open',
            vscode.Uri.file(this._memoryFilePath)
          );
        }
        return;

      case 'selectFile':
        this._showFilePicker();
        return;
    }
  }

  /**
   * Shows a quick pick to select from available memory files.
   */
  private async _showFilePicker(): Promise<void> {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
      return;
    }

    const memoryPattern = new vscode.RelativePattern(
      workspaceFolders[0],
      'memory/*.json'
    );

    const files = await vscode.workspace.findFiles(memoryPattern);
    if (files.length === 0) {
      vscode.window.showInformationMessage('No memory files found.');
      return;
    }

    const picked = await vscode.window.showQuickPick(
      files.map((f) => ({
        label: path.basename(f.fsPath),
        description: f.fsPath,
        uri: f,
      })),
      { placeHolder: 'Select a memory file to view' }
    );

    if (picked) {
      this._loadMemoryFile(picked.uri.fsPath);
    }
  }

  /**
   * Builds the full HTML document for the webview.
   *
   * @param webview - The webview instance for URI conversion
   * @param bodyContent - The inner content to render
   * @returns Complete HTML string with CSP, nonce, and theme support
   */
  private _getHtmlContent(
    _webview: vscode.Webview,
    bodyContent: string
  ): string {
    const nonce = _getNonce();
    const themeClass = _getThemeClass();

    return /* html */ `<!DOCTYPE html>
<html lang="en" class="${themeClass}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta
    http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline' 'nonce-${nonce}'; script-src 'nonce-${nonce}';"
  />
  <title>Tropelex Memory</title>
  <style nonce="${nonce}">
    :root {
      --bg: #1e1e1e;
      --fg: #d4d4d4;
      --border: #333;
      --card-bg: #252526;
      --toolbar-bg: #2d2d2d;
      --btn-bg: #0e639c;
      --btn-hover: #1177bb;
      --btn-fg: #ffffff;
      --link-fg: #3794ff;
      --key-fg: #9cdcfe;
      --string-fg: #ce9178;
      --number-fg: #b5cea8;
      --bool-fg: #569cd6;
      --null-fg: #d16969;
      --indent-guide: #404040;
      --file-badge-bg: #3a3a3a;
      --file-badge-fg: #cccccc;
    }

    html.light {
      --bg: #ffffff;
      --fg: #1e1e1e;
      --border: #e0e0e0;
      --card-bg: #f3f3f3;
      --toolbar-bg: #f8f8f8;
      --btn-bg: #007acc;
      --btn-hover: #005fa3;
      --btn-fg: #ffffff;
      --link-fg: #0066bf;
      --key-fg: #0451a5;
      --string-fg: #a31515;
      --number-fg: #098658;
      --bool-fg: #0000ff;
      --null-fg: #0000ff;
      --indent-guide: #d4d4d4;
      --file-badge-bg: #e0e0e0;
      --file-badge-fg: #333333;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont,
        'Segoe UI', Roboto, Helvetica, Arial, sans-serif);
      font-size: var(--vscode-font-size, 13px);
      background: var(--bg);
      color: var(--fg);
      line-height: 1.5;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      background: var(--toolbar-bg);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 10;
    }

    .toolbar h1 {
      font-size: 13px;
      font-weight: 600;
      margin: 0;
    }

    .toolbar-spacer { flex: 1; }

    .file-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 4px;
      background: var(--file-badge-bg);
      color: var(--file-badge-fg);
    }

    .btn {
      padding: 3px 10px;
      border: none;
      border-radius: 3px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      background: var(--btn-bg);
      color: var(--btn-fg);
      transition: background 0.15s;
    }
    .btn:hover { background: var(--btn-hover); }

    .content {
      padding: 16px;
    }

    pre {
      margin: 0;
      font-family: var(--vscode-editor-font-family, 'Cascadia Code',
        'Fira Code', Consolas, 'Courier New', monospace);
      font-size: var(--vscode-editor-font-size, 13px);
      white-space: pre-wrap;
      word-break: break-word;
      tab-size: 2;
    }

    /* Syntax highlighting tokens */
    .json-key   { color: var(--key-fg); }
    .json-str   { color: var(--string-fg); }
    .json-num   { color: var(--number-fg); }
    .json-bool  { color: var(--bool-fg); }
    .json-null  { color: var(--null-fg); }
    .json-brace { color: var(--fg); }
    .json-punct { color: var(--fg); }

    .error-msg {
      padding: 24px;
      color: var(--null-fg);
      text-align: center;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <div class="toolbar">
    <h1>Tropelex Memory</h1>
    <span class="file-badge" id="fileBadge">${_escapeHtml(this._memoryFilePath ? path.basename(this._memoryFilePath) : '')}</span>
    <span class="toolbar-spacer"></span>
    <button class="btn" id="selectFileBtn" title="Select memory file">Open File</button>
    <button class="btn" id="refreshBtn" title="Refresh content">&#x21bb; Refresh</button>
  </div>
  <div class="content" id="content">
    ${bodyContent}
  </div>
  <script nonce="${nonce}">
    (function() {
      const vscode = acquireVsCodeApi();
      const refreshBtn = document.getElementById('refreshBtn');
      const selectFileBtn = document.getElementById('selectFileBtn');

      if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
          vscode.postMessage({ command: 'refresh' });
        });
      }
      if (selectFileBtn) {
        selectFileBtn.addEventListener('click', function() {
          vscode.postMessage({ command: 'selectFile' });
        });
      }
    })();
  </script>
</body>
</html>`;
  }

  /**
   * Renders memory content with basic JSON syntax highlighting.
   */
  private _renderMemoryContent(
    _fileName: string,
    jsonText: string
  ): string {
    const highlighted = _highlightJson(jsonText);
    return `<pre>${highlighted}</pre>`;
  }

  /**
   * Disposes of the panel and cleans up subscriptions.
   */
  public dispose(): void {
    MemoryWebviewPanel._instance = undefined;
    this._panel.dispose();

    while (this._disposables.length) {
      const disposable = this._disposables.pop();
      if (disposable) {
        disposable.dispose();
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Utility helpers (module-private)
// ---------------------------------------------------------------------------

/**
 * Generates a random nonce string for CSP.
 */
function _getNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < 32; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

/**
 * Returns "light" or "dark" based on the active VS Code theme kind.
 */
function _getThemeClass(): string {
  const kind = vscode.window.activeColorTheme?.kind;
  // ColorThemeKind.Light = 1, ColorThemeKind.HighContrast = 2, Dark = 3
  if (kind === vscode.ColorThemeKind.Light) {
    return 'light';
  }
  return 'dark';
}

/**
 * Escapes HTML special characters to prevent injection.
 */
function _escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Applies basic syntax highlighting to a JSON string.
 *
 * Uses simple regex-based tokenization — no external dependencies required.
 * Handles nested objects/arrays by operating on individual lines.
 */
function _highlightJson(text: string): string {
  const escaped = _escapeHtml(text);

  return escaped.replace(
    /("(?:[^"\\]|\\.)*")\s*:/g,     // keys
    '<span class="json-key">$1</span><span class="json-punct">:</span>'
  ).replace(
    /:\s*("(?:[^"\\]|\\.)*")/g,     // string values
    ': <span class="json-str">$1</span>'
  ).replace(
    /:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,  // numbers
    ': <span class="json-num">$1</span>'
  ).replace(
    /:\s*(true|false)/g,            // booleans
    ': <span class="json-bool">$1</span>'
  ).replace(
    /:\s*(null)/g,                   // null
    ': <span class="json-null">$1</span>'
  ).replace(
    /([{}[\]])/g,                    // braces/brackets
    '<span class="json-brace">$1</span>'
  );
}
