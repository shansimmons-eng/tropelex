---
source: Context7 API + Official VS Code Docs
library: vscode-extension-api
package: vscode-extension
topic: commands-activation-events
fetched: 2026-07-15T00:00:00Z
official_docs: https://code.visualstudio.com/api/references/activation-events
---

# Commands and Activation Events

## Registering Commands

```typescript
import * as vscode from 'vscode';

export function activate(context: vscode.ExtensionContext) {
    // Simple command
    context.subscriptions.push(
        vscode.commands.registerCommand('myExtension.hello', () => {
            vscode.window.showInformationMessage('Hello!');
        })
    );

    // Command with arguments
    context.subscriptions.push(
        vscode.commands.registerCommand('myExtension.openMemory', (filePath: string) => {
            vscode.window.showTextDocument(vscode.Uri.file(filePath));
        })
    );

    // Async command
    context.subscriptions.push(
        vscode.commands.registerCommand('myExtension.refreshAll', async () => {
            await vscode.commands.executeCommand('memoryFiles.refresh');
            vscode.window.showInformationMessage('Refreshed!');
        })
    );
}
```

## package.json Command Declaration

```json
{
  "contributes": {
    "commands": [
      {
        "command": "myExtension.openMemoryViewer",
        "title": "Open Memory Viewer",
        "category": "Memory"
      },
      {
        "command": "myExtension.initializeMemory",
        "title": "Initialize Memory Directory",
        "category": "Memory"
      }
    ]
  }
}
```

## Activation Events Reference

### Common Events (Most Relevant for Memory Viewer)

```json
{
  "activationEvents": [
    "onCommand:myExtension.openMemoryViewer",
    "onView:memoryFiles",
    "workspaceContains:**/memory/*.json"
  ]
}
```

### Full Event Types

| Event | When It Fires | Example |
|-------|--------------|---------|
| `onCommand:id` | Command invoked | `"onCommand:myExtension.open"` |
| `onView:id` | View expanded in sidebar | `"onView:memoryFiles"` |
| `workspaceContains:glob` | Workspace contains matching file | `"workspaceContains:**/memory/*.json"` |
| `onLanguage:lang` | File of language opened | `"onLanguage:json"` |
| `onFileSystem:scheme` | File with URI scheme read | `"onFileSystem:file"` |
| `onStartupFinished` | After VS Code startup (lazy) | `"onStartupFinished"` |
| `*` | VS Code starts (avoid if possible) | `"*"` |

### VS Code 1.74+ Auto-Inference

**You can often leave `activationEvents: []` empty** because VS Code auto-generates them:

- `contributes.commands` → `onCommand:...` auto-inferred
- `contributes.views` → `onView:...` auto-inferred
- `contributes.languages` → `onLanguage:...` auto-inferred
- `contributes.customEditors` → `onCustomEditor:...` auto-inferred
- `contributes.authentication` → `onAuthenticationRequest:...` auto-inferred

**Still need explicit events for:**
- `workspaceContains` (must declare manually)
- `onStartupFinished`
- `*` (startup)
- `onFileSystem` (custom schemes)

## Keybinding Contributions

```json
{
  "contributes": {
    "keybindings": [
      {
        "command": "myExtension.openMemoryViewer",
        "key": "ctrl+shift+m",
        "mac": "cmd+shift+m",
        "when": "editorTextFocus"
      }
    ]
  }
}
```

## Menu Contributions

```json
{
  "contributes": {
    "menus": {
      "commandPalette": [
        {
          "command": "myExtension.openMemoryViewer",
          "when": "workspaceContains:**/memory"
        }
      ],
      "editor/context": [
        {
          "command": "myExtension.openMemory",
          "when": "editorHasSelection",
          "group": "navigation"
        }
      ]
    }
  }
}
```

## Configuration Settings

```json
{
  "contributes": {
    "configuration": {
      "title": "Memory Viewer",
      "properties": {
        "memoryViewer.path": {
          "type": "string",
          "default": "memory",
          "description": "Relative path to memory directory within workspace"
        },
        "memoryViewer.autoRefresh": {
          "type": "boolean",
          "default": true,
          "description": "Automatically refresh when memory files change"
        }
      }
    }
  }
}
```

Read settings in code:
```typescript
const config = vscode.workspace.getConfiguration('memoryViewer');
const memPath = config.get<string>('path', 'memory');
const autoRefresh = config.get<boolean>('autoRefresh', true);
```

## Complete package.json for Memory Viewer Extension

```json
{
  "name": "tropelex-memory-viewer",
  "displayName": "Tropelex Memory Viewer",
  "description": "View and browse Tropelex memory files in VS Code",
  "version": "0.0.1",
  "publisher": "retroporter",
  "engines": { "vscode": "^1.74.0" },
  "categories": ["Other"],
  "activationEvents": [
    "workspaceContains:**/memory/*.json"
  ],
  "main": "./out/extension.js",
  "contributes": {
    "commands": [
      { "command": "memoryFiles.refresh", "title": "Refresh", "category": "Memory" },
      { "command": "memoryFiles.openFile", "title": "Open File", "category": "Memory" },
      { "command": "memoryViewer.openPanel", "title": "Open Memory Viewer", "category": "Memory" }
    ],
    "viewsContainers": {
      "activitybar": [
        { "id": "memoryExplorer", "title": "Memory", "icon": "media/memory-icon.svg" }
      ]
    },
    "views": {
      "memoryExplorer": [
        { "id": "memoryFiles", "name": "Memory Files", "contextualTitle": "Memory Explorer" }
      ]
    },
    "menus": {
      "view/title": [
        { "command": "memoryFiles.refresh", "when": "view == memoryFiles", "group": "navigation" }
      ],
      "view/item/context": [
        { "command": "memoryFiles.openFile", "when": "view == memoryFiles && viewItem == file", "group": "inline" }
      ]
    },
    "configuration": {
      "title": "Tropelex Memory Viewer",
      "properties": {
        "memoryViewer.path": { "type": "string", "default": "memory", "description": "Path to memory directory" },
        "memoryViewer.autoRefresh": { "type": "boolean", "default": true, "description": "Auto-refresh on changes" }
      }
    }
  },
  "scripts": {
    "vscode:prepublish": "npm run compile",
    "compile": "tsc -p ./",
    "watch": "tsc -watch -p ./"
  },
  "devDependencies": {
    "@types/vscode": "^1.74.0",
    "@types/node": "^16.x",
    "typescript": "^5.x"
  }
}
```
