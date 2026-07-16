"""
Tropelex Research Feeds CLI
Create, manage, and run research feeds from the command line.

Usage:
    python -m scripts.feed_cli list
    python -m scripts.feed_cli create "AI Safety News" "AI safety OR alignment OR x-risk"
    python -m scripts.feed_cli run <feed_id>
    python -m scripts.feed_cli tick
    python -m scripts.feed_cli show <feed_id>
    python -m scripts.feed_cli delete <feed_id>
    python -m scripts.feed_cli markdown <feed_id>
    python -m scripts.feed_cli stats
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tropebook.research_feeds import ResearchFeedManager
from core.tropebook.scheduler import FeedScheduler

STORAGE = str(Path(__file__).parent.parent / "memory")


def get_fm():
    return ResearchFeedManager(storage_path=STORAGE)


def get_scheduler():
    return FeedScheduler(feed_manager=get_fm(), storage_path=str(Path(STORAGE) / "tropebook"))


def cmd_list(args):
    try:
        fm = get_fm()
        feeds = fm.list_feeds(enabled_only=args.enabled)
        if not feeds:
            print("No feeds found.")
            return
        for f in feeds:
            status = "active" if f.enabled else "disabled"
            print(f"  {f.id}  {status:8s}  {f.interval:8s}  {f.total_citations:3d} cit  {f.name}")
            print(f"           query: {f.query[:60]}")
    except Exception as e:
        print(f"Error listing feeds: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_create(args):
    try:
        fm = get_fm()
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else ["web"]
        feed = fm.create(
            name=args.name,
            query=args.query,
            description=args.description or "",
            interval=args.interval,
            sources=sources,
            tags=tags,
            max_results_per_run=args.max_results,
        )
        print(f"Created feed: {feed.id}")
        print(f"  Name:     {feed.name}")
        print(f"  Query:    {feed.query}")
        print(f"  Interval: {feed.interval}")
        print(f"  Next run: {feed.next_run}")
    except ValueError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error creating feed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_run(args):
    try:
        scheduler = get_scheduler()
        fm = get_fm()
        feed = fm.get(args.feed_id)
        if not feed:
            print(f"Feed not found: {args.feed_id}")
            sys.exit(1)
        print(f"Running feed: {feed.name} ...")
        run = scheduler.run_feed(feed)
        if run.status == "success":
            print(f"  Status:    success")
            print(f"  Results:   {run.results_count} new citations")
            print(f"  Duration:  {run.duration_seconds}s")
            if run.source_breakdown:
                print(f"  Sources:   {run.source_breakdown}")
        else:
            print(f"  Status:    error")
            print(f"  Error:     {run.error}")
    except Exception as e:
        print(f"Error running feed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_tick(args):
    try:
        scheduler = get_scheduler()
        runs = scheduler.tick()
        if not runs:
            print("No feeds due.")
            return
        for run in runs:
            status = "ok" if run.status == "success" else "FAIL"
            print(f"  [{status}] {run.feed_id}: {run.results_count} results in {run.duration_seconds}s")
    except Exception as e:
        print(f"Error during tick: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_show(args):
    try:
        fm = get_fm()
        feed = fm.get(args.feed_id)
        if not feed:
            print(f"Feed not found: {args.feed_id}")
            sys.exit(1)
        print(f"Feed:       {feed.name}")
        print(f"ID:         {feed.id}")
        print(f"Query:      {feed.query}")
        print(f"Interval:   {feed.interval}")
        print(f"Sources:    {', '.join(feed.sources)}")
        print(f"Tags:       {', '.join(feed.tags)}")
        print(f"Enabled:    {feed.enabled}")
        print(f"Status:     {feed.status}")
        print(f"Total runs: {feed.total_runs}")
        print(f"Citations:  {feed.total_citations}")
        print(f"Created:    {feed.created_at}")
        print(f"Last run:   {feed.last_run or 'never'}")
        print(f"Next run:   {feed.next_run}")
    except Exception as e:
        print(f"Error showing feed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_delete(args):
    try:
        fm = get_fm()
        if fm.delete(args.feed_id):
            print(f"Deleted feed: {args.feed_id}")
        else:
            print(f"Feed not found: {args.feed_id}")
            sys.exit(1)
    except Exception as e:
        print(f"Error deleting feed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_markdown(args):
    try:
        fm = get_fm()
        md = fm.get_feed_markdown(args.feed_id)
        if not md:
            print("No markdown output yet.")
            return
        print(md)
    except Exception as e:
        print(f"Error reading markdown: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args):
    try:
        fm = get_fm()
        stats = fm.stats()
        print(f"Total feeds:     {stats['total_feeds']}")
        print(f"Active feeds:    {stats['active_feeds']}")
        print(f"Total runs:      {stats['total_runs']}")
        print(f"Total citations: {stats['total_citations']}")
        print(f"By interval:")
        for interval, count in stats.get("by_interval", {}).items():
            print(f"  {interval}: {count}")
    except Exception as e:
        print(f"Error getting stats: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Tropelex Research Feeds CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List all feeds")
    p_list.add_argument("--enabled", action="store_true", help="Only show enabled feeds")
    p_list.set_defaults(func=cmd_list)

    p_create = sub.add_parser("create", help="Create a new feed")
    p_create.add_argument("name", help="Feed name")
    p_create.add_argument("query", help="Search query (use OR or | for multi-term)")
    p_create.add_argument("--description", "-d", default="", help="Description")
    p_create.add_argument("--interval", "-i", default="weekly", choices=["daily", "weekly", "monthly", "manual"])
    p_create.add_argument("--tags", "-t", default="", help="Comma-separated tags")
    p_create.add_argument("--sources", "-s", default="web", help="Comma-separated sources")
    p_create.add_argument("--max-results", "-m", type=int, default=20, help="Max results per run")
    p_create.set_defaults(func=cmd_create)

    p_run = sub.add_parser("run", help="Run a feed immediately")
    p_run.add_argument("feed_id", help="Feed ID")
    p_run.set_defaults(func=cmd_run)

    p_tick = sub.add_parser("tick", help="Run all due feeds")
    p_tick.set_defaults(func=cmd_tick)

    p_show = sub.add_parser("show", help="Show feed details")
    p_show.add_argument("feed_id", help="Feed ID")
    p_show.set_defaults(func=cmd_show)

    p_delete = sub.add_parser("delete", help="Delete a feed")
    p_delete.add_argument("feed_id", help="Feed ID")
    p_delete.set_defaults(func=cmd_delete)

    p_md = sub.add_parser("markdown", help="Show feed markdown output")
    p_md.add_argument("feed_id", help="Feed ID")
    p_md.set_defaults(func=cmd_markdown)

    p_stats = sub.add_parser("stats", help="Show aggregate stats")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
