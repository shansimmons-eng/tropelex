import * as vscode from 'vscode';
import { MemoryWebviewPanel } from './memoryWebviewPanel';
import { LensDecorationManager } from './lensDecorations';
import { getProjectName, scanFileForDecisions, TropelexClientError } from './tropelexClient';

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

  // Memory Lens — GitLens-style inline decision annotations. Manually
  // triggered (command palette / keybinding), not run automatically on
  // save or edit, since each scan is a network call to the Tropelex
  // server and firing one on every keystroke or save would be a real
  // extension-etiquette problem, not just noise.
  const lensManager = new LensDecorationManager();

  const scanFileCmd = vscode.commands.registerCommand(
    'tropelex.scanFileForDecisions',
    async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showWarningMessage('Tropelex: open a file to scan first.');
        return;
      }
      const project = getProjectName();
      if (!project) {
        vscode.window.showWarningMessage(
          'Tropelex: no project configured. Set "tropelex.project" or open a workspace folder.'
        );
        return;
      }

      const relativePath = vscode.workspace.asRelativePath(editor.document.uri);
      try {
        const annotations = await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: 'Tropelex: scanning for decision references…',
          },
          () => scanFileForDecisions(project, relativePath, editor.document.getText())
        );
        lensManager.apply(editor, annotations);
        if (annotations.length === 0) {
          vscode.window.showInformationMessage('Tropelex: no decision references found in this file.');
        } else {
          vscode.window.showInformationMessage(
            `Tropelex: found ${annotations.length} decision reference${annotations.length === 1 ? '' : 's'}.`
          );
        }
      } catch (err) {
        const message = err instanceof TropelexClientError ? err.message : String(err);
        vscode.window.showErrorMessage(message);
      }
    }
  );

  const clearLensCmd = vscode.commands.registerCommand('tropelex.clearLensAnnotations', () => {
    lensManager.clear();
  });

  context.subscriptions.push(
    openMemoryViewerCmd,
    refreshMemoryCmd,
    scanFileCmd,
    clearLensCmd,
    lensManager
  );
}

/**
 * Deactivates the Tropelex Memory Viewer extension.
 */
export function deactivate(): void {
  // Cleanup resources if needed
}
