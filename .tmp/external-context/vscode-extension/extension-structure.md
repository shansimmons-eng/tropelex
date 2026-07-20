---
source: Context7 API + Official VS Code Docs
library: vscode-extension-api
package: vscode-extension
topic: extension-structure-package-json-extension-ts
fetched: 2026-07-15T00:00:00Z
official_docs: https://code.visualstudio.com/api/get-started/extension-anatomy
---

# VS Code Extension Structure

## package.json Manifest

Every extension needs a `package.json` with these critical fields:

```json
{
  "name": "my-extension",
  "displayName": "My Extension",
  "description": "Description here",
  "version": "0.0.1",
  "publisher": "your-publisher-id",
  "engines": {
    "vscode": "^1.74.0"
  },
  "categories": ["Other"],
  "activationEvents": [],
  "main": "./out/extension.js",
  "contributes": {
    "commands": [
      {
        "command": "myExtension.openMemoryViewer",
        "title": "Open Memory Viewer",
        "category": "My Extension"
      }
    ],
    "views": {
      "explorer": [
        {
          "id": "memoryFiles",
          "name": "Memory Files"
        }
      ]
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

### Key Fields

- **`engines.vscode`**: Minimum VS Code version (use `^1.74.0` for modern API)
- **`main`**: Entry point JS file (compiled from TypeScript)
- **`activationEvents`**: When to activate (can be empty `[]` for VS Code 1.74+ with auto-inferred events from contributions)
- **`contributes`**: All contribution points (commands, views, menus, configuration, etc.)

### Important: VS Code 1.74+ Auto-Activation

As of VS Code 1.74.0, many activation events are **automatically inferred** from contributions:
- `contributes.commands` → auto-generates `onCommand:...`
- `contributes.views` → auto-generates `onView:...`
- `contributes.languages` → auto-generates `onLanguage:...`
- `contributes.customEditors` → auto-generates `onCustomEditor:...`

You can leave `activationEvents: []` if your activation is covered by contributions.

## extension.ts Entry Point

```typescript
import * as vscode from 'vscode';

export function activate(context: vscode.ExtensionContext) {
    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('myExtension.openMemoryViewer', () => {
            vscode.window.showInformationMessage('Hello from Memory Viewer!');
        })
    );

    // Register tree data providers
    // Register webview panel serializers
    // Set up file watchers, etc.

    // All disposables pushed to context.subscriptions
    // are automatically cleaned up on deactivation
}

export function deactivate() {
    // Optional cleanup - resources in context.subscriptions
    // are disposed automatically
}
```

### Extension Lifecycle

1. **`activate(context)`** — Called once when extension is first needed (matching activation event)
2. **`deactivate()`** — Optional, called on VS Code shutdown
3. **`context.subscriptions`** — Array of `Disposable` objects; all auto-disposed on deactivation
4. **`context.extensionUri`** — URI to the extension's install directory (use for loading local resources)
5. **`context.extensionPath`** — Filesystem path to extension directory (deprecated, use `extensionUri`)

### TypeScript Configuration (tsconfig.json)

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2020",
    "outDir": "out",
    "lib": ["ES2020"],
    "sourceMap": true,
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "exclude": ["node_modules", ".vscode-test"]
}
```

### Recommended Project Structure

```
my-extension/
├── src/
│   └── extension.ts        # Main entry point
├── media/                   # Icons, images for webview
├── out/                     # Compiled JS (gitignored)
├── package.json
├── tsconfig.json
└── .vscodeignore            # Files to exclude from VSIX
```
