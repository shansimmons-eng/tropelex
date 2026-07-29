import * as vscode from 'vscode';
import { LensAnnotation } from './tropelexClient';

/**
 * Renders Memory Lens annotations as inline decorations — GitLens-style
 * grey text at the end of the annotated line, with the full decision
 * text and match metadata on hover.
 */
export class LensDecorationManager {
  private readonly decorationType: vscode.TextEditorDecorationType;
  private activeEditor: vscode.TextEditor | undefined;

  constructor() {
    this.decorationType = vscode.window.createTextEditorDecorationType({
      after: {
        color: new vscode.ThemeColor('editorCodeLens.foreground'),
        margin: '0 0 0 1.5em',
      },
      rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed,
    });
  }

  /** Applies annotations to the given editor, replacing any prior set. */
  apply(editor: vscode.TextEditor, annotations: LensAnnotation[]): void {
    this.activeEditor = editor;

    const byLine = new Map<number, LensAnnotation[]>();
    for (const ann of annotations) {
      const line = ann.line_number - 1; // Lens lines are 1-indexed
      if (line < 0 || line >= editor.document.lineCount) {
        continue;
      }
      const existing = byLine.get(line) ?? [];
      existing.push(ann);
      byLine.set(line, existing);
    }

    const options: vscode.DecorationOptions[] = [];
    for (const [line, lineAnnotations] of byLine) {
      // One decoration per line: show the highest-confidence match inline,
      // list every match (this line can be referenced by more than one
      // decision) in the hover.
      const best = lineAnnotations.reduce((a, b) => (b.confidence > a.confidence ? b : a));
      const lineText = editor.document.lineAt(line).text;

      options.push({
        range: new vscode.Range(line, lineText.length, line, lineText.length),
        renderOptions: {
          after: {
            contentText: `  ⚡ ${truncate(best.decision_text, 60)}`,
          },
        },
        hoverMessage: buildHoverMessage(lineAnnotations),
      });
    }

    editor.setDecorations(this.decorationType, options);
  }

  /** Clears decorations from the currently decorated editor, if any. */
  clear(): void {
    if (this.activeEditor) {
      this.activeEditor.setDecorations(this.decorationType, []);
      this.activeEditor = undefined;
    }
  }

  dispose(): void {
    this.decorationType.dispose();
  }
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildHoverMessage(annotations: LensAnnotation[]): vscode.MarkdownString {
  const md = new vscode.MarkdownString();
  md.isTrusted = false;
  for (const ann of annotations) {
    md.appendMarkdown(`**${escapeMarkdown(ann.decision_text)}**\n\n`);
    md.appendMarkdown(
      `_${ann.relationship} · confidence ${(ann.confidence * 100).toFixed(0)}% · referenced ${ann.reference_count}x_\n\n`
    );
    md.appendMarkdown('---\n\n');
  }
  return md;
}

function escapeMarkdown(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+.!-]/g, '\\$&');
}
