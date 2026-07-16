import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Represents a memory file node in the tree view.
 */
export class MemoryFileItem extends vscode.TreeItem {
  constructor(
    public readonly filePath: string,
    public readonly fileName: string,
    public readonly lastModified: Date,
    public readonly fileSize: number,
    public readonly relativePath: string
  ) {
    super(fileName, vscode.TreeItemCollapsibleState.None);

    // Format the label with file size and last modified
    this.description = `${this.formatSize(fileSize)} · ${this.formatDate(lastModified)}`;

    // Set the tooltip to show full details
    this.tooltip = [
      `File: ${relativePath}`,
      `Size: ${this.formatSize(fileSize)}`,
      `Modified: ${lastModified.toLocaleString()}`,
    ].join('\n');

    // Set resource URI for theming and file icon
    this.resourceUri = vscode.Uri.file(filePath);

    // Command to open file in editor when clicked
    this.command = {
      command: 'vscode.open',
      title: 'Open Memory File',
      arguments: [vscode.Uri.file(filePath)],
    };

    // Set context value for conditional menu items
    this.contextValue = 'memoryFile';
  }

  /**
   * Formats file size in human-readable format.
   */
  private formatSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  /**
   * Formats the last modified date relative to now.
   */
  private formatDate(date: Date): string {
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) {
      return 'just now';
    }
    if (diffMins < 60) {
      return `${diffMins}m ago`;
    }
    if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    if (diffDays < 7) {
      return `${diffDays}d ago`;
    }
    return date.toLocaleDateString();
  }
}

/**
 * TreeDataProvider that displays memory files from the workspace memory/ directory.
 *
 * Watches for file system changes and auto-refreshes the tree view.
 * Supports refresh via command and provides file metadata (size, last modified).
 */
export class MemoryTreeProvider implements vscode.TreeDataProvider<MemoryFileItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<MemoryFileItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private watcherDisposables: vscode.Disposable[] = [];

  constructor() {
    this.setupFileWatcher();
  }

  /**
   * Triggers a refresh of the entire tree.
   */
  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  /**
   * Returns the tree item representation for the given element.
   */
  getTreeItem(element: MemoryFileItem): vscode.TreeItem {
    return element;
  }

  /**
   * Returns children for the given element (or root elements if element is undefined).
   */
  async getChildren(element?: MemoryFileItem): Promise<MemoryFileItem[]> {
    if (element) {
      return [];
    }

    // Root level: return all memory files
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
      return [];
    }

    const files: MemoryFileItem[] = [];

    for (const folder of workspaceFolders) {
      const memoryDir = path.join(folder.uri.fsPath, 'memory');

      if (!fs.existsSync(memoryDir)) {
        continue;
      }

      const entries = fs.readdirSync(memoryDir, { withFileTypes: true });

      for (const entry of entries) {
        // Only include JSON files (memory files)
        if (!entry.isFile() || !entry.name.endsWith('.json')) {
          continue;
        }

        const filePath = path.join(memoryDir, entry.name);

        try {
          const stats = fs.statSync(filePath);
          const relativePath = path.relative(folder.uri.fsPath, filePath);

          files.push(
            new MemoryFileItem(
              filePath,
              entry.name,
              stats.mtime,
              stats.size,
              relativePath
            )
          );
        } catch {
          // Skip files that can't be stat'd (permission issues, etc.)
        }
      }
    }

    // Sort by last modified date (newest first)
    files.sort((a, b) => b.lastModified.getTime() - a.lastModified.getTime());

    return files;
  }

  /**
   * Sets up a file system watcher on the memory/ directory.
   * Triggers tree refresh on file create, change, or delete events.
   */
  private setupFileWatcher(): void {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
      return;
    }

    // Watch for JSON files in memory/ directory across all workspace folders
    for (const folder of workspaceFolders) {
      const memoryPattern = new vscode.RelativePattern(folder, 'memory/**/*.json');
      const watcher = vscode.workspace.createFileSystemWatcher(memoryPattern);

      const onEvent = () => this.refresh();

      watcher.onDidCreate(onEvent);
      watcher.onDidChange(onEvent);
      watcher.onDidDelete(onEvent);

      this.watcherDisposables.push(watcher);
    }
  }

  /**
   * Disposes of all resources held by this provider.
   */
  dispose(): void {
    this._onDidChangeTreeData.dispose();
    for (const disposable of this.watcherDisposables) {
      disposable.dispose();
    }
    this.watcherDisposables = [];
  }
}
