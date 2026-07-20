---
source: Context7 API + Official VS Code Docs
library: vscode-extension-api
package: vscode-extension
topic: reading-local-files-workspace
fetched: 2026-07-15T00:00:00Z
official_docs: https://code.visualstudio.com/api/references/vscode-api
---

# Reading Local Files from the Workspace

## Getting the Workspace Folder

```typescript
function getWorkspaceRoot(): string | undefined {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showWarningMessage('No workspace folder open');
        return undefined;
    }
    return workspaceFolders[0].uri.fsPath;
}
```

## Reading Files with Node.js `fs`

```typescript
import * as fs from 'fs';
import * as path from 'path';

function readMemoryFile(workspaceRoot: string, filename: string): any | undefined {
    const filePath = path.join(workspaceRoot, 'memory', filename);
    try {
        if (fs.existsSync(filePath)) {
            const content = fs.readFileSync(filePath, 'utf-8');
            return JSON.parse(content);
        }
    } catch (err) {
        console.error(`Error reading ${filePath}:`, err);
    }
    return undefined;
}

// Read all JSON files in a directory
function readAllMemoryFiles(workspaceRoot: string): Map<string, any> {
    const memDir = path.join(workspaceRoot, 'memory');
    const files = new Map<string, any>();

    if (!fs.existsSync(memDir)) return files;

    for (const file of fs.readdirSync(memDir)) {
        if (file.endsWith('.json')) {
            const content = readMemoryFile(workspaceRoot, file);
            if (content) files.set(file, content);
        }
    }
    return files;
}
```

## Reading Files with VS Code Workspace API (async)

```typescript
// Read a text document
async function readMemoryDocument(relativePath: string): Promise<string> {
    const uri = vscode.Uri.joinPath(
        vscode.workspace.workspaceFolders![0].uri,
        relativePath
    );
    const document = await vscode.workspace.openTextDocument(uri);
    return document.getText();
}

// Read binary content
async function readBinaryFile(relativePath: string): Uint8Array {
    const uri = vscode.Uri.joinPath(
        vscode.workspace.workspaceFolders![0].uri,
        relativePath
    );
    return await vscode.workspace.fs.readFile(uri);
}
```

## Watching for File Changes

```typescript
import * as path from 'path';

function watchMemoryFiles(
    workspaceRoot: string,
    on changed: (filename: string) => void
): vscode.Disposable {
    const memDir = path.join(workspaceRoot, 'memory');
    const pattern = new vscode.RelativePattern(memDir, '**/*.json');
    const watcher = vscode.workspace.createFileSystemWatcher(pattern);

    watcher.onDidChange(uri => changed(path.basename(uri.fsPath)));
    watcher.onDidCreate(uri => changed(path.basename(uri.fsPath)));
    watcher.onDidDelete(uri => changed(path.basename(uri.fsPath)));

    return watcher;
}

// Register in activate():
const watcher = watchMemoryFiles(rootPath, filename => {
    memoryTreeProvider.refresh();
    // Optionally update webview
    if (currentPanel) {
        const files = readAllMemoryFiles(rootPath);
        currentPanel.webview.postMessage({
            command: 'loadMemoryFiles',
            files: Object.fromEntries(files)
        });
    }
});
context.subscriptions.push(watcher);
```

## Glob Pattern for Finding Files

```typescript
// Find all .json files recursively
const files = await vscode.workspace.findFiles('**/memory/**/*.json');

// Find with exclusion
const files = await vscode.workspace.findFiles(
    '**/memory/**/*.json',
    '**/node_modules/**'
);

// Limit results
const files = await vscode.workspace.findFiles('**/*.json', undefined, 100);
```

## Reading Relative to Extension (not workspace)

```typescript
// Files bundled with the extension itself
const bundledData = vscode.Uri.joinPath(
    context.extensionUri,
    'data',
    'defaults.json'
);
const content = await vscode.workspace.fs.readFile(bundledData);
const json = JSON.parse(new TextDecoder().decode(content));
```

## Practical Pattern: Memory File Explorer

```typescript
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

interface MemoryFile {
    name: string;
    path: string;
    lastModified: Date;
    data: any;
}

function scanMemoryFiles(workspaceRoot: string): MemoryFile[] {
    const memDir = path.join(workspaceRoot, 'memory');
    if (!fs.existsSync(memDir)) return [];

    return fs.readdirSync(memDir)
        .filter(f => f.endsWith('.json'))
        .map(f => {
            const fullPath = path.join(memDir, f);
            const stat = fs.statSync(fullPath);
            return {
                name: f,
                path: fullPath,
                lastModified: stat.mtime,
                data: JSON.parse(fs.readFileSync(fullPath, 'utf-8'))
            };
        });
}
```
