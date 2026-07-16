"""
Tropebook CLI - Command line interface for Tropebook
Usage: python -m core.tropebook.cli [command] [args]
"""
import json
import sys


def main():
    args = sys.argv[1:]
    if not args:
        print_help()
        return

    cmd = args[0]

    if cmd == "add":
        handle_add(args[1:])
    elif cmd == "search":
        handle_search(args[1:])
    elif cmd == "list":
        handle_list(args[1:])
    elif cmd == "import":
        handle_import(args[1:])
    elif cmd == "stats":
        handle_stats(args[1:])
    elif cmd == "link":
        handle_link(args[1:])
    elif cmd in ("help", "--help", "-h"):
        print_help()
    else:
        print(f"Unknown command: {cmd}")
        print_help()

def print_help():
    print("""Tropebook CLI - Research Knowledge Base

Commands:
  add <title> <url> [summary]    Add a citation
  search <query>                 Search knowledge base
  list [tag]                     List all citations or by tag
  import <file>                  Import from file (JSON/md)
  stats                          Show knowledge base stats
  link <url1> <url2> <rel>       Add relationship between citations
  help                           Show this help

Examples:
  python -m core.tropebook.cli add "Python Docs" "https://docs.python.org" "Official Python docs"
  python -m core.tropebook.cli search "machine learning"
  python -m core.tropebook.cli import research_exports.json""")

def get_tropebook():
    try:
        from core.tropebook import Tropebook
        return Tropebook()
    except Exception as e:
        print(f"Error loading Tropebook: {e}")
        return None

def handle_add(args):
    if len(args) < 2:
        print("Usage: add <title> <url> [summary]")
        return
    title, url = args[0], args[1]
    summary = args[2] if len(args) > 2 else ""
    tb = get_tropebook()
    if tb:
        cid = tb.add(title, url, summary)
        print(f"Added citation: {cid}")

def handle_search(args):
    if not args:
        print("Usage: search <query>")
        return
    query = " ".join(args)
    tb = get_tropebook()
    if tb:
        results = tb.search(query)
        for r in results:
            print(f"[{r.url}] {r.title}")
            if r.summary:
                print(f"  {r.summary[:100]}...")

def handle_list(args):
    tag = args[0] if args else None
    tb = get_tropebook()
    if tb:
        if tag:
            citations = tb.find_by_tag(tag)
        else:
            citations = list(tb.citations.values())
        for c in citations:
            print(f"[{c.source_type}] {c.title} - {c.url}")

def handle_import(args):
    if not args:
        print("Usage: import <file>")
        return
    from core.tropebook import create_importer
    tb = get_tropebook()
    if not tb:
        return
    importer = create_importer(tb)
    count = importer.import_file(args[0])
    print(f"Imported {count} sources")

def handle_stats(args):
    tb = get_tropebook()
    if tb:
        stats = tb.stats()
        print(json.dumps(stats, indent=2))

def handle_link(args):
    if len(args) < 3:
        print("Usage: link <url1> <url2> <relationship>")
        return
    tb = get_tropebook()
    if tb:
        tb.add_relationship(args[0], args[1], args[2])
        print("Link created")

if __name__ == "__main__":
    main()
