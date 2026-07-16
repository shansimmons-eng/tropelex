import * as vscode from 'vscode';
import { MemoryWebviewPanel } from './memoryWebviewPanel';

/**
 * Activates the Tropelex Memory Viewer extension.
 *
 * Registers commands for opening and refreshing the memory viewer.
 *
 * @param context - The extension context provided by VS Code
 */
export function activate(context: vscode.ExtensionContext): void {
  console.log('Tropelex Memory Viewer is now active');

  const openMemoryViewerCmd = vscode.commands.registerCommand(
    'tropelex.openMemoryViewer',
    () => {
      MemoryWebviewPanel.createOrShow(context.extensionUri);
    }
  );

  const refreshMemoryCmd = vscode.commands.registerCommand(
    'tropelex.refreshMemory',
    () => {
      // Refresh is handled internally by the panel when it exists.
      // If the panel is not open, opening it will load fresh content.
      MemoryWebviewPanel.createOrShow(context.extensionUri);
    }
  );

  // Restore panel if VS Code serialized it (webview persistence).
  if (vscode.window.registerWebviewPanelSerializer) {
    vscode.window.registerWebviewPanelSerializer(
      MemoryWebviewPanel.viewType,
      {
        deserializeWebviewPanel(
          webviewPanel: vscode.WebviewPanel,
          _state: unknown
        ): Thenable<void> {
          MemoryWebviewPanel.revive(webviewPanel, context.extensionUri);
          return Promise.resolve();
        },
      }
    );
  }

  context.subscriptions.push(openMemoryViewerCmd, refreshMemoryCmd);
}

/**
 * Deactivates the Tropelex Memory Viewer extension.
 */
export function deactivate(): void {
  // Cleanup resources if needed
}
