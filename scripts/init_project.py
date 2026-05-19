"""
Tropelex Project Initializer
Creates universal markdown files for new projects.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

def create_project_structure(project_name: str, base_path: str = "."):
    base = Path(base_path)
    project_dir = base / project_name
    
    tropebook_root = Path(__file__).parent.parent
    template_dir = tropebook_root / "templates"
    
    if not template_dir.exists():
        print(f"Error: Templates directory not found at {template_dir}")
        print("Please ensure Tropelex is properly installed.")
        return None
    
    if project_dir.exists():
        print(f"Warning: {project_dir} already exists")
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            return
    
    project_dir.mkdir(parents=True, exist_ok=True)
    
    created = []
    
    for md_file in template_dir.glob("*.md"):
        dest = project_dir / md_file.name
        content = md_file.read_text()
        content = content.replace("{{PROJECT_NAME}}", project_name)
        content = content.replace("{{DATE}}", datetime.utcnow().strftime("%Y-%m-%d"))
        dest.write_text(content)
        created.append(str(dest))
        print(f"Created: {dest}")
    
    (project_dir / "memory").mkdir(exist_ok=True)
    created.append(str(project_dir / "memory"))
    print(f"Created: {project_dir / 'memory'}")
    
    return created

def init_project(args):
    if len(args) < 1:
        print("Usage: python -m scripts.init_project <project_name> [base_path]")
        return 1
    
    project_name = args[0]
    base_path = args[1] if len(args) > 1 else "."
    
    created = create_project_structure(project_name, base_path)
    if created:
        print(f"\n✓ Created {len(created)} items in {project_name}/")
    return 0

if __name__ == "__main__":
    sys.exit(init_project(sys.argv[1:]))