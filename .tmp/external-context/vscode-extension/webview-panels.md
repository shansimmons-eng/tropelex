---
source: Context7 API + Official VS Code Docs
library: vscode-extension-api
package: vscode-extension
topic: webview-panels-custom-ui
fetched: 2026-07-15T00:00:00Z
official_docs: https://code.visualstudio.com/api/extension-guides/webview
---

# Webview Panels for Custom UI

## Creating a Webview Panel

```typescript
import * as vscode from 'vscode';

function createMemoryViewerPanel(context: vscode.ExtensionContext) {
    const panel = vscode.window.createWebviewPanel(
        'memoryViewer',           // viewType — unique identifier
        'Memory Viewer',          // Title shown in tab
        vscode.ViewColumn.One,    // Editor column
        {
            enableScripts: true,  // Enable JS in webview
            localResourceRoots: [
                vscode.Uri.joinPath(context.extensionUri, 'media')
            ]
        }
    );

    // Convert local file URI to webview-safe URI
    const scriptUri = panel.webview.asWebviewUri(
        vscode.Uri.joinPath(context.extensionUri, 'media', 'main.js')
    );
    const styleUri = panel.webview.asWebviewUri(
        vscode.Uri.joinPath(context.extensionUri, 'media', 'style.css')
    );

    // CSP nonce for security
    const nonce = getNonce();

    panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy"
          content="default-src 'none';
                   style-src ${panel.webview.cspSource} 'nonce-${nonce}';
                   script-src ${panel.webview.cspSource} 'nonce-${nonce}';">
    <link rel="stylesheet" href="${styleUri}">
    <title>Memory Viewer</title>
</head>
<body>
    <div id="app"></div>
    <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;

    return panel;
}

function getNonce(): string {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
```

## Message Passing: Extension ↔ Webview

### Extension → Webview (send data)

```typescript
// Send memory file contents to webview
panel.webview.postMessage({
    command: 'loadMemoryFiles',
    files: [
        { name: 'decisions.json', content: {...} },
        { name: 'patterns.json', content: {...} }
    ]
});
```

### Webview → Extension (receive commands)

```typescript
panel.webview.onDidReceiveMessage(
    async message => {
        switch (message.command) {
            case 'refresh':
                const files = await readMemoryFiles();
                panel.webview.postMessage({ command: 'loadMemoryFiles', files });
                return;
            case 'openFile':
                const doc = await vscode.workspace.openTextDocument(message.path);
                vscode.window.showTextDocument(doc);
                return;
        }
    },
    undefined,
    context.subscriptions
);
```

### Inside the Webview (script.js)

```javascript
// Acquire VS Code API — can only be called once per session
const vscode = acquireVsCodeApi();

// Receive messages from extension
window.addEventListener('message', event => {
    const message = event.data;
    switch (message.command) {
        case 'loadMemoryFiles':
            renderFiles(message.files);
            break;
    }
});

// Send message to extension
vscode.postMessage({
    command: 'refresh'
});
```

## Webview State Persistence

```typescript
// Inside webview script
const vscode = acquireVsCodeApi();

// Restore previous state
const previousState = vscode.getState();
let selectedFile = previousState?.selectedFile ?? null;

// Save state (persists when panel hidden)
vscode.setState({ selectedFile });
```

## Singleton Panel Pattern

```typescript
let currentPanel: vscode.WebviewPanel | undefined = undefined;

function showMemoryViewer(context: vscode.ExtensionContext) {
    if (currentPanel) {
        currentPanel.reveal(vscode.ViewColumn.One);
    } else {
        currentPanel = createMemoryViewerPanel(context);
        currentPanel.onDidDispose(
            () => { currentPanel = undefined; },
            null,
            context.subscriptions
        );
    }
}
```

## Loading Local Content in Webview

```typescript
// Convert extension local files to webview URIs
const onDiskPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'logo.png');
const webviewUri = panel.webview.asWebviewUri(onDiskPath);
// Result: vscode-resource:/path/to/extension/media/logo.png

// Access workspace files
const workspacePath = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders![0].uri,
    'memory',
    'decisions.json'
);
const workspaceUri = panel.webview.asWebviewUri(workspacePath);
```

## Webview Theming

Use VS Code CSS variables for automatic theme support:

```css
body {
    color: var(--vscode-editor-foreground);
    background-color: var(--vscode-editor-background);
    font-family: var(--vscode-editor-font-family);
}

.card {
    border: 1px solid var(--vscode-widget-border);
    background: var(--vscode-editorWidget-background);
}

a { color: var(--vscode-textLink-foreground); }
```

Theme classes on body: `vscode-light`, `vscode-dark`, `vscode-high-contrast`.

## Serialization (Restore after restart)

```typescript
// package.json: "activationEvents": ["onWebviewPanel:memoryViewer"]

vscode.window.registerWebviewPanelSerializer('memoryViewer', {
    async deserializeWebviewPanel(webviewPanel, state) {
        webviewPanel.webview.html = getWebviewContent();
        // Restore state if available
        if (state) {
            webviewPanel.webview.postMessage({ command: 'restore', state });
        }
    }
});
```
