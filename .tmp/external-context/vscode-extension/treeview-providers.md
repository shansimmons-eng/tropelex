---
source: Context7 API + Official VS Code Docs
library: vscode-extension-api
package: vscode-extension
topic: treeview-providers-sidebar
fetched: 2026-07-15T00:00:00Z
official_docs: https://code.visualstudio.com/api/extension-guides/tree-view
---

# TreeView Providers for Sidebar

## package.json Declaration

```json
{
  "contributes": {
    "viewsContainers": {
      "activitybar": [
        {
          "id": "memoryExplorer",
          "title": "Memory Explorer",
          "icon": "media/memory-icon.svg"
        }
      ]
    },
    "views": {
      "memoryExplorer": [
        {
          "id": "memoryFiles",
          "name": "Memory Files",
          "icon": "media/dep.svg",
          "contextualTitle": "Memory Explorer"
        }
      ]
    }
  }
}
```

### View Locations

Views can be contributed to:
- `explorer` — Explorer sidebar
- `debug` — Run and Debug sidebar
- `scm` — Source Control sidebar
- `test` — Test explorer sidebar
- Custom View Containers (activitybar or panel)

## TreeDataProvider Implementation

```typescript
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

// --- Data Model ---

class MemoryItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly filePath: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'file' | 'section' | 'entry'
    ) {
        super(label, collapsibleState);
        this.tooltip = this.filePath;
        this.contextValue = itemType;

        if (itemType === 'file') {
            this.iconPath = new vscode.ThemeIcon('file');
            this.command = {
                command: 'memoryFiles.openFile',
                title: 'Open File',
                arguments: [this]
            };
        } else if (itemType === 'section') {
            this.iconPath = new vscode.ThemeIcon('folder');
        } else {
            this.iconPath = new vscode.ThemeIcon('symbol-event');
        }
    }
}

// --- Data Provider ---

class MemoryFilesProvider implements vscode.TreeDataProvider<MemoryItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<MemoryItem | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    constructor(private workspaceRoot: string | undefined) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: MemoryItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: MemoryItem): Thenable<MemoryItem[]> {
        if (!this.workspaceRoot) {
            return Promise.resolve([]);
        }

        if (!element) {
            // Root level: list JSON files in memory/
            return Promise.resolve(this.getMemoryFiles());
        }

        if (element.itemType === 'file') {
            // Second level: list sections within a JSON file
            return Promise.resolve(this.getFileSections(element.filePath));
        }

        if (element.itemType === 'section') {
            // Third level: list entries within a section
            return Promise.resolve(this.getSectionEntries(element.filePath, element.label));
        }

        return Promise.resolve([]);
    }

    private getMemoryFiles(): MemoryItem[] {
        const memDir = path.join(this.workspaceRoot!, 'memory');
        if (!fs.existsSync(memDir)) return [];

        return fs.readdirSync(memDir)
            .filter(f => f.endsWith('.json'))
            .sort()
            .map(f => new MemoryItem(
                f,
                path.join(memDir, f),
                vscode.TreeItemCollapsibleState.Collapsed,
                'file'
            ));
    }

    private getMemoryFiles(filePath: string): MemoryItem[] {
        try {
            const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
            const sections: MemoryItem[] = [];

            if (data.decisions?.length) {
                sections.push(new MemoryItem(
                    `Decisions (${data.decisions.length})`,
                    filePath,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'section'
                ));
            }
            if (data.session_history?.length) {
                sections.push(new MemoryItem(
                    `Sessions (${data.session_history.length})`,
                    filePath,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'section'
                ));
            }
            if (data.patterns?.length) {
                sections.push(new MemoryItem(
                    `Patterns (${data.patterns.length})`,
                    filePath,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'section'
                ));
            }
            return sections;
        } catch {
            return [];
        }
    }

    private getSectionEntries(filePath: string, sectionName: string): MemoryItem[] {
        try {
            const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
            const key = sectionName.split(' (')[0].toLowerCase(); // "Decisions (3)" → "decisions"
            const items = data[key] || [];

            return items.map((item: any, i: number) => {
                const label = item.decision || item.summary || item.name || `Item ${i + 1}`;
                const treeItem = new MemoryItem(
                    label,
                    filePath,
                    vscode.TreeItemCollapsibleState.None,
                    'entry'
                );
                treeItem.description = item.timestamp
                    ? new Date(item.timestamp).toLocaleDateString()
                    : '';
                return treeItem;
            });
        } catch {
            return [];
        }
    }
}
```

## Registration in activate()

```typescript
export function activate(context: vscode.ExtensionContext) {
    const rootPath = vscode.workspace.workspaceFolders
        ? vscode.workspace.workspaceFolders[0].uri.fsPath
        : undefined;

    // Register TreeDataProvider
    const memoryProvider = new MemoryFilesProvider(rootPath);
    vscode.window.registerTreeDataProvider('memoryFiles', memoryProvider);

    // Refresh command
    context.subscriptions.push(
        vscode.commands.registerCommand('memoryFiles.refresh', () => {
            memoryProvider.refresh();
        })
    );

    // Open file command
    context.subscriptions.push(
        vscode.commands.registerCommand('memoryFiles.openFile', async (item: MemoryItem) => {
            const doc = await vscode.workspace.openTextDocument(item.filePath);
            vscode.window.showTextDocument(doc);
        })
    );
}
```

## View Title Actions (Refresh Button)

```json
{
  "contributes": {
    "commands": [
      {
        "command": "memoryFiles.refresh",
        "title": "Refresh",
        "icon": {
          "light": "resources/light/refresh.svg",
          "dark": "resources/dark/refresh.svg"
        }
      }
    ],
    "menus": {
      "view/title": [
        {
          "command": "memoryFiles.refresh",
          "when": "view == memoryFiles",
          "group": "navigation"
        }
      ],
      "view/item/context": [
        {
          "command": "memoryFiles.openFile",
          "when": "view == memoryFiles && viewItem == file",
          "group": "inline"
        }
      ]
    }
  }
}
```

## Welcome Content (Empty State)

```json
{
  "contributes": {
    "viewsWelcome": [
      {
        "view": "memoryFiles",
        "contents": "No memory files found.\n[Initialize Memory](command:memoryFiles.initialize)\n[Learn More](https://github.com/your-project)"
      }
    ]
  }
}
```

## createTreeView (for programmatic control)

```typescript
// Use instead of registerTreeDataProvider when you need TreeView API access
const treeView = vscode.window.createTreeView('memoryFiles', {
    treeDataProvider: memoryProvider
});

// Now you can:
treeView.reveal(someItem, { select: true, focus: true });
treeView.visible; // boolean
```

## Key Patterns

- **`getChildren(element?)`** — Returns root items when `element` is undefined, children when defined
- **`getTreeItem(element)`** — Returns the UI representation (TreeItem) for display
- **`onDidChangeTreeData`** — Fire this event to refresh the tree
- **`contextValue`** — Used in `when` clauses for conditional menu visibility
- **`TreeItemCollapsibleState`** — `.None`, `.Collapsed`, `.Expanded`
- **`TreeItem.description`** — Secondary text shown in the tree item
- **`TreeItem.iconPath`** — Can be a `ThemeIcon` (built-in), or `{light: Uri, dark: Uri}`
